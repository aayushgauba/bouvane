import time
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from allauth.account.forms import LoginForm, RequestLoginCodeForm
from allauth.account.internal.flows.login_by_code import LoginCodeVerificationProcess
from allauth.account.internal.stagekit import clear_login
from allauth.account.models import EmailAddress
from allauth.account.utils import get_next_redirect_url
from allauth.account.views import LoginView, ReauthenticateView, RequestLoginCodeView
from allauth.mfa.models import Authenticator

LOGIN_IDENTITY = 'bouvane_login_identity'


def is_company_email(email):
    return email.strip().rpartition('@')[2].lower() == settings.COMPANY_LOGIN_DOMAIN


class EmailStepForm(forms.Form):
    login = forms.EmailField(label='Email address', widget=forms.EmailInput(attrs={
        'autocomplete': 'username', 'autofocus': True, 'placeholder': 'you@company.com',
    }))

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)


class CompanyLoginCodeForm(RequestLoginCodeForm):
    def clean_email(self):
        email = super().clean_email().strip().lower()
        if not is_company_email(email):
            raise forms.ValidationError('Use the email sign-in screen for this address.')
        if self._user and (not self._user.is_staff or self._user.email.lower() != email):
            self._user = None
        if self._user:
            EmailAddress.objects.get_or_create(
                user=self._user, email=email,
                defaults={'primary': not EmailAddress.objects.filter(user=self._user, primary=True).exists(), 'verified': False},
            )
        return email


class PasswordStepForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['login'].widget = forms.HiddenInput()
        self.fields['password'].widget.attrs['autofocus'] = True

    def clean_login(self):
        email = super().clean_login()
        if is_company_email(email):
            raise forms.ValidationError('Use the emailed sign-in code for this address.')
        return email


class EmailFirstLoginView(LoginView):
    def get_form_class(self):
        return EmailStepForm

    def form_valid(self, form):
        email = form.cleaned_data['login'].strip().lower()
        clear_login(self.request)
        self.request.session[LOGIN_IDENTITY] = {'email': email, 'at': time.time()}
        if is_company_email(email):
            code_form = CompanyLoginCodeForm({'email': email})
            if not code_form.is_valid():
                for errors in code_form.errors.values():
                    for error in errors:
                        form.add_error('login', error)
                return self.form_invalid(form)
            LoginCodeVerificationProcess.initiate(request=self.request, user=code_form._user, email=email)
            return redirect(self.passthrough_next_url(reverse('account_confirm_login_code')))
        return redirect(self.passthrough_next_url(reverse('account_password_login')))


class PasswordLoginView(LoginView):
    template_name = 'account/login_password.html'

    def dispatch(self, request, *args, **kwargs):
        identity = request.session.get(LOGIN_IDENTITY, {})
        if not request.user.is_authenticated and (
            not identity.get('email') or time.time() - identity.get('at', 0) > 600
            or is_company_email(identity['email'])
        ):
            return redirect('account_login')
        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        return PasswordStepForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        email = self.request.session[LOGIN_IDENTITY]['email']
        kwargs.setdefault('initial', {})['login'] = email
        if self.request.method == 'POST':
            kwargs['data'] = kwargs['data'].copy()
            # Bind the password to the identity chosen on the previous screen.
            kwargs['data']['login'] = email
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['selected_email'] = self.request.session[LOGIN_IDENTITY]['email']
        return context


class CompanyRequestCodeView(RequestLoginCodeView):
    def get(self, request, *args, **kwargs):
        return redirect('account_login')

    def get_form_class(self):
        return CompanyLoginCodeForm

    def form_valid(self, form):
        self.request.session[LOGIN_IDENTITY] = {'email': form.cleaned_data['email'], 'at': time.time()}
        return super().form_valid(form)


class AccountReauthenticateView(ReauthenticateView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and is_company_email(request.user.email):
            types = set(Authenticator.objects.filter(user=request.user).values_list('type', flat=True))
            if types & {'totp', 'webauthn'}:
                url = reverse('mfa_reauthenticate' if 'totp' in types else 'mfa_reauthenticate_webauthn')
                next_url = get_next_redirect_url(request)
                return redirect(url + ('?' + urlencode({'next': next_url}) if next_url else ''))
            logout(request)
            messages.info(request, 'Please sign in again to continue securely.')
            return redirect('account_login')
        return super().dispatch(request, *args, **kwargs)


@never_cache
@require_POST
def restart_login(request):
    if not request.user.is_authenticated:
        clear_login(request)
        request.session.pop(LOGIN_IDENTITY, None)
    return redirect('account_login')
