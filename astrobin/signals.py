import datetime
import logging
import re
from itertools import chain
from typing import List

from annoying.functions import get_object_or_None
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import Group as DjangoGroup, User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.cache.utils import make_template_fragment_key
from django.core.exceptions import MultipleObjectsReturned
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.signals import (m2m_changed, post_delete, post_save, pre_save)
from django.urls import reverse as reverse_url
from django.utils import timezone
from django.utils.translation import gettext, override
from persistent_messages.models import Message
from pybb.models import Forum, Post, Topic, TopicReadTracker
from pybb.permissions import perms
from pybb.util import get_pybb_profile
from rest_framework.authtoken.models import Token
from safedelete.models import SafeDeleteModel
from safedelete.signals import post_softdelete
from subscription.models import Transaction, UserSubscription
from subscription.signals import paid, signed_up

from astrobin.tasks import process_camera_rename_proposal
from astrobin_apps_groups.models import Group
from astrobin_apps_images.services import ImageService
from astrobin_apps_iotd.models import IotdSubmission, IotdVote, TopPickArchive, TopPickNominationsArchive
from astrobin_apps_iotd.services import IotdService
from astrobin_apps_notifications.services import NotificationsService
from astrobin_apps_notifications.tasks import push_notification_for_new_image, push_notification_for_new_image_revision
from astrobin_apps_notifications.utils import (
    build_notification_url, clear_notifications_template_cache,
    push_notification,
)
from astrobin_apps_platesolving.models import Solution
from astrobin_apps_platesolving.solver import Solver
from astrobin_apps_premium.services.premium_service import PremiumService
from astrobin_apps_premium.templatetags.astrobin_apps_premium_tags import (
    is_any_premium_subscription, is_any_ultimate, is_free, is_lite, is_lite_2020, is_premium, is_premium_2020,
)
from astrobin_apps_premium.utils import premium_get_valid_usersubscription
from astrobin_apps_users.services import UserService
from common.models import ABUSE_REPORT_DECISION_OVERRULED, AbuseReport
from common.services import DateTimeService
from common.services.mentions_service import MentionsService
from common.services.moderation_service import ModerationService
from nested_comments.models import NestedComment
from nested_comments.services.comment_notifications_service import CommentNotificationsService
from toggleproperties.models import ToggleProperty
from .models import CameraRenameProposal, Image, ImageRevision, UserProfile
from .search_indexes import ImageIndex, UserIndex
from .stories import add_story

log = logging.getLogger('apps')


def image_pre_save(sender, instance, **kwargs):
    if instance.uploader_in_progress:
        return

    if not instance.pk and not instance.is_wip:
        instance.published = datetime.datetime.now()

    try:
        image = sender.objects_including_wip.get(pk=instance.pk)
    except sender.DoesNotExist:
        # Image is being created.

        last_image: Image = Image.objects_including_wip.filter(user=instance.user).order_by('-pk').first()
        if last_image:
            instance.watermark = last_image.watermark
            instance.watermark_text = last_image.watermark_text
            instance.watermark_position = last_image.watermark_position
            instance.watermark_size = last_image.watermark_size
            instance.watermark_opacity = last_image.watermark_opacity


        user_scores_index = instance.user.userprofile.get_scores()['user_scores_index'] or 0
        if user_scores_index >= 1.00 or \
                is_any_premium_subscription(instance.user) or \
                ModerationService.auto_approve(instance.user):
            instance.moderated_when = datetime.date.today()
            instance.moderator_decision = 1
    else:
        if image.moderator_decision != 1 and instance.moderator_decision == 1:
            # This image is being approved
            if not instance.is_wip:
                add_story(instance.user, verb='VERB_UPLOADED_IMAGE', action_object=instance)

        if not instance.is_wip and not instance.published:
            # This image is being published
            instance.published = datetime.datetime.now()

        previous_mentions = MentionsService.get_mentions(image.description_bbcode)
        current_mentions = MentionsService.get_mentions(instance.description_bbcode)
        mentions = [item for item in current_mentions if item not in previous_mentions]
        cache.set("image.%d.image_pre_save_mentions" % instance.pk, mentions, 2)

        if (
                instance.watermark_text != image.watermark_text or
                instance.watermark != image.watermark or
                instance.watermark_position != image.watermark_position or
                instance.watermark_size != image.watermark_size or
                instance.watermark_opacity != image.watermark_opacity
        ):
            ImageService(image).invalidate_all_thumbnails()


pre_save.connect(image_pre_save, sender=Image)


