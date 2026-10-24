"""
URL configuration for bouvane project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from website.views import home
from website import portal

urlpatterns = [
    path('', home, name='home'),
    path('accounts/', include('allauth.urls')),
    path('dashboard/', portal.dashboard, name='dashboard'),
    path('dashboard/setup/', portal.setup, name='dashboard_setup'),
    path('dashboard/enquiries/<uuid:pk>/', portal.enquiry, name='dashboard_enquiry'),
    path('dashboard/beta/<uuid:pk>/status/', portal.beta_status, name='dashboard_beta_status'),
    re_path(r'^admin(?:/.*)?$', RedirectView.as_view(pattern_name='dashboard', permanent=False)),
]
