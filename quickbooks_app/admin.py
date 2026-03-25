from .backend.qb_admin_mixin import QuickBooksAdminMixin
from .models import QuickBooksToken, Customer, Invoice, Account, OAuthState
from unfold.admin import ModelAdmin
from django.contrib import admin


@admin.register(QuickBooksToken)
class QuickBooksTokenAdmin(ModelAdmin):
    change_list_template = "unfold/admin/change_list.html"
    list_display = ["user", "realm_id", "access_token_expires_at", "updated_at"]
    readonly_fields = ["access_token", "refresh_token"]
    search_fields = ["realm_id", "user__username"]
    ordering = ["-updated_at"]

    def has_add_permission(self, request):
        return False

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["qb_connect_url"] = "https://integrations.dimeapp.co.ke/qb/connect/"
        return super().changelist_view(request, extra_context=extra_context)



@admin.register(Customer)
class CustomerAdmin(QuickBooksAdminMixin, ModelAdmin):
    list_display = ["display_name", "email", "balance", "active", "synced_at"]
    search_fields = ["display_name", "email", "qb_id"]
    list_filter = ["active"]
    ordering = ["-synced_at"]

    actions = [
        "push_to_quickbooks",
        "sync_customers",
        "connect_quickbooks",
    ]


@admin.register(Invoice)
class InvoiceAdmin(QuickBooksAdminMixin, ModelAdmin):
    list_display = ["doc_number", "customer_name", "total_amt", "balance", "txn_date", "synced_at"]
    search_fields = ["doc_number", "customer_name", "qb_id"]
    ordering = ["-txn_date"]

    actions = [
        "push_to_quickbooks",
        "sync_invoices",
    ]


@admin.register(Account)
class AccountAdmin(QuickBooksAdminMixin, ModelAdmin):
    list_display = ["name", "account_type", "current_balance", "active", "synced_at"]
    search_fields = ["name", "qb_id"]
    list_filter = ["account_type", "active"]
    ordering = ["-synced_at"]

    actions = [
        "sync_customers",
    ]


@admin.register(OAuthState)
class OAuthStateAdmin(ModelAdmin):
    list_display = ("id", "state", "user", "used", "created_at")
    list_filter = ("used", "created_at")
    search_fields = ("state", "user__username", "user__email")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    fieldsets = (
        (None, {
            "fields": ("state", "user", "used")
        }),
        ("Metadata", {
            "fields": ("created_at",)
        }),
    )