import base64
import time

from app.services.tts_token import mint, verify

# Drift guard: viewer/app/services/tts_token.py must stay byte-identical in behavior
# to tts_service/app/segtoken.py (separate containers, no shared import).

SECRET = "x" * 48


def _tamper(token):
    """서명 마지막 바이트를 결정적으로 뒤집는다(trailing base64 비트 변조의 flakiness 회피)."""
    raw = bytearray(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    raw[-1] ^= 0xFF
    return base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")


def test_roundtrip_playlist_and_segment():
    t = mint(SECRET, kind="playlist", source_id="p.pdf", sha12="abc123def456", ttl=60)
    ok, reason = verify(SECRET, t, kind="playlist", source_id="p.pdf", sha12="abc123def456", now=time.time())
    assert ok, reason
    ts = mint(SECRET, kind="segment", source_id="p.pdf", sha12="abc123def456", ttl=60)
    ok2, _ = verify(SECRET, ts, kind="segment", source_id="p.pdf", sha12="abc123def456", now=time.time())
    assert ok2


def test_expired_rejected():
    t = mint(SECRET, kind="segment", source_id="p", sha12="s", ttl=10)
    ok, reason = verify(SECRET, t, kind="segment", source_id="p", sha12="s", now=time.time() + 11)
    assert not ok and reason == "expired"


def test_wrong_kind_or_sha_rejected():
    t = mint(SECRET, kind="playlist", source_id="p", sha12="s1", ttl=60)
    assert not verify(SECRET, t, kind="segment", source_id="p", sha12="s1", now=time.time())[0]
    assert not verify(SECRET, t, kind="playlist", source_id="p", sha12="s2", now=time.time())[0]


def test_tamper_rejected():
    t = mint(SECRET, kind="segment", source_id="p", sha12="s", ttl=60)
    bad = _tamper(t)
    assert not verify(SECRET, bad, kind="segment", source_id="p", sha12="s", now=time.time())[0]
