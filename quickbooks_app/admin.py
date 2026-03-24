from django.contrib import admin
from .models import QuickBooksToken, Customer, Invoice, Account


@admin.register(QuickBooksToken)
class QuickBooksTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "realm_id", "access_token_expires_at", "updated_at"]
    readonly_fields = ["access_token", "refresh_token"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["display_name", "email", "balance", "active", "synced_at"]
    search_fields = ["display_name", "email", "qb_id"]
    list_filter = ["active"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["doc_number", "customer_name", "total_amt", "balance", "txn_date", "synced_at"]
    search_fields = ["doc_number", "customer_name", "qb_id"]


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["name", "account_type", "current_balance", "active", "synced_at"]
    search_fields = ["name", "qb_id"]
    list_filter = ["account_type", "active"]

from django.contrib import admin
from .models import OAuthState


@admin.register(OAuthState)
class OAuthStateAdmin(admin.ModelAdmin):
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