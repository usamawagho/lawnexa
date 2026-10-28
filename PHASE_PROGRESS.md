# LawNexa phase progress

This document tracks the **top-level project only**. The `nonpay/`, `regfix/`, and nested legacy copies are not the release source.

## Phase 0 — Source-of-truth and test alignment

**Status: implemented in this working patch.**

- Selected top-level `main.py`, `models.py`, `database.py`, `index.html`, and `admin.html` as the canonical source for this release package.
- Reworked `test_main.py` to test the real `/api/*` routes rather than stale `/api/v1/*` routes from older snapshots.
- Added `/admin`, real admin API routes, environment-driven first-admin provisioning, explicit CORS allowlisting for deployed environments, and token expiry configuration.
- Added clean source-control/container ignore rules and removed local databases, virtual environments, uploads, Git history, archives, and secrets from the release package.

## Phase 1 — Database compatibility and migrations

**Status: implemented and tested.**

- Added versioned Alembic revisions to add legacy missing columns and appointment fields, backfill legacy advocate profiles as **unverified**, and preserve existing user/appointment data.
- Startup applies migrations before serving requests; repeated migration execution is idempotent.
- Added a regression test that starts from an intentionally old SQLite schema, preserves existing rows, checks advocate privacy defaults, and verifies the schema revision.
- Default local SQLite path is resolved relative to the project rather than whichever terminal directory happens to be active; `DATABASE_URL` still controls deployments.

## Phase 2 — Frontend safety and honest product state

**Status: implemented for the reviewed root frontend; broader manual browser/security testing remains required.**

- Escaped user-controlled text before HTML rendering and reject unsafe media URLs. Added local state parsing and upload type/size guards.
- Moved browser auth token storage to `sessionStorage` with a one-time migration path from existing local storage.
- Removed fake lawyer/case-law data, mock legal citations, fabricated escrow success, and fake emergency-dispatch claims.
- Clearly label chat/feed as local previews until server-backed implementations exist; avoid claiming end-to-end encryption or delivery.
- Legal document generation is described as a draft and stored using an authenticated API endpoint; it is not presented as an official court/government document. Server-side HTML sanitization strips active tags, event handlers, links/media, and unsafe CSS before persistence.
- Added dependency-free XSS/source regression tests.

## Phase 3 — Advocate registration and verification

**Status: implemented and covered by integration tests.**

- Advocate registration creates the account and private/public advocate profile atomically.
- Public directory only shows active, approved advocates whose license is verified by an admin.
- Legacy advocate profiles are backfilled as unverified, never automatically trusted.
- Admin verification requires an approved account and a non-empty Bar Council number. The admin panel calls the current API contract.
- Changes to identity/license fields revoke public verification until an admin reviews them again.
- Profile partial updates do not erase specializations when the field is omitted; private residential address is not copied into the public chamber address.

## Phase 4 — Appointment workflow

**Status: implemented and covered by integration tests; external payment is intentionally disabled.**

- Booking requires an authenticated client, a verified/approved advocate, a future local Pakistan date/time, and supported meeting type/mode.
- The server determines the consultation fee; the browser cannot choose a fake fee.
- Duplicate active bookings for the same advocate/date/time are rejected; booking status transitions and actor permissions are enforced.
- Frontend loads directory, profile, and appointment state from the current backend rather than relying on fake seeded lawyer/booking data.
- Wallet/payment/escrow state is clearly disabled. No funds are claimed to be held, transferred, or refunded.

## Current verification

- `python -m py_compile main.py models.py database.py auth.py schemas.py admin_bootstrap.py html_sanitizer.py test_main.py test_schema_migrations.py test_html_sanitizer.py`: passed.
- `pytest -q test_main.py test_schema_migrations.py test_html_sanitizer.py`: **15 passed** (12 API integration, 1 migration, 2 sanitizer tests).
- Current API integration suite: **12 passed** with a temporary test-only dependency shim for password hash/verify in this constrained audit environment. The shim is outside the project and is **not** part of the release ZIP; password hashing itself must be checked again using the actual installed dependencies in the user's development environment.
- `node --check test_frontend_security.js` and `node test_frontend_security.js`: passed, including a malicious legal-document field regression case.
- Inline JavaScript syntax checks for both `index.html` and `admin.html`: passed.
- Full browser-based test against the live Render/Vercel deployment has **not** been run here; deploy configuration, real email/payment integrations, and multi-browser/manual smoke testing remain release gates.

## Phase 5 — Safepay sandbox payments (implementation in progress)

- Added additive Alembic migration `20261029_0004` for payment records and append-only ledger events; it does not alter existing appointment/user rows.
- Added server-priced appointment checkout, PKR minor-unit amounts, per-request idempotency, provider tracker creation, and a hosted checkout URL. Checkout creation is disabled until sandbox credentials are configured.
- Added webhook HMAC verification against the exact raw request body, provider-event deduplication, amount/currency checks, and server-only payment status updates. Browser redirects do not confirm payment. Confirm the exact signature header/algorithm against the merchant's current Safepay webhook configuration before deploying.
- Added admin reconciliation endpoint and idempotent refund-request ledger workflow. A refund is **not** marked complete unless a verified provider event confirms it. Safepay's published one-time tracker reference did not provide a definitive universal refund endpoint, so automatic provider-side refund initiation remains gated pending confirmation from Safepay; do not claim this part is production-ready yet.
- Automated tests cover checkout idempotency, webhook signature rejection/acceptance, successful webhook reconciliation, duplicate event delivery, and additive migration. Tests in this audit environment use temporary test-only auth/password shims because `python-jose` and `passlib` are not installed here; those shims are not included in the project.

## Next phases

- **Phase 6 — Legal AI and research:** connect a real retrieval/citation source, jurisdiction/date aware workflows, and adversarial citation tests; no invented legal authority.
- **Phase 6 — Legal AI and research:** connect a real retrieval/citation source, jurisdiction/date aware workflows, and adversarial citation tests; no invented legal authority.
- **Phase 7 — Production readiness:** run the full suite using the actual production dependency set, secure upload storage, CI/security scans, deployment smoke tests, logs/alerting, and a backup/restore exercise.
