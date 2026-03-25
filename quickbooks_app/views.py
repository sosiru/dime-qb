import logging
import uuid

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from . import services
from .models import Account, Customer, Invoice, QuickBooksToken, OAuthState
import secrets
import json
import base64
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([AllowAny])
def api_login(request):
    """
    POST /auth/login/
    Body: { "username": "...", "password": "..." }
    Returns CSRF token and session cookie — use these for all subsequent requests.
    """
    username = request.data.get("username")
    password = request.data.get("password")

    if not username or not password:
        return Response({"error": "username and password are required"}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({"error": "Invalid credentials"}, status=401)

    login(request, user)
    return Response({
        "message": f"Logged in as {user.username}",
        "username": user.username,
        "note": "Session cookie has been set. Postman will send it automatically on subsequent requests."
    })


@api_view(["POST"])
def api_logout(request):
    """POST /auth/logout/"""
    logout(request)
    return Response({"message": "Logged out successfully"})

@login_required
def connect(request):
    auth_url, state_token = services.get_authorization_url()
    print(auth_url)
    OAuthState.objects.create(
        state=state_token,
        user=request.user
    )

    return JsonResponse({"auth_url": auth_url})

from .models import OAuthState

@csrf_exempt
def callback(request):
    print("callback", request.GET)
    code = request.GET.get("code")
    realm_id = request.GET.get("realmId")
    state = request.GET.get("state")
    print("State: ", state)
    print("State: ", state)
    if not code or not realm_id:
        return JsonResponse({"success": False, "message": "Missing code or realm ID"}, status=400)
    try:
        state_obj = OAuthState.objects.get(state=state, used=False)
    except OAuthState.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invalid state"}, status=400)
    user = state_obj.user
    state_obj.used = True
    state_obj.save()
    services.exchange_code_for_tokens(code, realm_id, user)
    return JsonResponse({
        "success": True,
        "message": "QuickBooks connected successfully",
        "realm_id": realm_id
    })

@login_required
def disconnect(request):
    """Revoke and delete stored tokens."""
    try:
        deleted_count, _ = QuickBooksToken.objects.filter(user=request.user).delete()

        return JsonResponse({
            "success": True,
            "message": "Disconnected from QuickBooks successfully",
            "deleted_records": deleted_count
        })
    except Exception as exc:
        logger.exception("Disconnect error: %s", exc)
        return JsonResponse({
            "success": False,
            "message": "Failed to disconnect",
            "error": str(exc)
        }, status=500)



@login_required
def dashboard(request):
    """Main dashboard showing connection status and counts."""
    is_connected = QuickBooksToken.objects.filter(user=request.user).exists()
    context = {
        "is_connected": is_connected,
        "customer_count": Customer.objects.count(),
        "invoice_count": Invoice.objects.count(),
        "account_count": Account.objects.count(),
    }
    return render(request, "quickbooks_app/dashboard.html", context)



@login_required
def sync_all(request):
    """Trigger a full sync of customers, invoices, and accounts."""
    if request.method != "POST":
        return redirect("qb:dashboard")

    try:
        c = services.sync_customers(request.user)
        i = services.sync_invoices(request.user)
        a = services.sync_accounts(request.user)
        messages.success(request, f"Sync complete — {c} customers, {i} invoices, {a} accounts.")
    except Exception as exc:
        logger.exception("Sync error: %s", exc)
        messages.error(request, f"Sync failed: {exc}")

    return redirect("qb:dashboard")



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_company_info(request):
    """GET /qb/api/company/ — return company info."""
    try:
        data = services.get_company_info(request.user)
        return Response(data)
    except Exception as exc:
        return Response({"error": str(exc)}, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_customers(request):
    """GET /qb/api/customers/ — list customers from QuickBooks."""
    try:
        data = services.get_customers(request.user)
        return Response({"count": len(data), "customers": data})
    except Exception as exc:
        return Response({"error": str(exc)}, status=400)


from decimal import Decimal
from django.utils import timezone
from decimal import Decimal
from django.utils import timezone
import uuid

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_create_customer(request):
    display_name = request.data.get("display_name")
    account_name = request.data.get("account_name")
    account_type = request.data.get("account_type")
    account_sub_type = request.data.get("account_sub_type")

    email = request.data.get("email", "")
    phone = request.data.get("phone", "")

    state = str(uuid.uuid4())

    if not display_name:
        return Response({"error": "display_name is required"}, status=400)

    OAuthState.objects.create(
        state=state,
        user=request.user
    )

    try:
        # ─────────────────────────────
        # 1. CREATE CUSTOMER
        # ─────────────────────────────
        data = services.create_customer(
            request.user,
            display_name=display_name,
            email=email,
            phone=phone,
        )
        qb_customer = data.get("Customer")
        if not qb_customer:
            return Response(
                {"error": "Failed to create customer in QuickBooks"},
                status=400
            )
        if account_name and account_type:
            account_response = services.create_account(
                user=request.user,
                name=account_name,
                account_type=account_type,
                account_sub_type=account_sub_type
            )

            qb_account = account_response.get("Account")

            if qb_account:
                qb_acc_id = qb_account.get("Id")
                account_obj, created = Account.objects.get_or_create(
                    qb_id=qb_acc_id,
                    defaults={
                        "name": qb_account.get("Name"),
                        "account_type": qb_account.get("AccountType", ""),
                        "account_sub_type": qb_account.get("AccountSubType", ""),
                        "current_balance": Decimal(qb_account.get("CurrentBalance", 0)),
                        "active": qb_account.get("Active", True),
                    }
                )

                if not created:
                    account_obj.name = qb_account.get("Name")
                    account_obj.account_type = qb_account.get("AccountType", "")
                    account_obj.account_sub_type = qb_account.get("AccountSubType", "")
                    account_obj.current_balance = Decimal(qb_account.get("CurrentBalance", 0))
                    account_obj.active = qb_account.get("Active", True)
                    account_obj.synced_at = timezone.now()
                    account_obj.save()


        qb_id = qb_customer.get("Id")
        customer_obj, created = Customer.objects.get_or_create(
            qb_id=qb_id,
            defaults={
                "display_name": qb_customer.get("DisplayName"),
                "email": qb_customer.get("PrimaryEmailAddr", {}).get("Address", ""),
                "phone": qb_customer.get("PrimaryPhone", {}).get("FreeFormNumber", ""),
                "balance": Decimal(qb_customer.get("Balance", 0)),
                "active": qb_customer.get("Active", True),
            }
        )
        if not created:
            customer_obj.display_name = qb_customer.get("DisplayName")
            customer_obj.email = qb_customer.get("PrimaryEmailAddr", {}).get("Address", "")
            customer_obj.phone = qb_customer.get("PrimaryPhone", {}).get("FreeFormNumber", "")
            customer_obj.balance = Decimal(qb_customer.get("Balance", 0))
            customer_obj.active = qb_customer.get("Active", True)
            customer_obj.synced_at = timezone.now()
            customer_obj.save()

        return Response(data, status=201)
    except Exception as exc:
        error_str = str(exc)
        if "6240" in error_str or "Duplicate Name Exists" in error_str:
            return Response(
                {
                    "error": "Customer already exists in QuickBooks",
                    "details": error_str
                },
                status=409
            )
        return Response({"error": error_str}, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_invoices(request):
    """GET /qb/api/invoices/ — list invoices from QuickBooks."""
    try:
        data = services.get_invoices(request.user)
        return Response({"count": len(data), "invoices": data})
    except Exception as exc:
        return Response({"error": str(exc)}, status=400)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_create_invoice(request):
    """
    POST /qb/api/invoices/create/
    """
    from django.utils.dateparse import parse_date
    customer_ref_id = request.data.get("customer_ref_id")
    line_items = request.data.get("line_items", [])
    if not customer_ref_id:
        return Response({"error": "customer_ref_id is required"}, status=400)
    if not line_items:
        return Response({"error": "At least one line_item is required"}, status=400)
    try:
        data = services.create_invoice(
            request.user,
            customer_ref_id=customer_ref_id,
            line_items=line_items,
            due_date=request.data.get("due_date"),
        )
        qb_invoice = data.get("Invoice")
        if not qb_invoice:
            return Response(
                {"error": "Failed to create invoice in QuickBooks"},
                status=400
            )
        customer = Customer.objects.filter(
            qb_id=customer_ref_id
        ).first()
        qb_id = qb_invoice.get("Id")
        invoice_obj, created = Invoice.objects.get_or_create(
            qb_id=qb_id,
            defaults={
                "doc_number": qb_invoice.get("DocNumber", ""),
                "customer": customer,
                "customer_name": qb_invoice.get("CustomerRef", {}).get("name", ""),
                "txn_date": parse_date(qb_invoice.get("TxnDate")),
                "due_date": parse_date(qb_invoice.get("DueDate")),
                "total_amt": Decimal(qb_invoice.get("TotalAmt", 0)),
                "balance": Decimal(qb_invoice.get("Balance", 0)),
                "status": "Pending" if qb_invoice.get("Balance", 0) > 0 else "Paid",
            }
        )
        if not created:
            invoice_obj.doc_number = qb_invoice.get("DocNumber", "")
            invoice_obj.customer = customer
            invoice_obj.customer_name = qb_invoice.get("CustomerRef", {}).get("name", "")
            invoice_obj.txn_date = parse_date(qb_invoice.get("TxnDate"))
            invoice_obj.due_date = parse_date(qb_invoice.get("DueDate"))
            invoice_obj.total_amt = Decimal(qb_invoice.get("TotalAmt", 0))
            invoice_obj.balance = Decimal(qb_invoice.get("Balance", 0))
            balance = Decimal(qb_invoice.get("Balance", 0))
            if balance == 0:
                invoice_obj.status = "Paid"
            elif qb_invoice.get("DueDate"):
                invoice_obj.status = "Pending"
            else:
                invoice_obj.status = "Draft"
            invoice_obj.synced_at = timezone.now()
            invoice_obj.save()
        return Response(data, status=201)
    except Exception as exc:
        return Response({"error": str(exc)}, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_accounts(request):
    """GET /qb/api/accounts/ — list chart of accounts."""
    try:
        data = services.get_accounts(request.user)
        return Response({"count": len(data), "accounts": data})
    except Exception as exc:
        return Response({"error": str(exc)}, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_profit_and_loss(request):
    """
    GET /qb/api/reports/pnl/?start_date=2024-01-01&end_date=2024-12-31
    """
    start_date = request.query_params.get("start_date", "2024-01-01")
    end_date = request.query_params.get("end_date", "2024-12-31")

    try:
        data = services.get_profit_and_loss(request.user, start_date, end_date)
        return Response(data)
    except Exception as exc:
        return Response({"error": str(exc)}, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_sync_status(request):
    """GET /qb/api/sync/status/ — return local DB record counts."""
    return Response({
        "customers": Customer.objects.count(),
        "invoices": Invoice.objects.count(),
        "accounts": Account.objects.count(),
    })