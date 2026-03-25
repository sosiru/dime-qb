# qb_admin_mixin.py

from django.contrib import messages
from django.conf import settings

from quickbooks_app.scripts.quickb import QuickBooksClient


class QuickBooksAdminMixin:
    """
    Adds QuickBooks actions to Django Unfold admin.
    """

    def get_qb_client(self):
        client = QuickBooksClient(base_url=getattr(settings, "QUICKBOOKS_BASE_URL"))
        client.login(
            getattr(settings, "QUICKBOOKS_USERNAME"),
            getattr(settings, "QUICKBOOKS_PASSWORD"),
        )
        return client

    def push_to_quickbooks(self, request, queryset):
        qb = self.get_qb_client()

        success = 0
        errors = []

        for obj in queryset:
            try:
                # Example mapping — customize per model
                customer = qb.create_customer(
                    display_name=getattr(obj, "name", str(obj)),
                    email=getattr(obj, "email", ""),
                    phone=getattr(obj, "phone", ""),
                )
                success += 1
            except Exception as e:
                errors.append(str(e))

        if success:
            self.message_user(request, f"✅ {success} pushed to QuickBooks", messages.SUCCESS)

        for err in errors:
            self.message_user(request, f"❌ {err}", messages.ERROR)
    push_to_quickbooks.short_description = "Push selected to QuickBooks"


    def sync_customers(self, request, queryset=None):
        qb = self.get_qb_client()
        customers = qb.list_customers()

        self.message_user(
            request,
            f"✅ Synced {len(customers)} customers from QuickBooks",
            messages.SUCCESS
        )
    sync_customers.short_description = "Sync Customers from QuickBooks"


    def sync_invoices(self, request, queryset=None):
        qb = self.get_qb_client()
        invoices = qb.list_invoices()

        self.message_user(
            request,
            f"✅ Synced {len(invoices)} invoices from QuickBooks",
            messages.SUCCESS
        )
    sync_invoices.short_description = "Sync Invoices from QuickBooks"


    def connect_quickbooks(self, request, queryset=None):
        qb = self.get_qb_client()
        url = qb.connect_oauth()
        self.message_user(
            request,
            f"🔗 Visit this URL to connect QuickBooks: {url}",
            messages.INFO
        )
    connect_quickbooks.short_description = "Connect QuickBooks"