# 💳 Paymob Payment Integration — Django

A clean, production-ready Django integration with [Paymob Accept](https://accept.paymob.com/) for online card payments in Egypt. Handles the full payment lifecycle: order registration → payment key generation → iFrame checkout → webhook verification.

---

## 📋 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Payment Flow](#-payment-flow)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [API Endpoints](#-api-endpoints)
- [Project Structure](#-project-structure)
- [Error Handling](#-error-handling)
- [Security](#-security)
- [License](#-license)

---

## ✨ Features

- **Full Paymob Accept API integration** — authentication, order registration, payment key, iFrame, and webhook callback
- **HMAC signature verification** — validates that webhooks genuinely originate from Paymob (SHA-512)
- **Token caching** — auth tokens are cached (50 min TTL) to avoid redundant API calls
- **Automatic retry on 401** — transparently refreshes expired tokens and retries the request
- **Atomic webhook processing** — `SELECT FOR UPDATE` prevents race conditions on concurrent callbacks
- **Amount validation** — the webhook handler verifies the received amount matches the stored order
- **Clean error hierarchy** — `PaymobError` → `PaymobConnectionError` / `PaymobAPIError` with status codes and response bodies
- **Environment-based configuration** — all secrets live in `.env`, never in source control

---

## 🏗 Architecture

```
┌────────────┐         ┌──────────────────┐         ┌──────────────┐
│   Browser   │ ──1──▶ │   Django Server   │ ──2──▶ │  Paymob API  │
│  (Customer) │        │                   │ ◀──3── │              │
│             │ ◀──4── │   /pay/<ref>/     │        │              │
│  ┌────────┐ │        │                   │        │              │
│  │ iFrame │ │ ──5──▶ │                   │        │              │
│  └────────┘ │        │                   │        │              │
└────────────┘         │   /webhook/       │ ◀──6── │              │
                       └──────────────────┘         └──────────────┘
```

---

## 🔄 Payment Flow

| Step | Action                      | Endpoint / Method                     |
|------|-----------------------------|---------------------------------------|
| 1    | Customer visits pay page    | `GET /pay/<uuid:reference>/`          |
| 2    | Server authenticates        | `POST /auth/tokens`                   |
| 3    | Server registers order      | `POST /ecommerce/orders`              |
| 4    | Server generates payment key| `POST /acceptance/payment_keys`       |
| 5    | iFrame rendered to customer | Paymob hosted iFrame                  |
| 6    | Customer completes payment  | Card form inside iFrame               |
| 7    | Paymob sends webhook        | `POST /webhook/?hmac=<signature>`     |
| 8    | Server verifies & updates   | HMAC check → Order status update      |

---

## 📦 Prerequisites

- **Python** 3.10+
- **Django** 6.1+
- A **Paymob Accept** merchant account ([sign up here](https://accept.paymob.com/))
- Your Paymob **API Key**, **Integration ID**, **iFrame ID**, and **HMAC Secret**

---

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/Mostafa-Talaat98/Paymob-Integration.git
cd Paymob-Integration
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install django django-environ requests
```

### 4. Set up environment variables

Create a `.env` file in the project root:

```env
PAYMOB_API_KEY=your_api_key_here
PAYMOB_BASE_URL=https://accept.paymob.com/api
PAYMOB_INTEGRATION_ID=your_integration_id
PAYMOB_IFRAME_ID=your_iframe_id
PAYMOB_TIMEOUT=15
PAYMOB_HMAC_SECRET=your_hmac_secret
```

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Start the development server

```bash
python manage.py runserver
```

---

## ⚙️ Configuration

All Paymob settings are loaded from environment variables via `django-environ`:

| Variable                | Description                                | Default                             |
|-------------------------|--------------------------------------------|-------------------------------------|
| `PAYMOB_API_KEY`        | Your merchant API key from Paymob dashboard| **Required**                        |
| `PAYMOB_BASE_URL`       | Paymob Accept API base URL                 | `https://accept.paymob.com/api`     |
| `PAYMOB_INTEGRATION_ID` | Payment integration ID (card payments)     | **Required**                        |
| `PAYMOB_IFRAME_ID`      | iFrame ID from your Paymob dashboard       | **Required**                        |
| `PAYMOB_HMAC_SECRET`    | HMAC secret for webhook signature verification | **Required**                    |
| `PAYMOB_TIMEOUT`        | HTTP request timeout in seconds            | `15`                                |

---

## 💡 Usage

### Create an Order (via Django Admin or Shell)

```python
from payments.models import Order

order = Order.objects.create(
    description="Premium subscription",
    amount_cents=50000,   # 500.00 EGP
    currency="EGP",
)

print(order.reference)  # → UUID to use in the payment URL
```

### Direct the Customer to Pay

```
http://localhost:8000/pay/<order-reference-uuid>/
```

The page renders a Paymob iFrame where the customer enters their card details.

---

## 🔗 API Endpoints

| Method | URL                          | Description                          |
|--------|------------------------------|--------------------------------------|
| `GET`  | `/pay/<uuid:reference>/`     | Renders the payment page with iFrame |
| `POST` | `/webhook/`                  | Receives Paymob transaction callbacks|

---

## 📁 Project Structure

```
Paymob-Integration/
├── config/
│   ├── settings.py          # Django settings + Paymob config
│   ├── urls.py              # Root URL configuration
│   ├── wsgi.py
│   └── asgi.py
├── payments/
│   ├── models.py            # Order model (status, amounts, Paymob IDs)
│   ├── views.py             # Pay page view + webhook handler
│   ├── urls.py              # /pay/ and /webhook/ routes
│   ├── services/
│   │   └── paymob.py        # Full Paymob API client (auth, orders, keys, HMAC)
│   ├── templates/
│   │   └── payments/
│   │       └── pay.html     # Payment page with iFrame embed
│   └── migrations/
├── .env                     # Environment variables (not committed)
├── .gitignore
├── manage.py
└── README.md
```

---

## 🛡 Error Handling

The service layer uses a structured exception hierarchy:

```
PaymobError (base)
├── PaymobConnectionError   — Network failures (timeout, DNS, etc.)
└── PaymobAPIError           — Non-2xx responses from Paymob
    ├── .status_code         — HTTP status code
    └── .body                — Raw response body for debugging
```

All errors are logged with full context. The pay view returns a user-friendly error page (HTTP 502) if anything goes wrong.

---

## 🔒 Security

- **HMAC Verification** — Every webhook is validated using SHA-512 HMAC with your secret key. Requests with invalid or missing signatures are rejected with `403 Forbidden`.
- **Atomic Updates** — Webhook processing uses `select_for_update()` within a transaction to prevent double-processing.
- **Amount Validation** — The webhook verifies `amount_cents` matches the stored order to prevent tampering.
- **No Secrets in Code** — All credentials are loaded from `.env` which is excluded via `.gitignore`.
- **CSRF Exemption** — Only the webhook endpoint is CSRF-exempt (required for Paymob server-to-server callbacks).

---

## 📝 License

This project is open source and available under the [MIT License](LICENSE).
