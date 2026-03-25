import requests
from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import path

from .backend.qb_admin_mixin import QuickBooksAdminMixin
from .forms import QuickBooksCustomerForm
from .models import QuickBooksToken, Customer, Invoice, Account, OAuthState
from unfold.admin import ModelAdmin
from django.contrib import admin, messages


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
class CustomerAdmin(ModelAdmin):
    list_display = ["display_name", "email", "balance", "active", "synced_at"]

    change_list_template = "admin/customer_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "create-qb-customer/",
                self.admin_site.admin_view(self.create_qb_customer),
                name="create_qb_customer",
            ),
        ]
        return custom_urls + urls

    def create_qb_customer(self, request):
        if request.method == "POST":
            form = QuickBooksCustomerForm(request.POST)

            if form.is_valid():
                payload = form.cleaned_data

                try:
                    response = requests.post(
                        f"{settings.QUICKBOOKS_BASE_URL}/qb/api/customers/create/",
                        json=payload,
                        timeout=15,
                    )

                    if response.status_code == 201:
                        messages.success(request, "✅ Customer created in QuickBooks")
                        return redirect("../")
                    else:
                        messages.error(request, f"❌ Error: {response.text}")

                except Exception as e:
                    messages.error(request, f"❌ {str(e)}")

        else:
            form = QuickBooksCustomerForm()

        return render(
            request,
            "admin/create_qb_customer.html",
            {"form": form}
        )

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