def image_post_save(sender, instance, created, **kwargs):
    # type: (object, Image, bool, object) -> None

    if created:
        instance.user.userprofile.premium_counter += 1
        instance.user.userprofile.save(keep_deleted=True)

        if not instance.is_wip:
            if not instance.skip_notifications:
                push_notification_for_new_image.apply_async(args=(instance.user.pk, instance.pk,))
            if instance.moderator_decision == 1:
                add_story(instance.user, verb='VERB_UPLOADED_IMAGE', action_object=instance)

        if Image.all_objects.filter(user=instance.user).count() == 1:
            push_notification([instance.user], None, 'congratulations_for_your_first_image', {
                'BASE_URL': settings.BASE_URL,
                'PREMIUM_MAX_IMAGES_FREE': settings.PREMIUM_MAX_IMAGES_FREE,
                'url': reverse_url('image_detail', args=(instance.get_id(),))
            })

        mentions = MentionsService.get_mentions(instance.description_bbcode)
    else:
        mentions = cache.get("image.%d.image_pre_save_mentions" % instance.pk, [])

    for username in mentions:
        user = get_object_or_None(User, username=username)
        if not user:
            try:
                profile = get_object_or_None(UserProfile, real_name=username)
                if profile:
                    user = profile.user
            except MultipleObjectsReturned:
                user = None
        if user and user != instance.user:
            thumb = instance.thumbnail_raw('gallery', None, sync=True)
            push_notification(
                [user], instance.user, 'new_image_description_mention',
                {
                    'image': instance,
                    'image_thumbnail': thumb.url if thumb else None,
                    'url': build_notification_url(settings.BASE_URL + instance.get_absolute_url(), instance.user),
                    'user': instance.user.userprofile.get_display_name(),
                    'user_url': settings.BASE_URL + reverse_url('user_page', kwargs={'username': instance.user}),
                }
            )

    if not instance.uploader_in_progress:
        groups = instance.user.joined_group_set.filter(autosubmission=True)
        for group in groups:
            if instance.is_wip:
                group.images.remove(instance)
            else:
                group.images.add(instance)

        if instance.user.userprofile.updated < datetime.datetime.now() - datetime.timedelta(minutes=5):
            instance.user.save()
            try:
                instance.user.userprofile.save(keep_deleted=True)
            except UserProfile.DoesNotExist:
                pass

        UserService(instance.user).clear_gallery_image_list_cache()

        if instance.user.userprofile.auto_submit_to_iotd_tp_process:
            IotdService.submit_to_iotd_tp_process(instance.user, instance, False)


post_save.connect(image_post_save, sender=Image)


def image_post_delete(sender, instance, **kwargs):
    def decrease_counter(user):
        user.userprofile.premium_counter -= 1
        with transaction.atomic():
            user.userprofile.save(keep_deleted=True)

    ImageIndex().remove_object(instance)
    UserService(instance.user).clear_gallery_image_list_cache()

    try:
        if instance.uploaded > datetime.datetime.now() - relativedelta(hours=24):
            decrease_counter(instance.user)
        elif is_lite(instance.user):
            usersub = premium_get_valid_usersubscription(instance.user)
            usersub_created = usersub.expires - relativedelta(years=1)
            dt = instance.uploaded.date() - usersub_created
            if dt.days >= 0:
                decrease_counter(instance.user)
        elif is_lite_2020(instance.user) or \
                is_premium(instance.user) or \
                is_premium_2020(instance.user) or \
                is_any_ultimate(instance.user):
            decrease_counter(instance.user)
    except IntegrityError:
        # Possibly the user is being deleted
        pass


post_softdelete.connect(image_post_delete, sender=Image)
post_delete.connect(image_post_delete, sender=Image)


def imagerevision_pre_save(sender, instance, **kwargs):
    if instance.pk:
        pre_save_instance = get_object_or_None(ImageRevision.uploads_in_progress, pk=instance.pk)
        if pre_save_instance and not instance.uploader_in_progress:
            cache.set("image_revision.%s.just_completed_upload" % instance.pk, True, 10)


pre_save.connect(imagerevision_pre_save, sender=ImageRevision)


def imagerevision_post_save(sender, instance, created, **kwargs):
    wip = instance.image.is_wip
    skip = instance.skip_notifications
    uploading = instance.uploader_in_progress
    just_completed_upload = cache.get("image_revision.%s.just_completed_upload" % instance.pk)

    UserService(instance.image.user).clear_gallery_image_list_cache()

    if wip or skip:
        return

    if (created and not uploading) or just_completed_upload:
        push_notification_for_new_image_revision.apply_async(args=(instance.pk,), countdown=10)
        add_story(instance.image.user,
                  verb='VERB_UPLOADED_REVISION',
                  action_object=instance,
                  target=instance.image)


