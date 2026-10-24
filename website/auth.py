import base64
import hashlib
import secrets
from functools import wraps

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django import forms
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.authentication import get_authentication_records
from allauth.account.models import EmailAddress
from allauth.mfa.adapter import DefaultMFAAdapter
from allauth.mfa.models import Authenticator
from allauth.mfa.webauthn.forms import AddWebAuthnForm, LoginWebAuthnForm
from allauth.mfa.webauthn.internal.auth import parse_authentication_response
from .emailing import brand_account_email


class StaffAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False

    def pre_login(self, request, user, **kwargs):
        if not user.is_active or not user.is_staff:
            raise PermissionDenied('This portal is for authorized Bouvane staff.')
        return super().pre_login(request, user, **kwargs)

    def render_mail(self, template_prefix, email, context, headers=None):
        context = {**context, 'support_email': settings.SUPPORT_EMAIL}
        mail = super().render_mail(template_prefix, email, context, headers=headers)
        return brand_account_email(mail, template_prefix, context)

    def generate_login_code(self):
        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(8))
            if any(character.isdigit() for character in code) and any(character.isalpha() for character in code):
                return code

    def post_login(self, request, user, **kwargs):
        from .login import is_company_email
        from allauth.account.internal.flows.login import record_authentication
        if is_company_email(user.email) and any(record.get('method') == 'code' for record in get_authentication_records(request)):
            # Freshly proved mailbox ownership permits initial MFA enrollment
            # without asking the passwordless account for a password.
            record_authentication(request, user, 'code', reauthenticated=True)
        return super().post_login(request, user, **kwargs)

    def get_reauthentication_methods(self, user):
        from .login import is_company_email
        methods = super().get_reauthentication_methods(user)
        if user.is_authenticated and is_company_email(user.email):
            methods = [method for method in methods if method['id'] != 'reauthenticate']
            if not methods:
                from django.urls import reverse
                methods = [{'id': 'company_code', 'description': 'Request a new email code', 'url': reverse('account_reauthenticate')}]
        return methods


class StaffAddWebAuthnForm(AddWebAuthnForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['passwordless'].initial = True
        self.fields['passwordless'].label = 'Use as a passkey for passwordless sign-in'


class VerifiedPasskeyLoginForm(LoginWebAuthnForm):
    def clean_credential(self):
        authenticator = super().clean_credential()
        assertion = parse_authentication_response(self.cleaned_data['credential'])
        if not authenticator.wrap().is_passwordless or not assertion.response.authenticator_data.is_user_verified():
            raise forms.ValidationError('Use a passkey with device PIN or biometric verification, or sign in with your password and second factor.')
        return authenticator


class StaffMFAAdapter(DefaultMFAAdapter):
    def _cipher(self):
        key = settings.MFA_ENCRYPTION_KEY
        if not key:
            # Domain-separated derivation for installations without a dedicated key.
            key = base64.urlsafe_b64encode(hashlib.sha256(
                b'bouvane-mfa-v1:' + settings.SECRET_KEY.encode()
            ).digest())
        return Fernet(key)

    def encrypt(self, text):
        return self._cipher().encrypt(text.encode()).decode()

    def decrypt(self, encrypted_text):
        return self._cipher().decrypt(encrypted_text.encode()).decode()

    def can_delete_authenticator(self, authenticator):
        if not authenticator.user.is_staff:
            return super().can_delete_authenticator(authenticator)
        # Require another real factor before removing the last device.
        return Authenticator.objects.filter(
            user=authenticator.user, type__in=['totp', 'webauthn'],
        ).exclude(pk=authenticator.pk).exists()


def staff_portal_required(view):
    @never_cache
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_active or not request.user.is_staff:
            raise PermissionDenied('This portal is for authorized Bouvane staff.')
        # Do not accept a different account's verified secondary address.
        if not EmailAddress.objects.filter(
            user=request.user, email__iexact=request.user.email, verified=True,
        ).exists():
            messages.info(request, 'Verify your sign-in email address before opening the dashboard.')
            return redirect('account_email')
        factors = Authenticator.objects.filter(user=request.user, type__in=['totp', 'webauthn'])
        if not factors.exists():
            return redirect('dashboard_setup')
        # An enrolled device alone is insufficient: the current session must
        # have actually used MFA. Enrollment requires a fresh MFA login.
        if not any(record.get('method') == 'mfa' for record in get_authentication_records(request)):
            logout(request)
            messages.info(request, 'Your security method is ready. Sign in again using your passkey or password and two-factor code.')
            return redirect('account_login')
        return view(request, *args, **kwargs)
    return wrapped
