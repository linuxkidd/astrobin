from annoying.functions import get_object_or_None
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_migrate, post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from notification import models as notification
from safedelete.signals import post_softdelete

from astrobin_apps_equipment.models import (
    Accessory, Camera, CameraEditProposal, EquipmentBrand, EquipmentPreset, Filter, Mount, Sensor,
    Software, Telescope,
)
from astrobin_apps_equipment.models.accessory_edit_proposal import AccessoryEditProposal
from astrobin_apps_equipment.models.filter_edit_proposal import FilterEditProposal
from astrobin_apps_equipment.models.mount_edit_proposal import MountEditProposal
from astrobin_apps_equipment.models.sensor_edit_proposal import SensorEditProposal
from astrobin_apps_equipment.models.software_edit_proposal import SoftwareEditProposal
from astrobin_apps_equipment.models.telescope_edit_proposal import TelescopeEditProposal
from astrobin_apps_equipment.notice_types import EQUIPMENT_NOTICE_TYPES
from astrobin_apps_notifications.utils import build_notification_url, push_notification
from common.services import AppRedirectionService
from nested_comments.models import NestedComment


@receiver(post_migrate, sender=apps.get_app_config('astrobin'))
def create_notice_types(sender, **kwargs):
    for notice_type in EQUIPMENT_NOTICE_TYPES:
        notification.create_notice_type(notice_type[0], notice_type[1], notice_type[2], default=notice_type[3])


@receiver(pre_save, sender=Camera)
def mirror_modified_camera_update(sender, instance: Camera, **kwargs):
    if not instance.modified:
        before_saving = get_object_or_None(Camera, pk=instance.pk)
        if before_saving:
            Camera.objects.filter(brand=before_saving.brand, name=before_saving.name, modified=True).update(
                name=instance.name,
                image=instance.image,
                type=instance.type,
                sensor=instance.sensor,
                cooled=instance.cooled,
                max_cooling=instance.max_cooling,
                back_focus=instance.back_focus
            )


@receiver(post_softdelete, sender=Camera)
def mirror_modified_camera_softdelete(sender, instance: Camera, **kwargs):
    if not instance.modified:
        Camera.objects.filter(brand=instance.brand, name=instance.name, modified=True).delete()


@receiver(post_softdelete, sender=Sensor)
@receiver(post_softdelete, sender=Camera)
@receiver(post_softdelete, sender=Telescope)
@receiver(post_softdelete, sender=Mount)
@receiver(post_softdelete, sender=Filter)
@receiver(post_softdelete, sender=Accessory)
@receiver(post_softdelete, sender=Software)
def rename_equipment_item_after_deletion(sender, instance, **kwargs):
    if '[DELETED] ' not in instance.name:
        instance.name = f'[DELETED] ({instance.id}) {instance.name}'
        instance.save(keep_deleted=True)


@receiver(post_softdelete, sender=Camera)
def remove_camera_from_presets_after_deletion(sender, instance, **kwargs):
    preset: EquipmentPreset

    for preset in EquipmentPreset.objects.filter(imaging_cameras=instance).iterator():
        preset.imaging_cameras.remove(instance)

    for preset in EquipmentPreset.objects.filter(guiding_cameras=instance).iterator():
        preset.guiding_cameras.remove(instance)


@receiver(post_softdelete, sender=Telescope)
def remove_telescope_from_presets_after_deletion(sender, instance, **kwargs):
    preset: EquipmentPreset

    for preset in EquipmentPreset.objects.filter(imaging_telescopes=instance).iterator():
        preset.imaging_telescopes.remove(instance)

    for preset in EquipmentPreset.objects.filter(guiding_telescopes=instance).iterator():
        preset.guiding_telescopes.remove(instance)


@receiver(post_softdelete, sender=Mount)
def remove_mount_from_presets_after_deletion(sender, instance, **kwargs):
    preset: EquipmentPreset

    for preset in EquipmentPreset.objects.filter(mounts=instance).iterator():
        preset.mounts.remove(instance)


