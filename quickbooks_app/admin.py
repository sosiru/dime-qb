from .backend.qb_admin_mixin import QuickBooksAdminMixin
from .models import QuickBooksToken, Customer, Invoice, Account, OAuthState
from unfold.admin import ModelAdmin
from django.contrib import admin

@admin.register(QuickBooksToken)
class QuickBooksTokenAdmin(ModelAdmin):
    list_display = ["user", "realm_id", "access_token_expires_at", "updated_at"]
    readonly_fields = ["access_token", "refresh_token"]
    search_fields = ["realm_id", "user__username"]
    ordering = ["-updated_at"]

    change_list_template = "admin/quickbooks_connect.html"

    def has_add_permission(self, request):
        return False  # removes "Add" button

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        try:
            from . import services
            auth_url, state_token = services.get_authorization_url()
            print(auth_url)
            OAuthState.objects.create(
                state=state_token,
                user=request.user
            )
        except Exception as e:
            auth_url = None
            self.message_user(request, f"Error connecting: {str(e)}", level="error")

        extra_context["qb_auth_url"] = auth_url

        return super().changelist_view(request, extra_context=extra_context)

@admin.register(Customer)
class CustomerAdmin(QuickBooksAdminMixin, ModelAdmin):
    list_display = ["display_name", "email", "balance", "active", "synced_at"]
    search_fields = ["display_name", "email", "qb_id"]
    list_filter = ["active"]
    ordering = ["-synced_at"]

    def save_model(self, request, obj, form, change):
        obj.save(user=request.user)


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