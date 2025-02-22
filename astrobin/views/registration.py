

from captcha.fields import ReCaptchaField
from captcha.widgets import ReCaptchaV2Checkbox
from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _
from registration.backends.hmac.views import RegistrationView
from registration.forms import (
    RegistrationFormUniqueEmail, RegistrationFormTermsOfService)
from registration.signals import user_registered

from astrobin.models import UserProfile
from astrobin_apps_notifications.utils import push_notification


class AstroBinRegistrationForm(RegistrationFormUniqueEmail, RegistrationFormTermsOfService):
    referral_code = forms.fields.CharField(
        required=False,
        label=_('Referral code (optional)'),
    )

    important_communications = forms.fields.BooleanField(
        widget=forms.CheckboxInput,
        required=False,
        label=_('I accept to receive rare important communications via email'),
        help_text=_(
            'This is highly recommended. These are very rare and contain information that you probably want to have.'))

    newsletter = forms.fields.BooleanField(
        widget=forms.CheckboxInput,
        required=False,
        label=_('I accept to receive occasional newsletters via email'),
        help_text=_(
            'Newsletters do not have a fixed schedule, but in any case they are not sent out more often than once per month.'))

    marketing_material = forms.fields.BooleanField(
        widget=forms.CheckboxInput,
        required=False,
        label=_('I accept to receive occasional marketing and commercial material via email'),
        help_text=_('These emails may contain offers, commercial news, and promotions from AstroBin or its partners.'))

    recaptcha = ReCaptchaField(
        label=_('Are you a robot?'),
        widget=ReCaptchaV2Checkbox(
            attrs={
                'data-theme': 'dark',
            }
        )
    )

    def clean(self):
        username_value = self.cleaned_data.get(User.USERNAME_FIELD)
        if username_value is not None and User.objects.filter(username__iexact=username_value).exists():
            self.add_error(
                User.USERNAME_FIELD,
                _('Sorry, this username already exists with a different capitalization.'))

        super(AstroBinRegistrationForm, self).clean()


class AstroBinRegistrationView(RegistrationView):
    form_class = AstroBinRegistrationForm


def user_created(sender, user, request, **kwargs):
    form = AstroBinRegistrationForm(request.POST)
    profile, created = UserProfile.objects.get_or_create(user=user)
    changed = False

    if 'referral_code' in form.data and form.data['referral_code'] != '':
        profile.referral_code = form.data['referral_code']
        changed = True

    if 'tos' in form.data:
        profile.accept_tos = form.data['tos'] == "on"
        changed = True

    if 'important_communications' in form.data:
        profile.receive_important_communications = form.data['important_communications'] == "on"
        changed = True

    if 'newsletter' in form.data:
        profile.receive_newsletter = form.data['newsletter'] == "on"
        changed = True

    if 'marketing_material' in form.data:
        profile.receive_marketing_and_commercial_material = form.data['marketing_material'] == "on"
        changed = True

    if changed:
        profile.save(keep_deleted=True)

    push_notification([user], None, 'welcome_to_astrobin', {
        'BASE_URL': settings.BASE_URL,
    })


user_registered.connect(user_created)
