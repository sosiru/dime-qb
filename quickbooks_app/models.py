from django.conf import settings
from django.db import models
from django.contrib.auth.models import User


class QuickBooksToken(models.Model):
    """Stores OAuth2 tokens per user/realm (company)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="qb_token")
    realm_id = models.CharField(max_length=255)  # QuickBooks company ID
    access_token = models.TextField()
    refresh_token = models.TextField()
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    refresh_token_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} — Realm {self.realm_id}"


from django.db import models
from decimal import Decimal
from django.utils import timezone


class Customer(models.Model):
    qb_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True, null=True)

    account_name = models.CharField(max_length=255, null=True, blank=True)
    account_type = models.CharField(max_length=100, null=True, blank=True)
    account_sub_type = models.CharField(max_length=100, null=True, blank=True)

    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    active = models.BooleanField(default=True)
    synced_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.display_name} (QB: {self.qb_id})"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new and not self.qb_id:
            from . import services
            try:
                data = services.create_customer(
                    user=None,
                    display_name=self.display_name,
                    email=self.email,
                    phone=self.phone,
                )
                qb_customer = data.get("Customer")
                if qb_customer:
                    self.qb_id = qb_customer.get("Id")
                    self.display_name = qb_customer.get("DisplayName")
                    self.email = qb_customer.get("PrimaryEmailAddr", {}).get("Address", "")
                    self.phone = qb_customer.get("PrimaryPhone", {}).get("FreeFormNumber", "")
                    self.balance = Decimal(qb_customer.get("Balance", 0))
                    self.active = qb_customer.get("Active", True)
                    if self.account_name and self.account_type:
                        account_response = services.create_account(
                            user=None,
                            name=self.account_name,
                            account_type=self.account_type,
                            account_sub_type=self.account_sub_type,
                        )
                        qb_account = account_response.get("Account")
                        if qb_account:
                            from .models import Account
                            Account.objects.update_or_create(
                                qb_id=qb_account.get("Id"),
                                defaults={
                                    "name": qb_account.get("Name"),
                                    "account_type": qb_account.get("AccountType", ""),
                                    "account_sub_type": qb_account.get("AccountSubType", ""),
                                    "current_balance": Decimal(qb_account.get("CurrentBalance", 0)),
                                    "active": qb_account.get("Active", True),
                                },
                            )
            except Exception as e:
                print("QuickBooks sync failed:", str(e))
        super().save(*args, **kwargs)


class Invoice(models.Model):
    """Cached QuickBooks invoices."""

    STATUS_CHOICES = [
        ("Draft", "Draft"),
        ("Pending", "Pending"),
        ("Overdue", "Overdue"),
        ("Paid", "Paid"),
        ("Voided", "Voided"),
    ]

    qb_id = models.CharField(max_length=100, unique=True)
    doc_number = models.CharField(max_length=100, blank=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices"
    )
    customer_name = models.CharField(max_length=255, blank=True)
    txn_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    total_amt = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Draft")
    synced_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Invoice #{self.doc_number} — {self.customer_name}"


class Account(models.Model):
    """Cached QuickBooks Chart of Accounts."""

    qb_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=100, blank=True)
    account_sub_type = models.CharField(max_length=100, blank=True)
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    active = models.BooleanField(default=True)
    synced_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.account_type})"

class OAuthState(models.Model):
    state = models.CharField(max_length=255, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user} - {self.state}"