# Applying the LawNexa fixed source package

This archive contains a cleaned top-level source snapshot and excludes local databases, uploaded user files, virtual environments, Git history, local `.env` files, backups, and logs.

## Before replacing source files

- Keep the current project folder as a backup until the revised app passes your local smoke test.
- Keep your existing private `.env` file outside this archive. Do not replace it with `.env.example`; preserve your existing `DATABASE_URL`, signing key, allowed frontend origins, and provider credentials.
- Make a separate backup of the SQLite/PostgreSQL database before starting the revised application. The app runs versioned Alembic migrations on startup.
- Use this archive as the canonical top-level source. Do not mix its `main.py` and models with the old nested `nonpay/`, `regfix/`, or `lawnexa/` snapshots.

## What changes when this version starts

- Alembic revisions `20261029_0001` to `20261029_0003` run before requests are served.
- Existing rows are preserved by additive migrations; legacy advocate listings are created as unverified, and must be checked before being made public.
- No real payment, wallet, escrow, verified legal research, or delivered chat/call infrastructure is activated by this archive.
- No bundled database is installed over your existing database.

## Verification

The bundled source passed 15 Python regression tests in the audit runner, frontend JavaScript regression tests, inline JavaScript syntax checks, and Python syntax compilation. In that isolated runner a temporary shim outside this archive stood in for unavailable `passlib` password-hash functions, so rerun the API suite after installing the exact `requirements.txt` dependencies in your normal development environment. This package does not claim a live deployment has been tested.
