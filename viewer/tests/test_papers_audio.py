"""Tests for _ko_audio.md as a first-class viewable format (paper-audio-korean).

Regression guard for the misclassification bug: a top-level `<name>_ko_audio.md`
must be detected as its own format, NOT as the English original — otherwise the
viewer would serve it as English and save_markdown(..., "en") could overwrite it.
"""
import pytest

from app import config as _cfg
from app.services import papers


@pytest.fixture(autouse=True)
def _rebind_settings(tmp_workspace, monkeypatch):
    # papers.py does `from ..config import settings` (module-level binding), so the
    # conftest's `_cfg.settings = Settings()` reassignment doesn't reach it. Rebind here
    # so dir resolution targets the tmp workspace.
    monkeypatch.setattr(papers, "settings", _cfg.settings)


def _make_paper(ws, name, files):
    d = ws / "outputs" / name
    d.mkdir(parents=True, exist_ok=True)
    for fn, content in files.items():
        (d / fn).write_text(content, encoding="utf-8")
    return d


def test_audio_detected_as_ko_audio_not_en(tmp_workspace):
    _make_paper(tmp_workspace, "Foo", {
        "Foo.md": "# en",
        "Foo_ko.md": "# ko",
        "Foo_ko_audio.md": "# audio",
    })
    info = papers.get_paper_info("Foo")
    assert info["formats"]["md_ko_audio"] is True
    # the real English original is still detected independently
    assert info["formats"]["md_en"] is True
    assert info["formats"]["md_ko"] is True


def test_get_md_ko_audio_path_returns_audio_file(tmp_workspace):
    _make_paper(tmp_workspace, "Foo", {
        "Foo_ko.md": "# ko",
        "Foo_ko_audio.md": "# audio",
    })
    p = papers.get_md_ko_audio_path("Foo")
    assert p is not None
    assert p.name == "Foo_ko_audio.md"


def test_get_md_en_path_excludes_audio_when_real_en_present(tmp_workspace):
    _make_paper(tmp_workspace, "Bar", {
        "Bar.md": "# en",
        "Bar_ko_audio.md": "# audio",
    })
    p = papers.get_md_en_path("Bar")
    assert p is not None
    assert p.name == "Bar.md"


def test_get_md_en_path_audio_only_returns_none(tmp_workspace):
    # No real English original — only Korean + audio. Audio must NOT be returned as English.
    _make_paper(tmp_workspace, "Baz", {
        "Baz_ko.md": "# ko",
        "Baz_ko_audio.md": "# audio",
    })
    p = papers.get_md_en_path("Baz")
    assert p is None


def test_save_markdown_en_does_not_target_audio(tmp_workspace):
    # No real English file present; saving "en" must NOT overwrite the audio file.
    _make_paper(tmp_workspace, "Qux", {
        "Qux_ko.md": "# ko",
        "Qux_ko_audio.md": "ORIGINAL AUDIO",
    })
    ok, _msg = papers.save_markdown("Qux", "en", "NEW CONTENT")
    assert ok is False
    audio = tmp_workspace / "outputs" / "Qux" / "Qux_ko_audio.md"
    assert audio.read_text(encoding="utf-8") == "ORIGINAL AUDIO"


# ── audio_mp3 flag: distinguishes "낭독 텍스트만" vs "재생 가능한 mp3 합성됨" ──
# Truth source = audio/<base>_ko_audio.manifest.json with status "complete"
# (see services/audio.py). Drives the list-view speaker emerald ring.

def _add_audio_manifest(paper_dir, base, payload):
    a = paper_dir / "audio"
    a.mkdir(parents=True, exist_ok=True)
    (a / f"{base}_ko_audio.manifest.json").write_text(payload, encoding="utf-8")


def test_audio_mp3_true_when_manifest_complete(tmp_workspace):
    d = _make_paper(tmp_workspace, "Mp3Done", {
        "Mp3Done_ko.md": "# ko",
        "Mp3Done_ko_audio.md": "# audio",
    })
    _add_audio_manifest(d, "Mp3Done",
                        '{"status":"complete","audio":{"file":"Mp3Done_ko_audio.v1.mp3"}}')
    info = papers.get_paper_info("Mp3Done")
    assert info["formats"]["md_ko_audio"] is True
    assert info["formats"]["audio_mp3"] is True


def test_audio_mp3_false_without_manifest(tmp_workspace):
    # 낭독 텍스트는 있으나 mp3 미합성 → 스피커는 켜지되 링은 없어야 한다.
    _make_paper(tmp_workspace, "NoMp3", {
        "NoMp3_ko.md": "# ko",
        "NoMp3_ko_audio.md": "# audio",
    })
    info = papers.get_paper_info("NoMp3")
    assert info["formats"]["md_ko_audio"] is True
    assert info["formats"]["audio_mp3"] is False


def test_audio_mp3_false_when_manifest_incomplete(tmp_workspace):
    # status가 complete가 아니면(streaming/failed 등) 재생 불가 → False.
    d = _make_paper(tmp_workspace, "Streaming", {
        "Streaming_ko_audio.md": "# audio",
    })
    _add_audio_manifest(d, "Streaming", '{"status":"streaming","audio":{}}')
    info = papers.get_paper_info("Streaming")
    assert info["formats"]["audio_mp3"] is False
