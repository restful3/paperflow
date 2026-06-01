import json

from app.services import audio as a


def test_audio_file_path_from_manifest(tmp_path, monkeypatch):
    paper = tmp_path / "P"; (paper / "audio").mkdir(parents=True)
    (paper / "audio" / "P_ko_audio.abc123def456.mp3").write_bytes(b"x")
    (paper / "audio" / "P_ko_audio.manifest.json").write_text(
        json.dumps({"status": "complete", "audio": {"file": "P_ko_audio.abc123def456.mp3"}}))
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    assert a.audio_file_path("P").name == "P_ko_audio.abc123def456.mp3"   # B1: manifest가 가리키는 버전드 파일
    assert a.manifest_path("P").name.endswith(".manifest.json")


def test_listening_progress_separate_from_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_progress_file", lambda: tmp_path / "listen.json")
    a.save_listening_progress("P", {"chunk_id": 3, "time_sec": 12.0, "percent": 10, "audio_version": "sha:x"})
    got = a.get_listening_progress("P")
    assert got["chunk_id"] == 3 and got["percent"] == 10


from app.services.audio import render_audio_html


def test_render_audio_html_from_manifest():
    manifest = {"chunks": [
        {"id": 0, "kind": "heading", "level": 2, "dom_id": "tts-s-000000", "text": "방법", "paragraph_index": 0},
        {"id": 1, "kind": "text", "dom_id": "tts-s-000001", "text": "첫 문장.", "paragraph_index": 1},
        {"id": 2, "kind": "text", "dom_id": "tts-s-000002", "text": "둘째 문장.", "paragraph_index": 1},
    ]}
    html = render_audio_html(manifest)
    assert '<h2 id="tts-s-000000" data-tts-chunk="0">방법</h2>' in html
    # 같은 문단의 두 문장은 한 <p> 안의 별도 span
    assert html.count("<p>") == 1
    assert '<span id="tts-s-000001" data-tts-chunk="1">첫 문장.</span>' in html
    assert '<span id="tts-s-000002" data-tts-chunk="2">둘째 문장.</span>' in html


def test_render_audio_html_escapes():
    manifest = {"chunks": [{"id": 0, "kind": "text", "dom_id": "tts-s-000000", "text": "a<b>&", "paragraph_index": 0}]}
    assert "a&lt;b&gt;&amp;" in render_audio_html(manifest)


def test_mp3_path_v1_and_v2(tmp_path, monkeypatch):
    paper = tmp_path/"P"; (paper/"audio").mkdir(parents=True)
    (paper/"P_ko_audio.md").write_text("# t\n\n본문.")
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    # v1
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        '{"schema_version":1,"status":"complete","audio":{"file":"P_ko_audio.v1.mp3"}}')
    (paper/"audio"/"P_ko_audio.v1.mp3").write_bytes(b"x")
    assert a.mp3_file_path("P").name == "P_ko_audio.v1.mp3"
    # v2
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"complete","audio":{"hls":{"playlist":"stream.m3u8"},'
        '"mp3":{"file":"P_ko_audio.abc.mp3"}}}')
    assert a.mp3_file_path("P").name == "P_ko_audio.abc.mp3"


def test_hls_paths_resolve(tmp_path, monkeypatch):
    paper = tmp_path/"P"; (paper/"audio"/"P_ko_audio.abc123def456").mkdir(parents=True)
    (paper/"P_ko_audio.md").write_text("# t\n\n본문.")
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"streaming","source":{"sha256":"abc123def456ff"},'
        '"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}}}')
    (paper/"audio"/"P_ko_audio.abc123def456"/"stream.m3u8").write_text("#EXTM3U")
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    assert a.hls_playlist_path("P").name == "stream.m3u8"
    # 실재하는 세그먼트
    (paper/"audio"/"P_ko_audio.abc123def456"/"seg_000000.ts").write_bytes(b"\x47" + b"\x00"*187)
    seg = a.hls_segment_path("P", "seg_000000.ts")
    assert seg.parent.name == "P_ko_audio.abc123def456"
    # 미존재 세그먼트 → None (Task 9 가 404 로 변환)
    assert a.hls_segment_path("P", "seg_000999.ts") is None
    # traversal 방어
    assert a.hls_segment_path("P", "../../etc") is None


