from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.http import Http404
from hitcount.models import HitCount
from persistent_messages.models import Message
from tastypie import fields, http
from tastypie.authentication import Authentication
from tastypie.exceptions import InvalidFilterError
from tastypie.resources import ModelResource, ALL, ALL_WITH_RELATIONS

from astrobin.enums.license import License
from astrobin.models import Location, Image, ImageRevision, ImageOfTheDay, App, Collection, UserProfile
from astrobin.views import get_image_or_404
from astrobin_apps_images.services import ImageService
from astrobin_apps_iotd.models import TopPickArchive, TopPickNominationsArchive
from astrobin_apps_platesolving.services import SolutionService
from astrobin_apps_platesolving.solver import Solver
from astrobin_apps_premium.utils import premium_get_valid_usersubscription
from toggleproperties.models import ToggleProperty


class AppAuthentication(Authentication):
    def is_authenticated(self, request, **kwargs):
        try:
            app_key = request.GET.get('api_key')
            app_secret = request.GET.get('api_secret')
        except:
            return False

        if app_key == '' or app_secret == '':
            return False

        try:
            app = App.objects.get(secret=app_secret, key=app_key)
        except App.DoesNotExist:
            return False

        return True


class LocationResource(ModelResource):
    """
    name = fields.CharField()
    city = fields.CharField()
    state = fields.CharField()
    country = fields.CharField()
    altitude = fields.IntegerField()
    """

    class Meta:
        authentication = AppAuthentication()
        queryset = Location.objects.all()
        fields = [
            'name',
            'city',
            'state',
            'country',
            'altitude',
        ]
        allowed_methods = ['get']


