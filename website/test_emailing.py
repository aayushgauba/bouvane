from email import policy
from email.parser import BytesParser
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from .auth import StaffAccountAdapter
from .emailing import branded_email, send_enquiry_notification
from .models import Enquiry


@override_settings(
    MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    CONTACT_RECIPIENT='support@bouvane.com',
)
class BrandedEmailTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('staff@example.com', is_staff=True)
        self.context = {
            'user': self.user, 'email': self.user.email, 'code': 'AB12CD34',
            'current_site': SimpleNamespace(name='Bouvane', domain='bouvane.com'),
            'password_reset_url': 'https://bouvane.com/accounts/password/reset/key/test-token/?next=dashboard&source=email',
            'activate_url': 'https://bouvane.com/accounts/confirm-email/test-token/',
            'ip': '192.0.2.1', 'user_agent': 'Example browser', 'timestamp': timezone.now(),
            'old_email': 'old@example.com', 'new_email': self.user.email,
        }

    def account_email(self, kind):
        return StaffAccountAdapter().render_mail(kind, self.user.email, self.context)

    def html(self, message):
        return next(part.content for part in message.alternatives if part.mimetype == 'text/html')

    def test_verification_is_html_and_plaintext_with_same_code(self):
        message = self.account_email('account/email/email_confirmation')
        html = self.html(message)
        self.assertIn(self.context['code'], html)
        self.assertIn(self.context['code'], message.body)
        self.assertIn('Verify your email address.', html)
        self.assertIn('#b62620', html)
        self.assertIn('#ff7317', html)
        self.assertIn('#ffb823', html)
        self.assertIn('cid:bouvane-logo', html)
        self.assertNotIn('<script', html)
        self.assertEqual(message.reply_to, ['support@bouvane.com'])

    def test_login_code_uses_dedicated_branded_template(self):
        message = self.account_email('account/email/login_code')
        html = self.html(message)
        self.assertEqual(message.subject, '[Bouvane] Your sign-in code')
        self.assertIn('YOUR ONE-TIME LOGIN CODE', html)
        self.assertIn('Keep this code private.', html)
        self.assertIn('5 minutes', html)
        self.assertIn(self.context['code'], html)
        self.assertIn(self.context['code'], message.body)
        self.assertIn('cid:bouvane-logo', html)

    def test_password_reset_button_retains_the_complete_token_url(self):
        message = self.account_email('account/email/password_reset_key')
        self.assertIn(self.context['password_reset_url'], message.body)
        self.assertIn('test-token/?next=dashboard&amp;source=email', self.html(message))
        self.assertIn('Reset your password', self.html(message))

    def test_all_security_notifications_receive_html_and_keep_audit_context(self):
        for prefix in [
            'account/email/email_changed', 'account/email/email_deleted',
            'account/email/password_changed', 'account/email/password_reset', 'account/email/password_set',
            'mfa/email/totp_activated', 'mfa/email/totp_deactivated',
            'mfa/email/webauthn_added', 'mfa/email/webauthn_removed',
            'mfa/email/recovery_codes_generated',
        ]:
            with self.subTest(prefix=prefix):
                message = self.account_email(prefix)
                self.assertIn('192.0.2.1', message.body)
                self.assertIn('192.0.2.1', self.html(message))
                self.assertIn('support@bouvane.com', self.html(message))
                self.assertTrue(message.subject.startswith('[Bouvane]'))

    def test_logo_is_a_related_inline_resource_not_a_remote_url(self):
        message = self.account_email('account/email/email_confirmation')
        parsed = BytesParser(policy=policy.default).parsebytes(message.message(policy=policy.SMTP).as_bytes())
        self.assertEqual(parsed.get_content_type(), 'multipart/alternative')
        html = parsed.get_body(preferencelist=('html',))
        self.assertIsNotNone(html)
        logos = [part for part in parsed.walk() if part['Content-ID'] == '<bouvane-logo>']
        self.assertEqual(len(logos), 1)
        self.assertEqual(logos[0].get_content_disposition(), 'inline')
        self.assertEqual(logos[0].get_content_type(), 'image/jpeg')
        self.assertTrue(logos[0].get_payload(decode=True).startswith(b'\xff\xd8'))
        self.assertNotIn('src="https://', html.get_content())

    def test_contact_notification_escapes_visitor_input_and_links_to_uuid_record(self):
        enquiry = Enquiry.objects.create(
            name='<img src=x onerror=alert(1)>', email='visitor@example.com', service='AIWAF',
            message='<script>alert(1)</script> This is a test message.',
        )
        send_enquiry_notification(enquiry)
        message = mail.outbox[0]
        html = self.html(message)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        self.assertIn(str(enquiry.pk), html)
        self.assertIn(enquiry.message, message.body)
        self.assertEqual(message.to, ['support@bouvane.com'])

    @override_settings(SUPPORT_EMAIL='help@bouvane.com', PUBLIC_SITE_URL='https://portal.example.com')
    def test_branding_uses_configured_support_and_site_url(self):
        message = branded_email(subject='Test', text_body='Plain fallback', to=['test@example.com'], heading='Test')
        self.assertIn('help@bouvane.com', self.html(message))
        self.assertIn('https://portal.example.com', self.html(message))
        self.assertEqual(message.reply_to, ['help@bouvane.com'])
