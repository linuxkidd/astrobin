import csv
import logging
import operator
import os
import urllib.error
import urllib.parse
import urllib.request
from functools import reduce

import flickrapi
import simplejson
from actstream.models import Action
from annoying.functions import get_object_or_None
from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.exceptions import MultipleObjectsReturned
from django.core.paginator import InvalidPage, Paginator
from django.db.models import Q
from django.forms.models import inlineformset_factory
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.template import RequestContext, loader
from django.template.defaultfilters import filesizeformat
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.datastructures import MultiValueDictKeyError
from django.utils.translation import ngettext as _n, ugettext as _
from django.views.decorators.cache import cache_control, cache_page, never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import last_modified, require_GET, require_POST
from django.views.decorators.vary import vary_on_cookie
from el_pagination.decorators import page_template
from flickrapi.auth import FlickrAccessToken
from haystack.query import SearchQuerySet
from silk.profiling.profiler import silk_profile

from astrobin.context_processors import common_variables, user_language
from astrobin.enums import SubjectType
from astrobin.forms import (
    AccessoryEditForm, AccessoryEditNewForm, CameraEditForm, CameraEditNewForm,
    DeepSky_AcquisitionBasicForm, DeepSky_AcquisitionForm, DefaultImageLicenseForm, DeleteAccountForm, FilterEditForm,
    FilterEditNewForm, FocalReducerEditForm, FocalReducerEditNewForm, GearUserInfoForm, ImageEditWatermarkForm,
    ImageLicenseForm, ImageRevisionUploadForm, ImageUploadForm, LocationEditForm, MountEditForm, MountEditNewForm,
    SoftwareEditForm, SoftwareEditNewForm, SolarSystem_AcquisitionForm, TelescopeEditForm, TelescopeEditNewForm,
    UserProfileEditBasicForm, UserProfileEditGearForm, UserProfileEditPreferencesForm,
)
from astrobin.forms.profile_edit_privacy_form import UserProfileEditPrivacyForm
from astrobin.gear import get_correct_gear, is_gear_complete
from astrobin.models import (
    Accessory, Acquisition, App, Camera, DeepSky_Acquisition, Filter, FocalReducer, Gear,
    GearUserInfo, Image, ImageRevision, Location, Mount, Software, SolarSystem_Acquisition, Telescope, UserProfile,
)
from astrobin.shortcuts import ajax_response, ajax_success
from astrobin.templatetags.tags import in_upload_wizard
from astrobin.utils import get_client_country_code
from astrobin_apps_images.services import ImageService
from astrobin_apps_platesolving.forms import PlateSolvingAdvancedSettingsForm, PlateSolvingSettingsForm
from astrobin_apps_platesolving.models import PlateSolvingSettings, Solution
from astrobin_apps_platesolving.services import SolutionService
from astrobin_apps_premium.templatetags.astrobin_apps_premium_tags import (
    can_perform_advanced_platesolving,
    can_restore_from_trash,
)
from astrobin_apps_premium.utils import (
    premium_get_max_allowed_image_size, premium_get_max_allowed_revisions,
    premium_user_has_valid_subscription,
)
from astrobin_apps_users.services import UserService
from common.services import AppRedirectionService, DateTimeService
from common.services.caching_service import CachingService
from common.services.constellations_service import ConstellationsService
from toggleproperties.models import ToggleProperty

log = logging.getLogger('apps')


def get_image_or_404(queryset, id):
    # hashes will always have at least a letter
    if id.isdigit():
        # old style numerical id
        image = get_object_or_404(queryset, pk=id)
        # if an image has a hash, we don't allow getting it by pk
        if image.hash is not None:
            raise Http404
        return image

    # we always allow getting by hash
    queryset = queryset.filter(hash=id)
    try:
        image = queryset.get()
    except queryset.model.DoesNotExist:
        raise Http404

    return image


def object_list(request, queryset, paginate_by=None, page=None,
                allow_empty=True, template_name=None, template_loader=loader,
                extra_context=None, context_processors=None, template_object_name='object',
                mimetype=None):
    """
    Generic list of objects.

    Templates: ``<app_label>/<model_name>_list.html``
    Context:
        object_list
            list of objects
        is_paginated
            are the results paginated?
        results_per_page
            number of objects per page (if paginated)
        has_next
            is there a next page?
        has_previous
            is there a prev page?
        page
            the current page
        next
            the next page
        previous
            the previous page
        pages
            number of pages, total
        hits
            number of objects, total
        last_on_page
            the result number of the last of object in the
            object_list (1-indexed)
        first_on_page
            the result number of the first object in the
            object_list (1-indexed)
        page_range:
            A list of the page numbers (1-indexed).
    """
    if extra_context is None: extra_context = {}

    queryset = queryset._clone()

    if paginate_by:
        paginator = Paginator(queryset, paginate_by, allow_empty_first_page=allow_empty)

        if not page:
            page = request.GET.get('page', 1)

        try:
            page_number = int(page)
        except ValueError:
            if page == 'last':
                page_number = paginator.num_pages
            else:
                # Page is not 'last', nor can it be converted to an int.
                raise Http404
        try:
            page_obj = paginator.page(page_number)
        except InvalidPage:
            raise Http404

        c = RequestContext(request, {
            '%s_list' % template_object_name: page_obj.object_list,
            'paginator': paginator,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),

            # Legacy template context stuff. New templates should use page_obj
            # to access this instead.
            'results_per_page': paginator.per_page,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'page': page_obj.number,
            'next': page_obj.next_page_number() if page_obj.has_next() else None,
            'previous': page_obj.previous_page_number() if page_obj.has_previous() else None,
            'first_on_page': page_obj.start_index(),
            'last_on_page': page_obj.end_index(),
            'pages': paginator.num_pages,
            'hits': paginator.count,
            'page_range': paginator.page_range,
        }, context_processors)
    else:
        c = RequestContext(request, {
            '%s_list' % template_object_name: queryset,
            'paginator': None,
            'page_obj': None,
            'is_paginated': False,
        }, context_processors)

        if not allow_empty and len(queryset) == 0:
            raise Http404

    for key, value in list(extra_context.items()):
        if callable(value):
            c[key] = value()
        else:
            c[key] = value

    if not template_name:
        model = queryset.model
        template_name = "%s/%s_list.html" % (model._meta.app_label, model._meta.object_name.lower())

    t = template_loader.get_template(template_name)

    context = c.flatten()
    context.update(user_language(request))
    context.update(common_variables(request))

    return HttpResponse(t.render(context, request))


