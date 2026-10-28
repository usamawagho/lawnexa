# LawNexa Phase 5 — Safepay Sandbox Payments

## Implemented in this source package

- Added `Payment` and `PaymentLedgerEntry` models.
- Added additive Alembic migration `20261029_0004_payment_ledger`; it does not drop or rewrite existing application rows.
- Added authenticated checkout creation for confirmed appointments. Price comes from the server-side appointment fee; PKR is represented in minor units (paisa).
- Added idempotency-key enforcement for checkout creation and refund requests.
- Added Safepay sandbox tracker creation and hosted checkout URL generation.
- Added a webhook endpoint that verifies an HMAC SHA-256 signature over the exact raw body, deduplicates events, checks amount/currency, and only updates payment state server-side.
- Added payment-status and admin reconciliation endpoints.
- Added admin refund-request ledger workflow. It does not claim funds are refunded until a signed provider event confirms it.
- Kept the frontend wallet/escrow disabled pending provider-account validation and end-to-end sandbox QA.

## Verification

- Python compilation: passed.
- `pytest` with temporary, external test-only `python-jose`/`passlib` shims: **19 passed**. The shims were stored under `/tmp/lawnexa-test-shims` and are not included in this package. They are not production authentication implementations.
- Frontend security regression tests: passed.
- Migration test verifies existing legacy rows survive and the new payment/ledger tables are added.
- Provider HTTP calls are mocked in tests; no real Safepay account or payment was used.

## Important release gates — not yet production-ready

1. Safepay sandbox credentials must be configured privately on the backend.
2. Confirm the exact webhook signature header and signing algorithm in the current Safepay merchant dashboard/documentation before relying on webhook verification in deployment. This package uses `X-SFPY-SIGNATURE` with hex HMAC-SHA256 over the raw body; the real merchant account's contract must match.
3. Safepay's published one-time tracker reference available during this implementation did not establish a definitive universal refund endpoint for this flow. Refund requests are audited and remain pending until provider confirmation; automatic provider-side refund submission must not be advertised as implemented until Safepay confirms the supported endpoint and payload.
4. Run the sandbox flow against the actual merchant account, including success, failure, duplicate webhook, partial/full refund, reconciliation and recovery tests.
5. Do not set `SAFEPAY_ENVIRONMENT=production`, enable wallet/escrow UI, or claim escrow until all gates pass.