class ImageRevisionResource(ModelResource):
    image = fields.ForeignKey('astrobin.api.ImageResource', 'image')
    url_thumb = fields.CharField()
    url_gallery = fields.CharField()
    url_regular = fields.CharField()
    url_regular_sharpened = fields.CharField()
    url_hd = fields.CharField()
    url_hd_sharpened = fields.CharField()
    url_real = fields.CharField()
    url_duckduckgo = fields.CharField()
    url_duckduckgo_small = fields.CharField()
    url_histogram = fields.CharField()
    url_skyplot = fields.CharField()
    url_advanced_skyplot = fields.CharField()
    url_advanced_skyplot_small = fields.CharField()
    url_solution = fields.CharField()
    url_advanced_solution = fields.CharField()

    is_solved = fields.BooleanField()
    solution_status = fields.CharField()

    ra = fields.DecimalField()
    dec = fields.DecimalField()
    pixscale = fields.DecimalField()
    orientation = fields.DecimalField()
    radius = fields.DecimalField()

    class Meta:
        authentication = AppAuthentication()
        queryset = ImageRevision.objects.filter(image__is_wip=False)
        fields = [
            'id',
            'uploaded',
            'w',
            'h',
            'label',
            'title',
            'description',

            'url_thumb',
            'url_gallery',
            'url_regular',
            'url_regular_sharpened',
            'url_hd',
            'url_hd_sharpened',
            'url_real',
            'url_duckduckgo',
            'url_duckduckgo_small',
            'url_histogram',
            'url_skyplot',
            'url_advanced_skyplot',
            'url_advanced_skyplot_small',
            'url_solution',
            'url_advanced_solution',

            'is_final',
            'is_solved',
            'solution_status',

            'ra',
            'dec',
            'pixscale',
            'orientation',
            'radius',
        ]

        allowed_methods = ['get']

    def dehydrate_url_thumb(self, bundle):
        return '%s/%s/%s/rawthumb/thumb/' % (settings.BASE_URL, bundle.obj.image.get_id(), bundle.obj.label)

    def dehydrate_url_gallery(self, bundle):
        return '%s/%s/%s/rawthumb/gallery/' % (settings.BASE_URL, bundle.obj.image.get_id(), bundle.obj.label)

    def dehydrate_url_regular(self, bundle):
        return '%s/%s/%s/rawthumb/regular/' % (settings.BASE_URL, bundle.obj.image.get_id(), bundle.obj.label)

    def dehydrate_url_regular_sharpened(self, bundle):
        return '%s/%s/%s/rawthumb/regular_sharpened/' % (settings.BASE_URL, bundle.obj.image.get_id(), bundle.obj.label)

    def dehydrate_url_hd(self, bundle):
        return '%s/%s/%s/rawthumb/hd/' % (settings.BASE_URL, bundle.obj.image.get_id(), bundle.obj.label)

    def dehydrate_url_hd_sharpened(self, bundle):
        return '%s/%s/%s/rawthumb/hd_sharpened/' % (settings.BASE_URL, bundle.obj.image.get_id(), bundle.obj.label)

    def dehydrate_url_real(self, bundle):
        return '%s/%s/%s/rawthumb/real/' % (settings.BASE_URL, bundle.obj.image.get_id(), bundle.obj.label)

    def dehydrate_url_duckduckgo(self, bundle):
        return '%s/%s/%s/rawthumb/duckduckgo/' % (settings.BASE_URL, bundle.obj.image.get_id(), bundle.obj.label)

    def dehydrate_url_duckduckgo_small(self, bundle):
        return '%s/%s/%s/rawthumb/duckduckgo_small/' % (settings.BASE_URL, bundle.obj.image.get_id(), bundle.obj.label)

    def dehydrate_url_histogram(self, bundle):
        return '%s/%s/%s/rawthumb/histogram/' % (settings.BASE_URL, bundle.obj.image.get_id(), bundle.obj.label)

    def dehydrate_url_skyplot(self, bundle):
        return bundle.obj.solution.skyplot_zoom1.url \
            if bundle.obj.solution and bundle.obj.solution.skyplot_zoom1 \
            else None

    def dehydrate_url_advanced_skyplot(self, bundle):
        return bundle.obj.solution.pixinsight_finding_chart.url \
            if bundle.obj.solution and bundle.obj.solution.pixinsight_finding_chart \
            else None

    def dehydrate_url_advanced_skyplot_small(self, bundle):
        return bundle.obj.solution.pixinsight_finding_chart_small.url \
            if bundle.obj.solution and bundle.obj.solution.pixinsight_finding_chart_small \
            else None

    def dehydrate_url_solution(self, bundle):
        return bundle.obj.solution.image_file.url \
            if bundle.obj.solution and bundle.obj.solution.image_file \
            else None

    def dehydrate_url_advanced_solution(self, bundle):
        return bundle.obj.solution.pixinsight_svg_annotation_hd.url \
            if bundle.obj.solution and bundle.obj.solution.pixinsight_svg_annotation_hd \
            else None

    def dehydrate_is_solved(self, bundle):
        solution = bundle.obj.solution
        return solution != None and solution.status >= Solver.SUCCESS

    def dehydrate_solution_status(self, bundle):
        solution = bundle.obj.solution

        if solution is None or solution.status == Solver.MISSING:
            return "MISSING"

        if solution.status == Solver.PENDING:
            return "PENDING"

        if solution.status == Solver.FAILED:
            return "FAILED"

        if solution.status == Solver.SUCCESS:
            return "SUCCESS"

        if solution.status == Solver.ADVANCED_PENDING:
            return "ADVANCED_PENDING"

        if solution.status == Solver.ADVANCED_FAILED:
            return "ADVANCED_FAILED"

        if solution.status == Solver.ADVANCED_SUCCESS:
            return "ADVANCED_SUCCESS"

    def dehydrate_ra(self, bundle):
        if bundle.obj.solution:
            return bundle.obj.solution.ra
        return None

    def dehydrate_dec(self, bundle):
        if bundle.obj.solution:
            return bundle.obj.solution.dec
        return None

    def dehydrate_pixscale(self, bundle):
        if bundle.obj.solution:
            return bundle.obj.solution.pixscale
        return None

    def dehydrate_orientation(self, bundle):
        if bundle.obj.solution:
            return bundle.obj.solution.orientation
        return None

    def dehydrate_radius(self, bundle):
        if bundle.obj.solution:
            return bundle.obj.solution.radius
        return None


