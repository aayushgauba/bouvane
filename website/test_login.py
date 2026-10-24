import re
import time
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from allauth.account.models import EmailAddress
from allauth.mfa.totp.internal.auth import TOTP, format_hotp_value, generate_totp_secret, hotp_value


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
)
class EmailFirstLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = get_user_model().objects.create_user('staff@bouvane.com', is_staff=True)
        cls.external = get_user_model().objects.create_user('staff@example.com', 'External-test-password-42!', is_staff=True)
        EmailAddress.objects.create(user=cls.external, email=cls.external.email, verified=True, primary=True)

    def setUp(self):
        cache.clear()

    def start_code(self, email=None):
        return self.client.post(reverse('account_login'), {'login': email or self.company.email})

    def emailed_code(self):
        return re.search(r'^([A-Z0-9]{8})$', mail.outbox[-1].body, flags=re.M).group(1)

    def test_first_screen_has_email_and_passkey_but_no_password(self):
        response = self.client.get(reverse('account_login'))
        self.assertContains(response, 'name="login"')
        self.assertContains(response, 'Sign in with a passkey')
        self.assertNotContains(response, 'type="password"')

    def test_external_email_goes_to_password_screen(self):
        response = self.start_code(self.external.email)
        self.assertRedirects(response, reverse('account_password_login'))
        self.assertEqual(len(mail.outbox), 0)
        page = self.client.get(reverse('account_password_login'))
        self.assertContains(page, 'type="password"')
        self.assertContains(page, self.external.email)
        self.assertNotContains(page, 'type="email"')

    def test_company_code_is_alphanumeric_and_html(self):
        response = self.start_code('STAFF@BOUVANE.COM')
        self.assertRedirects(response, reverse('account_confirm_login_code'))
        code = self.emailed_code()
        self.assertTrue(any(character.isdigit() for character in code))
        self.assertTrue(any(character.isalpha() for character in code))
        self.assertEqual(mail.outbox[-1].to, [self.company.email])
        self.assertIn(code, mail.outbox[-1].alternatives[0].content)

    def test_otp_verifies_email_and_still_requires_mfa_enrollment(self):
        self.start_code()
        code = self.emailed_code()
        response = self.client.post(reverse('account_confirm_login_code'), {'code': code.lower()})
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)
        self.assertTrue(EmailAddress.objects.get(user=self.company).verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('dashboard_setup'))
        self.assertEqual(self.client.get(reverse('mfa_activate_totp')).status_code, 200)

    def test_otp_requires_existing_mfa_before_authenticating(self):
        secret = generate_totp_secret()
        TOTP.activate(self.company, secret)
        self.start_code()
        response = self.client.post(reverse('account_confirm_login_code'), {'code': self.emailed_code()})
        self.assertRedirects(response, reverse('mfa_authenticate'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)
        code = format_hotp_value(hotp_value(secret, int(time.time()) // 30))
        self.client.post(reverse('mfa_authenticate'), {'code': code})
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_unknown_nonstaff_and_inactive_company_addresses_send_no_codes(self):
        get_user_model().objects.create_user('nonstaff@bouvane.com')
        get_user_model().objects.create_user('inactive@bouvane.com', is_staff=True, is_active=False)
        count = get_user_model().objects.count()
        for email in ['unknown@bouvane.com', 'nonstaff@bouvane.com', 'inactive@bouvane.com']:
            with self.subTest(email=email):
                response = self.start_code(email)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(len(mail.outbox), 0)
                self.assertNotIn('_auth_user_id', self.client.session)
                self.client.post(reverse('account_restart_login'))
        self.assertEqual(get_user_model().objects.count(), count)

    def test_domain_lookalikes_use_password_not_otp(self):
        for email in ['staff@bouvane.com.attacker.com', 'staff@notbouvane.com', 'staff@sub.bouvane.com']:
            with self.subTest(email=email):
                self.assertRedirects(self.start_code(email), reverse('account_password_login'))
                self.assertEqual(len(mail.outbox), 0)

    def test_password_step_requires_email_session_and_ignores_tampered_login(self):
        self.assertRedirects(self.client.get(reverse('account_password_login')), reverse('account_login'))
        self.start_code(self.external.email)
        response = self.client.post(reverse('account_password_login'), {
            'login': self.company.email, 'password': 'External-test-password-42!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session['_auth_user_id'], str(self.external.pk))

    def test_company_identity_cannot_use_password_endpoint(self):
        self.start_code()
        response = self.client.post(reverse('account_password_login'), {'password': 'anything'})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_direct_code_request_rejects_external_addresses(self):
        response = self.client.post(reverse('account_request_login_code'), {'email': self.external.email})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_code_expiration_and_attempt_limit(self):
        self.start_code()
        code = self.emailed_code()
        session = self.client.session
        session['account_login']['state']['stages']['login_by_code']['data']['at'] = time.time() - 301
        session.save()
        self.client.post(reverse('account_confirm_login_code'), {'code': code})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.client.post(reverse('account_restart_login'))
        self.start_code()
        for _ in range(5):
            self.client.post(reverse('account_confirm_login_code'), {'code': 'INVALID0'})
        self.assertNotIn('account_login', self.client.session)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_resend_invalidates_previous_code_and_restart_clears_challenge(self):
        self.start_code()
        old = self.emailed_code()
        self.client.post(reverse('account_confirm_login_code'), {'action': 'resend'})
        new = self.emailed_code()
        self.assertNotEqual(old, new)
        self.client.post(reverse('account_confirm_login_code'), {'code': old})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.client.post(reverse('account_restart_login'))
        self.client.post(reverse('account_confirm_login_code'), {'code': new})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_code_cannot_be_replayed_after_login(self):
        self.start_code()
        code = self.emailed_code()
        self.client.post(reverse('account_confirm_login_code'), {'code': code})
        self.client.post(reverse('account_logout'))
        self.client.post(reverse('account_confirm_login_code'), {'code': code})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_email_step_and_restart_are_csrf_protected(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('account_login'), {'login': self.company.email}).status_code, 403)
        self.assertEqual(client.post(reverse('account_restart_login')).status_code, 403)

    def test_selected_email_expires(self):
        self.start_code(self.external.email)
        session = self.client.session
        session['bouvane_login_identity']['at'] = time.time() - 601
        session.save()
        self.assertRedirects(self.client.get(reverse('account_password_login')), reverse('account_login'))

    @patch('website.management.commands.create_staff.getpass.getpass')
    def test_company_staff_provisioning_does_not_prompt_for_password(self, prompt):
        call_command('create_staff', 'new@bouvane.com', stdout=StringIO())
        user = get_user_model().objects.get(email='new@bouvane.com')
        self.assertFalse(user.has_usable_password())
        prompt.assert_not_called()

    def test_company_sensitive_reauthentication_uses_mfa_not_password(self):
        secret = generate_totp_secret()
        TOTP.activate(self.company, secret)
        self.client.force_login(self.company)
        response = self.client.get(reverse('account_reauthenticate'))
        self.assertRedirects(response, reverse('mfa_reauthenticate'), fetch_redirect_response=False)

    def test_external_redirect_target_is_rejected(self):
        self.client.post(reverse('account_login'), {'login': self.external.email, 'next': 'https://attacker.invalid/'})
        response = self.client.post(reverse('account_password_login'), {'password': 'External-test-password-42!', 'next': 'https://attacker.invalid/'})
        self.assertNotIn('attacker.invalid', response.url)
