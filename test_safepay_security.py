import hashlib
import hmac

from safepay_security import verify_webhook_signature


def test_safepay_webhook_signature_accepts_exact_raw_body():
    body = b'{"event":"payment.succeeded","tracker":"track_test"}'
    secret = "sandbox-webhook-secret-for-tests"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, signature, secret)
    assert verify_webhook_signature(body, "sha256=" + signature, secret)


def test_safepay_webhook_signature_rejects_modified_body_and_missing_secret():
    body = b'{"event":"payment.succeeded"}'
    secret = "sandbox-webhook-secret-for-tests"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert not verify_webhook_signature(body + b" ", signature, secret)
    assert not verify_webhook_signature(body, signature, "")
    assert not verify_webhook_signature(body, None, secret)
