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