class ImageResource(ModelResource):
    user = fields.CharField('user__username')
    revisions = fields.ToManyField(ImageRevisionResource, 'revisions')

    subjects = fields.ListField()

    imaging_telescopes = fields.ListField()
    imaging_cameras = fields.ListField()

    uploaded = fields.DateField('uploaded')
    published = fields.DateField('published')
    updated = fields.DateField('updated')

    description = fields.CharField()
    locations = fields.ToManyField(LocationResource, 'locations')
    data_source = fields.CharField('data_source', null=True)
    remote_source = fields.CharField('remote_source', null=True)
    license_name = fields.CharField('license')

    url_thumb = fields.CharField()
    url_gallery = fields.CharField()
    url_regular = fields.CharField()
    url_hd = fields.CharField()
    url_real = fields.CharField()
    url_duckduckgo = fields.CharField()
    url_duckduckgo_small = fields.CharField()
    url_histogram = fields.CharField()
    url_skyplot = fields.CharField()
    url_advanced_skyplot = fields.CharField()
    url_advanced_skyplot_small = fields.CharField()
    url_solution = fields.CharField()
    url_advanced_solution = fields.CharField()

    is_solved = fields.BooleanField()
    solution_status = fields.CharField()

    ra = fields.DecimalField()
    dec = fields.DecimalField()
    pixscale = fields.DecimalField()
    orientation = fields.DecimalField()
    radius = fields.DecimalField()

    likes = fields.IntegerField()
    bookmarks = fields.IntegerField()
    comments = fields.IntegerField()
    views = fields.IntegerField()

    class Meta:
        authentication = AppAuthentication()
        queryset = Image.all_objects.filter(is_wip=False, deleted__isnull=True, uploader_in_progress__isnull=True)
        fields = [
            'id',
            'hash',
            'title',
            'w',
            'h',
            'locations',
            'data_source',
            'remote_source',

            'url_thumb',
            'url_gallery',
            'url_regular',
            'url_hd',
            'url_real',
            'url_duckduckgo',
            'url_duckduckgo_small',
            'url_histogram',
            'url_skyplot',
            'url_advanced_skyplot',
            'url_advanced_skyplot_small',
            'url_solution',
            'url_advanced_solution',

            'uploaded',
            'published',
            'description',
            'h',
            'w',
            'animated',
            'link',
            'link_to_fits',
            'license',  # Deprecated
            'license_name',

            'is_final',
            'is_solved',
            'solution_status',

            'ra',
            'dec',
            'pixscale',
            'orientation',
            'radius',
        ]
        allowed_methods = ['get']

        filtering = {
            'title': ALL,
            'description': ALL,
            'is_solved': ALL,
            'user': ALL_WITH_RELATIONS,
            'uploaded': ALL,
            'published': ALL,
            'imaging_telescopes': ALL,
            'imaging_cameras': ALL,
            'w': ALL,
            'h': ALL,
            'data_source': ALL,
            'remote_source': ALL,
        }
        ordering = ['published', 'uploaded', 'title']

    def dehydrate_url_thumb(self, bundle):
        return '%s/%s/0/rawthumb/thumb/' % (settings.BASE_URL, bundle.obj.get_id())

    def dehydrate_url_gallery(self, bundle):
        return '%s/%s/0/rawthumb/gallery/' % (settings.BASE_URL, bundle.obj.get_id())

    def dehydrate_url_regular(self, bundle):
        return '%s/%s/0/rawthumb/regular/' % (settings.BASE_URL, bundle.obj.get_id())

    def dehydrate_url_hd(self, bundle):
        return '%s/%s/0/rawthumb/hd/' % (settings.BASE_URL, bundle.obj.get_id())

    def dehydrate_url_real(self, bundle):
        return '%s/%s/0/rawthumb/real/' % (settings.BASE_URL, bundle.obj.get_id())

    def dehydrate_url_duckduckgo(self, bundle):
        return '%s/%s/0/rawthumb/duckduckgo/' % (settings.BASE_URL, bundle.obj.get_id())

    def dehydrate_url_duckduckgo_small(self, bundle):
        return '%s/%s/0/rawthumb/duckduckgo_small/' % (settings.BASE_URL, bundle.obj.get_id())

    def dehydrate_url_histogram(self, bundle):
        return '%s/%s/0/rawthumb/histogram/' % (settings.BASE_URL, bundle.obj.get_id())

    def dehydrate_url_skyplot(self, bundle):
        return bundle.obj.solution.skyplot_zoom1.url \
            if bundle.obj.solution and bundle.obj.solution.skyplot_zoom1 \
            else None

    def dehydrate_url_advanced_skyplot(self, bundle):
        return bundle.obj.solution.pixinsight_finding_chart.url \
            if bundle.obj.solution and bundle.obj.solution.pixinsight_finding_chart \
            else None

    def dehydrate_url_advanced_skyplot_small(self, bundle):
        return bundle.obj.solution.pixinsight_finding_chart_small.url \
            if bundle.obj.solution and bundle.obj.solution.pixinsight_finding_chart_small \
            else None

    def dehydrate_url_solution(self, bundle):
        return bundle.obj.solution.image_file.url \
            if bundle.obj.solution and bundle.obj.solution.image_file \
            else None

    def dehydrate_url_advanced_solution(self, bundle):
        return bundle.obj.solution.pixinsight_svg_annotation_hd.url \
            if bundle.obj.solution and bundle.obj.solution.pixinsight_svg_annotation_hd \
            else None

    def dehydrate_is_solved(self, bundle):
        solution = bundle.obj.solution
        return solution != None and solution.status >= Solver.SUCCESS

    def dehydrate_solution_status(self, bundle):
        solution = bundle.obj.solution

        if solution is None or solution.status == Solver.MISSING:
            return "MISSING"

        if solution.status == Solver.PENDING:
            return "PENDING"

        if solution.status == Solver.FAILED:
            return "FAILED"

        if solution.status == Solver.SUCCESS:
            return "SUCCESS"

        if solution.status == Solver.ADVANCED_PENDING:
            return "ADVANCED_PENDING"

        if solution.status == Solver.ADVANCED_FAILED:
            return "ADVANCED_FAILED"

        if solution.status == Solver.ADVANCED_SUCCESS:
            return "ADVANCED_SUCCESS"

    def dehydrate_subjects(self, bundle):
        if bundle.obj.solution:
            subjects = SolutionService(bundle.obj.solution).get_objects_in_field()
            solar_system_main_subject = bundle.obj.solar_system_main_subject

            ret = subjects

            if solar_system_main_subject:
                ret.append(ImageService(bundle.obj).get_solar_system_main_subject_label())

            return ret
        return []

    def dehydrate_ra(self, bundle):
        if bundle.obj.solution:
            return bundle.obj.solution.ra
        return None

    def dehydrate_dec(self, bundle):
        if bundle.obj.solution:
            return bundle.obj.solution.dec
        return None

    def dehydrate_pixscale(self, bundle):
        if bundle.obj.solution:
            return bundle.obj.solution.pixscale
        return None

    def dehydrate_orientation(self, bundle):
        if bundle.obj.solution:
            return bundle.obj.solution.orientation
        return None

    def dehydrate_radius(self, bundle):
        if bundle.obj.solution:
            return bundle.obj.solution.radius
        return None

    def dehydrate_imaging_telescopes(self, bundle):
        telescopes = bundle.obj.imaging_telescopes.all()
        return [str(x) for x in telescopes]

    def dehydrate_imaging_cameras(self, bundle):
        cameras = bundle.obj.imaging_cameras.all()
        return [str(x) for x in cameras]

    def dehydrate_description(self, bundle):
        if bundle.obj.description_bbcode:
            return bundle.obj.description_bbcode
        return bundle.obj.description

    def dehydrate_license(self, bundle):
        return License.to_deprecated_integer(bundle.obj.license)

    def dehydrate_likes(self, bundle):
        return ToggleProperty.objects.toggleproperties_for_object('like', bundle.obj).count()

    def dehydrate_bookmarks(self, bundle):
        return ToggleProperty.objects.toggleproperties_for_object('bookmark', bundle.obj).count()

    def dehydrate_comments(self, bundle):
        return bundle.obj.nested_comments.count()

    def dehydrate_views(self, bundle):
        try:
            return HitCount.objects.get(
                object_pk=bundle.obj.pk,
                content_type=ContentType.objects.get_for_model(Image),
            ).hits
        except (HitCount.DoesNotExist, HitCount.MultipleObjectsReturned):
            return 0

    def get_detail(self, request, **kwargs):
        """
        Returns a single serialized resource.

        Calls ``cached_obj_get/obj_get`` to provide the data, then handles that result
        set and serializes it.

        Should return a HttpResponse (200 OK).
        """

        try:
            obj = get_image_or_404(self._meta.queryset, kwargs.get("pk"))
        except Http404:
            return http.HttpNotFound()

        bundle = self.build_bundle(obj=obj, request=request)
        bundle = self.full_dehydrate(bundle)
        bundle = self.alter_detail_data_to_serialize(request, bundle)
        return self.create_response(request, bundle)

    def build_filters(self, filters=None, ignore_bad_filters=False):
        subjects = None
        ids = None
        user = None

        if filters is None:
            filters = {}

        if 'subjects' in filters:
            subjects = filters['subjects']
            del filters['subjects']

        if 'ids' in filters:
            ids = filters['ids']
            del filters['ids']

        if 'user' in filters:
            user = filters['user']
            del filters['user']

        orm_filters = super(ImageResource, self).build_filters(filters, ignore_bad_filters)

        if subjects:
            from astrobin_apps_platesolving.models import Solution

            def fix_catalog(name):
                capitalize = ('ngc', 'm', 'b', 'ic', 'ugc', 'pgc',)
                if name.lower() in [x.lower() for x in capitalize]:
                    return name.upper() + ' '
                remove = ('name',)
                if name.lower() in [x.lower() for x in remove]:
                    return ''
                return name + ' '

            def fix_name(name):
                import re
                fix = re.compile('^(?P<catalog>M|NGC)(?P<name>\d+)', re.IGNORECASE)
                m = fix.match(name)
                if m:
                    return '%s%s' % (fix_catalog(m.group('catalog')), m.group('name'))
                return name

            qs = Solution.objects.filter(objects_in_field__icontains=fix_name(subjects))[:100]
            orm_filters['pk__in'] = [i.object_id for i in qs]

        if ids:
            max = 100
            if len(ids) > max:
                raise InvalidFilterError(f'Please do not request over {max} image IDs')
            orm_filters['pk__in'] = ids.split(',')

        if user:
            orm_filters['user__username'] = user

        return orm_filters