post_save.connect(imagerevision_post_save, sender=ImageRevision)


def imagerevision_post_delete(sender, instance, **kwargs):
    UserService(instance.image.user).clear_gallery_image_list_cache()


post_softdelete.connect(imagerevision_post_delete, sender=ImageRevision)
post_delete.connect(imagerevision_post_delete, sender=ImageRevision)


def nested_comment_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            previous_mentions = MentionsService.get_mentions(sender.objects.get(pk=instance.pk).text)
            current_mentions = MentionsService.get_mentions(instance.text)
            mentions = [item for item in current_mentions if item not in previous_mentions]
        except sender.DoesNotExist:
            mentions = []

        cache.set("user.%d.comment_pre_save_mentions" % instance.author.pk, mentions, 2)
    else:
        insufficient_index = instance.author.userprofile.get_scores()['user_scores_index'] is not None and \
                             instance.author.userprofile.get_scores()['user_scores_index'] < 1.00
        free_account = is_free(instance.author)
        insufficient_previous_approvals = NestedComment.objects.filter(
            Q(author=instance.author) & ~Q(pending_moderation=True)
        ).count() < 3

        is_content_owner = False
        ct = ContentType.objects.get_for_id(instance.content_type_id)
        if ct.model == 'image':
            is_content_owner = instance.author == instance.content_object.user

        if insufficient_index and \
                free_account and \
                insufficient_previous_approvals and \
                not is_content_owner and \
                not ModerationService.auto_approve(instance.author):
            instance.pending_moderation = True


pre_save.connect(nested_comment_pre_save, sender=NestedComment)


def nested_comment_post_save(sender, instance, created, **kwargs):
    if created:
        mentions = MentionsService.get_mentions(instance.text)

        if hasattr(instance.content_object, "updated"):
            # This will trigger the auto_now fields in the content_object
            # We do it only if created, because the content_object needs to
            # only be updated if the number of comments changes.
            save_kwargs = {}
            if issubclass(type(instance.content_object), SafeDeleteModel):
                save_kwargs['keep_deleted'] = True
            instance.content_object.save(**save_kwargs)

        if instance.pending_moderation:
            CommentNotificationsService(instance).send_moderation_required_notification()
        else:
            CommentNotificationsService(instance).send_notifications()
    else:
        mentions = cache.get("user.%d.comment_pre_save_mentions" % instance.author.pk, [])

    if not instance.pending_moderation:
        for username in mentions:
            user = get_object_or_None(User, username=username)
            if not user:
                try:
                    profile = get_object_or_None(UserProfile, real_name=username)
                    if profile:
                        user = profile.user
                except MultipleObjectsReturned:
                    user = None
            if user:
                push_notification(
                    [user], instance.author, 'new_comment_mention',
                    {
                        'url': build_notification_url(settings.BASE_URL + instance.get_absolute_url(), instance.author),
                        'user': instance.author.userprofile.get_display_name(),
                        'user_url': settings.BASE_URL + reverse_url(
                            'user_page', kwargs={'username': instance.author}),
                    }
                )


post_save.connect(nested_comment_post_save, sender=NestedComment)


def toggleproperty_post_delete(sender, instance, **kwargs):
    if hasattr(instance.content_object, "updated"):
        # This will trigger the auto_now fields in the content_object
        try:
            kwargs = {}
            if issubclass(type(instance.content_object), SafeDeleteModel):
                kwargs['keep_deleted'] = True
            instance.content_object.save(**kwargs)
        except instance.content_object.DoesNotExist:
            pass


post_delete.connect(toggleproperty_post_delete, sender=ToggleProperty)


