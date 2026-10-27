# LawNexa updated source package

This package is based on the uploaded `zip 2.zip`. Existing source files are complete replacement files, not snippets.

## Files
- `index.html` — public app UI updates: virtual consultation fee/availability, user-triggered nearby GPS permission, FIR language selector, Urdu speech synthesis, chat quotation display, sponsored post badge and Legal Insights empty state.
- `main.py` — API additions/updates for lawyer fee/virtual settings, profile sync, nearby sorting, FIR language prompt and file signature checks, lawyer-only document generator, admin portal serving, admin overview/user/invite endpoints, Q&A, case tracker, Bar campaign feed, corporate subscriptions/retainer assignment, wallet/escrow records and analytics.
- `models.py` — existing models plus consultation, featured listing, wallet/escrow, Q&A, case tracker, corporate subscription/request, Bar campaign, invitation and audit models.
- `admin.html` — separate private management UI at `/admin`; not linked from public navigation. Server endpoints still enforce admin role.
- `database.py`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `geo_engine.py`, and `test_main.py` are included. `geo_engine.py`, `requirements.txt`, `main.py`, `models.py`, `index.html`, and tests have been updated in this revision.

## Before deployment
1. Back up your production database.
2. Set `ENVIRONMENT=production`, a random `SECRET_KEY` of at least 32 characters, explicit `ALLOWED_ORIGINS`, and `ADMIN_EMAIL` or `ADMIN_PHONE` plus a strong `ADMIN_PASSWORD` in Render/server environment settings. Never commit these secrets.
3. Deploy to a staging environment first. `Base.metadata.create_all` creates new tables; `upgrade_schema()` adds listed columns to existing tables. For production, use a formal migration (Alembic) and verify it against a copy of the production database before deployment.
4. Open `/admin` and sign in with the environment-provisioned admin account. Admin APIs reject non-admin roles.
5. Payment gateway and cloud storage work are outside the scope of this revision; do not treat any existing payment or local-upload scaffolding as production-ready.
7. Configure an email/SMS provider before using automated invitation delivery. Admin invite endpoint currently returns a time-limited token for secure manual sharing.

## Verification status
- Python syntax compilation: passed.
- Frontend JavaScript syntax check: passed.
- Automated pytest suite could not run in this execution environment because `python-jose` is not installed and network access was unavailable to install dependencies. Run `pip install -r requirements.txt` and `pytest -q` in your development environment before production deployment.
- Real Gemini analysis requires `GEMINI_API_KEY`. Live payment gateway transactions, cloud object storage, Redis caching, OTP/SMS delivery, WebRTC mediation, and end-to-end production testing are not claimed as complete by this package.


## Update scope (2026-10)
This package focuses on the non-payment, non-cloud requirements: registration address/location fields, optional browser GPS capture, normalized Pakistani phone validation, real database-backed lawyer locations, Haversine clamping, document-type-specific fields, FIR file-type checks, legal Q&A/case tracking/bar campaigns/corporate subscription scaffolding, and an ODR dispute-case draft workflow.

**Not implemented in this package:** real payment gateway processing, S3/DigitalOcean Spaces, Redis caching, SMS/OTP verification, WebRTC rooms, or a legally binding e-signature workflow. ODR settlement output is explicitly a draft and must not be treated as legally binding. Production deployment requires migrations/backups, secrets, and provider/security review.

Existing databases receive additive columns on startup. Back up the database before first run; `create_all()` does not alter existing columns, and this project does not replace a full migration tool such as Alembic.