def test_reconcile_stale_streaming_to_failed(tmp_path, monkeypatch):
    paper = tmp_path/"P"; (paper/"audio").mkdir(parents=True)
    (paper/"P_ko_audio.md").write_text("# t\n\n본문.")
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"streaming","heartbeat":"2000-01-01T00:00:00+00:00",'
        '"source":{"sha256":"s"},"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}},"chunks":[]}')
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    assert a.reconcile_stale("P") is True                    # 오래된 heartbeat → failed 전이
    import json as _j
    assert _j.loads((paper/"audio"/"P_ko_audio.manifest.json").read_text())["status"] == "failed"
    assert a.reconcile_stale("P") is False                   # 이미 failed → no-op


# ── Task 9: HLS streaming endpoints ───────────────────────────────────────────
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    from app.config import settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(_s, "JWT_SECRET_KEY", "x" * 48)
    monkeypatch.setattr(_s, "LOGIN_ID", "admin")        # .env 가 실자격을 덮으므로 테스트값 고정
    monkeypatch.setattr(_s, "LOGIN_PASSWORD", "admin")
    from app.main import create_app
    return TestClient(create_app())


def test_stream_url_then_playlist_then_seg(tmp_path, monkeypatch):
    paper = tmp_path / "outputs" / "P"
    (paper / "audio" / "P_ko_audio.abc123def456").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    (paper / "audio" / "P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"complete","source":{"path":"P_ko_audio.md","sha256":"abc123def456ff"},'
        '"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}},"chunks":[]}')
    hd = paper / "audio" / "P_ko_audio.abc123def456"
    (hd / "stream.m3u8").write_text("#EXTM3U\n#EXTINF:1.0,\nseg/seg_000000.ts\n#EXT-X-ENDLIST\n")
    (hd / "seg_000000.ts").write_bytes(b"\x47" + b"\x00" * 187)
    c = _client(monkeypatch, tmp_path)
    assert c.post("/api/login", json={"username": "admin", "password": "admin"}).status_code == 200
    su = c.get("/api/papers/P/audio/stream-url")
    assert su.status_code == 200, su.text
    ptoken = su.json()["ptoken"]
    pl = c.get(f"/api/papers/P/audio/stream.m3u8?ptoken={ptoken}")
    assert pl.status_code == 200
    assert "token=" in pl.text                                  # segment URI 에 토큰 주입
    seg_uri = [ln for ln in pl.text.splitlines() if ln.startswith("seg/")][0]
    tok = seg_uri.split("token=")[1]
    sg = c.get(f"/api/papers/P/audio/seg/seg_000000.ts?token={tok}")
    assert sg.status_code == 200
    bad = c.get("/api/papers/P/audio/seg/seg_000000.ts?token=bad")
    assert bad.status_code == 403


def test_stream_url_425_when_no_segments(tmp_path, monkeypatch):
    paper = tmp_path / "outputs" / "P"
    (paper / "audio" / "P_ko_audio.abc123def456").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    (paper / "audio" / "P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"streaming","source":{"path":"P_ko_audio.md","sha256":"abc123def456ff"},'
        '"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}},"chunks":[]}')
    (paper / "audio" / "P_ko_audio.abc123def456" / "stream.m3u8").write_text("#EXTM3U\n")  # 세그먼트 0
    c = _client(monkeypatch, tmp_path)
    c.post("/api/login", json={"username": "admin", "password": "admin"})
    assert c.get("/api/papers/P/audio/stream-url").status_code == 425


def test_audio_delete_endpoint(tmp_path, monkeypatch):
    paper = tmp_path / "outputs" / "P"; (paper / "audio").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    (paper / "audio" / "P_ko_audio.manifest.json").write_text('{"status":"complete","audio":{}}')
    (paper / "audio" / "P_ko_audio.v.mp3").write_bytes(b"\xff\xfb")
    c = _client(monkeypatch, tmp_path)
    c.post("/api/login", json={"username": "admin", "password": "admin"})
    assert c.delete("/api/papers/P/audio").status_code == 200
    assert not (paper / "audio").exists()
    # 미존재 논문 → 404
    assert c.delete("/api/papers/Nope/audio").status_code == 404