def toggleproperty_post_save(sender, instance, created, **kwargs):
    if hasattr(instance.content_object, "updated"):
        # This will trigger the auto_now fields in the content_object
        kwargs = {}
        if issubclass(type(instance.content_object), SafeDeleteModel):
            kwargs['keep_deleted'] = True
        instance.content_object.save(**kwargs)

    if created:
        verb = None

        if instance.property_type in ("like", "bookmark"):

            if instance.content_type == ContentType.objects.get_for_model(Image):
                image = instance.content_type.get_object_for_this_type(id=instance.object_id)
                Image.all_objects.filter(pk=instance.content_object.pk).update(updated=timezone.now())

                if image.is_wip:
                    return

                if instance.property_type == "like":
                    verb = 'VERB_LIKED_IMAGE'
                elif instance.property_type == "bookmark":
                    verb = 'VERB_BOOKMARKED_IMAGE'
                else:
                    return

                push_notification(
                    [instance.content_object.user], instance.user, 'new_' + instance.property_type,
                    {
                        'url': build_notification_url(
                            settings.BASE_URL + instance.content_object.get_absolute_url(), instance.user),
                        'title': instance.content_object.title,
                        'user': instance.user.userprofile.get_display_name(),
                        'user_url': settings.BASE_URL + reverse_url(
                            'user_page', kwargs={'username': instance.user.username}),
                    })

            elif instance.content_type == ContentType.objects.get_for_model(NestedComment):
                push_notification(
                    [instance.content_object.author], instance.user, 'new_comment_like',
                    {
                        'url': build_notification_url(
                            settings.BASE_URL + instance.content_object.get_absolute_url(), instance.user),
                        'user': instance.user.userprofile.get_display_name(),
                        'user_url': settings.BASE_URL + reverse_url(
                            'user_page', kwargs={'username': instance.user.username}),
                        'comment': instance.content_object.text
                    })

                UserProfile.all_objects.filter(user=instance.content_object.author).update(updated=timezone.now())

            elif instance.content_type == ContentType.objects.get_for_model(Post):
                push_notification(
                    [instance.content_object.user], instance.user, 'new_forum_post_like',
                    {
                        'url': build_notification_url(
                            settings.BASE_URL + instance.content_object.get_absolute_url(), instance.user),
                        'user': instance.user.userprofile.get_display_name(),
                        'user_url': settings.BASE_URL + reverse_url(
                            'user_page', kwargs={'username': instance.user.username}),

                        'post': instance.content_object.topic.name
                    })

                UserProfile.all_objects.filter(user=instance.content_object.user).update(updated=timezone.now())

            if verb is not None:
                add_story(instance.user,
                          verb=verb,
                          action_object=instance.content_object)

        elif instance.property_type == "follow":
            user_ct = ContentType.objects.get_for_model(User)
            if instance.content_type == user_ct:
                followed_user = user_ct.get_object_for_this_type(pk=instance.object_id)
                push_notification(
                    [followed_user], instance.user, 'new_follower', {
                        'object': instance.user.userprofile.get_display_name(),
                        'object_url': build_notification_url(settings.BASE_URL + reverse_url(
                            'user_page', kwargs={'username': instance.user.username}), instance.user),
                    }
                )


post_save.connect(toggleproperty_post_save, sender=ToggleProperty)


def create_auth_token(sender, instance, created, **kwargs):
    if created:
        Token.objects.get_or_create(user=instance)


post_save.connect(create_auth_token, sender=User)


def solution_pre_save(sender, instance, **kwargs):
    try:
        solution_before_save = Solution.objects.get(pk=instance.pk)
    except Solution.DoesNotExist:
        return

    if solution_before_save.status >= instance.status:
        return

    if instance.status == Solver.FAILED:
        notification = 'image_not_solved'
    elif instance.status == Solver.SUCCESS:
        notification = 'image_solved'
    elif instance.status == Solver.ADVANCED_SUCCESS:
        notification = 'image_solved_advanced'
    elif instance.status == Solver.ADVANCED_FAILED:
        notification = 'image_not_solved_advanced'
    else:
        return

    ct = instance.content_type

    try:
        target = ct.get_object_for_this_type(pk=instance.object_id)
    except ct.model_class().DoesNotExist:
        return

    if ct.model == 'image':
        user = target.user
        title = target.title
        thumb = target.thumbnail_raw('gallery', '0', sync=True)
    elif ct.model == 'imagerevision':
        user = target.image.user
        title = target.image.title
        thumb = target.image.thumbnail_raw('gallery', target.label, sync=True)
    else:
        return

    push_notification(
        [user],
        None,
        notification,
        {
            'object_url': build_notification_url(settings.BASE_URL + target.get_absolute_url()),
            'title': title,
            'image_thumbnail': thumb.url if thumb else None,
        }
    )


pre_save.connect(solution_pre_save, sender=Solution)


def subscription_paid(sender, **kwargs):
    subscription = kwargs.get('subscription')
    user = kwargs.get('user')
    profile = user.userprofile

    UserProfile.all_objects.filter(user=user).update(updated=timezone.now())
    PremiumService.clear_subscription_status_cache_keys(user.pk)

    if subscription.group.name == 'astrobin_lite':
        profile.premium_counter = 0
        profile.save(keep_deleted=True)
    elif subscription.group.name == 'astrobin_lite_2020':
        profile.premium_counter = Image.objects_including_wip.filter(user=user).count()
        profile.save(keep_deleted=True)

    if 'premium' in subscription.category and Transaction.objects.filter(
            user=user,
            event='new usersubscription',
            timestamp__gte=DateTimeService.now() - datetime.timedelta(minutes=5)):
        push_notification([user], None, 'new_subscription', {'BASE_URL': settings.BASE_URL})
    else:
        push_notification([user], None, 'new_payment', {'BASE_URL': settings.BASE_URL})