def monthdelta(date, delta):
    m, y = (date.month + delta) % 12, date.year + ((date.month) + delta - 1) // 12
    if not m: m = 12
    d = [31,
         29 if y % 4 == 0 and not y % 400 == 0 else 28,
         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date.replace(day=d, month=m, year=y)


def valueReader(source, field):
    def unicode_truncate(s, length, encoding='utf-8'):
        encoded = s.encode(encoding)[:length]
        return encoded.decode(encoding, 'ignore')

    def utf_8_encoder(data):
        for line in data:
            yield line.encode('utf-8')

    as_field = 'as_values_' + field
    value = ''
    if as_field in source:
        value += source[as_field]
    if field in source:
        value += ',' + source[field]

    if not (as_field in source or field in source):
        return [], ""

    items = []
    reader = csv.reader(utf_8_encoder([value]),
                        skipinitialspace=True)
    for row in reader:
        items += [unicode_truncate(str(x, 'utf-8'), 64) for x in row if x != '']

    return items, value


def get_or_create_location(prop, value):
    k = None
    created = False

    try:
        return Location.objects.get(id=value)
    except ValueError:
        pass

    try:
        k, created = Location.objects.get_or_create(**{prop: value})
    except MultipleObjectsReturned:
        k = Location.objects.filter(**{prop: value})[0]

    if created:
        k.user_generated = True
        k.save()

    return k


def jsonDump(all):
    if len(all) > 0:
        return simplejson.dumps([{'id': i.id, 'name': i.get_name(), 'complete': is_gear_complete(i.id)} for i in all])
    else:
        return []


def upload_error(request, image=None, errors=None):
    message = _("Invalid image or no image provided. Allowed formats are JPG, PNG and GIF.")

    if errors and 'image_file' in errors and errors['image_file'][0]:
        message += " " + errors['image_file'][0]

    messages.error(request, message)

    log.warning("Upload error (%d): %s" % (request.user.pk, message))

    if image is not None:
        url = image.get_absolute_url()
    else:
        url = '/upload/?forceClassicUploader'

    return HttpResponseRedirect(url)


def upload_size_error(request, max_size, image=None):
    subscriptions_url = "https://welcome.astrobin.com/pricing"
    open_link = "<a href=\"%s\" target=\"blank\">" % subscriptions_url
    close_link = "</a>"
    msg = "Sorry, but this image is too large. Under your current subscription plan, the maximum allowed image size " \
          "is %(max_size)s. %(open_link)sWould you like to upgrade?%(close_link)s"
    compiled_msg = _(msg) % {
        "max_size": filesizeformat(max_size),
        "open_link": open_link,
        "close_link": close_link
    }

    messages.error(request, compiled_msg)

    log.warning("Upload error (%d): %s" % (request.user.pk, compiled_msg))

    if image is not None:
        return HttpResponseRedirect(image.get_absolute_url())

    return HttpResponseRedirect('/upload/?forceClassicUploader')


def upload_max_revisions_error(request, max_revisions, image):
    subscriptions_url = "https://welcome.astrobin.com/pricing"
    open_link = "<a href=\"%s\" target=\"_blank\">" % subscriptions_url
    close_link = "</a>"
    msg_singular = "Sorry, but you have reached the maximum amount of allowed image revisions. Under your current subscription, the limit is %(max_revisions)s revision per image. %(open_link)sWould you like to upgrade?%(close_link)s"
    msg_plural = "Sorry, but you have reached the maximum amount of allowed image revisions. Under your current subscription, the limit is %(max_revisions)s revisions per image. %(open_link)sWould you like to upgrade?%(close_link)s"

    messages.error(request, _n(msg_singular, msg_plural, max_revisions) % {
        "max_revisions": max_revisions,
        "open_link": open_link,
        "close_link": close_link
    })

    return HttpResponseRedirect(image.get_absolute_url())


# VIEWS

@cache_page(120)
@vary_on_cookie
@cache_control(private=True)
@page_template('index/stream_page.html', key='stream_page')
@page_template('index/recent_images_page.html', key='recent_images_page')
@silk_profile('Index')
def index(request, template='index/root.html', extra_context=None):
    """Main page"""

    if not request.user.is_authenticated:
        from django.shortcuts import redirect
        return redirect("https://welcome.astrobin.com/")

    image_ct = ContentType.objects.get_for_model(Image)
    image_rev_ct = ContentType.objects.get_for_model(ImageRevision)
    user_ct = ContentType.objects.get_for_model(User)

    recent_images = Image.objects \
        .filter(Q(~Q(title=None) & ~Q(title='') & Q(moderator_decision=1) & Q(published__isnull=False))) \
        .order_by('-published')

    response_dict = {
        'recent_images': recent_images,
        'recent_images_alias': 'gallery',
        'recent_images_batch_size': 70,
        'section': 'recent',
    }

    profile = request.user.userprofile

    section = request.GET.get('s')
    if section is None:
        section = profile.default_frontpage_section
    response_dict['section'] = section

    if section == 'global':
        ##################
        # GLOBAL ACTIONS #
        ##################
        actions = Action.objects.all().prefetch_related(
            'actor__userprofile',
            'target_content_type',
            'target')
        response_dict['actions'] = actions
        response_dict['cache_prefix'] = 'astrobin_global_actions'

    elif section == 'personal':
        ####################
        # PERSONAL ACTIONS #
        ####################
        cache_key = 'astrobin_users_image_ids_%s' % request.user
        users_image_ids = cache.get(cache_key)
        if users_image_ids is None:
            users_image_ids = [
                str(x) for x in
                Image.objects.filter(
                    user=request.user).values_list('id', flat=True)
            ]
            cache.set(cache_key, users_image_ids, 300)

        cache_key = 'astrobin_users_revision_ids_%s' % request.user
        users_revision_ids = cache.get(cache_key)
        if users_revision_ids is None:
            users_revision_ids = [
                str(x) for x in
                ImageRevision.objects.filter(
                    image__user=request.user).values_list('id', flat=True)
            ]
            cache.set(cache_key, users_revision_ids, 300)

        cache_key = 'astrobin_followed_user_ids_%s' % request.user
        followed_user_ids = cache.get(cache_key)
        if followed_user_ids is None:
            followed_user_ids = [
                str(x) for x in
                ToggleProperty.objects.filter(
                    property_type="follow",
                    user=request.user,
                    content_type=ContentType.objects.get_for_model(User)
                ).values_list('object_id', flat=True)
            ]
            cache.set(cache_key, followed_user_ids, 900)
        response_dict['has_followed_users'] = len(followed_user_ids) > 0

        cache_key = 'astrobin_followees_image_ids_%s' % request.user
        followees_image_ids = cache.get(cache_key)
        if followees_image_ids is None:
            followees_image_ids = [
                str(x) for x in
                Image.objects.filter(user_id__in=followed_user_ids).values_list('id', flat=True)
            ]
            cache.set(cache_key, followees_image_ids, 900)

        actions = Action.objects \
            .prefetch_related(
            'actor__userprofile',
            'target_content_type',
            'target'
        ).filter(
            # Actor is user, or...
            Q(
                Q(actor_content_type=user_ct) &
                Q(actor_object_id=request.user.id)
            ) |

            # Action concerns user's images as target, or...
            Q(
                Q(target_content_type=image_ct) &
                Q(target_object_id__in=users_image_ids)
            ) |
            Q(
                Q(target_content_type=image_rev_ct) &
                Q(target_object_id__in=users_revision_ids)
            ) |

            # Action concerns user's images as object, or...
            Q(
                Q(action_object_content_type=image_ct) &
                Q(action_object_object_id__in=users_image_ids)
            ) |
            Q(
                Q(action_object_content_type=image_rev_ct) &
                Q(action_object_object_id__in=users_revision_ids)
            ) |

            # Actor is somebody the user follows, or...
            Q(
                Q(actor_content_type=user_ct) &
                Q(actor_object_id__in=followed_user_ids)
            ) |

            # Action concerns an image by a followed user...
            Q(
                Q(target_content_type=image_ct) &
                Q(target_object_id__in=followees_image_ids)
            ) |
            Q(
                Q(action_object_content_type=image_ct) &
                Q(action_object_object_id__in=followees_image_ids)
            )
        )
        response_dict['actions'] = actions
        response_dict['cache_prefix'] = 'astrobin_personal_actions'

    elif section == 'followed':
        followed = [x.object_id for x in ToggleProperty.objects.filter(
            property_type="follow",
            content_type=ContentType.objects.get_for_model(User),
            user=request.user)]

        response_dict['recent_images'] = recent_images.filter(user__in=followed)

    if extra_context is not None:
        response_dict.update(extra_context)

    return render(request, template, response_dict)


@never_cache
@login_required
def image_upload(request):
    if not settings.TESTING and "forceClassicUploader" not in request.GET:
        return redirect(AppRedirectionService.redirect("/uploader"))

    from astrobin_apps_premium.utils import (
        premium_used_percent,
        premium_progress_class,
        premium_user_has_subscription,
        premium_user_has_invalid_subscription,
    )

    tmpl_premium_used_percent = premium_used_percent(request.user)
    tmpl_premium_progress_class = premium_progress_class(tmpl_premium_used_percent)
    tmpl_premium_has_inactive_subscription = \
        premium_user_has_subscription(request.user) and \
        premium_user_has_invalid_subscription(request.user) and \
        not premium_user_has_valid_subscription(request.user)

    response_dict = {
        'premium_used_percent': tmpl_premium_used_percent,
        'premium_progress_class': tmpl_premium_progress_class,
        'premium_has_inactive_subscription': tmpl_premium_has_inactive_subscription,
    }

    if tmpl_premium_used_percent < 100:
        response_dict['upload_form'] = ImageUploadForm()

    return render(request, "upload.html", response_dict)


@never_cache
@login_required
@require_POST
def image_upload_process(request):
    """Process the form"""

    from astrobin_apps_premium.utils import premium_used_percent

    log.info("Classic uploader (%d): submitted" % request.user.pk)

    used_percent = premium_used_percent(request.user)
    if used_percent >= 100:
        messages.error(request, _("You have reached your image count limit. Please upgrade!"))
        return HttpResponseRedirect('/upload/?forceClassicUploader')

    if settings.READONLY_MODE:
        messages.error(request, _(
            "AstroBin is currently in read-only mode, because of server maintenance. Please try again soon!"))
        return HttpResponseRedirect('/upload/?forceClassicUploader')

    if 'image_file' not in request.FILES:
        return upload_error(request)

    form = ImageUploadForm(request.POST, request.FILES)

    if not form.is_valid():
        return upload_error(request, None, form.errors)

    image_file = request.FILES["image_file"]
    ext = os.path.splitext(image_file.name)[1].lower()

    if ext not in settings.ALLOWED_IMAGE_EXTENSIONS:
        return upload_error(request)

    max_size = premium_get_max_allowed_image_size(request.user)
    if image_file.size > max_size:
        return upload_size_error(request, max_size)

    if image_file.size < 1e+7:
        try:
            from PIL import Image as PILImage
            trial_image = PILImage.open(image_file)
            trial_image.verify()
            image_file.file.seek(0)  # Because we opened it with PIL

            if ext == '.png' and trial_image.mode == 'I':
                indexed_png_error = "You uploaded an Indexed PNG file. AstroBin will need to lower the color count " \
                                    "to 256 in order to work with it."
                messages.warning(request, _(indexed_png_error))
                log.warning("Upload error (%d): %s" % (request.user.pk, indexed_png_error))
        except Exception as e:
            log.warning("Upload error (%d): %s" % (request.user.pk, str(e)))
            return upload_error(request)

    profile = request.user.userprofile
    image = form.save(commit=False)
    image.user = request.user
    image.license = profile.default_license

    if 'wip' in request.POST:
        image.is_wip = True

    image.save(keep_deleted=True)

    return HttpResponseRedirect(reverse('image_edit_thumbnails', kwargs={'id': image.get_id()}))


@never_cache
@login_required
@require_GET
def image_edit_watermark(request, id):
    image = get_image_or_404(Image.objects_including_wip, id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    profile = image.user.userprofile
    if not profile.default_watermark_text or profile.default_watermark_text == '':
        profile.default_watermark_text = "Copyright %s" % image.user.username
        profile.save(keep_deleted=True)

    image.watermark = profile.default_watermark
    image.watermark_text = profile.default_watermark_text
    image.watermark_position = profile.default_watermark_position
    image.watermark_size = profile.default_watermark_size
    image.watermark_opacity = profile.default_watermark_opacity

    form = ImageEditWatermarkForm(instance=image)

    return render(request, 'image/edit/watermark.html', {
        'image': image,
        'form': form,
    })


@never_cache
@login_required
@require_GET
def image_edit_acquisition(request, id):
    image = get_image_or_404(Image.objects_including_wip, id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    from astrobin_apps_platesolving.solver import Solver

    dsa_qs = DeepSky_Acquisition.objects.filter(image=image)
    solar_system_acquisition = None

    try:
        solar_system_acquisition = SolarSystem_Acquisition.objects.get(image=image)
    except:
        pass

    if dsa_qs:
        edit_type = 'deep_sky'
    elif solar_system_acquisition:
        edit_type = 'solar_system'
    elif 'edit_type' in request.GET:
        edit_type = request.GET['edit_type']
    else:
        edit_type = None

    deep_sky_acquisition_formset = None
    deep_sky_acquisition_basic_form = None
    advanced = False
    if edit_type == 'deep_sky' or (image.solution and image.solution.status != Solver.FAILED):
        advanced = request.GET.get('advanced', 'false') == 'true' or dsa_qs.count() > 0

        if advanced:
            extra = 0
            if 'add_more' in request.GET:
                extra = 1
            if not dsa_qs:
                extra = 1
            DSAFormSet = inlineformset_factory(
                Image, DeepSky_Acquisition, extra=extra, form=DeepSky_AcquisitionForm
            )
            deep_sky_acquisition_formset = DSAFormSet(
                instance=image,
                form_kwargs={'user': request.user},
                queryset=DeepSky_Acquisition.objects.filter(image=image).order_by('pk')
            )
        else:
            dsa = dsa_qs[0] if dsa_qs else DeepSky_Acquisition({image: image, advanced: False})
            deep_sky_acquisition_basic_form = DeepSky_AcquisitionBasicForm(instance=dsa)

    response_dict = {
        'image': image,
        'edit_type': edit_type,
        'ssa_form': SolarSystem_AcquisitionForm(instance=solar_system_acquisition),
        'deep_sky_acquisitions': deep_sky_acquisition_formset,
        'deep_sky_acquisition_basic_form': deep_sky_acquisition_basic_form,
        'advanced': advanced,
        'solar_system_acquisition': solar_system_acquisition,
    }

    return render(request, 'image/edit/acquisition.html', response_dict)


@never_cache
@login_required
@require_GET
def image_edit_acquisition_reset(request, id):
    image = get_image_or_404(Image.objects_including_wip, id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    DeepSky_Acquisition.objects.filter(image=image).delete()
    SolarSystem_Acquisition.objects.filter(image=image).delete()

    response_dict = {
        'image': image,
        'deep_sky_acquisition_basic_form': DeepSky_AcquisitionBasicForm(),
    }
    return render(request, 'image/edit/acquisition.html', response_dict)


@never_cache
@login_required
@require_GET
def image_edit_make_final(request, id):
    image = get_image_or_404(Image.objects_including_wip, id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    revisions = ImageRevision.all_objects.filter(image=image)
    for r in revisions:
        r.is_final = False
        r.save(keep_deleted=True)
    image.is_final = True
    image.save(keep_deleted=True)

    return HttpResponseRedirect(image.get_absolute_url())


@never_cache
@login_required
@require_GET
def image_edit_revision_make_final(request, id):
    r = get_object_or_404(ImageRevision, pk=id)
    if request.user != r.image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    other = ImageRevision.all_objects.filter(image=r.image)
    for i in other:
        i.is_final = False
        i.save(keep_deleted=True)

    r.image.is_final = False
    r.image.save(keep_deleted=True)

    r.is_final = True
    r.save(keep_deleted=True)

    return HttpResponseRedirect('/%s/%s/' % (r.image.get_id(), r.label))


@login_required
@require_GET
def image_edit_license(request, id):
    image = get_image_or_404(Image.objects_including_wip, id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    form = ImageLicenseForm(instance=image)
    return render(request, 'image/edit/license.html', {
        'form': form,
        'image': image
    })


@never_cache
@login_required
def image_edit_platesolving_settings(request, id, revision_label):
    image = get_image_or_404(Image.objects_including_wip, id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    if revision_label in (None, 'None', '0'):
        url = reverse('image_edit_platesolving_settings', args=(image.get_id(),))
        if image.revisions.count() > 0:
            return_url = reverse('image_detail', args=(image.get_id(), '0',))
        else:
            return_url = reverse('image_detail', args=(image.get_id(),))
        solution, created = Solution.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(Image),
            object_id=image.pk)
    else:
        url = reverse('image_edit_platesolving_settings', args=(image.get_id(), revision_label,))
        return_url = reverse('image_detail', args=(image.get_id(), revision_label,))
        revision = ImageRevision.objects.get(image=image, label=revision_label)
        solution, created = Solution.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(ImageRevision),
            object_id=revision.pk)

    settings = solution.settings
    if settings is None:
        solution.settings = PlateSolvingSettings.objects.create()
        solution.save()

    if request.method == 'GET':
        form = PlateSolvingSettingsForm(instance=settings)
        return render(request, 'image/edit/platesolving_settings.html', {
            'form': form,
            'image': image,
            'revision_label': revision_label,
            'return_url': return_url,
        })

    if request.method == 'POST':
        form = PlateSolvingSettingsForm(instance=settings, data=request.POST)
        if not form.is_valid():
            messages.error(
                request,
                _("There was one or more errors processing the form. You may need to scroll down to see them."))
            return render(request, 'image/edit/platesolving_settings.html', {
                'form': form,
                'image': image,
                'revision_label': revision_label,
                'return_url': return_url,
            })

        form.save()
        solution.clear()

        messages.success(
            request,
            _("Form saved. A new plate-solving process will start now."))
        return HttpResponseRedirect(return_url)


@never_cache
@login_required
def image_edit_platesolving_advanced_settings(request, id, revision_label):
    image = get_image_or_404(Image.objects_including_wip, id)
    if request.user != image.user and not request.user.is_superuser and not can_perform_advanced_platesolving(
            image.user):
        return HttpResponseForbidden()

    if revision_label in (None, 'None', '0'):
        if image.revisions.count() > 0:
            return_url = reverse('image_detail', args=(image.get_id(), '0',))
        else:
            return_url = reverse('image_detail', args=(image.get_id(),))
        solution, created = Solution.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(Image),
            object_id=image.pk)
        advanced_settings = solution.advanced_settings
        if advanced_settings is None:
            solution.advanced_settings, created = SolutionService.get_or_create_advanced_settings(image)
            solution.save()
    else:
        return_url = reverse('image_detail', args=(image.get_id(), revision_label,))
        revision = ImageRevision.objects.get(image=image, label=revision_label)
        solution, created = Solution.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(ImageRevision),
            object_id=revision.pk)
        advanced_settings = solution.advanced_settings
        if advanced_settings is None:
            solution.advanced_settings, created = SolutionService.get_or_create_advanced_settings(revision)
            solution.save()

    if request.method == 'GET':
        form = PlateSolvingAdvancedSettingsForm(instance=advanced_settings)
        return render(request, 'image/edit/platesolving_advanced_settings.html', {
            'form': form,
            'image': image,
            'revision_label': revision_label,
            'return_url': return_url,
        })

    if request.method == 'POST':
        form = PlateSolvingAdvancedSettingsForm(request.POST or None, request.FILES or None, instance=advanced_settings)
        if not form.is_valid():
            messages.error(
                request,
                _("There was one or more errors processing the form. You may need to scroll down to see them."))
            return render(request, 'image/edit/platesolving_advanced_settings.html', {
                'form': form,
                'image': image,
                'revision_label': revision_label,
                'return_url': return_url,
            })

        form.save()
        solution.clear_advanced()

        messages.success(
            request,
            _("Form saved. A new advanced plate-solving process will start now."))
        return HttpResponseRedirect(return_url)


@login_required
def image_restart_platesolving(request, id, revision_label):
    image = get_image_or_404(Image.objects_including_wip, id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    if revision_label in (None, 'None', '0'):
        if image.revisions.count() > 0:
            return_url = reverse('image_detail', args=(image.get_id(), '0',))
        else:
            return_url = reverse('image_detail', args=(image.get_id(),))
        solution, created = Solution.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(Image),
            object_id=image.pk)
    else:
        return_url = reverse('image_detail', args=(image.get_id(), revision_label,))
        revision = ImageRevision.objects.get(image=image, label=revision_label)
        solution, created = Solution.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(ImageRevision),
            object_id=revision.pk)

    solution.delete()

    return HttpResponseRedirect(return_url)


@never_cache
@login_required
def image_restart_advanced_platesolving(request, id, revision_label):
    image = get_image_or_404(Image.objects_including_wip, id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    if revision_label in (None, 'None', '0'):
        if image.revisions.count() > 0:
            return_url = reverse('image_detail', args=(image.get_id(), '0',))
        else:
            return_url = reverse('image_detail', args=(image.get_id(),))
        solution, created = Solution.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(Image),
            object_id=image.pk)
    else:
        return_url = reverse('image_detail', args=(image.get_id(), revision_label,))
        revision = ImageRevision.objects.get(image=image, label=revision_label)
        solution, created = Solution.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(ImageRevision),
            object_id=revision.pk)

    solution.clear_advanced()

    return HttpResponseRedirect(return_url)


@never_cache
@login_required
@require_POST
def image_edit_save_watermark(request):
    try:
        image_id = request.POST['image_id']
    except MultiValueDictKeyError:
        raise Http404

    image: Image = get_image_or_404(Image.objects_including_wip, image_id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    form = ImageEditWatermarkForm(data=request.POST, instance=image)
    if not form.is_valid():
        messages.error(request,
                       _("There was one or more errors processing the form. You may need to scroll down to see them."))
        return render(request, 'image/edit/watermark.html', {
            'image': image,
            'form': form,
        })

    form.save()

    # Save defaults in profile
    profile: UserProfile = image.user.userprofile
    profile.default_watermark = form.cleaned_data['watermark']
    profile.default_watermark_text = form.cleaned_data['watermark_text']
    profile.default_watermark_position = form.cleaned_data['watermark_position']
    profile.default_watermark_size = form.cleaned_data['watermark_size']
    profile.default_watermark_opacity = form.cleaned_data['watermark_opacity']
    profile.save(keep_deleted=True)

    if in_upload_wizard(image, request):
        return HttpResponseRedirect(
            reverse('image_edit_basic', kwargs={'id': image.get_id()}) + "?upload")

    # Force new thumbnails
    image.thumbnail_invalidate()
    revision: ImageRevision
    for revision in ImageService(image).get_revisions():
        revision.thumbnail_invalidate()

    return HttpResponseRedirect(image.get_absolute_url())


@never_cache
@login_required
@require_POST
def image_edit_save_acquisition(request):
    try:
        image_id = request.POST['image_id']
    except MultiValueDictKeyError:
        raise Http404

    image = get_image_or_404(Image.objects_including_wip, image_id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    edit_type = request.POST.get('edit_type')
    advanced = request.POST['advanced'] if 'advanced' in request.POST else False
    advanced = True if advanced == 'true' else False

    response_dict = {
        'image': image,
        'edit_type': edit_type,
    }

    dsa_qs = DeepSky_Acquisition.objects.filter(image=image)

    for a in SolarSystem_Acquisition.objects.filter(image=image):
        a.delete()

    if edit_type == 'deep_sky' or image.solution:
        if advanced:
            DSAFormSet = inlineformset_factory(
                Image,
                DeepSky_Acquisition,
                form=DeepSky_AcquisitionForm
            )

            saving_data = {}

            for i in request.POST:
                saving_data[i] = request.POST[i]

            for i in range(0, int(saving_data['deepsky_acquisition_set-INITIAL_FORMS'])):
                id = saving_data[f'deepsky_acquisition_set-{i}-acquisition_ptr']
                if id and get_object_or_None(DeepSky_Acquisition, id=id) is None:
                    obj = DeepSky_Acquisition.objects.create(
                        date=saving_data[f'deepsky_acquisition_set-{i}-date'] or None,
                        image=Image.objects_including_wip.get(id=saving_data[f'deepsky_acquisition_set-{i}-image']),
                        is_synthetic=saving_data[
                            f'deepsky_acquisition_set-{i}-is_synthetic'] if f'deepsky_acquisition_set-{i}-is_synthetic' in saving_data else False,
                        filter=get_object_or_None(Filter, id=saving_data[f'deepsky_acquisition_set-{i}-filter']) \
                            if saving_data[f'deepsky_acquisition_set-{i}-filter'] \
                            else None,
                        binning=saving_data[f'deepsky_acquisition_set-{i}-binning'] or None,
                        number=saving_data[f'deepsky_acquisition_set-{i}-number'],
                        duration=saving_data[f'deepsky_acquisition_set-{i}-duration'],
                        iso=saving_data[f'deepsky_acquisition_set-{i}-iso'] or None,
                        gain=saving_data[f'deepsky_acquisition_set-{i}-gain'] or None,
                        sensor_cooling=saving_data[f'deepsky_acquisition_set-{i}-sensor_cooling'] or None,
                        darks=saving_data[f'deepsky_acquisition_set-{i}-darks'] or None,
                        flats=saving_data[f'deepsky_acquisition_set-{i}-flats'] or None,
                        flat_darks=saving_data[f'deepsky_acquisition_set-{i}-flat_darks'] or None,
                        bias=saving_data[f'deepsky_acquisition_set-{i}-bias'] or None,
                        bortle=saving_data[f'deepsky_acquisition_set-{i}-bortle'] or None,
                        mean_sqm=saving_data[f'deepsky_acquisition_set-{i}-mean_sqm'] or None,
                        mean_fwhm=saving_data[f'deepsky_acquisition_set-{i}-mean_fwhm'] or None,
                        temperature=saving_data[f'deepsky_acquisition_set-{i}-temperature'] or None,
                        advanced=True,
                    )
                    saving_data[f'deepsky_acquisition_set-{i}-acquisition_ptr'] = obj.acquisition_ptr.id

            saving_data['advanced'] = advanced
            deep_sky_acquisition_formset = DSAFormSet(
                saving_data,
                instance=image,
                form_kwargs={'user': request.user},
                queryset=DeepSky_Acquisition.objects.filter(image=image).order_by('pk')
            )
            response_dict['deep_sky_acquisitions'] = deep_sky_acquisition_formset
            response_dict['advanced'] = True

            if deep_sky_acquisition_formset.is_valid():
                deep_sky_acquisition_formset.save()
                if 'add_more' in request.POST:
                    DSAFormSet = inlineformset_factory(
                        Image, DeepSky_Acquisition, extra=1, form=DeepSky_AcquisitionForm
                    )
                    deep_sky_acquisition_formset = DSAFormSet(
                        instance=image,
                        form_kwargs={'user': request.user},
                        queryset=DeepSky_Acquisition.objects.filter(image=image).order_by('pk')
                    )
                    response_dict['deep_sky_acquisitions'] = deep_sky_acquisition_formset
                    response_dict['next_acquisition_session'] = deep_sky_acquisition_formset.total_form_count() - 1
                    if not dsa_qs:
                        messages.info(request, _("Fill in one session, before adding more."))
                    return render(request, 'image/edit/acquisition.html', response_dict)
            else:
                messages.error(
                    request,
                    _("There was one or more errors processing the form. You may need to scroll down to see them.")
                )
                return render(request, 'image/edit/acquisition.html', response_dict)
        else:
            DeepSky_Acquisition.objects.filter(image=image).delete()
            dsa = DeepSky_Acquisition()
            dsa.image = image
            deep_sky_acquisition_basic_form = DeepSky_AcquisitionBasicForm(data=request.POST, instance=dsa)
            if deep_sky_acquisition_basic_form.is_valid():
                deep_sky_acquisition_basic_form.save()
            else:
                messages.error(request, _(
                    "There was one or more errors processing the form. You may need to scroll down to see them."))
                response_dict['deep_sky_acquisition_basic_form'] = deep_sky_acquisition_basic_form
                return render(request, 'image/edit/acquisition.html', response_dict)

    elif edit_type == 'solar_system':
        ssa = SolarSystem_Acquisition(image=image)
        form = SolarSystem_AcquisitionForm(data=request.POST, instance=ssa)
        response_dict['ssa_form'] = form
        if not form.is_valid():
            response_dict['ssa_form'] = form
            messages.error(request, _(
                "There was one or more errors processing the form. You may need to scroll down to see them."))
            return render(request, 'image/edit/acquisition.html', response_dict)
        form.save()

    messages.success(request, _("Form saved. Thank you!"))
    return HttpResponseRedirect(image.get_absolute_url())


@never_cache
@login_required
@require_POST
def image_edit_save_license(request):
    try:
        image_id = request.POST['image_id']
    except MultiValueDictKeyError:
        raise Http404

    image = get_image_or_404(Image.objects_including_wip, image_id)
    if request.user != image.user and not request.user.is_superuser:
        return HttpResponseForbidden()

    form = ImageLicenseForm(data=request.POST, instance=image)
    if not form.is_valid():
        messages.error(request,
                       _("There was one or more errors processing the form. You may need to scroll down to see them."))
        return render(request, 'image/edit/license.html', {
            'form': form,
            'image': image
        })

    form.save()

    messages.success(request, _("Form saved. Thank you!"))
    return HttpResponseRedirect(image.get_absolute_url())


@never_cache
@login_required
@require_GET
def me(request):
    return HttpResponseRedirect('/users/%s/?%s' % (request.user.username, request.META['QUERY_STRING']))


@require_GET
@last_modified(CachingService.get_user_page_last_modified)
@cache_control(private=True, no_cache=True)
@vary_on_cookie
@silk_profile('User page')
def user_page(request, username):
    try:
        user = UserService.get_case_insensitive(username)
    except User.DoesNotExist:
        raise Http404

    if user.username != username:
        return HttpResponseRedirect(reverse('user_page', args=(user.username,)))

    profile = user.userprofile

    if profile.deleted:
        raise Http404

    if Image.objects_including_wip.filter(user=user, moderator_decision=2).count() > 0:
        if (not request.user.is_authenticated or \
                not request.user.is_superuser and \
                not request.user.userprofile.is_image_moderator()):
            raise Http404

    user_ct = ContentType.objects.get_for_model(User)

    section = 'public'
    subsection = request.GET.get('sub')
    if subsection is None:
        subsection = profile.default_gallery_sorting
        if subsection == 1:
            subsection = 'acquired'
        elif subsection == 2:
            subsection = 'subject'
        elif subsection == 3:
            subsection = 'year'
        elif subsection == 4:
            subsection = 'gear'
        elif subsection == 5:
            subsection = 'collections'
        elif subsection == 6:
            subsection = 'title'
        elif subsection == 7:
            subsection = 'constellation'
        else:
            subsection = 'uploaded'

    if subsection == 'collections':
        return HttpResponseRedirect(reverse('user_collections_list', args=(username,)))

    active = request.GET.get('active')
    menu = []

    if user.userprofile.display_wip_images_on_public_gallery in (None, True):
        qs = UserService(user).get_all_images()
    else:
        qs = UserService(user).get_public_images()
    wip_qs = UserService(user).get_wip_images()

    if request.user != user:
        qs = qs.exclude(is_wip=True)

    if 'staging' in request.GET:
        if request.user != user and not request.user.is_superuser:
            return HttpResponseForbidden()
        qs = wip_qs
        section = 'staging'
        subsection = None
    elif 'trash' in request.GET:
        if request.user != user or not can_restore_from_trash(request.user) and not request.user.is_superuser:
            return HttpResponseForbidden()
        qs = Image.deleted_objects.filter(user=user)
        section = 'trash'
        subsection = None
    else:
        #########
        # TITLE #
        #########
        if subsection == 'title':
            qs = qs.order_by('title')

        ############
        # UPLOADED #
        ############
        if subsection == 'uploaded':
            qs = qs.order_by('-published', '-uploaded')

        ############
        # ACQUIRED #
        ############
        elif subsection == 'acquired':
            last_acquisition_date_sql = 'SELECT date FROM astrobin_acquisition ' \
                                        'WHERE date IS NOT NULL AND image_id = astrobin_image.id ' \
                                        'ORDER BY date DESC ' \
                                        'LIMIT 1'
            qs = qs \
                .filter(acquisition__isnull=False) \
                .extra(
                select={'last_acquisition_date': last_acquisition_date_sql},
                order_by=['-last_acquisition_date', '-published']) \
                .distinct()

        ########
        # YEAR #
        ########
        elif subsection == 'year':
            acquisitions = Acquisition.objects.filter(
                image__user=user,
                image__is_wip=False,
                image__deleted=None)
            if acquisitions:
                distinct_years = sorted(list(set([a.date.year for a in acquisitions if a.date])), reverse=True)
                no_date_message = _("No date specified")
                menu = [(str(year), str(year)) for year in distinct_years] + [('0', no_date_message)]

                if active == '0':
                    qs = qs.filter(
                        Q(subject_type__in=(
                            SubjectType.DEEP_SKY,
                            SubjectType.SOLAR_SYSTEM,
                            SubjectType.WIDE_FIELD,
                            SubjectType.STAR_TRAILS,
                            SubjectType.NORTHERN_LIGHTS,
                            SubjectType.OTHER
                        )) &
                        Q(acquisition=None) | Q(acquisition__date=None)).distinct()
                else:
                    if active is None and distinct_years:
                        active = str(distinct_years[0])

                    if active:
                        qs = qs.filter(acquisition__date__year=active).order_by('-published').distinct()

        ########
        # GEAR #
        ########
        elif subsection == 'gear':
            telescopes = profile.telescopes.all()
            cameras = profile.cameras.all()

            no_date_message = _("No imaging telescopes or lenses, or no imaging cameras specified")
            gi = _("Gear images")

            menu += [(x.id, str(x)) for x in telescopes]
            menu += [(x.id, str(x)) for x in cameras]
            menu += [(0, no_date_message)]
            menu += [(-1, gi)]

            if active == '0':
                qs = qs.filter(
                    (Q(subject_type=SubjectType.DEEP_SKY) | Q(subject_type=SubjectType.SOLAR_SYSTEM)) &
                    (Q(imaging_telescopes=None) | Q(imaging_cameras=None))).distinct()
            elif active == '-1':
                qs = qs.filter(Q(subject_type=SubjectType.GEAR)).distinct()
            else:
                if active is None:
                    if telescopes:
                        active = telescopes[0].id
                if active:
                    qs = qs.filter(Q(imaging_telescopes__id=active) |
                                   Q(imaging_cameras__id=active)).distinct()

        ###########
        # SUBJECT #
        ###########
        elif subsection == 'subject':
            menu += [('DEEP', _("Deep sky"))]
            menu += [('SOLAR', _("Solar system"))]
            menu += [('WIDE', _("Extremely wide field"))]
            menu += [('TRAILS', _("Star trails"))]
            menu += [('GEAR', _("Gear"))]
            menu += [('OTHER', _("Other"))]

            if active is None:
                active = 'DEEP'

            if active == 'DEEP':
                qs = qs.filter(subject_type=SubjectType.DEEP_SKY)

            elif active == 'SOLAR':
                qs = qs.filter(subject_type=SubjectType.SOLAR_SYSTEM)

            elif active == 'WIDE':
                qs = qs.filter(subject_type=SubjectType.WIDE_FIELD)

            elif active == 'TRAILS':
                qs = qs.filter(subject_type=SubjectType.STAR_TRAILS)

            elif active == 'GEAR':
                qs = qs.filter(subject_type=SubjectType.GEAR)

            elif active == 'OTHER':
                qs = qs.filter(subject_type=SubjectType.OTHER)

        elif subsection == 'constellation':
            qs = qs.filter(subject_type=SubjectType.DEEP_SKY)

            images_by_constellation = {
                'n/a': []
            }

            for image in qs.iterator():
                image_constellation = ImageService.get_constellation(image.solution)
                if image_constellation:
                    if not images_by_constellation.get(image_constellation.get('abbreviation')):
                        images_by_constellation[image_constellation.get('abbreviation')] = []
                    images_by_constellation.get(image_constellation.get('abbreviation')).append(image)
                else:
                    images_by_constellation.get('n/a').append(image)

            menu += [('ALL', _('All'))]
            for constellation in ConstellationsService.constellation_table:
                if images_by_constellation.get(constellation[0]):
                    menu += [(
                        constellation[0],
                        constellation[1] + ' (%d)' % len(images_by_constellation.get(constellation[0]))
                    )]
            if images_by_constellation.get('n/a') and len(images_by_constellation.get('n/a')) > 0:
                menu += [('n/a', _('n/a') + ' (%d)' % len(images_by_constellation.get('n/a')))]

            if active is None:
                active = 'ALL'

            if active != 'ALL':
                try:
                    qs = qs.filter(pk__in=[x.pk for x in images_by_constellation[active]])
                except KeyError:
                    log.warning("Requested missing constellation %s for user %d" % (active, user.pk))
                    qs = Image.objects.none()

        ###########
        # NO DATA #
        ###########
        elif subsection == 'nodata':
            menu += [('SUB', _("No subjects specified"))]
            menu += [('GEAR', _("No imaging telescopes or lenses, or no imaging cameras specified"))]
            menu += [('ACQ', _("No acquisition details specified"))]

            if active is None:
                active = 'SUB'

            if active == 'SUB':
                qs = qs.filter(
                    (Q(subject_type=SubjectType.DEEP_SKY) | Q(subject_type=SubjectType.SOLAR_SYSTEM)) &
                    (Q(solar_system_main_subject=None)))
                qs = [x for x in qs if (x.solution is None or x.solution.objects_in_field is None)]
                for i in qs:
                    for r in i.revisions.all():
                        if r.solution and r.solution.objects_in_field:
                            if i in qs:
                                qs.remove(i)

            elif active == 'GEAR':
                qs = qs.filter(
                    Q(subject_type__in=(
                        SubjectType.DEEP_SKY,
                        SubjectType.SOLAR_SYSTEM,
                        SubjectType.WIDE_FIELD,
                        SubjectType.STAR_TRAILS,
                        SubjectType.NORTHERN_LIGHTS,
                    )) &
                    (Q(imaging_telescopes=None) | Q(imaging_cameras=None)))

            elif active == 'ACQ':
                qs = qs.filter(
                    Q(subject_type__in=(
                        SubjectType.DEEP_SKY,
                        SubjectType.SOLAR_SYSTEM,
                        SubjectType.WIDE_FIELD,
                        SubjectType.STAR_TRAILS,
                        SubjectType.NORTHERN_LIGHTS,
                    )) &
                    Q(acquisition=None))

    # Calculate some stats

    followers = ToggleProperty.objects.toggleproperties_for_object("follow", user).count()
    following = ToggleProperty.objects.filter(
        property_type="follow",
        user=user,
        content_type=user_ct).count()

    key = "User.%d.Stats.%s" % (user.pk, getattr(request, 'LANGUAGE_CODE', 'en'))
    data = cache.get(key)
    if not data:
        user_sqs = SearchQuerySet().models(User).filter(django_id=user.pk)
        data = {}

        if user_sqs.count():
            try:
                data['stats'] = (
                    (_('Member since'), user.date_joined \
                        if user.userprofile.display_member_since \
                        else None, 'datetime'),
                    (_('Last seen online'), user.userprofile.last_seen or user.last_login \
                        if user.userprofile.display_last_seen \
                        else None, 'datetime'),
                    (_('Total integration time'),
                     "%.1f %s" % (user_sqs[0].integration, _("hours")) if user_sqs[0].integration else None),
                    (_('Average integration time'),
                     "%.1f %s" % (user_sqs[0].avg_integration, _("hours")) if user_sqs[0].avg_integration else None),
                    (_('Forum posts'), "%d" % user_sqs[0].forum_posts if user_sqs[0].forum_posts else 0),
                    (_('Comments'), "%d" % user_sqs[0].comments if user_sqs[0].comments else 0),
                    (_('Likes'), "%d" % user_sqs[0].total_likes_received if user_sqs[0].total_likes_received else 0),
                )
            except Exception as e:
                log.error("User page (%d): unable to get stats from search index: %s" % (user.pk, str(e)))

            cache.set(key, data, 300)
        else:
            log.error("User page (%d): unable to get user's SearchQuerySet" % user.pk)

    response_dict = {
        'paginate_by': settings.PAGINATE_USER_PAGE_BY,
        'followers': followers,
        'following': following,
        'image_list': qs,
        'sort': request.GET.get('sort'),
        'view': request.GET.get('view', 'default'),
        'requested_user': user,
        'profile': profile,
        'section': section,
        'subsection': subsection,
        'active': active,
        'menu': menu,
        'stats': data['stats'] if 'stats' in data else None,
        'alias': 'gallery',
        'public_images_without_acquisition': UserService(user).get_public_images().filter(acquisition__isnull=True),
    }

    try:
        response_dict['mobile_header_background'] = \
            UserService(user).get_public_images().first().thumbnail('regular', None, sync=True) \
                if UserService(user).get_public_images().exists() \
                else None
    except IOError:
        response_dict['mobile_header_background'] = None

    response_dict.update(UserService(user).get_image_numbers())

    template_name = 'user/profile.html'
    if request.is_ajax():
        template_name = 'inclusion_tags/image_list_entries.html'

    return render(request, template_name, response_dict)


@never_cache
@user_passes_test(lambda u: u.is_superuser)
def user_ban(request, username):
    user = get_object_or_404(UserProfile, user__username=username).user

    if request.method == 'POST':
        user.userprofile.deleted_reason = UserProfile.DELETE_REASON_BANNED
        user.userprofile.save(keep_deleted=True)
        user.userprofile.delete()
        log.info("User (%d) was banned" % user.pk)

    return render(request, 'user/ban.html', {
        'user': user,
        'deleted': request.method == 'POST',
    })


@never_cache
@require_GET
def user_page_bookmarks(request, username):
    user = get_object_or_404(UserProfile, user__username=username).user

    template_name = 'user/bookmarks.html'
    if request.is_ajax():
        template_name = 'inclusion_tags/image_list_entries.html'

    response_dict = {
        'requested_user': user,
        'image_list': UserService(user).get_bookmarked_images(),
        'paginate_by': settings.PAGINATE_USER_PAGE_BY,
        'alias': 'gallery',
    }

    response_dict.update(UserService(user).get_image_numbers())

    return render(request, template_name, response_dict)


@never_cache
@require_GET
def user_page_liked(request, username):
    user = get_object_or_404(UserProfile, user__username=username).user

    template_name = 'user/liked.html'
    if request.is_ajax():
        template_name = 'inclusion_tags/image_list_entries.html'

    response_dict = {
        'requested_user': user,
        'image_list': UserService(user).get_liked_images(),
        'paginate_by': settings.PAGINATE_USER_PAGE_BY,
        'alias': 'gallery',
    }

    response_dict.update(UserService(user).get_image_numbers())

    return render(request, template_name, response_dict)


@never_cache
@require_GET
@page_template('astrobin_apps_users/inclusion_tags/user_list_entries.html', key='users_page')
def user_page_following(request, username, extra_context=None):
    user = get_object_or_404(UserProfile, user__username=username).user

    user_ct = ContentType.objects.get_for_model(User)
    followed_users = []
    properties = ToggleProperty.objects.filter(
        property_type="follow",
        user=user,
        content_type=user_ct)

    for p in properties:
        try:
            followed_users.append(user_ct.get_object_for_this_type(pk=p.object_id))
        except User.DoesNotExist:
            pass

    followed_users.sort(key=lambda x: x.username)

    template_name = 'user/following.html'
    if request.is_ajax():
        template_name = 'astrobin_apps_users/inclusion_tags/user_list_entries.html'

    response_dict = {
        'request_user': UserProfile.objects.get(
            user=request.user).user if request.user.is_authenticated else None,
        'requested_user': user,
        'user_list': followed_users,
        'view': request.GET.get('view', 'default'),
    }

    response_dict.update(UserService(user).get_image_numbers())

    return render(request, template_name, response_dict)


@never_cache
@require_GET
@page_template('astrobin_apps_users/inclusion_tags/user_list_entries.html', key='users_page')
def user_page_followers(request, username, extra_context=None):
    user = get_object_or_404(UserProfile, user__username=username).user

    user_ct = ContentType.objects.get_for_model(User)
    followers = [
        x.user for x in
        ToggleProperty.objects.filter(
            property_type="follow",
            object_id=user.pk,
            content_type=user_ct)
    ]

    followers.sort(key=lambda x: x.username)

    template_name = 'user/followers.html'
    if request.is_ajax():
        template_name = 'astrobin_apps_users/inclusion_tags/user_list_entries.html'

    response_dict = {
        'request_user': UserProfile.objects.get(
            user=request.user).user if request.user.is_authenticated else None,
        'requested_user': user,
        'user_list': followers,
        'view': request.GET.get('view', 'default'),
    }

    response_dict.update(UserService(user).get_image_numbers())

    return render(request, template_name, response_dict)


@require_GET
@page_template('astrobin_apps_users/inclusion_tags/user_list_entries.html', key='users_page')
def user_page_friends(request, username, extra_context=None):
    user = get_object_or_404(UserProfile, user__username=username).user

    user_ct = ContentType.objects.get_for_model(User)
    friends = []
    followers = [
        x.user for x in
        ToggleProperty.objects.filter(
            property_type="follow",
            object_id=user.pk,
            content_type=user_ct)
    ]

    for follower in followers:
        if ToggleProperty.objects.filter(
                property_type="follow",
                user=user,
                object_id=follower.pk,
                content_type=user_ct).exists():
            friends.append(follower)

    friends.sort(key=lambda x: x.username)

    template_name = 'user/friends.html'
    if request.is_ajax():
        template_name = 'astrobin_apps_users/inclusion_tags/user_list_entries.html'

    response_dict = {
        'request_user': UserProfile.objects.get(
            user=request.user).user if request.user.is_authenticated else None,
        'requested_user': user,
        'user_list': friends,
        'view': request.GET.get('view', 'default'),
    }

    response_dict.update(UserService(user).get_image_numbers())

    return render(request, template_name, response_dict)


@never_cache
@require_GET
def user_page_plots(request, username):
    """Shows the user's public page"""
    user = get_object_or_404(UserProfile, user__username=username).user
    profile = user.userprofile

    response_dict = {
        'requested_user': user,
        'profile': profile,
    }

    response_dict.update(UserService(user).get_image_numbers())

    return render(request, 'user/plots.html', response_dict)


@never_cache
@require_GET
def user_page_api_keys(request, username):
    """Shows the user's API Keys"""
    user = get_object_or_404(UserProfile, user__username=username).user
    if user != request.user:
        return HttpResponseForbidden()

    profile = user.userprofile
    keys = App.objects.filter(registrar=user)

    response_dict = {
        'requested_user': user,
        'profile': profile,
        'api_keys': keys,
    }

    response_dict.update(UserService(user).get_image_numbers())

    return render(request, 'user/api_keys.html', response_dict)


@never_cache
@login_required
@require_GET
def user_profile_edit_basic(request):
    """Edits own profile"""
    profile = request.user.userprofile
    form = UserProfileEditBasicForm(instance=profile)

    response_dict = {
        'form': form,
    }
    return render(request, "user/profile/edit/basic.html", response_dict)


@never_cache
@login_required
@require_POST
def user_profile_save_basic(request):
    """Saves the form"""

    profile = request.user.userprofile
    form = UserProfileEditBasicForm(data=request.POST, instance=profile)
    response_dict = {'form': form}

    if not form.is_valid():
        return render(request, "user/profile/edit/basic.html", response_dict)

    form.save()

    messages.success(request, _("Form saved. Thank you!"))
    return HttpResponseRedirect("/profile/edit/basic/")


@never_cache
@login_required
@require_GET
def user_profile_edit_license(request):
    profile = request.user.userprofile
    form = DefaultImageLicenseForm(instance=profile)
    return render(request, 'user/profile/edit/license.html', {
        'form': form
    })


@never_cache
@login_required
@require_POST
def user_profile_save_license(request):
    profile = request.user.userprofile
    form = DefaultImageLicenseForm(data=request.POST, instance=profile)

    if not form.is_valid():
        return render(request, 'user/profile/edit/license.html', {
            'form': form
        })

    form.save()

    messages.success(request, _("Form saved. Thank you!"))
    return HttpResponseRedirect('/profile/edit/license/')


@never_cache
@login_required
@require_GET
def user_profile_edit_gear(request):
    """Edits own profile"""
    profile = request.user.userprofile

    def uniq(seq):
        # Not order preserving
        keys = {}
        for e in seq:
            keys[e] = 1
        return list(keys.keys())

    response_dict = {
        'initial': 'initial' in request.GET,
        'all_gear_makes': simplejson.dumps(
            uniq([x.get_make() for x in Gear.objects.exclude(make=None).exclude(make='')])),
        'all_gear_names': simplejson.dumps(
            uniq([x.get_name() for x in Gear.objects.exclude(name=None).exclude(name='')])),
    }

    prefill = {}
    for attr, label, klass in (
            ['telescopes', _("Telescopes and lenses"), 'Telescope'],
            ['cameras', _("Cameras"), 'Camera'],
            ['mounts', _("Mounts"), 'Mount'],
            ['focal_reducers', _("Focal reducers"), 'FocalReducer'],
            ['software', _("Software"), 'Software'],
            ['filters', _("Filters"), 'Filter'],
            ['accessories', _("Accessories"), 'Accessory']):
        all_gear = getattr(profile, attr).all()
        prefill[label] = [all_gear, klass]

    response_dict['prefill'] = prefill
    return render(request, "user/profile/edit/gear.html", response_dict)


@never_cache
@login_required
@require_POST
def user_profile_edit_gear_remove(request, id):
    profile = request.user.userprofile
    gear, gear_type = get_correct_gear(id)
    if not gear:
        raise Http404

    profile.remove_gear(gear, gear_type)

    return ajax_success()


@never_cache
@login_required
@require_GET
def user_profile_edit_locations(request):
    profile = request.user.userprofile
    LocationsFormset = inlineformset_factory(
        UserProfile, Location, form=LocationEditForm, extra=1)

    return render(request, 'user/profile/edit/locations.html', {
        'formset': LocationsFormset(instance=profile),
        'profile': profile,
    })


@never_cache
@login_required
@require_POST
def user_profile_save_locations(request):
    profile = request.user.userprofile
    LocationsFormset = inlineformset_factory(
        UserProfile, Location, form=LocationEditForm, extra=1)
    formset = LocationsFormset(data=request.POST, instance=profile)
    if not formset.is_valid():
        messages.error(request,
                       _("There was one or more errors processing the form. You may need to scroll down to see them."))
        return render(request, 'user/profile/edit/locations.html', {
            'formset': formset,
            'profile': profile,
        })

    formset.save()
    messages.success(request, _("Form saved. Thank you!"))
    return HttpResponseRedirect('/profile/edit/locations/')


@never_cache
@login_required
@require_POST
def user_profile_save_gear(request):
    """Saves the form"""

    profile = request.user.userprofile

    profile.telescopes.clear()
    profile.mounts.clear()
    profile.cameras.clear()
    profile.focal_reducers.clear()
    profile.filters.clear()
    profile.software.clear()
    profile.accessories.clear()

    form = UserProfileEditGearForm(data=request.POST)
    if not form.is_valid():
        response_dict = {"form": form}
        prefill_dict = {}
        for k in ("telescopes", "mounts", "cameras", "focal_reducers",
                  "software", "filters", "accessories",):
            allGear = getattr(profile, k).all()
            prefill_dict[k] = jsonDump(allGear)

        return render(request, "user/profile/edit/gear.html", response_dict)

    for k, v in {"telescopes": [Telescope, profile.telescopes],
                 "mounts": [Mount, profile.mounts],
                 "cameras": [Camera, profile.cameras],
                 "focal_reducers": [FocalReducer, profile.focal_reducers],
                 "software": [Software, profile.software],
                 "filters": [Filter, profile.filters],
                 "accessories": [Accessory, profile.accessories],
                 }.items():
        (names, value) = valueReader(request.POST, k)
        for name in names:
            try:
                id = float(name)
                gear_item = v[0].objects.get(id=id)
            except ValueError:
                gear_item, created = v[0].objects.get_or_create(name=name)
            except v[0].DoesNotExist:
                continue
            getattr(profile, k).add(gear_item)
        form.fields[k].initial = value

    profile.save(keep_deleted=True)

    initial = "&initial=true" if "initial" in request.POST else ""
    messages.success(request, _("Form saved. Thank you!"))
    return HttpResponseRedirect("/profile/edit/gear/" + initial)


@never_cache
@login_required
def user_profile_flickr_import(request):
    from django.core.files import File
    from django.core.files.temp import NamedTemporaryFile
    from astrobin_apps_premium.templatetags.astrobin_apps_premium_tags import is_free

    response_dict = {
        'readonly': settings.READONLY_MODE
    }

    log.debug("Flickr import (user %d): accessed view" % request.user.pk)

    if not request.user.is_superuser and is_free(request.user) or settings.READONLY_MODE:
        return render(request, "user/profile/flickr_import.html", response_dict)

    flickr_token = None
    if 'flickr_token_token' in request.session:
        flickr_token = FlickrAccessToken(
            request.session['flickr_token_token'],
            request.session['flickr_token_token_secret'],
            request.session['flickr_token_access_level'],
            request.session['flickr_token_fullname'],
            request.session['flickr_token_username'],
            request.session['flickr_token_token_user_nsid'],
        )

    flickr = flickrapi.FlickrAPI(settings.FLICKR_API_KEY,
                                 settings.FLICKR_SECRET,
                                 username=request.user.username,
                                 token=flickr_token)

    if not flickr.token_valid(perms='read'):
        # We were never authenticated, or authentication expired. We need
        # to reauthenticate.
        log.debug("Flickr import (user %d): token not valid" % request.user.pk)
        flickr.get_request_token(settings.BASE_URL + reverse('flickr_auth_callback'))
        authorize_url = flickr.auth_url(perms='read')
        request.session['request_token'] = flickr.flickr_oauth.resource_owner_key
        request.session['request_token_secret'] = flickr.flickr_oauth.resource_owner_secret
        request.session['requested_permissions'] = flickr.flickr_oauth.requested_permissions
        return HttpResponseRedirect(authorize_url)

    if not request.POST:
        # If we made it this far (it's a GET request), it means that we
        # are authenticated with flickr. Let's fetch the sets and send them to
        # the template.
        log.debug("Flickr import (user %d): token valid, GET request, fetching sets" % request.user.pk)

        # Does it have to be so insane to get the info on the
        # authenticated user?
        sets = flickr.photosets_getList().find('photosets').findall('photoset')

        log.debug("Flickr import (user %d): token valid, fetched sets" % request.user.pk)
        template_sets = {}
        for set in sets:
            template_sets[set.find('title').text] = set.attrib['id']
        response_dict['flickr_sets'] = template_sets
    else:
        log.debug("Flickr import (user %d): token valid, POST request" % request.user.pk)
        if 'id_flickr_set' in request.POST:
            log.debug("Flickr import (user %d): set in POST request" % request.user.pk)
            set_id = request.POST['id_flickr_set']
            urls_sq = {}
            for photo in flickr.walk_set(set_id, extras='url_sq'):
                urls_sq[photo.attrib['id']] = photo.attrib['url_sq']
                response_dict['flickr_photos'] = urls_sq
        elif 'flickr_selected_photos[]' in request.POST:
            log.debug("Flickr import (user %s): photos in POST request" % request.user.username)
            selected_photos = request.POST.getlist('flickr_selected_photos[]')
            # Starting the process of importing
            for index, photo_id in enumerate(selected_photos):
                log.debug("Flickr import (user %d): iterating photo %s" % (request.user.pk, photo_id))
                sizes = flickr.photos_getSizes(photo_id=photo_id)
                info = flickr.photos_getInfo(photo_id=photo_id).find('photo')

                title = info.find('title').text
                description = info.find('description').text

                # Attempt to find the largest image
                found_size = None
                for label in ['Square', 'Thumbnail', 'Small', 'Medium', 'Medium640', 'Large', 'Original']:
                    for size in sizes.find('sizes').findall('size'):
                        if size.attrib['label'] == label:
                            found_size = size

                if found_size is not None:
                    log.debug("Flickr import (user %s): found largest side of photo %s" % (
                        request.user.username, photo_id))
                    source = found_size.attrib['source']

                    img = NamedTemporaryFile(delete=True)
                    img.write(urllib.request.urlopen(source).read())
                    img.flush()
                    img.seek(0)
                    f = File(img)

                    profile = request.user.userprofile
                    image = Image(image_file=f,
                                  user=request.user,
                                  title=title if title is not None else '',
                                  description=description if description is not None else '',
                                  subject_type=600,  # Default to Other only when doing a Flickr import
                                  is_wip=True,
                                  license=profile.default_license)
                    image.save(keep_deleted=True)
                    log.debug("Flickr import (user %d): saved image %d" % (request.user.pk, image.pk))

        log.debug("Flickr import (user %s): returning ajax response: %s" % (
            request.user.username, simplejson.dumps(response_dict)))
        return ajax_response(response_dict)

    return render(request, "user/profile/flickr_import.html", response_dict)


@never_cache
def flickr_auth_callback(request):
    log.debug("Flickr import (user %d): received auth callback" % request.user.pk)
    flickr = flickrapi.FlickrAPI(
        settings.FLICKR_API_KEY, settings.FLICKR_SECRET,
        username=request.user.username)
    flickr.flickr_oauth.resource_owner_key = request.session['request_token']
    flickr.flickr_oauth.resource_owner_secret = request.session['request_token_secret']
    flickr.flickr_oauth.requested_permissions = request.session['requested_permissions']
    verifier = request.GET['oauth_verifier']
    flickr.get_access_token(verifier)

    request.session['flickr_token_token'] = flickr.token_cache.token.token
    request.session['flickr_token_token_secret'] = flickr.token_cache.token.token_secret
    request.session['flickr_token_access_level'] = flickr.token_cache.token.access_level
    request.session['flickr_token_fullname'] = flickr.token_cache.token.fullname
    request.session['flickr_token_username'] = flickr.token_cache.token.username
    request.session['flickr_token_token_user_nsid'] = flickr.token_cache.token.user_nsid

    return HttpResponseRedirect("/profile/edit/flickr/")


@never_cache
@login_required
@require_POST
def user_profile_seen_realname(request):
    profile = request.user.userprofile
    profile.seen_realname = True
    profile.save(keep_deleted=True)

    return HttpResponseRedirect(request.POST.get('next', '/'))


@never_cache
@login_required
@require_POST
def user_profile_seen_iotd_tp_is_explicit_submission(request):
    profile = request.user.userprofile
    profile.seen_iotd_tp_is_explicit_submission = DateTimeService.now()
    profile.save(keep_deleted=True)

    return HttpResponseRedirect(request.POST.get('next', '/'))


@never_cache
@login_required
@require_POST
@csrf_exempt
def user_profile_shadow_ban(request):
    user_pk = request.POST.get('userPk')

    if user_pk == request.user.pk:
        return HttpResponseForbidden()

    user_to_ban = User.objects.get(pk=user_pk)
    profile_to_ban = user_to_ban.userprofile

    requester_profile = request.user.userprofile

    if profile_to_ban in requester_profile.shadow_bans.all():
        return HttpResponseBadRequest()

    requester_profile.shadow_bans.add(profile_to_ban)

    msg = "You have shadow-banned %s. They will not be notified about it."
    messages.success(request, _(msg) % profile_to_ban.get_display_name())

    return HttpResponseRedirect(request.POST.get('next', '/'))


@never_cache
@login_required
@require_POST
@csrf_exempt
def user_profile_remove_shadow_ban(request):
    user_pk = request.POST.get('userPk')

    if user_pk == request.user.pk:
        return HttpResponseForbidden()

    user_to_unban = User.objects.get(pk=user_pk)
    profile_to_unban = user_to_unban.userprofile

    requester_profile = request.user.userprofile

    if not profile_to_unban in requester_profile.shadow_bans.all():
        return HttpResponseBadRequest()

    requester_profile.shadow_bans.remove(profile_to_unban)

    msg = "You have removed your shadow-ban for %s. They will not be notified about it."
    messages.success(request, _(msg) % profile_to_unban.get_display_name())

    return HttpResponseRedirect(request.POST.get('next', '/'))


@never_cache
@login_required
@require_GET
def user_profile_edit_preferences(request):
    """Edits own preferences"""
    profile = request.user.userprofile
    form = UserProfileEditPreferencesForm(
        instance=profile,
        initial={'other_languages': profile.other_languages.split(',') if profile.other_languages else []}
    )
    response_dict = {
        'form': form,
    }

    return render(request, "user/profile/edit/preferences.html", response_dict)


@login_required
@require_POST
def user_profile_save_preferences(request):
    """Saves the form"""

    profile = request.user.userprofile
    form = UserProfileEditPreferencesForm(data=request.POST, instance=profile)
    response_dict = {'form': form}
    response = HttpResponseRedirect("/profile/edit/preferences/")

    if form.is_valid():
        form.save()
        # Activate the chosen language
        from django.utils.translation import check_for_language, activate
        lang = form.cleaned_data['language']
        if lang and check_for_language(lang):
            if hasattr(request, 'session'):
                request.session['django_language'] = lang

            response.set_cookie(
                settings.LANGUAGE_COOKIE_NAME, lang,
                max_age=settings.LANGUAGE_COOKIE_AGE
            )
            activate(lang)
    else:
        return render(request, "user/profile/edit/preferences.html", response_dict)

    messages.success(request, _("Form saved. Thank you!"))
    return response


@never_cache
@login_required
@require_GET
def user_profile_edit_privacy(request):
    return render(request, "user/profile/edit/privacy.html", {
        'form': UserProfileEditPrivacyForm(instance=request.user.userprofile),
    })


@login_required
@require_POST
def user_profile_save_privacy(request):
    form = UserProfileEditPrivacyForm(data=request.POST, instance=request.user.userprofile)

    if form.is_valid():
        form.save()
        for lang in settings.LANGUAGES:
            cache.delete("User.%d.Stats.%s" % (request.user.pk, lang[0]))

        messages.success(request, _("Form saved. Thank you!"))
        return HttpResponseRedirect("/profile/edit/privacy/")

    return render(request, "user/profile/edit/privacy.html", {'form': form})


@never_cache
@login_required
def user_profile_delete(request):
    if request.method == 'POST':
        form = DeleteAccountForm(instance=request.user.userprofile, data=request.POST)
        form.full_clean()
        if form.is_valid():
            request.user.userprofile.deleted_reason = form.cleaned_data.get('deleted_reason')
            request.user.userprofile.deleted_reason_other = form.cleaned_data.get('deleted_reason_other')
            request.user.userprofile.save(keep_deleted=True)
            request.user.userprofile.delete()

            log.info("User %s (%d) deleted their account with reason %s ('%s')" % (
                request.user.username,
                request.user.pk,
                request.user.userprofile.deleted_reason,
                request.user.userprofile.deleted_reason_other,
            ))

            auth.logout(request)

            return render(request, 'user/profile/deleted.html', {})
    elif request.method == 'GET':
        form = DeleteAccountForm(instance=request.user.userprofile)

    return render(request, 'user/profile/delete.html', {'form': form})


@never_cache
@login_required
@require_POST
def image_revision_upload_process(request):
    try:
        image_id = request.POST['image_id']
    except MultiValueDictKeyError:
        raise Http404

    image = get_image_or_404(Image.objects_including_wip, image_id)

    log.info("Classic uploader (revision) (%d) (%d): submitted" % (request.user.pk, image.pk))

    if settings.READONLY_MODE:
        messages.error(request, _(
            "AstroBin is currently in read-only mode, because of server maintenance. Please try again soon!"))
        return HttpResponseRedirect(image.get_absolute_url())

    form = ImageRevisionUploadForm(request.POST, request.FILES)

    if not form.is_valid():
        return upload_error(request, image, form.errors)

    max_revisions = premium_get_max_allowed_revisions(request.user)
    if image.revisions.count() >= max_revisions:
        return upload_max_revisions_error(request, max_revisions, image)

    image_file = request.FILES["image_file"]
    ext = os.path.splitext(image_file.name)[1].lower()

    if ext not in settings.ALLOWED_IMAGE_EXTENSIONS:
        return upload_error(request, image)

    max_size = premium_get_max_allowed_image_size(request.user)
    if image_file.size > max_size:
        return upload_size_error(request, max_size, image)

    if image_file.size < 1e+7:
        try:
            from PIL import Image as PILImage
            trial_image = PILImage.open(image_file)
            trial_image.verify()
            image_file.file.seek(0)  # Because we opened it with PIL

            if ext == '.png' and trial_image.mode == 'I':
                messages.warning(request, _(
                    "You uploaded an Indexed PNG file. AstroBin will need to lower the color count to 256 in order to work with it."))
        except:
            return upload_error(request, image)

    image_revision = form.save(commit=False)  # type: ImageRevision
    image_revision.user = request.user
    image_revision.image = image
    image_revision.label = ImageService(image).get_next_available_revision_label()
    image_revision.is_final = request.POST.get('mark_as_final', None) == 'on'
    image_revision.save(keep_deleted=True)

    messages.success(request, _("Image uploaded. Thank you!"))
    return HttpResponseRedirect(reverse('image_edit_revision', args=(image_revision.pk,)))


@never_cache
@require_GET
def astrophotographers_list(request):
    if request.user.is_authenticated and \
            request.user.userprofile.exclude_from_competitions and \
            not request.user.is_superuser:
        return HttpResponseForbidden()

    sqs = SearchQuerySet()

    default_sorting = [
        '-normalized_likes',
        '-likes',
        '-images',
    ]

    sort = request.GET.get('sort', default_sorting)

    if sort in ('', 'default'):
        sort = default_sorting

    if sort not in (
            default_sorting,

            'normalized_likes',
            'followers',
            'images',
            'likes',
            'integration',

            '-normalized_likes',
            '-followers',
            '-images',
            '-likes',
            '-integration',
            '-top_pick_nominations',
            '-top_picks',
            '-iotds',

            'normalized_likes',
            'followers',
            'images',
            'likes',
            'integration',
            'top_pick_nominations',
            'top_picks',
            'iotds',
    ):
        raise Http404

    if not isinstance(sort, list):
        sort = [sort, ]

    queryset = sqs.models(User).exclude(exclude_from_competitions=True).order_by(*sort)

    if 'q' in request.GET:
        queryset = queryset.filter(text__contains=request.GET.get('q'))

    return object_list(
        request,
        queryset=queryset,
        template_name='astrophotographers_list.html',
        template_object_name='user',
    )


@never_cache
@require_GET
def contributors_list(request):
    if request.user.is_authenticated and \
            request.user.userprofile.exclude_from_competitions and \
            not request.user.is_superuser:
        return HttpResponseForbidden()

    queryset = SearchQuerySet()

    default_sorting = [
        # DEPRECATED: remove once contribution_index is populated
        '-contribution_index',
        '-comment_likes_received',
        '-forum_post_likes_received',
        '-comments_written',
        '-forum_posts'
    ]

    sort = request.GET.get('sort', default_sorting)

    if sort in ('', 'default'):
        sort = default_sorting

    if sort not in (
            default_sorting,

            'comments_written',
            'comments',
            'comment_likes_received',
            'forum_posts',
            'forum_post_likes_received',
            'contribution_index',

            '-comments_written',
            '-comments',
            '-comment_likes_received',
            '-forum_posts',
            '-forum_post_likes_received',
            '-contribution_index'
    ):
        raise Http404

    if not isinstance(sort, list):
        sort = [sort, ]

    queryset = queryset.models(User).exclude(exclude_from_competitions=True).order_by(*sort)

    if 'q' in request.GET:
        queryset = queryset.filter(text__contains=request.GET.get('q'))

    return object_list(
        request,
        queryset=queryset,
        template_name='contributors_list.html',
        template_object_name='user',
    )


@require_GET
def api_help(request):
    return HttpResponseRedirect('https://welcome.astrobin.com/application-programming-interface')


@never_cache
@login_required
@require_GET
def location_edit(request, id):
    location = get_object_or_404(Location, pk=id)
    form = LocationEditForm(instance=location)

    return render(request, 'location/edit.html', {
        'form': form,
        'id': id,
    })


@never_cache
@require_GET
def set_language(request, language_code):
    from django.utils.translation import check_for_language, activate

    next = request.GET.get('next', None)

    if not next:
        next = request.META.get('HTTP_REFERER', None)

    if not next:
        next = '/'

    response = HttpResponseRedirect(next)

    if language_code and check_for_language(language_code):
        if hasattr(request, 'session'):
            request.session['django_language'] = language_code

        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME, language_code,
            max_age=settings.LANGUAGE_COOKIE_AGE
        )
        activate(language_code)

        if request.user.is_authenticated:
            profile = request.user.userprofile
            profile.language = language_code
            profile.save(keep_deleted=True)
    else:
        messages.error(request, _("Sorry, AstroBin was unable to activate the requested language"))
        log.error("set_language: unable to activate %s" % language_code)

    return response


@never_cache
@require_GET
@login_required
def get_edit_gear_form(request, id):
    gear, gear_type = get_correct_gear(id)
    if not gear:
        raise Http404

    form = None
    if gear_type == 'Telescope':
        form = TelescopeEditForm(instance=gear)
    elif gear_type == 'Mount':
        form = MountEditForm(instance=gear)
    elif gear_type == 'Camera':
        form = CameraEditForm(instance=gear)
    elif gear_type == 'FocalReducer':
        form = FocalReducerEditForm(instance=gear)
    elif gear_type == 'Software':
        form = SoftwareEditForm(instance=gear)
    elif gear_type == 'Filter':
        form = FilterEditForm(instance=gear)
    elif gear_type == 'Accessory':
        form = AccessoryEditForm(instance=gear)

    from bootstrap_toolkit.templatetags.bootstrap_toolkit import as_bootstrap
    response_dict = {
        'form': as_bootstrap(form, 'horizontal') if form else '',
    }

    return HttpResponse(
        simplejson.dumps(response_dict),
        content_type='application/javascript')


@never_cache
@require_GET
@login_required
def get_empty_edit_gear_form(request, gear_type):
    form_lookup = {
        'Telescope': TelescopeEditNewForm,
        'Mount': MountEditNewForm,
        'Camera': CameraEditNewForm,
        'FocalReducer': FocalReducerEditNewForm,
        'Software': SoftwareEditNewForm,
        'Filter': FilterEditNewForm,
        'Accessory': AccessoryEditNewForm,
    }

    form = form_lookup[gear_type]()
    from bootstrap_toolkit.templatetags.bootstrap_toolkit import as_bootstrap
    response_dict = {
        'form': as_bootstrap(form, 'horizontal') if form else '',
    }

    return HttpResponse(
        simplejson.dumps(response_dict),
        content_type='application/javascript')


@never_cache
@require_POST
@login_required
def save_gear_details(request):
    gear = None
    if 'gear_id' in request.POST:
        id = request.POST.get('gear_id')
        gear, gear_type = get_correct_gear(id)
    else:
        gear_type = request.POST.get('gear_type')

    from astrobin.gear import CLASS_LOOKUP

    form_lookup = {
        'Telescope': TelescopeEditNewForm,
        'Mount': MountEditNewForm,
        'Camera': CameraEditNewForm,
        'FocalReducer': FocalReducerEditNewForm,
        'Software': SoftwareEditNewForm,
        'Filter': FilterEditNewForm,
        'Accessory': AccessoryEditNewForm,
    }

    if gear and gear.get_name() != '':
        form_lookup = {
            'Telescope': TelescopeEditForm,
            'Mount': MountEditForm,
            'Camera': CameraEditForm,
            'FocalReducer': FocalReducerEditForm,
            'Software': SoftwareEditForm,
            'Filter': FilterEditForm,
            'Accessory': AccessoryEditForm,
        }

    user_gear_lookup = {
        'Telescope': 'telescopes',
        'Mount': 'mounts',
        'Camera': 'cameras',
        'FocalReducer': 'focal_reducers',
        'Software': 'software',
        'Filter': 'filters',
        'Accessory': 'accessories',
    }

    name = request.POST.get('name')
    filters = Q(name=name)
    if request.POST.get('make'):
        filters = filters & Q(make=request.POST.get('make'))

    if not gear:
        try:
            if request.POST.get('make'):
                gear, created = CLASS_LOOKUP[gear_type].objects.get_or_create(
                    make=request.POST.get('make'),
                    name=request.POST.get('name'))
            else:
                gear, created = CLASS_LOOKUP[gear_type].objects.get_or_create(
                    name=request.POST.get('name'))
        except CLASS_LOOKUP[gear_type].MultipleObjectsReturned:
            gear = CLASS_LOOKUP[gear_type].objects.filter(filters)[0]

    form = form_lookup[gear_type](data=request.POST, instance=gear)
    if not form.is_valid():
        from bootstrap_toolkit.templatetags.bootstrap_toolkit import as_bootstrap
        response_dict = {
            'form': as_bootstrap(form, 'horizontal') if form else '',
            'gear_id': gear.id,
        }
        return HttpResponse(
            simplejson.dumps(response_dict),
            content_type='application/javascript')

    form.save()

    profile = request.user.userprofile
    user_gear = getattr(profile, user_gear_lookup[gear_type])
    if gear not in user_gear.all():
        user_gear.add(gear)

    alias = _("no alias")
    gear_user_info = GearUserInfo(gear=gear, user=request.user)
    if gear_user_info.alias is not None and gear_user_info.alias != '':
        alias = gear_user_info.alias

    response_dict = {
        'success': True,
        'id': gear.id,
        'make': gear.get_make(),
        'name': gear.get_name(),
        'alias': alias,
        'complete': is_gear_complete(gear.id),
    }

    return HttpResponse(
        simplejson.dumps(response_dict),
        content_type='application/javascript')


@never_cache
@require_GET
@login_required
def get_is_gear_complete(request, id):
    return HttpResponse(
        simplejson.dumps({'complete': is_gear_complete(id)}),
        content_type='application/javascript')


@never_cache
@require_GET
@login_required
def get_gear_user_info_form(request, id):
    gear = get_object_or_404(Gear, id=id)
    gear_user_info, created = GearUserInfo.objects.get_or_create(
        gear=gear,
        user=request.user,
    )

    form = GearUserInfoForm(instance=gear_user_info)

    from bootstrap_toolkit.templatetags.bootstrap_toolkit import as_bootstrap
    response_dict = {
        'form': as_bootstrap(form, 'horizontal') if form else '',
    }

    return HttpResponse(
        simplejson.dumps(response_dict),
        content_type='application/javascript')


@never_cache
@require_POST
@login_required
def save_gear_user_info(request):
    gear = get_object_or_404(Gear, id=request.POST.get('gear_id'))
    gear_user_info, created = GearUserInfo.objects.get_or_create(
        gear=gear,
        user=request.user,
    )

    form = GearUserInfoForm(data=request.POST, instance=gear_user_info)
    if not form.is_valid():
        from bootstrap_toolkit.templatetags.bootstrap_toolkit import as_bootstrap
        response_dict = {
            'form': as_bootstrap(form, 'horizontal') if form else '',
        }
        return HttpResponse(
            simplejson.dumps(response_dict),
            content_type='application/javascript')

    form.save()
    return ajax_success()


@never_cache
@require_GET
def gear_popover_ajax(request, id, image_id):
    gear, gear_type = get_correct_gear(id)
    image = get_object_or_404(Image.objects_including_wip, id=image_id)
    template = 'popover/gear.html'

    html = render_to_string(template, {
        'request': request,
        'user': request.user,
        'gear': gear,
        'image': image,
        'is_authenticated': request.user.is_authenticated,
        'IMAGES_URL': settings.IMAGES_URL,
        'REQUEST_COUNTRY': get_client_country_code(request),
        'search_query': request.GET.get('q', ''),
    })

    response_dict = {
        'success': True,
        'html': html,
    }

    return HttpResponse(
        simplejson.dumps(response_dict),
        content_type='application/javascript')


@never_cache
@require_GET
def user_popover_ajax(request, username):
    profile = get_object_or_404(UserProfile, user__username=username)
    template = 'popover/user.html'

    from django.template.defaultfilters import timesince

    date_time = profile.user.date_joined.replace(tzinfo=None)
    span = timesince(date_time)
    span = span.split(",")[0]  # just the most significant digit
    if span == "0 " + _("minutes"):
        member_since = _("seconds ago")
    else:
        member_since = _("%s ago") % span

    html = render_to_string(template,
                            {
                                'user': profile.user,
                                'images': Image.objects.filter(user=profile.user).count(),
                                'member_since': member_since,
                                'is_authenticated': request.user.is_authenticated,
                                'request': request,
                            })

    response_dict = {
        'success': True,
        'html': html,
    }

    return HttpResponse(
        simplejson.dumps(response_dict),
        content_type='application/javascript')


@never_cache
@require_GET
def gear_by_image(request, image_id):
    image = get_object_or_404(Image.objects_including_wip, pk=image_id)

    if image.user != request.user:
        return HttpResponseForbidden()

    attrs = ('imaging_telescopes', 'guiding_telescopes', 'mounts',
             'imaging_cameras', 'guiding_cameras', 'focal_reducers',
             'software', 'filters', 'accessories',)
    response_dict = {}

    for attr in attrs:
        ids = [int(x) for x in getattr(image, attr).all().values_list('id', flat=True)]
        response_dict[attr] = ids

    return HttpResponse(
        simplejson.dumps(response_dict),
        content_type='application/javascript')


@never_cache
@require_GET
def gear_by_make(request, make):
    klass = request.GET.get('klass', Gear)

    ret = {
        'make': make,
        'gear': []
    }

    from astrobin.gear import CLASS_LOOKUP

    if klass != Gear:
        klass = CLASS_LOOKUP[klass]

    gear = klass.objects.filter(make=ret['make']).order_by('name')

    ret['gear'] = [{'id': x.id, 'name': x.get_name()} for x in gear]

    return HttpResponse(
        simplejson.dumps(ret),
        content_type='application/javascript')


@never_cache
@require_GET
def gear_by_ids(request, ids):
    filters = reduce(operator.or_, [Q(**{'id': x}) for x in ids.split(',')])
    gear = [[str(x.id), x.get_make(), x.get_name()] for x in Gear.objects.filter(filters)]
    return HttpResponse(
        simplejson.dumps(gear),
        content_type='application/javascript')


@never_cache
@require_GET
def get_makes_by_type(request, klass):
    ret = {
        'makes': []
    }

    from astrobin.gear import CLASS_LOOKUP
    from astrobin.utils import unique_items

    ret['makes'] = unique_items([x.get_make() for x in CLASS_LOOKUP[klass].objects.exclude(make='').exclude(make=None)])
    return HttpResponse(
        simplejson.dumps(ret),
        content_type='application/javascript')
