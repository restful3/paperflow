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