def test_audio_file_v2_fallback(tmp_path, monkeypatch):
    paper = tmp_path / "outputs" / "P"
    (paper / "audio").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    (paper / "audio" / "P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"complete","source":{"path":"P","sha256":"abc123def456ff"},'
        '"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":"P_ko_audio.abc.mp3"}},"chunks":[]}')
    (paper / "audio" / "P_ko_audio.abc.mp3").write_bytes(b"\xff\xfb")
    c = _client(monkeypatch, tmp_path)
    c.post("/api/login", json={"username": "admin", "password": "admin"})
    assert c.get("/api/papers/P/audio/file").status_code == 200


def test_redact_filter_masks_token():
    import logging
    from app.main import _TokenRedactFilter
    rec = logging.LogRecord("x", 20, "", 0, 'GET /a?token=SECRET&ptoken=Y', (), None)
    _TokenRedactFilter().filter(rec)
    assert "SECRET" not in rec.getMessage() and "token=REDACTED" in rec.getMessage()


def test_redact_filter_preserves_int_status_code():
    # 회귀: uvicorn.access 레코드는 마지막 %d 에 int 상태코드를 넘긴다.
    # 필터가 모든 arg 를 str() 로 바꾸면 %d 포맷이 TypeError 로 깨진다.
    import logging
    from app.main import _TokenRedactFilter
    rec = logging.LogRecord(
        "uvicorn.access", 20, "", 0,
        '%s - "%s %s HTTP/%s" %d',
        ('1.2.3.4:5', 'GET', '/a?token=SECRET', '1.1', 200),
        None,
    )
    _TokenRedactFilter().filter(rec)
    msg = rec.getMessage()  # %d % "200" 이면 TypeError
    assert "SECRET" not in msg
    assert "token=REDACTED" in msg
    assert msg.endswith(" 200")


def test_reconcile_stale_keeps_fresh_heartbeat(tmp_path, monkeypatch):
    # 회귀: 막 시작한 job(최근 heartbeat)은 streaming 유지 — failed 로 뒤집지 않는다.
    from datetime import datetime, timezone
    paper = tmp_path / "P"; (paper / "audio").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    fresh = datetime.now(timezone.utc).isoformat()
    (paper / "audio" / "P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"streaming","heartbeat":"' + fresh + '",'
        '"source":{"sha256":"s"},"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}},"chunks":[]}')
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    assert a.reconcile_stale("P") is False
    import json as _j
    assert _j.loads((paper / "audio" / "P_ko_audio.manifest.json").read_text())["status"] == "streaming"


def test_reconcile_stale_none_heartbeat_uses_mtime(tmp_path, monkeypatch):
    # heartbeat 부재 + 파일 방금 생성(mtime 최근) → stale 아님(죽이지 않음). Codex 방어 제안.
    paper = tmp_path / "P"; (paper / "audio").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    mp = paper / "audio" / "P_ko_audio.manifest.json"
    mp.write_text(
        '{"schema_version":2,"status":"streaming","heartbeat":null,'
        '"source":{"sha256":"s"},"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}},"chunks":[]}')
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    assert a.reconcile_stale("P") is False                       # 최근 mtime → 유지
    # 오래된 mtime(2000년) → heartbeat 없으니 stale 로 전이
    import os as _os
    old = 946684800  # 2000-01-01
    _os.utime(mp, (old, old))
    assert a.reconcile_stale("P") is True


def test_delete_audio_removes_dir_and_progress(tmp_path, monkeypatch):
    # 생성된 오디오 삭제: audio/ 디렉터리 전체 + 그 논문의 듣기 진행률만 제거(다른 논문은 보존).
    paper = tmp_path / "P"; (paper / "audio" / "P_ko_audio.abc123def456").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    (paper / "audio" / "P_ko_audio.manifest.json").write_text('{"status":"complete"}')
    (paper / "audio" / "P_ko_audio.abc123def456" / "seg_000000.ts").write_bytes(b"x")
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    monkeypatch.setattr(a, "_progress_file", lambda: tmp_path / "listen.json")
    (tmp_path / "listen.json").write_text('{"P":{"time_sec":3},"Other":{"time_sec":1}}')

    assert a.delete_audio("P") is True
    assert not (paper / "audio").exists()                 # 오디오 산출물 전부 제거
    import json as _j
    prog = _j.loads((tmp_path / "listen.json").read_text())
    assert "P" not in prog and "Other" in prog            # 해당 논문 진행률만 제거
    assert a.delete_audio("P") is True                    # idempotent(없어도 ok)


