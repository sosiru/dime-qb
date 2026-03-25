"""
QuickBooks Django Integration Client
=====================================
A Python interface for the QuickBooks Django Integration API.
Designed to be dropped into any Django project that uses django-unfold.

Usage (standalone):
    from quickbooks_client import QuickBooksClient

    qb = QuickBooksClient(base_url="http://localhost:8000")
    qb.login("admin", "your_password")

    customers = qb.list_customers()
    invoice   = qb.create_invoice(
        customer_ref_id=customers[0].id,
        due_date="2025-12-31",
        line_items=[
            LineItem(description="Consulting", amount=50000, quantity=1, unit_price=50000),
        ],
    )

Usage (Django Unfold admin actions):
    from quickbooks_client import QuickBooksAdminMixin
    from unfold.admin import ModelAdmin

    @admin.register(Order)
    class OrderAdmin(QuickBooksAdminMixin, ModelAdmin):
        actions = ["push_to_quickbooks"]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class Customer:
    id: str
    display_name: str
    email: str = ""
    phone: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Customer":
        return cls(
            id=str(data.get("Id", "")),
            display_name=data.get("DisplayName", data.get("display_name", "")),
            email=data.get("PrimaryEmailAddr", {}).get("Address", "") if isinstance(data.get("PrimaryEmailAddr"), dict) else data.get("email", ""),
            phone=data.get("PrimaryPhone", {}).get("FreeFormNumber", "") if isinstance(data.get("PrimaryPhone"), dict) else data.get("phone", ""),
            raw=data,
        )


@dataclass
class LineItem:
    description: str
    amount: float
    quantity: int = 1
    unit_price: float = 0.0

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "amount": self.amount,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
        }


@dataclass
class Invoice:
    id: str
    customer_ref_id: str
    due_date: str
    total: float = 0.0
    status: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Invoice":
        return cls(
            id=str(data.get("Id", "")),
            customer_ref_id=str(data.get("CustomerRef", {}).get("value", "")),
            due_date=data.get("DueDate", ""),
            total=float(data.get("TotalAmt", 0)),
            status=data.get("EmailStatus", ""),
            raw=data,
        )


@dataclass
class Account:
    id: str
    name: str
    account_type: str = ""
    balance: float = 0.0
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        return cls(
            id=str(data.get("Id", "")),
            name=data.get("Name", ""),
            account_type=data.get("AccountType", ""),
            balance=float(data.get("CurrentBalance", 0)),
            raw=data,
        )


@dataclass
class CompanyInfo:
    id: str
    name: str
    country: str = ""
    fiscal_year_start: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "CompanyInfo":
        info = data.get("QueryResponse", {}).get("CompanyInfo", [{}])[0]
        return cls(
            id=str(info.get("Id", "")),
            name=info.get("CompanyName", ""),
            country=info.get("Country", ""),
            fiscal_year_start=info.get("FiscalYearStartMonth", ""),
            raw=data,
        )


@dataclass
class SyncStatus:
    customers: int = 0
    invoices: int = 0
    accounts: int = 0
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "SyncStatus":
        return cls(
            customers=data.get("customers", 0),
            invoices=data.get("invoices", 0),
            accounts=data.get("accounts", 0),
            raw=data,
        )


class QuickBooksError(Exception):
    """Raised when the API returns a non-2xx response."""
    def __init__(self, message: str, status_code: int = 0, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class AuthenticationError(QuickBooksError):
    """Raised on 401 / 403 responses."""


class NotConnectedError(QuickBooksError):
    """Raised when QuickBooks OAuth is not yet connected."""


class QuickBooksClient:
    """
    Thread-safe HTTP client for the QuickBooks Django Integration API.

    The session persists cookies across calls so you only need to call
    ``login()`` once per client instance.

    Args:
        base_url:  Base URL of your Django server, e.g. ``http://localhost:8000``
        timeout:   Request timeout in seconds (default 30)
        verify_ssl: Verify SSL certificates (default True; set False for local dev)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: int = 30,
        verify_ssl: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        self._csrf_token: str = ""


    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _set_csrf(self) -> None:
        """Pull the latest CSRF token from the session cookie jar."""
        token = self._session.cookies.get("csrftoken", "")
        if token:
            self._csrf_token = token
            self._session.headers["X-CSRFToken"] = token

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict | None = None,
    ) -> Any:
        url = self._url(path)
        self._set_csrf()
        try:
            response = self._session.request(
                method=method,
                url=url,
                json=json,
                params=params,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
        except requests.ConnectionError as exc:
            raise QuickBooksError(f"Could not connect to {self.base_url}: {exc}") from exc
        except requests.Timeout as exc:
            raise QuickBooksError(f"Request timed out after {self.timeout}s: {url}") from exc

        logger.debug("[QB] %s %s → %s", method.upper(), url, response.status_code)

        if response.status_code in (401, 403):
            raise AuthenticationError(
                f"Authentication failed: {response.text}",
                status_code=response.status_code,
                response_body=response.text,
            )

        if not response.ok:
            raise QuickBooksError(
                f"Request failed [{response.status_code}]: {response.text}",
                status_code=response.status_code,
                response_body=response.text,
            )

        if not response.content:
            return {}
        return response.json()


    def login(self, username: str, password: str) -> dict:
        """
        Authenticate and persist the session cookie.
        Must be called before any other method.

        Returns:
            ``{"message": ..., "username": ...}``
        """
        data = self._request("POST", "/auth/login/", json={
            "username": username,
            "password": password,
        })
        self._set_csrf()
        logger.info("[QB] Logged in as %s", data.get("username"))
        return data

    def logout(self) -> dict:
        """Terminate the current session."""
        return self._request("POST", "/auth/logout/")

    def connect_oauth(self) -> dict:
        """
        Initiate the QuickBooks OAuth flow.
        Returns a redirect URL the user must visit to authorise the app.
        """
        return self._request("GET", "/qb/connect/")


    def get_company_info(self) -> CompanyInfo:
        """Return basic information about the connected QuickBooks company."""
        data = self._request("GET", "/qb/api/company/")
        return CompanyInfo.from_dict(data)


    def list_customers(self) -> list[Customer]:
        """Return all customers synced from QuickBooks."""
        data = self._request("GET", "/qb/api/customers/")
        return [Customer.from_dict(c) for c in data.get("customers", [])]

    def create_customer(
        self,
        display_name: str,
        email: str = "",
        phone: str = "",
    ) -> Customer:
        """
        Create a new customer in QuickBooks.

        Args:
            display_name: Full name or company name shown in QuickBooks.
            email:        Primary billing email address.
            phone:        Primary phone number (any format).

        Returns:
            The newly created :class:`Customer`.

        Example::

            customer = qb.create_customer(
                display_name="Acme Corp",
                email="billing@acme.com",
                phone="+254 700 123456",
            )
            print(customer.id)  # QuickBooks-assigned ID
        """
        payload = {"display_name": display_name}
        if email:
            payload["email"] = email
        if phone:
            payload["phone"] = phone

        data = self._request("POST", "/qb/api/customers/create/", json=payload)
        return Customer.from_dict(data.get("Customer", data))



    def list_invoices(self) -> list[Invoice]:
        """Return all invoices synced from QuickBooks."""
        data = self._request("GET", "/qb/api/invoices/")
        return [Invoice.from_dict(inv) for inv in data.get("invoices", [])]

    def create_invoice(
        self,
        customer_ref_id: str,
        due_date: str | date,
        line_items: list[LineItem],
    ) -> Invoice:
        """
        Create a new invoice in QuickBooks.

        Args:
            customer_ref_id: QuickBooks customer ID (use :meth:`list_customers`
                             to find one or save from :meth:`create_customer`).
            due_date:        Due date as ``"YYYY-MM-DD"`` string or :class:`date`.
            line_items:      One or more :class:`LineItem` instances.

        Returns:
            The newly created :class:`Invoice`.

        Example::

            invoice = qb.create_invoice(
                customer_ref_id="42",
                due_date="2025-12-31",
                line_items=[
                    LineItem("Website redesign", amount=120000, quantity=1, unit_price=120000),
                    LineItem("Hosting (annual)",  amount=24000,  quantity=1, unit_price=24000),
                ],
            )
            print(invoice.id, invoice.total)
        """
        if isinstance(due_date, date):
            due_date = due_date.isoformat()

        payload = {
            "customer_ref_id": str(customer_ref_id),
            "due_date": due_date,
            "line_items": [item.to_dict() for item in line_items],
        }
        data = self._request("POST", "/qb/api/invoices/create/", json=payload)
        return Invoice.from_dict(data.get("Invoice", data))



    def list_accounts(self) -> list[Account]:
        """Return the chart of accounts from QuickBooks."""
        data = self._request("GET", "/qb/api/accounts/")
        return [Account.from_dict(a) for a in data.get("accounts", [])]


    def get_pnl_report(
        self,
        start_date: str | date,
        end_date: str | date,
    ) -> dict:
        """
        Fetch the Profit & Loss report for a date range.

        Args:
            start_date: Start of period, e.g. ``"2025-01-01"`` or :class:`date`.
            end_date:   End of period, e.g. ``"2025-12-31"`` or :class:`date`.

        Returns:
            Raw QuickBooks report dict containing ``Header``, ``Columns``,
            and ``Rows`` keys.

        Example::

            report = qb.get_pnl_report("2025-01-01", "2025-12-31")
            print(report["Header"]["ReportName"])
        """
        if isinstance(start_date, date):
            start_date = start_date.isoformat()
        if isinstance(end_date, date):
            end_date = end_date.isoformat()

        return self._request(
            "GET",
            "/qb/api/reports/pnl/",
            params={"start_date": start_date, "end_date": end_date},
        )



    def get_sync_status(self) -> SyncStatus:
        """Return the count of locally synced customers, invoices, and accounts."""
        data = self._request("GET", "/qb/api/sync/status/")
        return SyncStatus.from_dict(data)



    def __enter__(self) -> "QuickBooksClient":
        return self

    def __exit__(self, *_: Any) -> None:
        try:
            self.logout()
        except QuickBooksError:
            pass
        self._session.close()

#
#
# class QuickBooksAdminMixin:
#     """
#     Mixin for django-unfold ModelAdmin classes.
#
#     Adds a ``push_to_quickbooks`` bulk action to any model admin that
#     includes it. Override ``get_qb_client()`` to provide credentials
#     from Django settings, environment variables, or a secrets manager.
#
#     Override ``model_to_customer()`` or ``model_to_invoice()`` to map
#     your model fields to QuickBooks payloads.
#
#     Example::
#
#         # settings.py
#         QUICKBOOKS_BASE_URL = "http://localhost:8000"
#         QUICKBOOKS_USERNAME = "admin"
#         QUICKBOOKS_PASSWORD = env("QB_PASSWORD")
#
#         # admin.py
#         from unfold.admin import ModelAdmin
#         from quickbooks_client import QuickBooksAdminMixin
#
#         @admin.register(Client)
#         class ClientAdmin(QuickBooksAdminMixin, ModelAdmin):
#             actions = ["push_to_quickbooks"]
#
#             def model_to_customer(self, obj):
#                 return {
#                     "display_name": obj.company_name,
#                     "email": obj.billing_email,
#                     "phone": obj.phone,
#                 }
#     """
#
#     # Override in subclass if needed
#     QB_BASE_URL_SETTING = "QUICKBOOKS_BASE_URL"
#     QB_USERNAME_SETTING = "QUICKBOOKS_USERNAME"
#     QB_PASSWORD_SETTING = "QUICKBOOKS_PASSWORD"
#
#     def get_qb_client(self) -> QuickBooksClient:
#         """
#         Return an authenticated :class:`QuickBooksClient`.
#
#         By default reads ``QUICKBOOKS_BASE_URL``, ``QUICKBOOKS_USERNAME``,
#         and ``QUICKBOOKS_PASSWORD`` from ``django.conf.settings``.
#         Override to customise credential sourcing.
#         """
#         from django.conf import settings  # noqa: PLC0415
#
#         base_url = getattr(settings, self.QB_BASE_URL_SETTING, "http://localhost:8000")
#         username = getattr(settings, self.QB_USERNAME_SETTING, "admin")
#         password = getattr(settings, self.QB_PASSWORD_SETTING, "")
#
#         client = QuickBooksClient(base_url=base_url)
#         client.login(username, password)
#         return client
#
#     # ------------------------------------------------------------------
#     # Override these to map your model → QB payload
#     # ------------------------------------------------------------------
#
#     def model_to_customer(self, obj: Any) -> Optional[dict]:
#         """
#         Map a model instance to a :meth:`QuickBooksClient.create_customer`
#         kwargs dict, or return ``None`` to skip.
#
#         Default implementation looks for ``display_name``/``name``,
#         ``email``, and ``phone`` attributes on the model.
#         """
#         name = getattr(obj, "display_name", None) or getattr(obj, "name", str(obj))
#         return {
#             "display_name": name,
#             "email": getattr(obj, "email", ""),
#             "phone": getattr(obj, "phone", ""),
#         }
#
#     def model_to_invoice(self, obj: Any, customer_id: str) -> Optional[dict]:
#         """
#         Map a model instance to a :meth:`QuickBooksClient.create_invoice`
#         kwargs dict, or return ``None`` to skip invoice creation.
#
#         Default: no invoice created. Override to enable.
#
#         Example::
#
#             def model_to_invoice(self, obj, customer_id):
#                 return {
#                     "customer_ref_id": customer_id,
#                     "due_date": obj.due_date.isoformat(),
#                     "line_items": [
#                         LineItem(
#                             description=item.name,
#                             amount=float(item.total),
#                             quantity=item.qty,
#                             unit_price=float(item.unit_price),
#                         )
#                         for item in obj.order_items.all()
#                     ],
#                 }
#         """
#         return None
#
#     # ------------------------------------------------------------------
#     # Unfold action
#     # ------------------------------------------------------------------
#
#     @staticmethod
#     def _action_description() -> str:
#         return "Push selected records to QuickBooks"
#
#     def push_to_quickbooks(self, request: Any, queryset: Any) -> None:
#         """
#         Unfold bulk action: creates a QuickBooks customer (and optionally an
#         invoice) for every selected object.
#         """
#         from django.contrib import messages  # noqa: PLC0415
#
#         created, skipped, errors = 0, 0, []
#
#         try:
#             qb = self.get_qb_client()
#         except QuickBooksError as exc:
#             self.message_user(request, f"Could not connect to QuickBooks: {exc}", messages.ERROR)
#             return
#
#         for obj in queryset:
#             try:
#                 customer_payload = self.model_to_customer(obj)
#                 if customer_payload is None:
#                     skipped += 1
#                     continue
#
#                 customer = qb.create_customer(**customer_payload)
#                 logger.info("[QB admin] Created customer %s for %s", customer.id, obj)
#
#                 invoice_payload = self.model_to_invoice(obj, customer.id)
#                 if invoice_payload is not None:
#                     qb.create_invoice(**invoice_payload)
#                     logger.info("[QB admin] Created invoice for customer %s", customer.id)
#
#                 created += 1
#
#             except QuickBooksError as exc:
#                 errors.append(f"{obj}: {exc}")
#                 logger.warning("[QB admin] Failed for %s: %s", obj, exc)
#
#         # User-facing feedback
#         if created:
#             self.message_user(request, f"✅ {created} record(s) pushed to QuickBooks.", messages.SUCCESS)
#         if skipped:
#             self.message_user(request, f"⏭ {skipped} record(s) skipped.", messages.WARNING)
#         for err in errors:
#             self.message_user(request, f"❌ {err}", messages.ERROR)
#
#     push_to_quickbooks.short_description = "Push to QuickBooks"  # type: ignore[attr-defined]



if __name__ == "__main__":


    base = "https://upstanding-amie-contritely.ngrok-free.dev"
    user = "steve"
    pwd  = "2755"

    print(f"\n🔌 Connecting to {base} as {user} …\n")

    with QuickBooksClient(base_url=base) as qb:
        qb.login(user, pwd)
        connect = qb.connect_oauth()
        print(f"Connect : {connect}")

        company = qb.get_company_info()
        print(f"🏢 Company : {company.name} ({company.country})")
        status = qb.get_sync_status()
        print(f"🔄 Sync    : {status.customers} customers | {status.invoices} invoices | {status.accounts} accounts")

        customers = qb.list_customers()
        print(f"👥 Customers ({len(customers)} total):")
        for c in customers[:3]:
            print(f"   • [{c.id}] {c.display_name}  {c.email}")

        invoices = qb.list_invoices()
        print(f"\n Invoices ({len(invoices)} total):")
        for inv in invoices[:3]:
            print(f"   • [{inv.id}] customer={inv.customer_ref_id}  due={inv.due_date}  total={inv.total}")

        accounts = qb.list_accounts()
        print(f"\n📒 Accounts ({len(accounts)} total):")
        for acc in accounts[:3]:
            print(f"   • [{acc.id}] {acc.name}  ({acc.account_type})  balance={acc.balance}")

        print("\n✅ All checks passed.")