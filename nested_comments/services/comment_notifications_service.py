import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet
from django.urls import reverse

from astrobin.models import Image
from astrobin.stories import add_story
from astrobin_apps_iotd.models import Iotd
from astrobin_apps_notifications.services import NotificationsService
from astrobin_apps_notifications.utils import build_notification_url, push_notification
from astrobin_apps_users.services import UserService
from common.services import AppRedirectionService
from common.services.mentions_service import MentionsService
from nested_comments.models import NestedComment

log = logging.getLogger('apps')


class CommentNotificationsService:
    def __init__(self, comment):
        # type: (NestedComment) -> None
        self.comment = comment

    def send_notifications(self, force=False):
        if self.comment.pending_moderation and not force:
            return

        instance = self.comment

        model_class = instance.content_type.model_class()
        obj = instance.content_type.get_object_for_this_type(id=instance.object_id)
        object_owner = None
        notification = None
        mentions = MentionsService.get_mentions(instance.text)
        url = None

        if model_class == Image:
            object_owner = obj.user
            notification = 'new_comment'
            url = settings.BASE_URL + instance.get_absolute_url()
        elif hasattr(model_class, 'edit_proposal_by'):
            object_owner = obj.edit_proposal_by
            notification = 'new_comment_to_edit_proposal'
            url = instance.get_absolute_url()
        elif model_class == Iotd:
            object_owner = obj.judge
            notification = 'new_comment_to_scheduled_iotd'
            url = AppRedirectionService.redirect(f'/iotd/judgement-queue#comments-{obj.pk}-{instance.pk}')

        if UserService(object_owner).shadow_bans(instance.author):
            log.info("Skipping notification for comment because %d shadow-bans %d" % (
                object_owner.pk, instance.author.pk))
            return

        exclude = MentionsService.get_mentioned_users_with_notification_enabled(mentions, 'new_comment_mention')

        if instance.parent and \
                instance.parent.author != instance.author and \
                not instance.pending_moderation:
            recipients = [x for x in [instance.parent.author] if x not in exclude]
            if recipients:
                push_notification(
                    recipients, instance.author, 'new_comment_reply',
                    {
                        'url': build_notification_url(url, instance.author),
                        'user': instance.author.userprofile.get_display_name(),
                        'user_url': settings.BASE_URL + reverse(
                            'user_page', kwargs={'username': instance.author.username}
                        ),
                    }
                )

        if model_class == Image:
            if (force or not instance.pending_moderation) and not obj.is_wip:
                add_story(instance.author,
                          verb='VERB_COMMENTED_IMAGE',
                          action_object=instance,
                          target=obj)

        if object_owner and notification:
            if instance.author != object_owner and \
                    (instance.parent is None or instance.parent.author != object_owner) and \
                    not instance.pending_moderation:
                recipients = [x for x in [object_owner] if x not in exclude]
                if recipients:
                    push_notification(
                        recipients, instance.author, notification,
                        {
                            'url': build_notification_url(url, instance.author),
                            'user': instance.author.userprofile.get_display_name(),
                            'user_url': settings.BASE_URL + reverse(
                                'user_page', kwargs={'username': instance.author.username}
                            ),
                        }
                    )

    def send_approval_notification(self):
        if not self.comment.pending_moderation:
            push_notification([self.comment.author], None, 'comment_approved', {
                'url': build_notification_url(settings.BASE_URL + self.comment.get_absolute_url())
            })

    def send_moderation_required_notification(self):
        if self.comment.pending_moderation:
            ct = ContentType.objects.get_for_id(self.comment.content_type_id)
            if ct.model == 'image':
                image = self.comment.content_object
                push_notification([image.user], None, 'new_image_comment_moderation', {
                    'title': image.title,
                    'url': build_notification_url(
                        '%s%s#c%d' % (settings.BASE_URL, image.get_absolute_url(), self.comment.pk),
                        additional_query_args={'moderate-comment': 1})
                })

    @staticmethod
    def send_moderation_required_email_to_superuser():
        NotificationsService.email_superusers(
            'New comment needs moderation',
            '%s/admin/nested_comments/nestedcomment/?pending_moderation__exact=1' % settings.BASE_URL
        )

    @staticmethod
    def approve_comments(queryset: QuerySet, moderator: User) -> None:
        queryset.update(pending_moderation=False, moderator=moderator)

        for comment in queryset:
            CommentNotificationsService(comment).send_notifications(force=True)
            CommentNotificationsService(comment).send_approval_notification()
