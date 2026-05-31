import hmac, hashlib, base64, time


def _sig(secret, kind, source_id, sha12, exp):
    msg = f"{kind}|{source_id}|{sha12}|{exp}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).digest()


def mint(secret, kind, source_id, sha12, ttl):
    exp = int(time.time()) + int(ttl)
    raw = str(exp).encode() + b"." + _sig(secret, kind, source_id, sha12, exp)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def verify(secret, token, kind, source_id, sha12, now):
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad)
        exp_b, sig = raw.split(b".", 1)
        exp = int(exp_b)
    except Exception:
        return False, "malformed"
    if now > exp:
        return False, "expired"
    want = _sig(secret, kind, source_id, sha12, exp)
    if not hmac.compare_digest(sig, want):
        return False, "bad_sig"
    return True, "ok"