@receiver(post_softdelete, sender=Filter)
def remove_filter_from_presets_after_deletion(sender, instance, **kwargs):
    preset: EquipmentPreset

    for preset in EquipmentPreset.objects.filter(filters=instance).iterator():
        preset.filters.remove(instance)


@receiver(post_softdelete, sender=Accessory)
def remove_accessory_from_presets_after_deletion(sender, instance, **kwargs):
    preset: EquipmentPreset

    for preset in EquipmentPreset.objects.filter(accessories=instance).iterator():
        preset.accessories.remove(instance)


@receiver(post_softdelete, sender=Software)
def remove_software_from_presets_after_deletion(sender, instance, **kwargs):
    preset: EquipmentPreset

    for preset in EquipmentPreset.objects.filter(software=instance).iterator():
        preset.software.remove(instance)


@receiver(post_save, sender=SensorEditProposal)
@receiver(post_save, sender=CameraEditProposal)
@receiver(post_save, sender=TelescopeEditProposal)
@receiver(post_save, sender=MountEditProposal)
@receiver(post_save, sender=FilterEditProposal)
@receiver(post_save, sender=AccessoryEditProposal)
@receiver(post_save, sender=SoftwareEditProposal)
def send_edit_proposal_created_notification(sender, instance, created, **kwargs):
    if created and instance.edit_proposal_target.created_by:
        target = instance.edit_proposal_target
        owner = instance.edit_proposal_target.created_by
        user = instance.edit_proposal_by

        recipients = []

        if owner != user:
            recipients.append(owner)

        previous_proposals = User.objects.filter(
            **{
                f'astrobin_apps_equipment_{instance.__class__.__name__.lower()}_edit_proposals__'
                f'edit_proposal_target': target
            }
        )
        previous_proposals_reviewed = User.objects.filter(
            **{
                f'astrobin_apps_equipment_{instance.__class__.__name__.lower()}_edit_proposals_reviewed__'
                f'edit_proposal_target': target
            }
        )
        commenters = User.objects.filter(
            pk__in=NestedComment.objects.filter(
                content_type=ContentType.objects.get_for_model(instance.__class__),
                object_id__in=instance.__class__.objects.filter(edit_proposal_target=target)
            ).values_list('author', flat=True)
        )
        recipients.extend(list(previous_proposals))
        recipients.extend(list(previous_proposals_reviewed))
        recipients.extend(list(commenters))
        recipients = list(set(recipients))
        recipients.remove(user)

        if len(recipients) > 0:
            push_notification(
                recipients,
                user,
                'equipment-edit-proposal-created',
                {
                    'user': user.userprofile.get_display_name(),
                    'user_url': build_notification_url(
                        settings.BASE_URL + reverse('user_page', args=(user.username,))
                    ),
                    'item': f'{target.brand.name if target.brand else _("(DIY)")} {target.name}',
                    'item_url': build_notification_url(
                        AppRedirectionService.redirect(
                            f'/equipment'
                            f'/explorer'
                            f'/{target.item_type}/{target.pk}'
                            f'/{target.slug}'
                        )
                    ),
                    'edit_proposal_url': build_notification_url(
                        AppRedirectionService.redirect(
                            f'/equipment'
                            f'/explorer'
                            f'/{target.item_type}/{target.pk}'
                            f'/{target.slug}'
                            f'/edit-proposals'
                            f'/{instance.pk}/'
                        )
                    ),
                }
            )


@receiver(post_softdelete, sender=EquipmentBrand)
def rename_equipment_brand_after_deletion(sender, instance: EquipmentBrand, **kwargs):
    if '[DELETED] ' not in instance.name:
        instance.name = f'[DELETED] {instance.name} ({instance.pk}'
        instance.save(keep_deleted=True)


@receiver(post_softdelete, sender=EquipmentPreset)
def rename_equipment_preset_after_deletion(sender, instance: EquipmentPreset, **kwargs):
    if '[DELETED] ' not in instance.name:
        instance.name = f'[DELETED] {instance.name} ({instance.pk}'
        instance.save(keep_deleted=True)
