import logging
from datetime import datetime, timedelta

import persistent_messages
from django.conf import settings
from django.core.mail import send_mail
from django.template import TemplateDoesNotExist
from django.template.loader import get_template, render_to_string
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext
from django_bouncy.models import Bounce, Complaint
from notification.backends import BaseBackend
from notification.backends.email import EmailBackend as BaseEmailBackend
from persistent_messages.models import Message

log = logging.getLogger('apps')


def shadow_ban_applies(notice_type, recipient, context):
    from astrobin_apps_users.services import UserService

    if notice_type.label == 'received_email':
        message_sender = context.get('message').sender
        if UserService(recipient).shadow_bans(message_sender):
            return True

    return False


class PersistentMessagesBackend(BaseBackend):
    spam_sensitivity = 1

    def deliver(self, recipient, sender, notice_type, extra_context):
        context = self.default_context()
        context.update(extra_context)

        if shadow_ban_applies(notice_type, recipient, context):
            return

        template = 'notice.html'
        message = self.get_formatted_messages([template], notice_type.label, context)[template]
        level = persistent_messages.INFO
        persistent_message = Message(user=recipient, from_user=sender, level=level, message=message)
        persistent_message.save()


class EmailBackend(BaseEmailBackend):
    def can_send(self, user, notice_type):
        hard_bounces = Bounce.objects.filter(
            hard=True,
            bounce_type="Permanent",
            address=user.email)
        soft_bounces = Bounce.objects.filter(
            hard=False,
            bounce_type="Transient",
            address=user.email,
            created_at__gte=datetime.now() - timedelta(days=7))
        complaints = Complaint.objects.filter(
            address=user.email)
        deleted = user.userprofile.deleted is not None
        ignored = 'ASTROBIN_IGNORE' in user.email

        if deleted or hard_bounces.exists() or soft_bounces.count() > 2 or complaints or ignored:
            return False

        return super(EmailBackend, self).can_send(user, notice_type)

    def deliver(self, recipient, sender, notice_type, extra_context):
        context = self.default_context()
        context.update({
            "recipient": recipient,
            "sender": sender,
            "notice": ugettext(notice_type.display),
        })
        context.update(extra_context)

        if shadow_ban_applies(notice_type, recipient, context):
            return

        messages = self.get_formatted_messages((
            "short.txt",
            "full.txt",
            "full.html"
        ), notice_type.label, context)

        subject = "".join(render_to_string("notification/email_subject.txt", dict(context, **{
            "message": messages["short.txt"],
        })).splitlines())

        body = render_to_string("notification/email_body.txt", dict(context, **{
            "message": messages["full.txt"]
        }))

        try:
            get_template("notification/%s/full.html" % notice_type.label)
            message = messages["full.html"]
        except TemplateDoesNotExist:
            message = messages["full.txt"]

        html_body = render_to_string("notification/email_body.html", dict(context, **{
            "message": mark_safe(str(message))
        }))

        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [settings.EMAIL_DEV_RECIPIENT if settings.SEND_EMAILS == 'dev' else recipient.email],
            html_message=html_body)

        log.info("Email sent to %s: %s" % (recipient.email, subject))
