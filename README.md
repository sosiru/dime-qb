# QuickBooks Django Integration

A Django project that integrates with the QuickBooks Online API via OAuth2.

## Features
- OAuth2 connect/disconnect flow with Intuit
- Customers — list & create
- Invoices — list & create
- Chart of Accounts — list
- Profit & Loss report
- Local DB sync (cache QB data locally)
- DRF REST API endpoints
- Django Admin for all models
- Full test suite

## Project Structure
```
quickbooks_integration/
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── quickbooks_app/
│   ├── models.py       # QuickBooksToken, Customer, Invoice, Account
│   ├── services.py     # All QB API logic
│   ├── views.py        # OAuth views + DRF API views
│   ├── urls.py
│   ├── admin.py
│   ├── tests.py
│   └── templates/
│       └── quickbooks_app/dashboard.html
├── manage.py
├── requirements.txt
└── .env.example
```

## Setup

### 1. Create a QuickBooks Developer App
1. Go to https://developer.intuit.com
2. Sign in / create an account
3. Click **Dashboard → Create an app → QuickBooks Online and Payments**
4. Under **Development → Keys & OAuth**, copy your **Client ID** and **Client Secret**
5. Add `http://localhost:8000/qb/callback/` to **Redirect URIs**

### 2. Local Environment
```bash
cd quickbooks_integration
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and fill in QUICKBOOKS_CLIENT_ID and QUICKBOOKS_CLIENT_SECRET
```

### 3. Database Setup
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

### 4. Run the Server
```bash
python manage.py runserver
```

Visit http://localhost:8000/qb/ for the dashboard.

---

## Testing

### Run the Full Test Suite
```bash
python manage.py test quickbooks_app
```

### Run a Specific Test Class
```bash
python manage.py test quickbooks_app.tests.APIEndpointsTest
python manage.py test quickbooks_app.tests.SyncServiceTest
python manage.py test quickbooks_app.tests.OAuthViewsTest
```

### Run with Verbosity
```bash
python manage.py test quickbooks_app -v 2
```

---

## API Reference

All endpoints require session authentication (login via `/admin/` or Django auth).

### GET /qb/api/company/
Returns QuickBooks company info.

### GET /qb/api/customers/
Lists all customers from QB.

### POST /qb/api/customers/create/
```json
{
  "display_name": "Acme Corporation",
  "email": "billing@acme.com",
  "phone": "+254 700 000000"
}
```

### GET /qb/api/invoices/
Lists all invoices from QB.

### POST /qb/api/invoices/create/
```json
{
  "customer_ref_id": "59",
  "due_date": "2024-12-31",
  "line_items": [
    {
      "description": "Web Development Services",
      "amount": 150000,
      "quantity": 1,
      "unit_price": 150000
    }
  ]
}
```

### GET /qb/api/accounts/
Lists chart of accounts.

### GET /qb/api/reports/pnl/?start_date=2024-01-01&end_date=2024-12-31
Profit & Loss report.

### GET /qb/api/sync/status/
Returns count of locally synced records.

---

## Testing with cURL (after login)

```bash
# Get CSRF token first (from browser or admin login)
curl -b cookies.txt http://localhost:8000/qb/api/sync/status/

# Create a customer
curl -X POST http://localhost:8000/qb/api/customers/create/ \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: YOUR_CSRF_TOKEN" \
  -b cookies.txt \
  -d '{"display_name": "Test Corp", "email": "test@corp.com"}'
```

## Testing with DRF Browsable API
Navigate to any `/qb/api/*` endpoint in your browser while logged in — Django REST Framework provides a built-in HTML interface for testing.