paid.connect(subscription_paid)


def subscription_signed_up(sender, **kwargs):
    subscription = kwargs.get('subscription')
    user_subscription = kwargs.get('usersubscription')
    user = kwargs.get('user')

    UserProfile.all_objects.filter(user=user).update(updated=timezone.now())
    PremiumService.clear_subscription_status_cache_keys(user.pk)

    if 'premium' in subscription.category:
        today = DateTimeService.today()
        if user_subscription.expires is None or user_subscription.expires < today:
            user_subscription.expires = today
        user_subscription.extend(datetime.timedelta(days=365.2425))
        user_subscription.save()

        # Invalidate other premium subscriptions
        UserSubscription.active_objects \
            .filter(user=user_subscription.user,
                    subscription__category__startswith='premium') \
            .exclude(pk=user_subscription.pk) \
            .update(active=False)

        if Transaction.objects.filter(
                user=user,
                event='new usersubscription',
                timestamp__gte=DateTimeService.now() - datetime.timedelta(minutes=5)):
            push_notification([user], None, 'new_subscription', {'BASE_URL': settings.BASE_URL})
        else:
            push_notification([user], None, 'new_payment', {'BASE_URL': settings.BASE_URL})


signed_up.connect(subscription_signed_up)


def user_subscription_post_delete(sender, instance, **kwargs):
    PremiumService.clear_subscription_status_cache_keys(instance.user.pk)


post_delete.connect(user_subscription_post_delete, sender=UserSubscription)


def group_pre_save(sender, instance, **kwargs):
    try:
        group = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        pass
    else:
        # Group is becoming autosubmission
        if not group.autosubmission and instance.autosubmission:
            instance.images.clear()
            images = Image.objects.filter(user__in=instance.members.all())
            for image in images:
                instance.images.add(image)

        # Group was renamed
        if group.name != instance.name:
            group.forum.name = instance.name
            group.forum.save()


pre_save.connect(group_pre_save, sender=Group)


def group_post_save(sender, instance, created, **kwargs):
    if created and instance.creator is not None:
        instance.members.add(instance.creator)
        if instance.moderated:
            instance.moderators.add(instance.creator)

        if instance.public:
            followers = [
                x.user for x in
                ToggleProperty.objects.toggleproperties_for_object(
                    "follow", UserProfile.objects.get(user__pk=instance.creator.pk).user)
            ]
            push_notification(followers, instance.creator, 'new_public_group_created',
                              {
                                  'creator': instance.creator.userprofile.get_display_name(),
                                  'group_name': instance.name,
                                  'url': settings.BASE_URL + reverse_url('group_detail', args=(instance.pk,)),
                              })

            add_story(
                instance.creator,
                verb='VERB_CREATED_PUBLIC_GROUP',
                action_object=instance)


post_save.connect(group_post_save, sender=Group)


