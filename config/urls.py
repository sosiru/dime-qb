from django.contrib import admin
from django.urls import path, include
from quickbooks_app import views as qb_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("qb/", include("quickbooks_app.urls")),
    path("auth/login/", qb_views.api_login, name="api_login"),
    path("auth/logout/", qb_views.api_logout, name="api_logout"),
]
