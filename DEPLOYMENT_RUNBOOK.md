# LawNexa — Deployment and Verification Runbook

This runbook describes the cleaned, top-level source tree (`main.py`, `models.py`, `database.py`, `index.html`, `admin.html`). Older nested `lawnexa/`, `nonpay/`, and `regfix/` source copies are intentionally excluded because they use competing API contracts.

## Current API areas

- `GET /` and `GET /health`
- `GET /admin` — admin UI shell; admin APIs still require an authenticated `admin` role
- `POST /api/register`, `POST /api/login`
- `GET /api/profile`, `PUT /api/profile`
- `GET /api/lawyers`, `GET /api/lawyers/{lawyer_id}` — only active, approved, manually verified advocates are public
- Appointment create/list/detail/status routes under `/api/appointments`
- Admin user/advocate approval and verification routes under `/api/admin/*`
- Document template/save/list routes under `/api/documents/*`; saved HTML drafts are sanitized server-side
- `POST /api/ai-legal-research` — placeholder/clarification flow, **not** a live verified legal-research engine

Do not point clients at `/api/v1/*`; those routes are not part of this canonical source.

## Private environment settings

Configure these in your hosting provider's private settings, not in Git or the source ZIP:

```env
ENVIRONMENT=production
SECRET_KEY=<unique random value, at least 32 characters>
DATABASE_URL=<persistent PostgreSQL URL>
FRONTEND_ORIGINS=https://lawnexa.vercel.app
ADMIN_EMAIL=<dedicated administrator email>
ADMIN_PASSWORD=<unique random password of at least 16 characters>
ADMIN_NAME=LawNexa Administrator
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

`ALLOWED_ORIGINS` is accepted as a compatibility alias, but `FRONTEND_ORIGINS` is preferred. Deployed origins must be explicit HTTPS origins without paths or trailing slashes. Do not use `*` with credentials. Add each Vercel preview origin explicitly only when needed.

Admin provisioning happens only when both `ADMIN_EMAIL` and `ADMIN_PASSWORD` are present. It creates an admin only if that email is unused; it never promotes an existing regular account or resets an existing admin password. There are no default admin credentials.

For local development, copy `.env.example` to `.env`. `DATABASE_URL=sqlite:///./lawnexa.db` is supported and resolved relative to the project directory. The release ZIP deliberately excludes SQLite databases and user uploads.

## Database and migrations

The application runs versioned Alembic migrations before `create_all()`:

- revision `20261029_0001`: repairs known missing legacy columns and backfills appointment timestamps
- revision `20261029_0002`: creates missing legacy advocate directory profiles as **unverified**, without leaking residential addresses into the public listing
- revision `20261029_0003`: adds appointment meeting fields and consultation fee

These revisions are additive and covered by a migration regression test. Back up the production database and verify a restore before deployment. For future changes, add a new reviewed migration; never rewrite an already deployed revision or delete production data to resolve schema mismatch.

For multi-instance production deployment, coordinate migration execution so multiple app instances do not race to apply the same revision. This MVP runs migrations at app import/startup for convenient single-instance deployments; a production release pipeline should migrate once before scaling app workers.

## Verification

With the dependencies in `requirements.txt` installed in a normal project environment:

```bash
python -m py_compile main.py models.py database.py auth.py schemas.py admin_bootstrap.py
pytest -q test_main.py test_schema_migrations.py test_html_sanitizer.py
node test_frontend_security.js
```

Current audit results: Python compilation passed; 12 API integration tests, one legacy migration test, and two HTML-sanitizer tests passed (15 Python tests total); inline JavaScript syntax checks passed for `index.html` and `admin.html`; and the frontend security regression test passed. The constrained audit runner used a temporary password-hash test shim outside this source tree because its environment lacked the project's normal `python-jose`/`passlib` runtime dependencies; those API tests verify route and data-flow behavior, but password hashing itself must be re-verified by running the suite with the actual locked project dependencies. Live Vercel/Render smoke tests have not been run from this package.

## Known release blockers / disabled integrations

- External payment provider, wallet, escrow, refunds, payment ledger reconciliation, and signed webhook handling are not enabled. Never show a successful money transfer until sandbox and production reconciliation tests pass.
- Real-time delivered chat/call infrastructure and feed persistence are not enabled; current UI describes local-only preview behavior.
- Verified legal research and authoritative case-law retrieval are not connected. Do not cite model-generated statutes/cases as verified law.
- The deployment target must provide persistent object storage before user-uploaded media is enabled for production; local filesystem upload storage is not durable across many hosting restarts.
- Before public launch, verify actual bar-license records through authoritative sources, test access isolation between multiple accounts, exercise backups/restores, and complete manual browser/mobile testing.
