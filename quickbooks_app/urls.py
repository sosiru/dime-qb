from django.urls import path
from . import views

app_name = "qb"

urlpatterns = [
    # OAuth
    path("connect/", views.connect, name="connect"),
    path("callback", views.callback, name="callback"),
    path("disconnect/", views.disconnect, name="disconnect"),

    # Dashboard
    path("", views.dashboard, name="dashboard"),

    # Sync
    path("sync/", views.sync_all, name="sync_all"),

    # REST API
    path("api/company/", views.api_company_info, name="api_company"),
    path("api/customers/", views.api_customers, name="api_customers"),
    path("api/customers/create/", views.api_create_customer, name="api_create_customer"),
    path("api/invoices/", views.api_invoices, name="api_invoices"),
    path("api/invoices/create/", views.api_create_invoice, name="api_create_invoice"),
    path("api/accounts/", views.api_accounts, name="api_accounts"),
    path("api/reports/pnl/", views.api_profit_and_loss, name="api_pnl"),
    path("api/sync/status/", views.api_sync_status, name="api_sync_status"),
]