def test_reconcile_stale_partial_segments_to_failed_partial(tmp_path, monkeypatch):
    # M1: a stale streaming job that already produced ≥1 playable segment must transition to
    # 'failed_partial' (prefix stays playable) — NOT 'failed', which gates the audio off entirely
    # (audio_html + frontend audioReady accept streaming/complete/failed_partial only).
    ver = "abcabcabcabc"
    paper = tmp_path / "P"; hd = paper / "audio" / f"P_ko_audio.{ver}"
    hd.mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    (paper / "audio" / "P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"streaming","heartbeat":"2000-01-01T00:00:00+00:00",'
        '"source":{"sha256":"s"},"audio":{"version":"' + ver + '",'
        '"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}},"chunks":[]}')
    # EVENT playlist with one segment, NOT finalized (no ENDLIST) — job died mid-stream.
    (hd / "stream.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-PLAYLIST-TYPE:EVENT\n"
        "#EXT-X-TARGETDURATION:16\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1.0,\nseg/seg_000000.ts\n")
    (hd / "seg_000000.ts").write_bytes(b"\x47" + b"\x00" * 187)
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)

    assert a.reconcile_stale("P") is True
    import json as _j
    man = _j.loads((paper / "audio" / "P_ko_audio.manifest.json").read_text())
    assert man["status"] == "failed_partial"               # not "failed" — prefix stays playable
    # playlist finalized so the prefix plays as VOD (player won't hang at live edge waiting for more)
    assert "#EXT-X-ENDLIST" in (hd / "stream.m3u8").read_text()
    assert a.reconcile_stale("P") is False                 # already terminal → no-op


def test_tts_json_normalizes_transport_error(monkeypatch):
    # MCP 는 에이전트 표면 — tts 다운이면 raw transport 예외가 아니라 명확한 ValueError 로.
    import asyncio, httpx, pytest
    from app.routers import mcp_router as mr

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def request(self, *a, **k): raise httpx.ConnectError("refused")
    monkeypatch.setattr(mr.httpx, "AsyncClient", lambda *a, **k: FakeClient())
    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(mr._tts_json("GET", "/jobs", timeout=5))


def test_tts_json_normalizes_http_500(monkeypatch):
    import asyncio, httpx, pytest
    from app.routers import mcp_router as mr

    class Resp:
        status_code = 500
        text = "boom"
        def raise_for_status(self):
            raise httpx.HTTPStatusError("e", request=httpx.Request("GET", "http://t/x"), response=self)
        def json(self): return {}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def request(self, *a, **k): return Resp()
    monkeypatch.setattr(mr.httpx, "AsyncClient", lambda *a, **k: FakeClient())
    with pytest.raises(ValueError, match="500"):
        asyncio.run(mr._tts_json("POST", "/sweep", timeout=5))


def test_resolve_for_audio_ok(tmp_path, monkeypatch):
    from app.config import settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", str(tmp_path))
    p = tmp_path / "outputs" / "P"; p.mkdir(parents=True)
    (p / "P_ko_audio.md").write_text("# t\n\n본문.")
    d, src = a.resolve_for_audio("P")
    assert d.name == "P" and src.name == "P_ko_audio.md"


def test_resolve_for_audio_missing_md_raises(tmp_path, monkeypatch):
    import pytest
    from app.config import settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", str(tmp_path))
    (tmp_path / "outputs" / "P").mkdir(parents=True)
    with pytest.raises(ValueError):
        a.resolve_for_audio("P")                       # _ko_audio.md 없음


def test_resolve_for_audio_rejects_archived(tmp_path, monkeypatch):
    import pytest
    from app.config import settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", str(tmp_path))
    p = tmp_path / "archives" / "P"; p.mkdir(parents=True)
    (p / "P_ko_audio.md").write_text("# t\n\n본문.")
    with pytest.raises(ValueError):
        a.resolve_for_audio("P")                       # archives → outputs 전용이라 거부