def group_members_changed(sender, instance, **kwargs):
    action = kwargs['action']
    pk_set = kwargs['pk_set']

    group_sync_map = {
        'IOTD Submitters': ['iotd_submitters', 'content_moderators', 'iotd_staff'],
        'IOTD Reviewers': ['iotd_reviewers', 'content_moderators', 'iotd_staff'],
        'IOTD Judges': ['iotd_judges', 'content_moderators', 'iotd_staff'],
    }
    if instance.name in list(group_sync_map.keys()):
        for django_group in group_sync_map[instance.name]:
            DjangoGroup.objects.get_or_create(name=django_group)
        django_groups = DjangoGroup.objects.filter(name__in=group_sync_map[instance.name])
    try:
        iotd_staff_group = Group.objects.get(name='IOTD Staff')
    except Group.DoesNotExist:
        iotd_staff_group = None

    if action == 'post_add':
        users = [profile.user for profile in UserProfile.objects.filter(user__pk__in=pk_set)]
        instance.save()  # trigger date_updated update

        if instance.public:
            for pk in pk_set:
                user = UserProfile.objects.get(user__pk=pk).user
                if user != instance.owner:
                    followers = [
                        x.user for x in
                        ToggleProperty.objects.toggleproperties_for_object("follow", user)
                    ]
                    push_notification(
                        followers + [instance.owner],
                        user,
                        'user_joined_public_group',
                        {
                            'user': user.userprofile.get_display_name(),
                            'user_url': build_notification_url(
                                settings.BASE_URL + reverse_url('user_page', kwargs={'username': user.username}),
                                user
                            ),
                            'group_name': instance.name,
                            'url': build_notification_url(
                                settings.BASE_URL + reverse_url('group_detail', args=(instance.pk,)),
                                user
                            ),
                        })

                    add_story(
                        user,
                        verb='VERB_JOINED_GROUP',
                        action_object=instance)

        if instance.autosubmission:
            images = Image.objects_including_wip.filter(user__pk__in=pk_set)
            for image in images:
                instance.images.add(image)

        # Sync IOTD AstroBin groups with django groups
        if instance.name in list(group_sync_map.keys()):
            for django_group in django_groups:
                django_group.user_set.add(*list(users))
            if iotd_staff_group:
                for user in users:
                    iotd_staff_group.members.add(user)

    elif action == 'post_remove':
        users = [profile.user for profile in UserProfile.objects.filter(user__pk__in=pk_set)]
        images = Image.objects_including_wip.filter(user__pk__in=pk_set)
        for image in images:
            instance.images.remove(image)

        if instance.forum and not instance.public:
            topics = Topic.objects.filter(forum=instance.forum)
            for topic in topics:
                topic.subscribers.remove(*User.objects.filter(pk__in=kwargs['pk_set']))

        # Sync IOTD AstroBin groups with django groups
        if instance.name in list(group_sync_map.keys()):
            all_members = []
            all_members_chain = chain([
                x.members.all()
                for x in Group.objects \
                    .filter(name__in=list(group_sync_map.keys())) \
                    .exclude(name=instance.name)
            ])
            for chain_item in all_members_chain:
                all_members += chain_item
            for user in [x for x in users if x not in all_members]:
                for django_group in django_groups:
                    django_group.user_set.remove(user)
                if iotd_staff_group:
                    iotd_staff_group.members.remove(user)

    elif action == 'pre_clear':
        # Sync IOTD AstroBin groups with django groups
        users = instance.members.all()
        if instance.name in list(group_sync_map.keys()):
            all_members = []
            all_members_chain = chain([
                x.members.all()
                for x in Group.objects \
                    .filter(name__in=list(group_sync_map.keys())) \
                    .exclude(name=instance.name)
            ])
            for chain_item in all_members_chain:
                all_members += chain_item
            for user in [x for x in users if x not in all_members]:
                for django_group in django_groups:
                    django_group.user_set.remove(user)
                if iotd_staff_group:
                    iotd_staff_group.members.remove(user)

    elif action == 'post_clear':
        instance.images.clear()


m2m_changed.connect(group_members_changed, sender=Group.members.through)


def group_images_changed(sender, instance, **kwargs):
    if kwargs['action'] == 'post_add' and 'pk_set' in kwargs:
        group = sender.group.get_queryset().first()
        group.save()  # trigger date_updated update


m2m_changed.connect(group_images_changed, sender=Group.images.through)


def group_post_delete(sender, instance, **kwargs):
    try:
        instance.forum.delete()
    except Forum.DoesNotExist:
        pass


post_delete.connect(group_post_delete, sender=Group)


def forum_topic_pre_save(sender, instance, **kwargs):
    if not hasattr(instance.forum, 'group'):
        return

    try:
        topic = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        pass
    else:
        if topic.on_moderation == True and instance.on_moderation == False:
            # This topic is being approved
            group = instance.forum.group
            push_notification(
                [x for x in group.members.all() if x != instance.user],
                instance.user,
                'new_topic_in_group',
                {
                    'user_url': build_notification_url(
                        settings.BASE_URL + reverse_url('user_page', kwargs={'username': instance.user})),
                    'user': instance.user.userprofile.get_display_name(),
                    'url': build_notification_url(settings.BASE_URL + instance.get_absolute_url(), instance.user),
                    'group_url': build_notification_url(
                        reverse_url('group_detail', kwargs={'pk': group.pk}), instance.user),
                    'group_name': group.name,
                    'topic_title': instance.name,
                },
            )


pre_save.connect(forum_topic_pre_save, sender=Topic)


