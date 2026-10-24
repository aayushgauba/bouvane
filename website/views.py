import logging

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import BetaSignupForm, ContactForm
from .models import BetaSignup
from .emailing import send_enquiry_notification

logger = logging.getLogger(__name__)


@require_http_methods(['GET', 'POST'])
def home(request):
    is_beta = request.method == 'POST' and request.POST.get('form_type') == 'beta'
    form = ContactForm(request.POST if request.method == 'POST' and not is_beta else None)
    beta_form = BetaSignupForm(request.POST if is_beta else None)
    if is_beta and beta_form.is_valid():
        if not beta_form.cleaned_data.get('website'):
            BetaSignup.objects.get_or_create(email=beta_form.cleaned_data['email'].lower())
        messages.success(request, 'You’re on the list. We’ll email you when Bouvane Cloud beta access is available.', extra_tags='beta')
        return redirect('/#cloud')
    if request.method == 'POST' and not is_beta and form.is_valid():
        # Silently discard honeypot submissions without creating a record.
        if not form.cleaned_data.get('website'):
            enquiry = form.save()
            if settings.CONTACT_RECIPIENT:
                try:
                    send_enquiry_notification(enquiry)
                except Exception:
                    # A delivery failure must not lose a successfully saved enquiry.
                    logger.exception('Email notification failed for enquiry %s', enquiry.pk)
        messages.success(request, 'Thank you. Your enquiry has been received. We look forward to talking with you.', extra_tags='contact')
        return redirect('/#contact')
    return render(request, 'website/home.html', {'form': form, 'beta_form': beta_form})
