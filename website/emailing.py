from email.policy import default
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse


class BrandedEmail(EmailMultiAlternatives):
    """Keep the logo next to its HTML body as a multipart/related resource."""

    logo_path = None

    def message(self, *, policy=default):
        message = super().message(policy=policy)
        html_part = message.get_body(preferencelist=('html',))
        if html_part is not None and self.logo_path:
            html_part.add_related(
                Path(self.logo_path).read_bytes(), maintype='image', subtype='jpeg',
                cid='<bouvane-logo>', disposition='inline',
            )
        return message


def branded_email(*, subject, text_body, to, heading, lead='', detail_text='',
                  code='', action_url='', action_label='', safety_note='',
                  reply_to=None, headers=None):
    logo_path = finders.find('images/logo.jpeg')
    html = render_to_string('website/email/message.html', {
        'heading': heading, 'lead': lead, 'detail_text': detail_text,
        'code': code, 'action_url': action_url, 'action_label': action_label,
        'safety_note': safety_note, 'has_logo': bool(logo_path),
        'support_email': settings.SUPPORT_EMAIL,
        'site_url': settings.PUBLIC_SITE_URL.rstrip('/'),
    })
    message = BrandedEmail(
        subject=subject, body=text_body, from_email=settings.DEFAULT_FROM_EMAIL,
        to=to, reply_to=reply_to or [settings.SUPPORT_EMAIL], headers=headers,
    )
    message.logo_path = logo_path
    message.attach_alternative(html, 'text/html')
    return message


def brand_account_email(message, template_prefix, context):
    kind = template_prefix.rsplit('/', 1)[-1]
    options = {'heading': message.subject.removeprefix(settings.ACCOUNT_EMAIL_SUBJECT_PREFIX), 'detail_text': message.body}
    if template_prefix.startswith('mfa/') or kind in ['password_changed', 'password_set', 'email_changed', 'email_deleted']:
        options.update(
            action_url=settings.PUBLIC_SITE_URL.rstrip('/') + reverse('mfa_index'),
            action_label='Review account security',
        )
    if kind in ['email_confirmation', 'email_confirmation_signup']:
        options = {
            'heading': 'Verify your email address.',
            'lead': 'One more step to your Bouvane workspace. Enter this code in the browser where you started signing in.',
            'code': context.get('code', ''),
            'safety_note': f'This code expires in {settings.ACCOUNT_EMAIL_VERIFICATION_BY_CODE_TIMEOUT // 60} minutes. If you did not request it, you can ignore this email. Never share your code.',
        }
        if not options['code']:
            options.update(
                lead='Confirm the email address linked to your Bouvane account using the secure button below.',
                action_url=context.get('activate_url', ''), action_label='Verify email address',
                safety_note='If you did not request this verification, you can ignore this email.',
            )
    elif kind == 'password_reset_key':
        options = {
            'heading': 'Reset your password.',
            'lead': 'We received a request to reset the password for your Bouvane account. Choose a new password using the secure link below.',
            'action_url': context.get('password_reset_url', ''),
            'action_label': 'Reset your password',
            'safety_note': 'If you did not request a password reset, you can ignore this email. Your password will stay the same.',
        }
    elif kind in ['password_reset_code', 'login_code']:
        options = {
            'heading': 'Your Bouvane security code.',
            'lead': 'Enter this code in the browser where you started the request.',
            'code': context.get('code', ''),
            'safety_note': 'Never share your code. If you did not request it, you can ignore this email.',
        }
    return branded_email(
        subject=message.subject, text_body=message.body, to=message.to,
        headers=message.extra_headers, **options,
    )


def send_enquiry_notification(enquiry):
    body = (
        f'Name: {enquiry.name}\nEmail: {enquiry.email}\nCompany: {enquiry.company or "Not provided"}'
        f'\nTopic: {enquiry.service}\n\n{enquiry.message}'
    )
    url = settings.PUBLIC_SITE_URL.rstrip('/') + reverse('dashboard_enquiry', args=[enquiry.pk])
    message = branded_email(
        subject=f'Bouvane enquiry: {enquiry.service}', text_body=body + f'\n\nView enquiry: {url}',
        to=[settings.CONTACT_RECIPIENT], heading='A new conversation.',
        lead='A visitor has contacted Bouvane. Sign in to the staff portal to review and manage the enquiry.',
        detail_text=body, action_url=url, action_label='View enquiry',
    )
    return message.send()
