# LawNexa — Current MVP Source

LawNexa is a Pakistan-focused legal-tech MVP using FastAPI, SQLAlchemy, Alembic, and a static HTML frontend. Local development uses SQLite; hosted environments should use persistent PostgreSQL.

## Canonical source

For this cleaned release, the top-level `main.py`, `models.py`, `database.py`, `auth.py`, `schemas.py`, `index.html`, and `admin.html` are canonical. The older nested `lawnexa/`, `nonpay/`, and `regfix/` variants in the original archive had competing API contracts and are intentionally excluded from this release bundle.

## Implemented and test-covered areas

- Registration and login with signed JWT tokens; private user responses do not expose password hashes.
- Authenticated profile read/update with advocate profile synchronization.
- Advocate registration, admin approval, manual license verification state, and verified-only public directory listing.
- Authenticated appointment create/list/detail/status APIs, server-side consultation fees, future-date validation, duplicate active-slot checks, and role-aware status transitions.
- Authenticated document draft saving and private document listing; server-side HTML allowlist sanitization strips active markup and unsafe CSS.
- `/admin` UI shell and role-protected admin endpoints.
- Additive Alembic migrations for known legacy columns, advocate profile backfill, and appointment fields.

## Not yet production-enabled

Payment collection, wallet/escrow, emergency dispatch, delivered real-time chat/calls, feed persistence, and verified legal research are **not enabled** in this source snapshot. The frontend labels these areas as unavailable/local preview rather than claiming a transaction or alert occurred. Legal-document output is a draft, not an official court/government document. Do not use it as legal advice without review by a qualified Pakistani advocate.

## Setup

1. Use a supported Python version and create a virtual environment.
2. Install dependencies listed in `requirements.txt`.
3. Copy `.env.example` to `.env` for local settings. Keep real deployment secrets in the hosting provider's private environment settings.
4. Run the FastAPI app from this project directory. Local SQLite is stored relative to this source directory; set `DATABASE_URL` to use another database.
5. Open `/` for the API health landing response, `/docs` for the development API schema, and `/admin` for the admin UI. The admin APIs still require a real admin account provisioned via `ADMIN_EMAIL` and `ADMIN_PASSWORD`.

The application applies versioned Alembic migrations before serving requests, then creates any missing tables. Back up real databases before migration. Existing rows should be preserved by the supplied additive revisions, but always verify a restorable backup before production rollout.

## Tests

With project dependencies installed, run:

```bash
pytest -q test_main.py test_schema_migrations.py test_html_sanitizer.py
node test_frontend_security.js
```

The API suite covers the current `/api/*` contract and request validation. `test_schema_migrations.py` migrates a deliberately old SQLite schema; `test_html_sanitizer.py` verifies saved-draft HTML sanitization, and `test_frontend_security.js` exercises key XSS-safe rendering/API wiring invariants without an external test framework. Full browser QA against deployed Vercel/Render services, real password-hash verification in the normal environment, payment-provider sandbox testing, and production restore drills remain separate release gates.
