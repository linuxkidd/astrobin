from annoying.functions import get_object_or_None
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser

from astrobin_apps_equipment.api.filters.camera_edit_proposal_filter import CameraEditProposalFilter
from astrobin_apps_equipment.api.serializers.camera_edit_proposal_image_serializer import \
    CameraEditProposalImageSerializer
from astrobin_apps_equipment.api.serializers.camera_edit_proposal_serializer import CameraEditProposalSerializer
from astrobin_apps_equipment.api.views.equipment_item_edit_proposal_view_set import EquipmentItemEditProposalViewSet
from astrobin_apps_equipment.models import CameraEditProposal, Camera


class CameraEditProposalViewSet(EquipmentItemEditProposalViewSet):
    serializer_class = CameraEditProposalSerializer
    filter_class = CameraEditProposalFilter

    @action(
        detail=True,
        methods=['post'],
        serializer_class=CameraEditProposalImageSerializer,
        parser_classes=[MultiPartParser, FormParser],
    )
    def image(self, request, pk):
        return super(CameraEditProposalViewSet, self).image_upload(request, pk)

    @action(detail=True, methods=['POST'])
    def approve(self, request, pk):
        edit_proposal: CameraEditProposal = get_object_or_404(CameraEditProposal, pk=pk)

        check_permissions, response = self.check_edit_proposal_permissions(request, edit_proposal)
        if not check_permissions:
            return response

        camera = edit_proposal.edit_proposal_target
        camera.type = edit_proposal.type
        camera.sensor = edit_proposal.sensor
        camera.cooled = edit_proposal.cooled
        camera.max_cooling = edit_proposal.max_cooling
        camera.back_focus = edit_proposal.back_focus

        camera.save()

        response = super().approve(request, pk)

        # This needs to happen after we have saved the basic target (camera) information in the base class.

        if edit_proposal.create_modified_variant:
            camera = Camera.objects.get(pk=edit_proposal.edit_proposal_target.pk)
            variant = get_object_or_None(Camera, brand=camera.brand, name=camera.name, modified=True)
            if variant is not None:
                raise ValidationError("This camera already has an modified variant.")

            Camera.objects.create(
                modified=True,
                type=camera.type,
                sensor=camera.sensor,
                cooled=camera.cooled,
                max_cooling=camera.max_cooling,
                back_focus=camera.back_focus,
                created_by=request.user,
                brand=camera.brand,
                name=camera.name,
                image=camera.image,
            )

        return response

    class Meta(EquipmentItemEditProposalViewSet.Meta):
        abstract = False