def forum_topic_post_save(sender, instance, created, **kwargs):
    if created and hasattr(instance.forum, 'group'):
        group = instance.forum.group

        if instance.on_moderation:
            recipients = group.moderators.all()
        else:
            recipients = group.members.all()
        recipients = [x for x in recipients if x != instance.user]

        push_notification(
            recipients,
            instance.user,
            'new_topic_in_group',
            {
                'user_url': build_notification_url(
                    settings.BASE_URL + reverse_url('user_page', kwargs={'username': instance.user})),
                'user': instance.user.userprofile.get_display_name(),
                'url': build_notification_url(settings.BASE_URL + instance.get_absolute_url(), instance.user),
                'group_url': build_notification_url(
                    settings.BASE_URL + reverse_url('group_detail', kwargs={'pk': group.pk}), instance.user),
                'group_name': group.name,
                'topic_title': instance.name,
            },
        )

    cache_key = make_template_fragment_key(
        'home_page_latest_from_forums',
        (instance.user.pk, instance.user.userprofile.language))
    cache.delete(cache_key)


post_save.connect(forum_topic_post_save, sender=Topic)


def forum_post_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            previous_mentions = MentionsService.get_mentions(sender.objects.get(pk=instance.pk).body)
            current_mentions = MentionsService.get_mentions(instance.body)
            if Post.objects.filter(pk=instance.pk, on_moderation=True).exists():
                mentions = current_mentions
            else:
                mentions = [item for item in current_mentions if item not in previous_mentions]
        except sender.DoesNotExist:
            mentions = []

        cache.set("post.%d.forum_post_pre_save_mentions" % instance.pk, mentions, 2)

        if not instance.on_moderation and Post.objects.filter(pk=instance.pk, on_moderation=True).exists():
            cache.set("post.%d.forum_post_pre_save_approved" % instance.pk, True, 2)

    for attribute in ['body', 'body_text', 'body_html']:
        for language in settings.LANGUAGES:
            with override(language[0]):
                for message in [
                    '*** Type your message here ***',
                    '*** Type your forum post here ***',
                    '*** Type your reply here ***',
                ]:
                    translated = gettext(message)
                    content = getattr(instance, attribute)
                    setattr(
                        instance,
                        attribute,
                        content.replace(translated, '')
                    )

        content = getattr(instance, attribute)
        re.sub(r'\n+', '\n', content).strip()
        setattr(instance, attribute, content)


pre_save.connect(forum_post_pre_save, sender=Post)


def forum_post_post_save(sender, instance, created, **kwargs):
    def notify_subscribers(mentions):
        # type: (List[str]) -> None
        recipients = list(instance.topic.subscribers.exclude(
            pk__in=list(set(
                [instance.user.pk] +
                [x.pk for x in MentionsService.get_mentioned_users_with_notification_enabled(
                    mentions, 'new_forum_post_mention')
                 ])
            ))
        )

        if recipients:
            push_notification(
                recipients,
                instance.user,
                'new_forum_reply',
                {
                    'user': instance.user.userprofile.get_display_name(),
                    'user_url': settings.BASE_URL + reverse_url('user_page', kwargs={'username': instance.user}),
                    'post_url': build_notification_url(settings.BASE_URL + instance.get_absolute_url(), instance.user),
                    'topic_url': build_notification_url(
                        settings.BASE_URL + instance.topic.get_absolute_url(), instance.user),
                    'topic_name': instance.topic.name,
                    'unsubscribe_url': build_notification_url(
                        settings.BASE_URL + reverse_url('pybb:delete_subscription', args=[instance.topic.id]),
                        instance.user
                    )
                }
            )

    def notify_mentioned(mentions):
        # type: (List[str]) -> None
        for username in mentions:
            user = get_object_or_None(User, username=username)
            if user is None:
                try:
                    profile = get_object_or_None(UserProfile, real_name=username)
                    if profile:
                        user = profile.user
                except MultipleObjectsReturned:
                    user = None
            if user:
                push_notification(
                    [user],
                    instance.user,
                    'new_forum_post_mention',
                    {
                        'url': build_notification_url(settings.BASE_URL + instance.get_absolute_url(), instance.user),
                        'user': instance.user.userprofile.get_display_name(),
                        'user_url': settings.BASE_URL + reverse_url(
                            'user_page', kwargs={'username': instance.user}),
                        'post': instance.topic.name,
                    }
                )

    if created:
        if hasattr(instance.topic.forum, 'group'):
            instance.topic.forum.group.save()  # trigger date_updated update

        if get_pybb_profile(instance.user).autosubscribe and \
                perms.may_subscribe_topic(instance.user, instance.topic):
            instance.topic.subscribers.add(instance.user)

        mentions = MentionsService.get_mentions(instance.body)
        if not instance.on_moderation:
            notify_subscribers(mentions)
            notify_mentioned(mentions)
        else:
            NotificationsService.email_superusers(
                'New forum post needs moderation',
                '%s%s' % (settings.BASE_URL, instance.get_absolute_url())
            )

    else:
        mentions = cache.get("post.%d.forum_post_pre_save_mentions" % instance.pk, [])
        cache.delete("post.%d.forum_post_pre_save_mentions" % instance.pk)
        if cache.get("post.%d.forum_post_pre_save_approved" % instance.pk):
            push_notification([instance.user], None, 'forum_post_approved', {
                'url': build_notification_url(settings.BASE_URL + instance.get_absolute_url())
            })
            notify_subscribers(mentions)
            notify_mentioned(mentions)
            cache.delete("post.%d.forum_post_pre_save_approved" % instance.pk)

    cache_key = make_template_fragment_key(
        'home_page_latest_from_forums',
        (instance.user.pk, instance.user.userprofile.language))
    cache.delete(cache_key)