class ImageOfTheDayResource(ModelResource):
    image = fields.ForeignKey('astrobin.api.ImageResource', 'image')
    runnerup_1 = fields.ForeignKey('astrobin.api.ImageResource', 'runnerup_1', null=True)
    runnerup_2 = fields.ForeignKey('astrobin.api.ImageResource', 'runnerup_2', null=True)

    class Meta:
        authentication = AppAuthentication()
        queryset = ImageOfTheDay.objects.filter()
        fields = [
            'image',
            'runnerup_1',
            'runnerup_2',
            'date',
        ]
        allowed_methods = ['get']

    def dehydrate_image(self, bundle):
        return "/api/v1/image/%s" % bundle.obj.image.get_id()


class TopPickResource(ModelResource):
    image = fields.ForeignKey('astrobin.api.ImageResource', 'image')
    date = fields.DateField('date', null=True)

    class Meta:
        authentication = AppAuthentication()
        queryset = TopPickArchive.objects.all()
        fields = [
            'image',
        ]
        allowed_methods = ['get']

    def dehydrate_image(self, bundle):
        return "/api/v1/image/%s" % bundle.obj.image.get_id()

    def dehydrate_date(self, bundle):
        return bundle.obj.image.published


class TopPickNominationResource(ModelResource):
    image = fields.ForeignKey('astrobin.api.ImageResource', 'image')
    date = fields.DateField('date', null=True)

    class Meta:
        authentication = AppAuthentication()
        queryset = TopPickNominationsArchive.objects.all()
        fields = [
            'image',
        ]
        allowed_methods = ['get']

    def dehydrate_image(self, bundle):
        return "/api/v1/image/%s" % bundle.obj.image.get_id()

    def dehydrate_date(self, bundle):
        return bundle.obj.image.published


