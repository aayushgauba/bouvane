from django.contrib import admin

from .models import BetaSignup, Enquiry


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'company', 'service', 'created_at', 'handled']
    list_filter = ['handled', 'service', 'created_at']
    search_fields = ['name', 'email', 'company', 'message']
    readonly_fields = ['created_at']
    list_editable = ['handled']


@admin.register(BetaSignup)
class BetaSignupAdmin(admin.ModelAdmin):
    list_display = ['email', 'created_at', 'consent', 'invited']
    list_filter = ['invited', 'created_at']
    search_fields = ['email']
    readonly_fields = ['created_at', 'consent']
    list_editable = ['invited']
