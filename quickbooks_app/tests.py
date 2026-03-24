"""
Tests for QuickBooks Integration.
Run with: python manage.py test quickbooks_app
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import Account, Customer, Invoice, QuickBooksToken
from . import services


class QuickBooksTokenModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("testuser", "test@test.com", "password")

    def test_create_token(self):
        token = QuickBooksToken.objects.create(
            user=self.user,
            realm_id="123456789",
            access_token="access_abc",
            refresh_token="refresh_xyz",
        )
        self.assertEqual(str(token), "testuser — Realm 123456789")
        self.assertEqual(token.realm_id, "123456789")

    def test_token_is_one_to_one_with_user(self):
        QuickBooksToken.objects.create(
            user=self.user, realm_id="111", access_token="a", refresh_token="r"
        )
        with self.assertRaises(Exception):
            QuickBooksToken.objects.create(
                user=self.user, realm_id="222", access_token="b", refresh_token="s"
            )


class CustomerModelTest(TestCase):
    def test_create_customer(self):
        c = Customer.objects.create(qb_id="C001", display_name="Acme Corp", email="acme@test.com")
        self.assertEqual(str(c), "Acme Corp (QB: C001)")

    def test_customer_defaults(self):
        c = Customer.objects.create(qb_id="C002", display_name="Test Co")
        self.assertEqual(c.balance, 0)
        self.assertTrue(c.active)


class InvoiceModelTest(TestCase):
    def test_create_invoice(self):
        customer = Customer.objects.create(qb_id="C001", display_name="Acme")
        inv = Invoice.objects.create(
            qb_id="INV001",
            doc_number="1001",
            customer=customer,
            customer_name="Acme",
            total_amt=1000.00,
            balance=1000.00,
        )
        self.assertEqual(str(inv), "Invoice #1001 — Acme")
        self.assertEqual(inv.total_amt, 1000.00)


class OAuthViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("testuser", "t@t.com", "password")

    def test_connect_redirects_unauthenticated(self):
        response = self.client.get(reverse("qb:connect"))
        self.assertRedirects(response, f"/accounts/login/?next=/qb/connect/", fetch_redirect_response=False)

    @patch("quickbooks_app.services.get_authorization_url")
    def test_connect_redirects_to_intuit(self, mock_auth_url):
        mock_auth_url.return_value = ("https://appcenter.intuit.com/oauth2?...", "state123")
        self.client.login(username="testuser", password="password")
        response = self.client.get(reverse("qb:connect"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("appcenter.intuit.com", response["Location"])

    @patch("quickbooks_app.services.exchange_code_for_tokens")
    def test_callback_success(self, mock_exchange):
        mock_exchange.return_value = MagicMock()
        self.client.login(username="testuser", password="password")
        response = self.client.get(
            reverse("qb:callback"), {"code": "authcode123", "realmId": "987654321", "state": "abc"}
        )
        self.assertRedirects(response, reverse("qb:dashboard"), fetch_redirect_response=False)
        mock_exchange.assert_called_once()

    def test_callback_missing_params(self):
        self.client.login(username="testuser", password="password")
        response = self.client.get(reverse("qb:callback"))
        # Should redirect back to dashboard with error
        self.assertRedirects(response, reverse("qb:dashboard"), fetch_redirect_response=False)

    def test_disconnect_removes_token(self):
        self.client.login(username="testuser", password="password")
        QuickBooksToken.objects.create(
            user=self.user, realm_id="111", access_token="a", refresh_token="r"
        )
        self.assertEqual(QuickBooksToken.objects.filter(user=self.user).count(), 1)
        self.client.get(reverse("qb:disconnect"))
        self.assertEqual(QuickBooksToken.objects.filter(user=self.user).count(), 0)


class DashboardViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("testuser", "t@t.com", "password")

    def test_dashboard_unauthenticated(self):
        response = self.client.get(reverse("qb:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_not_connected(self):
        self.client.login(username="testuser", password="password")
        response = self.client.get(reverse("qb:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_connected"])

    def test_dashboard_connected(self):
        self.client.login(username="testuser", password="password")
        QuickBooksToken.objects.create(
            user=self.user, realm_id="111", access_token="a", refresh_token="r"
        )
        response = self.client.get(reverse("qb:dashboard"))
        self.assertTrue(response.context["is_connected"])

    def test_dashboard_shows_correct_counts(self):
        self.client.login(username="testuser", password="password")
        Customer.objects.create(qb_id="C1", display_name="A")
        Customer.objects.create(qb_id="C2", display_name="B")
        response = self.client.get(reverse("qb:dashboard"))
        self.assertEqual(response.context["customer_count"], 2)


class APIEndpointsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("testuser", "t@t.com", "password")
        QuickBooksToken.objects.create(
            user=self.user,
            realm_id="123",
            access_token="tok",
            refresh_token="ref",
            access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        self.client.login(username="testuser", password="password")

    @patch("quickbooks_app.services.get_company_info")
    def test_api_company_info(self, mock_fn):
        mock_fn.return_value = {"CompanyInfo": {"CompanyName": "Test Inc"}}
        response = self.client.get(reverse("qb:api_company"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("CompanyInfo", data)

    @patch("quickbooks_app.services.get_customers")
    def test_api_list_customers(self, mock_fn):
        mock_fn.return_value = [
            {"Id": "1", "DisplayName": "Alice"},
            {"Id": "2", "DisplayName": "Bob"},
        ]
        response = self.client.get(reverse("qb:api_customers"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)

    @patch("quickbooks_app.services.create_customer")
    def test_api_create_customer(self, mock_fn):
        mock_fn.return_value = {"Customer": {"Id": "99", "DisplayName": "New Co"}}
        response = self.client.post(
            reverse("qb:api_create_customer"),
            data=json.dumps({"display_name": "New Co", "email": "new@co.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_api_create_customer_missing_name(self):
        response = self.client.post(
            reverse("qb:api_create_customer"),
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    @patch("quickbooks_app.services.get_invoices")
    def test_api_list_invoices(self, mock_fn):
        mock_fn.return_value = [{"Id": "1", "TotalAmt": 500}]
        response = self.client.get(reverse("qb:api_invoices"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    @patch("quickbooks_app.services.create_invoice")
    def test_api_create_invoice(self, mock_fn):
        mock_fn.return_value = {"Invoice": {"Id": "42", "TotalAmt": 300}}
        payload = {
            "customer_ref_id": "1",
            "line_items": [{"description": "Dev work", "amount": 300, "quantity": 1, "unit_price": 300}],
        }
        response = self.client.post(
            reverse("qb:api_create_invoice"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_api_create_invoice_missing_customer(self):
        payload = {"line_items": [{"amount": 100}]}
        response = self.client.post(
            reverse("qb:api_create_invoice"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("quickbooks_app.services.get_accounts")
    def test_api_accounts(self, mock_fn):
        mock_fn.return_value = [{"Id": "1", "Name": "Cash"}]
        response = self.client.get(reverse("qb:api_accounts"))
        self.assertEqual(response.status_code, 200)

    @patch("quickbooks_app.services.get_profit_and_loss")
    def test_api_pnl(self, mock_fn):
        mock_fn.return_value = {"Header": {"ReportName": "ProfitAndLoss"}}
        response = self.client.get(
            reverse("qb:api_pnl"), {"start_date": "2024-01-01", "end_date": "2024-12-31"}
        )
        self.assertEqual(response.status_code, 200)

    def test_api_sync_status(self):
        Customer.objects.create(qb_id="C1", display_name="A")
        response = self.client.get(reverse("qb:api_sync_status"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["customers"], 1)


class SyncServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("syncuser", "s@s.com", "password")
        QuickBooksToken.objects.create(
            user=self.user,
            realm_id="123",
            access_token="tok",
            refresh_token="ref",
            access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    @patch("quickbooks_app.services.get_customers")
    def test_sync_customers(self, mock_get):
        mock_get.return_value = [
            {"Id": "1", "DisplayName": "Alice", "Balance": 100, "Active": True},
            {"Id": "2", "DisplayName": "Bob", "Balance": 200, "Active": False},
        ]
        count = services.sync_customers(self.user)
        self.assertEqual(count, 2)
        self.assertEqual(Customer.objects.count(), 2)
        alice = Customer.objects.get(qb_id="1")
        self.assertEqual(alice.display_name, "Alice")

    @patch("quickbooks_app.services.get_customers")
    def test_sync_customers_upsert(self, mock_get):
        Customer.objects.create(qb_id="1", display_name="Old Name")
        mock_get.return_value = [
            {"Id": "1", "DisplayName": "New Name", "Balance": 50, "Active": True}
        ]
        services.sync_customers(self.user)
        self.assertEqual(Customer.objects.get(qb_id="1").display_name, "New Name")
        self.assertEqual(Customer.objects.count(), 1)

    @patch("quickbooks_app.services.get_accounts")
    def test_sync_accounts(self, mock_get):
        mock_get.return_value = [
            {"Id": "A1", "Name": "Cash", "AccountType": "Bank", "AccountSubType": "", "CurrentBalance": 5000, "Active": True}
        ]
        count = services.sync_accounts(self.user)
        self.assertEqual(count, 1)
        self.assertEqual(Account.objects.first().name, "Cash")
