# LawNexa implementation and deployment runbook

## What is implemented in this package
- Business workspace in the existing frontend: create legal requests, view lifecycle/status, review proposals, accept/decline and pay an accepted proposal.
- Admin portal: corporate request queue, request status management, proposal creation and approved Advocate assignment.
- Safepay hosted-checkout integration for corporate subscriptions and accepted paid proposals. A signed HMAC-SHA512 webhook is required before marking a payment paid or activating a subscription.
- Email OTP password reset endpoints, single-use 10-minute codes, hashed OTP storage, attempt limits and generic account-existence response.
- New database tables are created additively by SQLAlchemy metadata; existing tables and user data are not dropped.

## Required environment settings
Keep secrets only in Render environment variables, never in Git or the ZIP.

```env
ENVIRONMENT=production
SECRET_KEY=<unique random value at least 32 characters>
DATABASE_URL=<persistent PostgreSQL URL>
ALLOWED_ORIGINS=https://lawnexa.vercel.app
FRONTEND_URL=https://lawnexa.vercel.app

# Email password reset; use a verified sender and SMTP credentials
SMTP_HOST=<provider SMTP hostname>
SMTP_PORT=587
SMTP_USERNAME=<SMTP username>
SMTP_PASSWORD=<SMTP app password>
EMAIL_FROM=<verified sender email>

# Safepay: start with sandbox credentials
SAFEPAY_ENVIRONMENT=sandbox
SAFEPAY_API_KEY=<sandbox merchant API key>
SAFEPAY_SECRET_KEY=<sandbox merchant secret key>
SAFEPAY_WEBHOOK_SECRET=<sandbox webhook signing secret>
SAFEPAY_INTENT=CYBERSOURCE
```

For live payments, Safepay must approve the merchant and provide live API/secret/webhook credentials. Switch `SAFEPAY_ENVIRONMENT=production` only after sandbox testing and configure the production webhook endpoint:
`https://lawnexa.onrender.com/api/v1/payments/safepay/webhook`

Use Safepay's webhook event for successful payments. Browser redirects are not payment proof. Official integration docs: https://safepay-docs.netlify.app/build-your-integration/express-checkout/?platform=web and https://safepay.helpscoutdocs.com/article/173-asp-net-integration-guide.

## Local verification
1. Create a fresh virtual environment.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`; set a development `SECRET_KEY`, local SQLite `DATABASE_URL`, and sandbox/email settings.
4. Run syntax checks: `python -m py_compile main.py models.py database.py geo_engine.py test_main.py`.
5. Run tests: `python -m pytest -q`.
6. Start server: `uvicorn main:app --reload`.
7. Open `http://127.0.0.1:8000/` and `http://127.0.0.1:8000/admin`.
8. Test with Safepay sandbox cards only; verify the signed webhook reaches the local/dev backend via a secure tunnel. Never simulate a successful payment by changing a DB status manually.

## Deployment steps
1. Back up the production database and confirm restore procedure.
2. Review the diff and commit only intended files. Do not commit `.env`, database files, uploads, tokens or provider credentials.
3. Deploy backend to Render and set all backend environment variables.
4. Set Safepay sandbox webhook endpoint to `https://lawnexa.onrender.com/api/v1/payments/safepay/webhook`.
5. Verify `GET /health`, `GET /openapi.json`, login, Business registration, request creation, proposal creation/decision, checkout creation, webhook signature rejection/acceptance, and password reset email delivery.
6. Deploy frontend/admin assets only after API smoke tests pass.
7. Perform a full sandbox payment and confirm the DB status changes only after the webhook.
8. Switch to live Safepay credentials only after merchant approval and successful sandbox verification.

## Limitations that require external account access
- No credentials are bundled. Safepay checkout and email OTP cannot operate until valid provider settings are supplied in Render.
- I cannot deploy to your Render/Vercel accounts or configure their dashboard from this ZIP.
- Full tests require installing dependencies. The current audit environment does not have `python-jose` and `passlib`, and package-index access was unavailable. Python syntax and JavaScript syntax checks are not substitutes for API integration tests.
- This code uses lightweight SQLAlchemy table creation, not versioned Alembic migrations. For production, run a database backup and review the schema before rollout.
