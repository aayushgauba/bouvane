from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from allauth.account.decorators import verified_email_required
from allauth.mfa.models import Authenticator

from .auth import staff_portal_required
from .models import BetaSignup, Enquiry, PortalAuditEvent


@never_cache
@login_required
@verified_email_required
@require_GET
def setup(request):
    if not request.user.is_active or not request.user.is_staff:
        raise PermissionDenied
    if Authenticator.objects.filter(user=request.user, type__in=['totp', 'webauthn']).exists():
        return redirect('dashboard')
    return render(request, 'website/portal/setup.html')


@staff_portal_required
@require_GET
def dashboard(request):
    tab = 'beta' if request.GET.get('tab') == 'beta' else 'enquiries'
    query = request.GET.get('q', '').strip()[:200]
    status = request.GET.get('status', '')
    records = BetaSignup.objects.all() if tab == 'beta' else Enquiry.objects.all()
    if query:
        condition = Q(email__icontains=query)
        if tab == 'enquiries':
            condition |= Q(name__icontains=query) | Q(company__icontains=query) | Q(message__icontains=query)
        records = records.filter(condition)
    if status in ['open', 'done']:
        records = records.filter(**{('invited' if tab == 'beta' else 'handled'): status == 'done'})
    return render(request, 'website/portal/dashboard.html', {
        'tab': tab, 'query': query, 'status': status,
        'page_obj': Paginator(records, 20).get_page(request.GET.get('page')),
        'open_count': Enquiry.objects.filter(handled=False).count(),
        'waitlist_count': BetaSignup.objects.filter(invited=False).count(),
        'enquiry_count': Enquiry.objects.count(), 'beta_count': BetaSignup.objects.count(),
    })


@staff_portal_required
@require_http_methods(['GET', 'POST'])
def enquiry(request, pk):
    record = get_object_or_404(Enquiry, pk=pk)
    if request.method == 'POST':
        status = request.POST.get('status')
        if status not in ['open', 'handled']:
            return HttpResponseBadRequest('Invalid enquiry status.')
        with transaction.atomic():
            record.handled = status == 'handled'
            record.save(update_fields=['handled'])
            PortalAuditEvent.objects.create(actor=request.user, record_type='enquiry', record_id=record.pk, action=status)
        messages.success(request, 'Enquiry status updated.')
        return redirect('dashboard_enquiry', pk=record.pk)
    return render(request, 'website/portal/enquiry.html', {'record': record})


@staff_portal_required
@require_POST
def beta_status(request, pk):
    record = get_object_or_404(BetaSignup, pk=pk)
    status = request.POST.get('status')
    if status not in ['waiting', 'invited']:
        return HttpResponseBadRequest('Invalid beta status.')
    with transaction.atomic():
        record.invited = status == 'invited'
        record.save(update_fields=['invited'])
        PortalAuditEvent.objects.create(actor=request.user, record_type='beta', record_id=record.pk, action=status)
    messages.success(request, 'Waitlist status updated. No invitation email was sent.')
    return redirect('/dashboard/?tab=beta')
