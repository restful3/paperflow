"""Cache behavior for list_papers / _paper_info fingerprint."""
import json
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _bind_settings(tmp_workspace):
    # papers.settings is bound at import time; tmp_workspace rebuilds
    # config.settings, so rebind the module's reference (same pattern as
    # test_books_api.py) and isolate the per-process cache.
    from app.services import papers
    from app import config as _cfg
    papers.settings = _cfg.settings
    papers._PAPER_INFO_CACHE.clear()
    yield


def _make_paper(ws: Path, name: str, *, title: str) -> Path:
    d = ws / "outputs" / name
    d.mkdir(parents=True)
    (d / "x.md").write_text("# en", encoding="utf-8")
    (d / "x_ko.md").write_text("# ko", encoding="utf-8")
    (d / "paper_meta.json").write_text(
        json.dumps({"title": title, "tags": []}), encoding="utf-8"
    )
    return d


def _write_audio_manifest(d: Path, status: str) -> Path:
    ad = d / "audio"
    ad.mkdir(exist_ok=True)
    mf = ad / "x_ko_audio.manifest.json"
    mf.write_text(json.dumps({"status": status}), encoding="utf-8")
    return mf


def test_fingerprint_changes_when_meta_rewritten(tmp_workspace):
    from app.services import papers
    d = _make_paper(tmp_workspace, "P1", title="Old")
    fp1 = papers._paper_info_fingerprint(d)
    time.sleep(0.01)
    (d / "paper_meta.json").write_text(
        json.dumps({"title": "New", "tags": []}), encoding="utf-8"
    )
    assert papers._paper_info_fingerprint(d) != fp1


def test_fingerprint_changes_on_audio_manifest_inplace_rewrite(tmp_workspace):
    from app.services import papers
    d = _make_paper(tmp_workspace, "P1", title="Old")
    (d / "x_ko_audio.md").write_text("narration", encoding="utf-8")
    _write_audio_manifest(d, "processing")
    fp1 = papers._paper_info_fingerprint(d)
    time.sleep(0.01)
    _write_audio_manifest(d, "complete")  # same filename, in-place rewrite
    assert papers._paper_info_fingerprint(d) != fp1


def test_list_papers_serves_fresh_after_meta_edit(tmp_workspace):
    from app.services import papers
    papers._PAPER_INFO_CACHE.clear()
    d = _make_paper(tmp_workspace, "P1", title="Old")
    assert papers.list_papers("unread")[0]["title"] == "Old"
    time.sleep(0.01)
    (d / "paper_meta.json").write_text(
        json.dumps({"title": "New", "tags": []}), encoding="utf-8"
    )
    assert papers.list_papers("unread")[0]["title"] == "New"


def test_list_papers_audio_flag_fresh_after_manifest_complete(tmp_workspace):
    from app.services import papers
    papers._PAPER_INFO_CACHE.clear()
    d = _make_paper(tmp_workspace, "P1", title="A")
    (d / "x_ko_audio.md").write_text("narration", encoding="utf-8")
    _write_audio_manifest(d, "processing")
    assert papers.list_papers("unread")[0]["formats"]["audio_mp3"] is False
    time.sleep(0.01)
    _write_audio_manifest(d, "complete")
    assert papers.list_papers("unread")[0]["formats"]["audio_mp3"] is True


def test_fingerprint_changes_on_same_size_meta_rewrite(tmp_workspace):
    # Round-3 #2: a same-size in-place paper_meta.json rewrite (e.g. a tag
    # swap that keeps byte length) must still change the fingerprint. Two
    # equal-length tag values -> identical file size; a content hash catches it.
    from app.services import papers
    d = _make_paper(tmp_workspace, "P1", title="A")
    mp = d / "paper_meta.json"
    mp.write_text(json.dumps({"title": "A", "tags": ["aaaa"]}), encoding="utf-8")
    fp1 = papers._paper_info_fingerprint(d)
    mp.write_text(json.dumps({"title": "A", "tags": ["bbbb"]}), encoding="utf-8")
    assert papers._paper_info_fingerprint(d) != fp1


def test_fingerprint_changes_on_same_size_manifest_rewrite(tmp_workspace):
    # Round-2 #3: a same-size in-place status flip must still change the
    # fingerprint. "done" and "fail" are both 4 chars -> same file size; a
    # (mtime,size)-only key could miss it on a coarse FS, a content hash won't.
    from app.services import papers
    d = _make_paper(tmp_workspace, "P1", title="A")
    mf = d / "audio" / "x_ko_audio.manifest.json"
    mf.parent.mkdir(exist_ok=True)
    mf.write_text('{"status":"aaaaaaaa"}', encoding="utf-8")
    fp1 = papers._paper_info_fingerprint(d)
    mf.write_text('{"status":"bbbbbbbb"}', encoding="utf-8")  # same length
    assert papers._paper_info_fingerprint(d) != fp1


def test_list_papers_source_fresh_after_sidecar_change_on_warm_cache(tmp_workspace):
    # Round-2 #1: sidecar-derived source_url must NOT be frozen in the cache.
    # Warm the cache while a sidecar exists, then change the sidecar; a cache
    # HIT must still reflect the new URL/domain because the fallback is applied
    # fresh outside the cached base info.
    from app.services import papers
    papers._PAPER_INFO_CACHE.clear()
    d = _make_paper(tmp_workspace, "P1", title="A")
    # meta has no source_url; original_filename drives the sidecar lookup
    (d / "paper_meta.json").write_text(
        json.dumps({"title": "A", "tags": [], "original_filename": "orig.pdf"}),
        encoding="utf-8",
    )
    papers._write_source_sidecar("orig.pdf", "https://old.example.com/p")
    first = papers.list_papers("unread")[0]
    assert first["source_url"] == "https://old.example.com/p"
    assert first["source_domain"] == "old.example.com"
    # change sidecar only (folder content/fingerprint unchanged -> cache HIT)
    papers._write_source_sidecar("orig.pdf", "https://new.example.org/q")
    second = papers.list_papers("unread")[0]
    assert second["source_url"] == "https://new.example.org/q"
    assert second["source_domain"] == "new.example.org"


def test_list_papers_uses_cache_on_no_change(tmp_workspace, monkeypatch):
    from app.services import papers
    papers._PAPER_INFO_CACHE.clear()
    _make_paper(tmp_workspace, "P1", title="Old")
    papers.list_papers("unread")  # warm
    calls = {"n": 0}
    real = papers._paper_info
    # wrapper MUST accept the new keyword (list_papers calls it with
    # apply_source_fallback=False) or the miss path raises TypeError.
    def counting(paper_dir, location, apply_source_fallback=True):
        calls["n"] += 1
        return real(paper_dir, location, apply_source_fallback=apply_source_fallback)
    monkeypatch.setattr(papers, "_paper_info", counting)
    papers.list_papers("unread")  # nothing changed
    assert calls["n"] == 0  # served from cache


def test_cached_dict_not_mutated_across_requests(tmp_workspace):
    from app.services import papers
    papers._PAPER_INFO_CACHE.clear()
    _make_paper(tmp_workspace, "P1", title="A")
    first = papers.list_papers("unread")
    first[0]["formats"]["pdf"] = True          # caller mutates nested object
    first[0]["last_read_at"] = "2099-01-01"
    second = papers.list_papers("unread")       # must be unaffected
    assert second[0]["formats"]["pdf"] is False
    assert second[0]["last_read_at"] is None