post_save.connect(forum_post_post_save, sender=Post)


def topic_read_tracker_post_save(sender, instance, created, **kwargs):
    cache_key = make_template_fragment_key(
        'home_page_latest_from_forums',
        (instance.user.pk, instance.user.userprofile.language))
    cache.delete(cache_key)


post_save.connect(topic_read_tracker_post_save, sender=TopicReadTracker)


def user_post_save(sender, instance, created, **kwargs):
    if not created:
        try:
            instance.userprofile.save(keep_deleted=True)
        except UserProfile.DoesNotExist:
            pass


post_save.connect(user_post_save, sender=User)


def userprofile_post_delete(sender, instance, **kwargs):
    # Images are attached to the auth.User object, and that's not really
    # deleted, so nothing is cascaded, hence the following line.
    instance.user.is_active = False

    if instance.user.email and 'ASTROBIN_IGNORE' not in instance.user.email:
        instance.user.email = instance.user.email.replace('@', '+ASTROBIN_IGNORE@')

    instance.user.save()
    Image.objects_including_wip.filter(user=instance.user).delete()
    NestedComment.objects.filter(author=instance.user, deleted=False).update(deleted=True)
    UserIndex().remove_object(instance.user)


post_softdelete.connect(userprofile_post_delete, sender=UserProfile)


def persistent_message_post_save(sender, instance, **kwargs):
    clear_notifications_template_cache(instance.user.username)


post_save.connect(persistent_message_post_save, sender=Message)


def top_pick_nominations_archive_post_save(sender, instance, created, **kwargs):
    if created:
        image = instance.image
        thumb = image.thumbnail_raw('gallery', None, sync=True)

        push_notification([image.user], None, 'your_image_is_tpn', {
            'image': image,
            'image_thumbnail': thumb.url if thumb else None
        })


post_save.connect(top_pick_nominations_archive_post_save, sender=TopPickNominationsArchive)


def top_pick_archive_item_post_save(sender, instance, created, **kwargs):
    if created:
        image = instance.image
        thumb = image.thumbnail_raw('gallery', None, sync=True)

        submitters = [x.submitter for x in IotdSubmission.objects.filter(image=image)]
        push_notification(submitters, None, 'image_you_promoted_is_tp', {
            'image': image,
            'image_thumbnail': thumb.url if thumb else None
        })

        reviewers = [x.reviewer for x in IotdVote.objects.filter(image=image)]
        push_notification(reviewers, None, 'image_you_promoted_is_tp', {
            'image': image,
            'image_thumbnail': thumb.url if thumb else None
        })

        push_notification([image.user], None, 'your_image_is_tp', {
            'image': image,
            'image_thumbnail': thumb.url if thumb else None
        })


post_save.connect(top_pick_archive_item_post_save, sender=TopPickArchive)


def abuse_report_post_save(sender, instance, created, **kwargs):
    if created:
        NotificationsService.email_superusers(
            'New abuse report',
            '%s/admin/common/abusereport/%d/' % (settings.BASE_URL, instance.pk)
        )

        if AbuseReport.objects.filter(
                content_owner=instance.content_owner
        ).exclude(
            decision=ABUSE_REPORT_DECISION_OVERRULED
        ).count() == 5:
            NotificationsService.email_superusers(
                'User %s received 5 abuse reports' % instance.content_owner,
                '%s/admin/common/abusereport/%d/' % (settings.BASE_URL, instance.pk)
            )


post_save.connect(abuse_report_post_save, sender=AbuseReport)


def camera_rename_proposal_post_save(sender, instance: CameraRenameProposal, created: bool, **kwargs):
    process_camera_rename_proposal.delay(instance.pk)


post_save.connect(camera_rename_proposal_post_save, sender=CameraRenameProposal)