class CollectionResource(ModelResource):
    date_created = fields.DateField('date_created')
    date_updated = fields.DateField('date_updated')
    user = fields.CharField('user__username')
    name = fields.CharField('name')
    description = fields.CharField('description')
    images = fields.ToManyField(ImageResource, 'images')

    class Meta:
        authentication = AppAuthentication()
        allowed_methods = ['get']
        queryset = Collection.objects.all()
        filtering = {
            'name': ALL,
            'description': ALL,
            'user': ALL_WITH_RELATIONS,
        }
        ordering = ['-date_created']

    def dehydrate_images(self, bundle):
        images = bundle.obj.images.all()
        return ["/api/v1/image/%s" % image.get_id() for image in images]


class UserProfileResource(ModelResource):
    username = fields.CharField("user__username")
    last_login = fields.DateTimeField("user__last_login", null=True)
    date_joined = fields.DateTimeField("user__date_joined")
    timezone = fields.CharField()

    image_count = fields.IntegerField()
    received_likes_count = fields.IntegerField()
    followers_count = fields.IntegerField()
    following_count = fields.IntegerField()
    total_notifications_count = fields.IntegerField()
    unread_notifications_count = fields.IntegerField()
    premium_subscription = fields.CharField()
    premium_subscription_expiration = fields.DateField()

    class Meta:
        authentication = AppAuthentication()
        allowed_methods = ["get"]
        queryset = UserProfile.objects.all()
        fields = [
            'about',
            'allow_astronomy_ads',
            'allow_retailer_integration',
            'astrobin_index_bonus',
            'avatar',
            'banned_from_competitions',
            'date_joined',
            'delete_reason',
            'delete_reason_other',
            'display_wip_images_on_public_gallery',
            'followers_count',
            'following_count',
            'hobbies',
            'id',
            'image_count',
            'job',
            'language',
            'last_login',
            'last_seen',
            'never_activated_account_reminder_sent',
            'plate_solution_overlay_on_full_disabled',
            'post_count',
            'premium_subscription',
            'premium_subscription_expiration',
            'real_name',
            'received_likes_count',
            'referral_code',
            'resource_uri',
            'total_notifications_count',
            'unread_notifications_count',
            'updated',
            'username',
            'website',
        ]
        ordering = ['-date_joined']

    def dehydrate_timezone(self, bundle):
        # Hardcode to GMT for compatibility reasons.
        # See https://github.com/astrobin/astrobin/pull/2429
        return 'Etc/GMT'

    def dehydrate_image_count(self, bundle):
        return Image.objects.filter(user=bundle.obj.user, is_wip=False).count()

    def dehydrate_received_likes_count(self, bundle):
        likes = 0
        for i in Image.objects.filter(user=bundle.obj.user):
            likes += ToggleProperty.objects.toggleproperties_for_object("like", i).count()
        return likes

    def dehydrate_followers_count(self, bundle):
        return ToggleProperty.objects.filter(
            property_type="follow",
            content_type=ContentType.objects.get_for_model(User),
            object_id=bundle.obj.user.pk,
        ).count()

    def dehydrate_following_count(self, bundle):
        return ToggleProperty.objects.filter(
            property_type="follow",
            user=bundle.obj.user,
        ).count()

    def dehydrate_total_notifications_count(self, bundle):
        return Message.objects.filter(user=bundle.obj.user).count()

    def dehydrate_unread_notifications_count(self, bundle):
        return Message.objects.filter(user=bundle.obj.user, read=False).count()

    def dehydrate_premium_subscription(self, bundle):
        user_subscription = premium_get_valid_usersubscription(bundle.obj.user)
        return user_subscription.subscription.name if user_subscription else None

    def dehydrate_premium_subscription_expiration(self, bundle):
        user_subscription = premium_get_valid_usersubscription(bundle.obj.user)
        return user_subscription.expires if user_subscription else None

    def build_filters(self, filters=None, ignore_bad_filters=False):
        if filters is None:
            filters = {}

        username = None

        if 'username' in filters:
            username = filters['username']
            del filters['username']

        orm_filters = super(UserProfileResource, self).build_filters(filters)

        if username:
            orm_filters['user__username'] = username

        return orm_filters
