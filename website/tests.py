from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import BetaSignup, Enquiry


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
    CONTACT_RECIPIENT='',
)
class WebsiteTests(TestCase):
    def setUp(self):
        self.contact = {'name': 'Alex Morgan', 'email': 'alex@example.com', 'company': 'Example',
                        'service': 'AIWAF', 'message': 'I would like to learn about application-aware security.'}

    def test_home_has_products_and_csrf(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Bouvane Cloud')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, 'https://github.com/aiwaf-project/aiwaf')

    def test_contact_persists_and_redirects_to_confirmation(self):
        response = self.client.post(reverse('home'), self.contact, follow=True)
        self.assertRedirects(response, '/#contact')
        self.assertContains(response, 'Your enquiry has been received')
        self.assertEqual(Enquiry.objects.get().email, 'alex@example.com')

    def test_invalid_contact_keeps_values_and_does_not_save(self):
        response = self.client.post(reverse('home'), {**self.contact, 'email': 'bad', 'message': 'short'})
        self.assertContains(response, 'Enter a valid email address')
        self.assertContains(response, 'at least 20 characters')
        self.assertContains(response, 'Alex Morgan')
        self.assertFalse(Enquiry.objects.exists())

    def test_honeypot_discards_bot(self):
        self.client.post(reverse('home'), {**self.contact, 'website': 'spam'})
        self.assertFalse(Enquiry.objects.exists())

    def test_beta_requires_consent_and_deduplicates(self):
        data = {'form_type': 'beta', 'email': 'BETA@example.com'}
        self.client.post(reverse('home'), data)
        self.assertFalse(BetaSignup.objects.exists())
        data['consent'] = 'on'
        response = self.client.post(reverse('home'), data, follow=True)
        self.assertContains(response, 'You’re on the list')
        self.client.post(reverse('home'), data)
        self.assertEqual(BetaSignup.objects.count(), 1)
        self.assertEqual(BetaSignup.objects.get().email, 'beta@example.com')

    def test_beta_honeypot_discards_bot(self):
        self.client.post(reverse('home'), {'form_type': 'beta', 'email': 'bot@example.com', 'consent': 'on', 'website': 'spam'})
        self.assertFalse(BetaSignup.objects.exists())

    def test_contact_enquiries_cannot_break_beta_signup(self):
        data = {**self.contact, 'service': 'Cloud beta access'}
        self.client.post(reverse('home'), data)
        self.client.post(reverse('home'), data)
        response = self.client.post(reverse('home'), {'form_type': 'beta', 'email': data['email'], 'consent': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Enquiry.objects.count(), 2)
        self.assertEqual(BetaSignup.objects.count(), 1)

    def test_csrf_is_enforced(self):
        response = Client(enforce_csrf_checks=True).post(reverse('home'), self.contact)
        self.assertEqual(response.status_code, 403)

    @override_settings(CONTACT_RECIPIENT='team@example.com')
    @patch('website.views.send_enquiry_notification', side_effect=RuntimeError('Mail unavailable'))
    def test_email_failure_preserves_enquiry(self, mail):
        with self.assertLogs('website.views', level='ERROR'):
            response = self.client.post(reverse('home'), self.contact)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Enquiry.objects.count(), 1)

    def test_admin_requires_login(self):
        response = self.client.get('/admin/website/enquiry/')
        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        response = self.client.get('/dashboard/')
        self.assertIn('/accounts/login/', response.url)
