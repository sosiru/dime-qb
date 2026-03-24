"""
QuickBooks API service layer (OAuth2 via requests).
Handles auth, token refresh, API calls, and sync helpers.
"""

import logging
import base64
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings

from .models import QuickBooksToken

logger = logging.getLogger(__name__)

QB_BASE_URLS = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}

OAUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"


def get_authorization_url():
    """Generate QuickBooks OAuth2 authorization URL."""
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": settings.QUICKBOOKS_CLIENT_ID,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": "https://upstanding-amie-contritely.ngrok-free.dev/qb/callback",
        "state": state,
    }

    url = f"{OAUTH_URL}?" + urllib.parse.urlencode(params)
    return url, state


def _get_basic_auth_header():
    credentials = f"{settings.QUICKBOOKS_CLIENT_ID}:{settings.QUICKBOOKS_CLIENT_SECRET}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"

def exchange_code_for_tokens(auth_code: str, realm_id: str, user):
    headers = {
        "Authorization": _get_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": "https://upstanding-amie-contritely.ngrok-free.dev/qb/callback" # settings.QUICKBOOKS_REDIRECT_URI,
    }

    response = requests.post(TOKEN_URL, headers=headers, data=data)
    print("STATUS:", response.status_code)
    print("BODY:", response.text)
    response.raise_for_status()
    token_data = response.json()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
    refresh_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=token_data["x_refresh_token_expires_in"]
    )
    token_obj, _ = QuickBooksToken.objects.update_or_create(
        user=user,
        defaults={
            "realm_id": realm_id,
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "access_token_expires_at": expires_at,
            "refresh_token_expires_at": refresh_expires_at,
        },
    )
    return token_obj


def refresh_access_token(token_obj: QuickBooksToken):
    """Refresh access token."""
    headers = {
        "Authorization": _get_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": token_obj.refresh_token,
    }

    response = requests.post(TOKEN_URL, headers=headers, data=data)
    response.raise_for_status()
    token_data = response.json()

    token_obj.access_token = token_data["access_token"]
    token_obj.refresh_token = token_data["refresh_token"]
    token_obj.access_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
    token_obj.refresh_token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=token_data["x_refresh_token_expires_in"]
    )
    token_obj.save()

    return token_obj


def get_valid_token(user) -> QuickBooksToken:
    """Ensure valid token (refresh if needed)."""
    now = datetime.now(timezone.utc)
    token_obj, created = QuickBooksToken.objects.get_or_create(
        user=user,
        defaults={
            "realm_id": None,
            "access_token": "",
            "refresh_token": "",
            "access_token_expires_at": None,
            "refresh_token_expires_at": None,
        }
    )
    print(created)
    if created:
        logger.warning("Created new empty QuickBooksToken for user %s", user.id)
    if token_obj.refresh_token_expires_at and token_obj.refresh_token_expires_at <= now:
        raise Exception("QuickBooks connection expired. Reconnect required.")
    if token_obj.access_token_expires_at and token_obj.access_token_expires_at <= now:
        logger.info("Refreshing QuickBooks token for %s", user.username)
        token_obj = refresh_access_token(token_obj)
    return token_obj

def _qb_get(user, endpoint: str, params: dict = None):
    token_obj = get_valid_token(user)
    base_url = QB_BASE_URLS[settings.QUICKBOOKS_ENVIRONMENT]

    url = f"{base_url}/v3/company/{token_obj.realm_id}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {token_obj.access_token}",
        "Accept": "application/json",
    }

    params = params or {}
    params["minorversion"] = 65

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 401:
        token_obj = refresh_access_token(token_obj)
        headers["Authorization"] = f"Bearer {token_obj.access_token}"
        response = requests.get(url, headers=headers, params=params)

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        logger.error("QB GET error: %s %s", response.status_code, response.text)
        raise

    return response.json()


def _qb_post(user, endpoint: str, payload: dict):
    token_obj = get_valid_token(user)
    base_url = QB_BASE_URLS[settings.QUICKBOOKS_ENVIRONMENT]

    url = f"{base_url}/v3/company/{token_obj.realm_id}/{endpoint}?minorversion=65"

    headers = {
        "Authorization": f"Bearer {token_obj.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=payload)

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        logger.error("QB POST error: %s %s", response.status_code, response.text)
        raise

    return response.json()


def query(user, sql: str):
    return _qb_get(user, "query", params={"query": sql})


def get_company_info(user):
    return query(user, "SELECT * FROM CompanyInfo")


def get_customers(user, max_results=100):
    data = query(user, f"SELECT * FROM Customer MAXRESULTS {max_results}")
    return data.get("QueryResponse", {}).get("Customer", [])


def get_invoices(user, max_results=100):
    data = query(user, f"SELECT * FROM Invoice MAXRESULTS {max_results}")
    return data.get("QueryResponse", {}).get("Invoice", [])


def get_accounts(user, max_results=100):
    data = query(user, f"SELECT * FROM Account MAXRESULTS {max_results}")
    return data.get("QueryResponse", {}).get("Account", [])


def create_customer(user, display_name, email="", phone=""):
    payload = {"DisplayName": display_name}

    if email:
        payload["PrimaryEmailAddr"] = {"Address": email}
    if phone:
        payload["PrimaryPhone"] = {"FreeFormNumber": phone}

    return _qb_post(user, "customer", payload)


def create_invoice(user, customer_ref_id, line_items, due_date=None):
    lines = []
    for item in line_items:
        lines.append({
            "Amount": item["amount"],
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {
                "Qty": item.get("quantity", 1),
                "UnitPrice": item.get("unit_price", item["amount"]),
            },
            "Description": item.get("description", ""),
        })

    payload = {
        "CustomerRef": {"value": customer_ref_id},
        "Line": lines,
    }

    if due_date:
        payload["DueDate"] = due_date

    return _qb_post(user, "invoice", payload)


# ─────────────────────────────────────────────────────────────
# 🔄 SYNC HELPERS
# ─────────────────────────────────────────────────────────────

def sync_customers(user):
    from .models import Customer

    customers = get_customers(user)
    for c in customers:
        Customer.objects.update_or_create(
            qb_id=c["Id"],
            defaults={
                "display_name": c.get("DisplayName", ""),
                "email": c.get("PrimaryEmailAddr", {}).get("Address", ""),
                "phone": c.get("PrimaryPhone", {}).get("FreeFormNumber", ""),
                "balance": c.get("Balance", 0),
                "active": c.get("Active", True),
            },
        )

    return len(customers)


def sync_invoices(user):
    from .models import Invoice, Customer

    invoices = get_invoices(user)

    for inv in invoices:
        customer_ref = inv.get("CustomerRef", {})
        customer = Customer.objects.filter(qb_id=customer_ref.get("value")).first()

        Invoice.objects.update_or_create(
            qb_id=inv["Id"],
            defaults={
                "doc_number": inv.get("DocNumber", ""),
                "customer": customer,
                "customer_name": customer_ref.get("name", ""),
                "txn_date": inv.get("TxnDate"),
                "due_date": inv.get("DueDate"),
                "total_amt": inv.get("TotalAmt", 0),
                "balance": inv.get("Balance", 0),
            },
        )

    return len(invoices)