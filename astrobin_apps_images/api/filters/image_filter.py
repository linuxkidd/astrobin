from django.db import models
from django_filters import FilterSet, IsoDateTimeFilter

from astrobin.models import Image
from common.filters.list_filter import ListFilter


class ImageFilter(FilterSet):
    id = ListFilter(field_name="id", lookup_expr='in')
    hash = ListFilter(field_name="hash", lookup_expr='in')

    class Meta:
        model = Image
        fields = {
            'id': (),
            'hash': (),
            'user': ('exact',),
            'uploaded': ('lt', 'lte', 'exact', 'gt', 'gte'),
            'published': ('lt', 'lte', 'exact', 'gt', 'gte'),
        }

    filter_overrides = {
        models.DateTimeField: {
            'filter_class': IsoDateTimeFilter
        },
    }
