import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
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

def callback(request):
    code = request.GET.get("code")
    realm_id = request.GET.get("realmId")
    state = request.GET.get("state")
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


# ─── Sync Views ──────────────────────────────────────────────────────────────

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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_create_customer(request):
    """
    POST /qb/api/customers/create/
    Body: { "display_name": "...", "email": "...", "phone": "..." }
    """
    display_name = request.data.get("display_name")
    if not display_name:
        return Response({"error": "display_name is required"}, status=400)

    try:
        data = services.create_customer(
            request.user,
            display_name=display_name,
            email=request.data.get("email", ""),
            phone=request.data.get("phone", ""),
        )
        return Response(data, status=201)
    except Exception as exc:
        return Response({"error": str(exc)}, status=400)


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
    Body: {
        "customer_ref_id": "...",
        "due_date": "YYYY-MM-DD",
        "line_items": [
            {"description": "...", "amount": 100, "quantity": 1, "unit_price": 100}
        ]
    }
    """
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