# -*- coding: utf-8 -*-

import django
from django.utils import translation
from pybb.compat import is_authenticated

from astrobin.middleware.mixins import MiddlewareParentClass


class RequestLanguageMiddleware(MiddlewareParentClass):
    def process_request(self, request):
        if is_authenticated(request.user) and \
                hasattr(request.user, 'userprofile') and \
                request.user.userprofile.language:
            request.LANGUAGE_CODE = translation.get_language()
        else:
            request.LANGUAGE_CODE = "en"
