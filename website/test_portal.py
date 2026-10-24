import hashlib
import json
import time
import uuid
from io import StringIO
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from allauth.account.models import EmailAddress
from allauth.account.utils import user_pk_to_url_str
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP, format_hotp_value, generate_totp_secret, hotp_value
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.webauthn.internal.auth import WebAuthn
from fido2.cose import ES256
from fido2.utils import websafe_decode, websafe_encode
from fido2.webauthn import Aaguid, AttestationObject, AttestedCredentialData, AuthenticatorData, CollectedClientData

from .auth import StaffMFAAdapter
from .models import BetaSignup, Enquiry, PortalAuditEvent


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
)
class PortalTests(TestCase):
    def setUp(self):
        cache.clear()
        self.password = 'Private-test-passphrase-42!'
        self.user = get_user_model().objects.create_user('staff@example.com', self.password, is_staff=True)
        self.address = EmailAddress.objects.create(user=self.user, email=self.user.email, verified=True, primary=True)
        self.record = Enquiry.objects.create(name='Alex', email='alex@example.com', service='AIWAF', message='<script>alert(1)</script> Please help with our application.')

    def enable_totp(self):
        self.secret = generate_totp_secret()
        return TOTP.activate(self.user, self.secret)

    def password_login(self):
        self.client.post(reverse('account_login'), {'login': self.user.email})
        return self.client.post(reverse('account_password_login'), {'password': self.password})

    def code(self):
        return format_hotp_value(hotp_value(self.secret, int(time.time()) // 30))

    def authenticated(self, client=None):
        client = client or self.client
        self.enable_totp()
        client.force_login(self.user)
        session = client.session
        session['account_authentication_methods'] = [{'method': 'mfa', 'type': 'totp', 'at': time.time()}]
        session.save()
        return client

    def test_all_owned_primary_keys_are_uuids(self):
        self.assertIsInstance(self.user.pk, uuid.UUID)
        self.assertIsInstance(self.record.pk, uuid.UUID)
        signup = BetaSignup.objects.create(email='beta@example.com')
        event = PortalAuditEvent.objects.create(actor=self.user, record_type='beta', record_id=signup.pk, action='invited')
        self.assertIsInstance(signup.pk, uuid.UUID)
        self.assertIsInstance(event.pk, uuid.UUID)

    def test_anonymous_cannot_view_or_modify_records(self):
        for url in [reverse('dashboard'), reverse('dashboard_enquiry', args=[self.record.pk])]:
            self.assertIn('/accounts/login/', self.client.get(url).url)
        self.client.post(reverse('dashboard_enquiry', args=[self.record.pk]), {'status': 'handled'})
        self.record.refresh_from_db()
        self.assertFalse(self.record.handled)

    def test_nonstaff_is_denied(self):
        self.user.is_staff = False
        self.user.save()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 403)

    def test_signup_is_closed(self):
        response = self.client.get(reverse('account_signup'))
        self.assertContains(response, 'Sign Up Closed')

    def test_login_page_has_passkey_form_and_branded_shell(self):
        response = self.client.get(reverse('account_login'))
        self.assertContains(response, 'Sign in with a passkey')
        self.assertContains(response, 'mfa/js/webauthn.js')
        self.assertContains(response, 'css/portal.css')
        self.assertNotContains(response, '>sign up<')
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_unverified_email_cannot_reach_dashboard_and_code_verifies(self):
        self.address.verified = False
        self.address.save()
        response = self.password_login()
        self.assertRedirects(response, reverse('account_email_verification_sent'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, ['support@bouvane.com'])
        code = self.client.session['account_email_verification_code']['code']
        self.assertIn(code, mail.outbox[0].body)
        self.client.post(reverse('account_email_verification_sent'), {'code': code})
        self.address.refresh_from_db()
        self.assertTrue(self.address.verified)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('dashboard_setup'))

    def test_password_only_user_must_enroll(self):
        self.password_login()
        response = self.client.get(reverse('dashboard'), follow=True)
        self.assertContains(response, 'Secure your account.')
        self.assertNotContains(response, self.record.email)

    def test_password_plus_totp_login(self):
        factor = self.enable_totp()
        self.assertNotEqual(factor.instance.data['secret'], self.secret)
        response = self.password_login()
        self.assertRedirects(response, reverse('mfa_authenticate'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.client.post(reverse('mfa_authenticate'), {'code': self.code()})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(reverse('dashboard')), self.record.email)

    def test_wrong_totp_and_password_cannot_enter(self):
        self.enable_totp()
        self.password_login()
        response = self.client.post(reverse('mfa_authenticate'), {'code': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertIn('/accounts/login/', self.client.get(reverse('dashboard')).url)

    def test_enrollment_or_legacy_session_does_not_count_as_mfa(self):
        self.enable_totp()
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('account_login'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_csrf_protects_status_updates(self):
        client = self.authenticated(Client(enforce_csrf_checks=True))
        response = client.post(reverse('dashboard_enquiry', args=[self.record.pk]), {'status': 'handled'})
        self.assertEqual(response.status_code, 403)

    def test_status_change_is_post_only_and_audited(self):
        self.authenticated()
        self.client.post(reverse('dashboard_enquiry', args=[self.record.pk]), {'status': 'handled'})
        self.record.refresh_from_db()
        self.assertTrue(self.record.handled)
        self.assertEqual(PortalAuditEvent.objects.get().actor_id, self.user.pk)
        signup = BetaSignup.objects.create(email='beta@example.com')
        url = reverse('dashboard_beta_status', args=[signup.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url, {'status': 'invited'})
        signup.refresh_from_db()
        self.assertTrue(signup.invited)
        self.assertEqual(PortalAuditEvent.objects.count(), 2)

    def test_enquiry_html_is_escaped_and_pages_are_private(self):
        self.authenticated()
        response = self.client.get(reverse('dashboard_enquiry', args=[self.record.pk]))
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_dashboard_search_and_beta_tab(self):
        self.authenticated()
        self.assertContains(self.client.get('/dashboard/?q=Alex'), self.record.email)
        self.assertNotContains(self.client.get('/dashboard/?q=not-a-match'), self.record.email)
        self.assertContains(self.client.get('/dashboard/?tab=beta'), 'No beta signups')

    def test_last_factor_cannot_be_removed(self):
        factor = self.enable_totp().instance
        self.assertFalse(StaffMFAAdapter().can_delete_authenticator(factor))

    def test_totp_qr_and_security_settings_render(self):
        self.password_login()
        response = self.client.get(reverse('mfa_activate_totp'))
        self.assertIn('reauthenticate', response.url)
        self.client.post(reverse('account_reauthenticate'), {'password': self.password})
        response = self.client.get(reverse('mfa_activate_totp'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data:image/svg+xml')
        self.assertContains(self.client.get(reverse('mfa_index')), 'Authenticator App')

    def make_passkey(self, passwordless=True):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = b'bouvane-test-passkey'
        binding = AttestedCredentialData.create(Aaguid.NONE, self.credential_id, ES256.from_cryptography_key(self.key.public_key()))
        data = AuthenticatorData.create(hashlib.sha256(b'testserver').digest(), AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.UV | AuthenticatorData.FLAG.AT, 0, binding)
        attestation = AttestationObject.create('none', data, {})
        client_data = CollectedClientData.create('webauthn.create', b'fixture-registration', 'https://testserver')
        WebAuthn.add(self.user, 'Test passkey', {
            'id': websafe_encode(self.credential_id), 'rawId': websafe_encode(self.credential_id), 'type': 'public-key',
            'response': {'clientDataJSON': websafe_encode(client_data), 'attestationObject': websafe_encode(attestation)},
            'clientExtensionResults': {'credProps': {'rk': passwordless}},
        })

    def passkey_assertion(self, verified=True, origin='https://testserver'):
        response = self.client.get(reverse('mfa_login_webauthn'), HTTP_X_REQUESTED_WITH='XMLHttpRequest', secure=True)
        self.assertEqual(response.status_code, 200)
        options = response.json()['request_options']['publicKey']
        client_data = CollectedClientData.create('webauthn.get', websafe_decode(options['challenge']), origin)
        flags = AuthenticatorData.FLAG.UP | (AuthenticatorData.FLAG.UV if verified else 0)
        data = AuthenticatorData.create(hashlib.sha256(b'testserver').digest(), flags, 1)
        signature = self.key.sign(data + client_data.hash, ec.ECDSA(hashes.SHA256()))
        return {
            'id': websafe_encode(self.credential_id), 'rawId': websafe_encode(self.credential_id), 'type': 'public-key',
            'response': {'authenticatorData': websafe_encode(data), 'clientDataJSON': websafe_encode(client_data),
                         'signature': websafe_encode(signature), 'userHandle': websafe_encode(user_pk_to_url_str(self.user).encode())},
        }

    def test_cryptographically_signed_passkey_login(self):
        self.make_passkey()
        credential = self.passkey_assertion()
        response = self.client.post(reverse('mfa_login_webauthn'), {'credential': json.dumps(credential)}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(reverse('dashboard')), self.record.email)

    def test_passkey_without_device_verification_is_rejected(self):
        self.make_passkey()
        credential = self.passkey_assertion(verified=False)
        self.client.post(reverse('mfa_login_webauthn'), {'credential': json.dumps(credential)}, secure=True)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_second_factor_key_cannot_be_used_for_passwordless_login(self):
        self.make_passkey(passwordless=False)
        credential = self.passkey_assertion()
        self.client.post(reverse('mfa_login_webauthn'), {'credential': json.dumps(credential)}, secure=True)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_passkey_from_wrong_origin_is_rejected(self):
        self.make_passkey()
        credential = self.passkey_assertion(origin='https://attacker.invalid')
        self.client.post(reverse('mfa_login_webauthn'), {'credential': json.dumps(credential)}, secure=True)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_passkey_assertion_cannot_be_replayed(self):
        self.make_passkey()
        credential = self.passkey_assertion()
        self.client.post(reverse('mfa_login_webauthn'), {'credential': json.dumps(credential)}, secure=True)
        self.client.post(reverse('account_logout'))
        self.client.post(reverse('mfa_login_webauthn'), {'credential': json.dumps(credential)}, secure=True)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_totp_code_cannot_be_replayed_in_another_login(self):
        self.enable_totp()
        self.password_login()
        code = self.code()
        self.client.post(reverse('mfa_authenticate'), {'code': code})
        other = Client()
        other.post(reverse('account_login'), {'login': self.user.email})
        other.post(reverse('account_password_login'), {'password': self.password})
        other.post(reverse('mfa_authenticate'), {'code': code})
        self.assertNotIn('_auth_user_id', other.session)

    def test_recovery_code_is_single_use(self):
        self.enable_totp()
        code = RecoveryCodes.activate(self.user).generate_codes()[0]
        self.password_login()
        self.client.post(reverse('mfa_authenticate'), {'code': code})
        self.assertContains(self.client.get(reverse('dashboard')), self.record.email)
        self.client.post(reverse('account_logout'))
        self.password_login()
        self.client.post(reverse('mfa_authenticate'), {'code': code})
        self.assertNotIn('_auth_user_id', self.client.session)

    @patch('website.management.commands.create_staff.getpass.getpass', side_effect=['New-private-test-password-42!', 'New-private-test-password-42!'])
    def test_staff_provisioning_requires_verification_and_mfa(self, prompt):
        call_command('create_staff', 'new-staff@example.com', stdout=StringIO())
        user = get_user_model().objects.get(email='new-staff@example.com')
        self.assertIsInstance(user.pk, uuid.UUID)
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        self.assertFalse(Authenticator.objects.filter(user=user).exists())

    def test_staff_provisioning_rejects_duplicate_email(self):
        with self.assertRaises(CommandError):
            call_command('create_staff', self.user.email, stdout=StringIO())
