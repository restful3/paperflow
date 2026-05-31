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
