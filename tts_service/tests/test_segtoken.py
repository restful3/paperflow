import time
from app.segtoken import mint, verify

SECRET = "x" * 48

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
    bad = t[:-2] + ("aa" if not t.endswith("aa") else "bb")
    assert not verify(SECRET, bad, kind="segment", source_id="p", sha12="s", now=time.time())[0]
