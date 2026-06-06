"""Tests for _ko_audio_brief.md as a first-class viewable format.

Regression guard: a top-level `<name>_ko_audio_brief.md` must be detected as its
own format — NOT as the English original (get_md_en_path) and NOT as the full
audio (md_ko_audio) — otherwise the viewer would mis-serve it or save_markdown
could overwrite it.
"""
import pytest

from app import config as _cfg
from app.services import papers, chat


@pytest.fixture(autouse=True)
def _rebind_settings(tmp_workspace, monkeypatch):
    # papers.py AND chat.py both do `from ..config import settings` (module-level
    # binding), so rebind BOTH or chat.get_or_create_chunks() won't see tmp_workspace.
    monkeypatch.setattr(papers, "settings", _cfg.settings)
    monkeypatch.setattr(chat, "settings", _cfg.settings)


def _make_paper(ws, name, files):
    d = ws / "outputs" / name
    d.mkdir(parents=True, exist_ok=True)
    for fn, content in files.items():
        (d / fn).write_text(content, encoding="utf-8")
    return d


def test_brief_detected_as_its_own_format(tmp_workspace):
    _make_paper(tmp_workspace, "Foo", {
        "Foo.md": "# en",
        "Foo_ko.md": "# ko",
        "Foo_ko_audio.md": "# audio",
        "Foo_ko_audio_brief.md": "# brief",
    })
    info = papers.get_paper_info("Foo")
    f = info["formats"]
    assert f["md_ko_audio_brief"] is True
    assert f["md_ko_audio"] is True   # full audio still detected
    assert f["md_en"] is True         # real English still detected
    assert f["md_ko"] is True


def test_get_md_ko_audio_brief_path_returns_brief(tmp_workspace):
    _make_paper(tmp_workspace, "Foo", {
        "Foo_ko_audio.md": "# audio",
        "Foo_ko_audio_brief.md": "# brief",
    })
    p = papers.get_md_ko_audio_brief_path("Foo")
    assert p is not None and p.name == "Foo_ko_audio_brief.md"


def test_get_md_en_path_excludes_brief_when_only_brief_present(tmp_workspace):
    # The critical regression: brief alone must NOT be served as English.
    _make_paper(tmp_workspace, "Bar", {
        "Bar_ko.md": "# ko",
        "Bar_ko_audio.md": "# audio",
        "Bar_ko_audio_brief.md": "# brief",
    })
    assert papers.get_md_en_path("Bar") is None


def test_save_markdown_en_does_not_target_brief(tmp_workspace):
    _make_paper(tmp_workspace, "Baz", {
        "Baz_ko_audio_brief.md": "# brief",
    })
    ok, msg = papers.save_markdown("Baz", "en", "# overwrite")
    assert ok is False  # no real English file exists; brief must not be picked
    assert (tmp_workspace / "outputs" / "Baz" / "Baz_ko_audio_brief.md").read_text() == "# brief"


def test_rag_skips_brief(tmp_workspace):
    d = _make_paper(tmp_workspace, "Qux", {
        "Qux_ko.md": "# korean body",
        "Qux_ko_audio_brief.md": "# brief narration",
    })
    # get_or_create_chunks must pick the Korean body, never the brief.
    chunks = chat.get_or_create_chunks("Qux")
    joined = " ".join(c.text if hasattr(c, "text") else (c.get("text", "") if isinstance(c, dict) else str(c)) for c in chunks)
    assert "brief narration" not in joined


def test_resolve_result_block_detects_brief(tmp_workspace):
    # The SECOND detection block lives in _resolve_result() (reached via
    # find_processed_paper). Guard it too — not just _paper_info().
    d = _make_paper(tmp_workspace, "Rr", {
        "Rr.md": "# en",
        "Rr_ko_audio_brief.md": "# brief",
    })
    res = papers._resolve_result(d, "outputs")
    assert res["formats"]["md_ko_audio_brief"] is True
    assert res["formats"]["md_en"] is True
    # brief-only (no real English): _resolve_result must NOT flag md_en (catch-all leak)
    d2 = _make_paper(tmp_workspace, "RrOnly", {"RrOnly_ko_audio_brief.md": "# brief"})
    res2 = papers._resolve_result(d2, "outputs")
    assert res2["formats"]["md_ko_audio_brief"] is True
    assert res2["formats"].get("md_en", False) is False


def test_get_md_ko_path_excludes_brief(tmp_workspace):
    _make_paper(tmp_workspace, "Kp", {
        "Kp_ko.md": "# ko",
        "Kp_ko_audio_brief.md": "# brief",
    })
    p = papers.get_md_ko_path("Kp")
    assert p is not None and p.name == "Kp_ko.md"


def test_mcp_zip_excludes_brief_when_translation_off(tmp_workspace):
    # mcp_zip gates _ko*.md by include_translation; brief must be gated identically,
    # else _ko_audio_brief.md leaks into the translation-excluded zip as a plain .md.
    import zipfile, io
    from app.services import mcp_zip
    d = _make_paper(tmp_workspace, "Zz", {
        "Zz.md": "# en",
        "Zz_ko_audio_brief.md": "# brief",
    })
    chunks = b"".join(mcp_zip.build_zip_stream(
        d, include_pdf=False, include_translation=False, job_meta={"job_id": "t"}))
    names = zipfile.ZipFile(io.BytesIO(chunks)).namelist()
    assert "Zz_ko_audio_brief.md" not in names
    assert "Zz.md" in names