def test_resolve_for_audio_unknown_raises(tmp_path, monkeypatch):
    import pytest
    from app.config import settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", str(tmp_path))
    (tmp_path / "outputs").mkdir(parents=True)
    with pytest.raises(ValueError):
        a.resolve_for_audio("Nope")


def test_delete_blocked_during_active_synthesis(tmp_path, monkeypatch):
    # 가드: 합성 진행 중(status=streaming + 최근 heartbeat)에는 DELETE /audio 가 409 로 거부 →
    # 재생성/삭제가 실행 중 워커의 디렉터리를 지워 자폭하는 것 방지.
    from datetime import datetime, timezone
    paper = tmp_path / "outputs" / "P"; (paper / "audio" / "P_ko_audio.abc123def456").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    fresh = datetime.now(timezone.utc).isoformat()
    (paper / "audio" / "P_ko_audio.manifest.json").write_text(
        '{"status":"streaming","heartbeat":"' + fresh + '","source":{"sha256":"s"},"audio":{}}')
    c = _client(monkeypatch, tmp_path)
    c.post("/api/login", json={"username": "admin", "password": "admin"})
    r = c.delete("/api/papers/P/audio")
    assert r.status_code == 409
    assert (paper / "audio").exists()                  # 활성 → 삭제 안 됨


def test_delete_allowed_when_synthesis_stale(tmp_path, monkeypatch):
    # 오래된 heartbeat(죽은 job) → 활성 아님 → 삭제 허용.
    paper = tmp_path / "outputs" / "P"; (paper / "audio").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    (paper / "audio" / "P_ko_audio.manifest.json").write_text(
        '{"status":"streaming","heartbeat":"2000-01-01T00:00:00+00:00","source":{"sha256":"s"},"audio":{}}')
    c = _client(monkeypatch, tmp_path)
    c.post("/api/login", json={"username": "admin", "password": "admin"})
    assert c.delete("/api/papers/P/audio").status_code == 200
    assert not (paper / "audio").exists()


def test_stream_url_425_while_streaming_even_with_segments(tmp_path, monkeypatch):
    # 생성-먼저: AUDIO_REQUIRE_COMPLETE=True 면 status=streaming 은 세그먼트가 있어도 425(아직 mount 안 함).
    # 완성(complete) 후에만 200 → 끊김 없는 VOD 재생.
    paper = tmp_path / "outputs" / "P"
    (paper / "audio" / "P_ko_audio.abc123def456").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    (paper / "audio" / "P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"streaming","source":{"path":"P_ko_audio.md","sha256":"abc123def456ff"},'
        '"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}},"chunks":[]}')
    hd = paper / "audio" / "P_ko_audio.abc123def456"
    (hd / "stream.m3u8").write_text("#EXTM3U\n#EXTINF:1.0,\nseg/seg_000000.ts\n")   # 세그먼트 1개 있음
    (hd / "seg_000000.ts").write_bytes(b"\x47" + b"\x00" * 187)
    c = _client(monkeypatch, tmp_path)
    c.post("/api/login", json={"username": "admin", "password": "admin"})
    assert c.get("/api/papers/P/audio/stream-url").status_code == 425   # 진행 중 → 아직 425


def test_hls_dir_uses_audio_version_not_source_sha(tmp_path, monkeypatch):
    # Codex Finding 2: dir/token 은 audio.version 으로 해석(source sha 가 달라도 version 우선).
    paper = tmp_path / "P"; ver = "0123456789ab"
    (paper / "audio" / f"P_ko_audio.{ver}").mkdir(parents=True)
    (paper / "P_ko_audio.md").write_text("# t\n\n본문.")
    (paper / "audio" / "P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"streaming","source":{"path":"P_ko_audio.md","sha256":"ffffffffffff99"},'
        '"audio":{"version":"' + ver + '","hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}}}')
    (paper / "audio" / f"P_ko_audio.{ver}" / "stream.m3u8").write_text("#EXTM3U")
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    assert a.hls_playlist_path("P").parent.name == f"P_ko_audio.{ver}"   # source sha 아닌 version
    assert a.source_id_and_sha("P") == ("P_ko_audio.md", ver)            # 토큰도 version 바인딩
