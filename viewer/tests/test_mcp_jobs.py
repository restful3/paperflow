"""Tests for mcp_jobs service."""
import json
import pytest


def test_job_record_roundtrip(tmp_workspace):
    from app.services import mcp_jobs
    rec = mcp_jobs.JobRecord(
        job_id="abc",
        input_type="url",
        source="https://arxiv.org/abs/1234.5678",
        expected_filename="pfmcp-abc-arxiv.pdf",
        import_method="site_transform",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="queued",
        stage=None,
        percent=0,
        paper_name=None,
        location=None,
        error=None,
        submitted_at="2026-05-24T10:00:00",
        completed_at=None,
        expires_at="2026-05-31T10:00:00",
    )
    payload = rec.model_dump()
    rec2 = mcp_jobs.JobRecord.model_validate(payload)
    assert rec2 == rec


async def test_load_index_creates_empty_when_missing(tmp_workspace):
    from app.services import mcp_jobs
    idx = await mcp_jobs._load_index()
    assert idx == {}


async def test_atomic_write_then_load(tmp_workspace):
    from app.services import mcp_jobs
    await mcp_jobs._atomic_write_index({"job1": {"job_id": "job1", "x": 1}})
    idx = await mcp_jobs._load_index()
    assert "job1" in idx
    assert idx["job1"]["x"] == 1


async def test_corrupt_index_quarantined(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    index_path = settings.logs_dir / "mcp_jobs.json"
    index_path.write_text("{not valid json")
    idx = await mcp_jobs._load_index()
    assert idx == {}
    # Quarantined file exists
    quarantined = list(settings.logs_dir.glob("mcp_jobs.corrupt.*.json"))
    assert len(quarantined) == 1


def test_build_expected_filename():
    from app.services import mcp_jobs
    name = mcp_jobs._build_expected_filename("abcdef1234567890", "arxiv.org")
    assert name.startswith("pfmcp-abcdef123456-")
    assert name.endswith(".pdf")
    assert len(name) <= 70  # reasonable bound


import base64


def test_write_part_file_then_publish(tmp_workspace):
    from app.services import mcp_jobs
    dest = tmp_workspace / "newones" / "pfmcp-test.pdf"
    part = dest.with_suffix(dest.suffix + ".part")
    mcp_jobs._write_part_file(b"%PDF-1.4 test", part)
    assert part.exists()
    assert not dest.exists()    # publish not yet
    mcp_jobs._atomic_publish_part(part, dest)
    assert dest.exists()
    assert not part.exists()
    assert dest.read_bytes() == b"%PDF-1.4 test"


async def test_submit_job_file_invalid_base64(tmp_workspace):
    from app.services import mcp_jobs
    with pytest.raises(ValueError, match="base64"):
        await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
                                   pdf_bytes_b64="not-base64-!!!")


async def test_submit_job_file_oversized(tmp_workspace, monkeypatch):
    from app.services import mcp_jobs
    monkeypatch.setattr(mcp_jobs, "_MAX_FILE_BYTES", 10)
    small_but_over_threshold = base64.b64encode(b"%PDF-1.4 " + b"x" * 5).decode()
    with pytest.raises(ValueError, match="200MB"):
        await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
                                   pdf_bytes_b64=small_but_over_threshold)


async def test_submit_job_file_not_pdf(tmp_workspace):
    from app.services import mcp_jobs
    not_pdf = base64.b64encode(b"hello world").decode()
    with pytest.raises(ValueError, match="PDF"):
        await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
                                   pdf_bytes_b64=not_pdf)


async def test_submit_job_file_success(tmp_workspace):
    from app.services import mcp_jobs
    pdf_b64 = base64.b64encode(b"%PDF-1.4 hello").decode()
    rec = await mcp_jobs.submit_job("file", "mydoc.pdf", mcp_jobs.JobOptions(),
                                     pdf_bytes_b64=pdf_b64)
    assert rec.status == "queued"
    assert rec.expected_filename.startswith("pfmcp-")
    assert rec.input_type == "file"
    assert rec.import_method == "file_upload"
    # File landed in newones/
    landed = tmp_workspace / "newones" / rec.expected_filename
    assert landed.exists()
    assert landed.read_bytes() == b"%PDF-1.4 hello"
    # Index has it
    idx = await mcp_jobs._load_index()
    assert rec.job_id in idx


async def test_submit_url_returns_downloading(tmp_workspace, monkeypatch):
    """URL submit returns immediately with status=downloading; bg task does the work."""
    from app.services import mcp_jobs

    monkeypatch.setattr(
        "app.services.papers._resolve_url_to_pdf_bytes",
        lambda u: (b"%PDF-1.4 fake", u, "site_transform"),
    )

    import asyncio
    rec = await mcp_jobs.submit_job("url", "https://arxiv.org/abs/1234.5678",
                                     mcp_jobs.JobOptions())
    assert rec.status == "downloading"
    assert rec.expected_filename.startswith("pfmcp-")

    # Wait for bg task to finish
    task = mcp_jobs._active_download_tasks.get(rec.job_id)
    if task:
        await task

    # Now should be queued + file landed
    final = await mcp_jobs.get_job(rec.job_id)
    assert final.status == "queued"
    assert final.import_method == "site_transform"
    landed = tmp_workspace / "newones" / rec.expected_filename
    assert landed.exists()


async def test_url_resolve_failure_marks_error(tmp_workspace, monkeypatch):
    from app.services import mcp_jobs

    def fail_resolve(url):
        raise ValueError("dead link")

    monkeypatch.setattr("app.services.papers._resolve_url_to_pdf_bytes", fail_resolve)

    rec = await mcp_jobs.submit_job("url", "https://bad.example.com/x",
                                     mcp_jobs.JobOptions())
    # Wait for bg task
    task = mcp_jobs._active_download_tasks.get(rec.job_id)
    if task:
        try:
            await task
        except Exception:
            pass

    final = await mcp_jobs.get_job(rec.job_id)
    assert final.status == "error"
    assert "dead link" in final.error


async def test_cancel_race_during_publish(tmp_workspace, monkeypatch):
    """Simulate cancel arriving between Stage 1 and Stage 2 — .pdf must not appear."""
    from app.services import mcp_jobs

    monkeypatch.setattr(
        "app.services.papers._resolve_url_to_pdf_bytes",
        lambda u: (b"%PDF-1.4 fake", u, "site_transform"),
    )

    rec = await mcp_jobs.submit_job("url", "https://arxiv.org/abs/9999.99999",
                                     mcp_jobs.JobOptions())
    # Flip status to cancelled BEFORE the bg task reaches Stage 2
    # (race window: between to_thread(write_part) return and the lock acquire)
    await mcp_jobs._set_job_fields(rec.job_id, status="cancelled",
                                    completed_at=mcp_jobs._now_iso())

    task = mcp_jobs._active_download_tasks.get(rec.job_id)
    if task:
        try:
            await task
        except Exception:
            pass

    # .pdf must NOT exist; .part must be cleaned
    dest = tmp_workspace / "newones" / rec.expected_filename
    part = dest.with_suffix(dest.suffix + ".part")
    assert not dest.exists(), "cancelled job's PDF was published"
    assert not part.exists(), "part file leaked"


async def test_reconcile_fallback_when_metadata_skipped(tmp_workspace):
    """Filesystem scan (no paper_meta.json) + _ko.md present → status=complete."""
    from app.services import mcp_jobs

    # Create a job manually in the index
    rec = await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
        pdf_bytes_b64=__import__("base64").b64encode(b"%PDF-fake").decode())
    # Place "processed" output: outputs/WhatevPaper/pfmcp-XXX.pdf + _ko.md
    # No paper_meta.json — forces filesystem scan path (step 2 of _resolve_completed_candidate)
    out_folder = tmp_workspace / "outputs" / "WhatevPaper"
    out_folder.mkdir(parents=True)
    (out_folder / rec.expected_filename).write_bytes(b"%PDF-fake")
    (out_folder / "WhatevPaper.md").write_text("en")
    (out_folder / "WhatevPaper_ko.md").write_text("ko")

    new_rec = await mcp_jobs.reconcile_job(rec.job_id)
    assert new_rec.status == "complete"
    assert new_rec.paper_name == "WhatevPaper"
    assert new_rec.location == "outputs"


async def test_reconcile_error_via_processing_status(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    import json as _json

    rec = await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
        pdf_bytes_b64=__import__("base64").b64encode(b"%PDF-fake").decode())
    # Converter wrote error status for our file
    (settings.logs_dir / "processing_status.json").write_text(_json.dumps({
        "current_file": rec.expected_filename, "stage": "error", "error": "OOM",
    }))
    new_rec = await mcp_jobs.reconcile_job(rec.job_id)
    assert new_rec.status == "error"
    assert "OOM" in new_rec.error


async def test_cancel_job_queued(tmp_workspace):
    """Cancelling a queued job removes the file AND its source sidecar AND partial outputs."""
    from app.services import mcp_jobs
    from app.services import papers as _papers
    from app.config import settings

    rec = await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
        pdf_bytes_b64=__import__("base64").b64encode(b"%PDF-fake").decode())
    landed = settings.newones_dir / rec.expected_filename
    assert landed.exists()

    # Manually create a sidecar (simulating what URL submits do)
    sidecar = settings.newones_meta_dir / f"{rec.expected_filename}.url.txt"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text("https://example.com/source", encoding="utf-8")

    # Manually create a partial output folder named by file stem
    from pathlib import Path
    stem = Path(rec.expected_filename).stem
    partial_out = settings.outputs_dir / stem
    partial_out.mkdir(parents=True)
    (partial_out / "partial.md").write_text("draft", encoding="utf-8")

    cancelled = await mcp_jobs.cancel_job(rec.job_id, delete_file=True)
    assert cancelled.status == "cancelled"

    # All three artifacts cleaned up by request_cancel_processing delegation
    assert not landed.exists(), "PDF file in newones/ not removed"
    assert not sidecar.exists(), "URL sidecar not removed"
    assert not partial_out.exists(), "partial output folder not removed"


async def test_list_jobs(tmp_workspace):
    from app.services import mcp_jobs
    import base64
    for i in range(3):
        await mcp_jobs.submit_job("file", f"doc{i}.pdf", mcp_jobs.JobOptions(),
            pdf_bytes_b64=base64.b64encode(b"%PDF-fake").decode())
    jobs = await mcp_jobs.list_jobs(limit=10)
    assert len(jobs) == 3
    statuses = {j.status for j in jobs}
    assert statuses == {"queued"}


async def test_reconcile_stalled_when_converter_moved_on(tmp_workspace):
    """Status=processing + processing_status references different file with old mtime → stalled."""
    from app.services import mcp_jobs
    from app.config import settings
    import json as _json
    import time as _time
    import os as _os

    rec = await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
        pdf_bytes_b64=__import__("base64").b64encode(b"%PDF-fake").decode())
    # Mark job as processing
    await mcp_jobs._set_job_fields(rec.job_id, status="processing", stage="converting", percent=50)
    # Converter moved to a different file (or is idle), and processing_status hasn't been touched in 31 min
    ps_path = settings.logs_dir / "processing_status.json"
    ps_path.write_text(_json.dumps({"current_file": "some-other-file.pdf", "stage": "converting"}))
    # Backdate the mtime to 31 minutes ago
    old = _time.time() - 31 * 60
    _os.utime(ps_path, (old, old))
    # Remove the newones file so reconcile doesn't downgrade to queued.
    # Stalled check is inside the ps_path.exists() block, BEFORE the newones fallback,
    # so stalled fires first even when the file is gone.
    (tmp_workspace / "newones" / rec.expected_filename).unlink()

    new_rec = await mcp_jobs.reconcile_job(rec.job_id)
    assert new_rec.status == "stalled", f"Expected stalled, got {new_rec.status}"


async def test_cleanup_expired_jobs(tmp_workspace):
    from app.services import mcp_jobs
    import datetime as dt
    # Inject an expired complete + a fresh queued
    expired_at = (dt.datetime.now() - dt.timedelta(days=1)).isoformat(timespec="seconds")
    async with mcp_jobs._index_lock:
        idx = await mcp_jobs._load_index()
        idx["expired"] = {
            "job_id": "expired", "input_type": "file", "source": "x.pdf",
            "expected_filename": "pfmcp-expired-x.pdf",
            "import_method": "file_upload",
            "options": {"force_reprocess": False},
            "status": "complete", "stage": None, "percent": 100,
            "paper_name": "x", "location": "outputs", "error": None,
            "submitted_at": "2020-01-01T00:00:00",
            "completed_at": "2020-01-01T00:01:00",
            "expires_at": expired_at,
        }
        idx["fresh"] = {
            "job_id": "fresh", "input_type": "file", "source": "y.pdf",
            "expected_filename": "pfmcp-fresh-y.pdf",
            "import_method": "file_upload",
            "options": {"force_reprocess": False},
            "status": "queued", "stage": None, "percent": 0,
            "paper_name": None, "location": None, "error": None,
            "submitted_at": "2020-01-01T00:00:00",
            "completed_at": None,
            "expires_at": (dt.datetime.now() + dt.timedelta(days=7)).isoformat(timespec="seconds"),
        }
        await mcp_jobs._atomic_write_index(idx)

    deleted = await mcp_jobs.cleanup_expired_jobs()
    assert deleted == 1
    assert await mcp_jobs.get_job("expired") is None
    assert await mcp_jobs.get_job("fresh") is not None


def test_cleanup_stale_mcp_tmp(tmp_workspace):
    from app.services import mcp_jobs
    import time, os as _os
    tmp_dir = tmp_workspace / "newones" / ".mcp_tmp"
    old_file = tmp_dir / "old.pdf"
    new_file = tmp_dir / "new.pdf"
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")
    # Make old_file mtime 2 hours ago
    two_hours_ago = time.time() - 7200
    _os.utime(old_file, (two_hours_ago, two_hours_ago))

    removed = mcp_jobs._cleanup_stale_mcp_tmp(max_age_seconds=3600)
    assert removed == 1
    assert not old_file.exists()
    assert new_file.exists()


async def test_submit_cached_url_returns_complete(tmp_workspace, monkeypatch):
    """If find_processed_paper returns hit on URL, submit returns status=complete (no download)."""
    from app.services import mcp_jobs
    from app.services import papers as _papers

    def fake_find(*, original_filename=None, source_url=None):
        if source_url:
            return {"name": "AlreadyHere", "location": "outputs", "viewer_path": "/viewer/AlreadyHere"}
        return None

    monkeypatch.setattr(_papers, "find_processed_paper", fake_find)

    rec = await mcp_jobs.submit_job("url", "https://arxiv.org/abs/0000.00000",
                                     mcp_jobs.JobOptions(force_reprocess=False))
    assert rec.status == "complete"
    assert rec.paper_name == "AlreadyHere"
    assert rec.location == "outputs"


async def test_force_reprocess_skips_cache(tmp_workspace, monkeypatch):
    from app.services import mcp_jobs
    from app.services import papers as _papers

    def fake_find(*, original_filename=None, source_url=None):
        return {"name": "AlreadyHere", "location": "outputs", "viewer_path": "x"}

    def fake_resolve(url):
        return b"%PDF-1.4 fake", url, "site_transform"

    monkeypatch.setattr(_papers, "find_processed_paper", fake_find)
    monkeypatch.setattr(_papers, "_resolve_url_to_pdf_bytes", fake_resolve)

    rec = await mcp_jobs.submit_job("url", "https://arxiv.org/abs/0000.00000",
                                     mcp_jobs.JobOptions(force_reprocess=True))
    assert rec.status == "downloading"  # cache bypassed


def test_is_safe_direct_child_accepts_direct_subdir(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    sub = settings.outputs_dir / "real_dir"
    sub.mkdir()
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, sub) is True


def test_is_safe_direct_child_rejects_nested(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    nested = settings.outputs_dir / "a" / "b"
    nested.mkdir(parents=True)
    # nested is a grandchild — not a direct child
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, nested) is False


def test_is_safe_direct_child_rejects_symlink_escape(tmp_workspace, tmp_path):
    from app.services import mcp_jobs
    from app.config import settings
    external = tmp_path / "external_target"
    external.mkdir()
    link = settings.outputs_dir / "evil_link"
    link.symlink_to(external)
    # symlink target is outside outputs_dir
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, link) is False


def test_is_safe_direct_child_rejects_missing(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    missing = settings.outputs_dir / "does_not_exist"
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, missing) is False


def test_is_safe_direct_child_rejects_file(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    f = settings.outputs_dir / "plain.txt"
    f.write_text("hi")
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, f) is False


def test_is_safe_direct_child_rejects_symlink_loop(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    a = settings.outputs_dir / "loop_a"
    b = settings.outputs_dir / "loop_b"
    a.symlink_to(b)
    b.symlink_to(a)
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, a) is False


def test_paper_has_ko_md_with_ko(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    pdir = settings.outputs_dir / "WithKo"
    pdir.mkdir()
    (pdir / "WithKo.md").write_text("en")
    (pdir / "WithKo_ko.md").write_text("ko")
    assert mcp_jobs._paper_has_ko_md(pdir) is True


def test_paper_has_ko_md_without_ko(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    pdir = settings.outputs_dir / "NoKo"
    pdir.mkdir()
    (pdir / "NoKo.md").write_text("en only")
    assert mcp_jobs._paper_has_ko_md(pdir) is False


def test_paper_has_ko_md_missing_folder(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    pdir = settings.outputs_dir / "DoesNotExist"
    assert mcp_jobs._paper_has_ko_md(pdir) is None


def test_paper_has_ko_md_only_ko_explained(tmp_workspace):
    """*_ko_explained.md must NOT satisfy the _ko.md requirement."""
    from app.services import mcp_jobs
    from app.config import settings
    pdir = settings.outputs_dir / "OnlyExplained"
    pdir.mkdir()
    (pdir / "OnlyExplained.md").write_text("en")
    (pdir / "OnlyExplained_ko_explained.md").write_text("ko_explained")
    assert mcp_jobs._paper_has_ko_md(pdir) is False


def test_scan_outputs_dir_only_finds_match(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    sub = settings.outputs_dir / "MyPaper"
    sub.mkdir()
    (sub / "src.pdf").touch()
    assert mcp_jobs._scan_outputs_dir_only("src.pdf") == "MyPaper"


def test_scan_outputs_dir_only_ignores_archives(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    arch = settings.archives_dir / "ArchPaper"
    arch.mkdir()
    (arch / "src.pdf").touch()
    assert mcp_jobs._scan_outputs_dir_only("src.pdf") is None


def test_scan_archives_dir_only_finds_match(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    arch = settings.archives_dir / "ArchPaper"
    arch.mkdir()
    (arch / "src.pdf").touch()
    assert mcp_jobs._scan_archives_dir_only("src.pdf") == "ArchPaper"


def test_scan_outputs_dir_only_rejects_symlink_escape(tmp_workspace, tmp_path):
    """T23 — scan helpers ignore symlinks that escape the base dir."""
    from app.services import mcp_jobs
    from app.config import settings
    # External target contains the file the scan would otherwise find
    external = tmp_path / "external_paper_dir"
    external.mkdir()
    (external / "src.pdf").touch()
    # Symlink inside outputs/ points at the external dir
    (settings.outputs_dir / "evil_link").symlink_to(external)
    assert mcp_jobs._scan_outputs_dir_only("src.pdf") is None


def test_scan_outputs_dir_only_no_outputs_dir(tmp_workspace):
    """Defensive: function returns None when outputs/ does not exist."""
    from app.services import mcp_jobs
    from app.config import settings
    import shutil
    shutil.rmtree(settings.outputs_dir)
    assert mcp_jobs._scan_outputs_dir_only("anything.pdf") is None


def test_find_metadata_match_in_dir_outputs_only(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    import json
    sub = settings.outputs_dir / "PaperA"
    sub.mkdir()
    (sub / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    assert mcp_jobs._find_metadata_match_in_dir(settings.outputs_dir, "src.pdf") == "PaperA"
    # archives/ does NOT match when outputs has the meta
    assert mcp_jobs._find_metadata_match_in_dir(settings.archives_dir, "src.pdf") is None


def test_find_metadata_match_ignores_corrupt_meta(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    sub = settings.outputs_dir / "Corrupt"
    sub.mkdir()
    (sub / "paper_meta.json").write_text("{not valid json")
    assert mcp_jobs._find_metadata_match_in_dir(settings.outputs_dir, "src.pdf") is None


def test_find_metadata_match_ignores_unrelated_meta(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    import json
    sub = settings.outputs_dir / "Other"
    sub.mkdir()
    (sub / "paper_meta.json").write_text(json.dumps({"original_filename": "different.pdf"}))
    assert mcp_jobs._find_metadata_match_in_dir(settings.outputs_dir, "src.pdf") is None


def test_find_metadata_match_rejects_symlink_escape(tmp_workspace, tmp_path):
    """T23 metadata path — same containment guard as scan helpers."""
    from app.services import mcp_jobs
    from app.config import settings
    import json
    external = tmp_path / "external_paper_dir"
    external.mkdir()
    (external / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    (settings.outputs_dir / "evil_link").symlink_to(external)
    assert mcp_jobs._find_metadata_match_in_dir(settings.outputs_dir, "src.pdf") is None


def test_resolve_outputs_metadata_wins_over_archives_metadata(tmp_workspace):
    """T22 — outputs metadata beats archives metadata, even if archives is newer."""
    from app.services import mcp_jobs
    from app.config import settings
    import json, os, time
    out_dir = settings.outputs_dir / "OutPaper"
    out_dir.mkdir()
    (out_dir / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    # No source PDF in outputs — only metadata
    arch_dir = settings.archives_dir / "ArchPaper"
    arch_dir.mkdir()
    (arch_dir / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    (arch_dir / "ArchPaper_ko.md").write_text("ko")
    # Make archives strictly newer
    future = time.time() + 60
    os.utime(arch_dir, (future, future))
    res = mcp_jobs._resolve_completed_candidate("src.pdf")
    assert res == ("OutPaper", "outputs")


def test_resolve_outputs_filesystem_beats_archives_metadata(tmp_workspace):
    """T21 — outputs filesystem scan (step 2) beats archives metadata (step 3)."""
    from app.services import mcp_jobs
    from app.config import settings
    import json, os, time
    out_dir = settings.outputs_dir / "OutPaper"
    out_dir.mkdir()
    (out_dir / "src.pdf").touch()  # filesystem only — no paper_meta
    arch_dir = settings.archives_dir / "ArchPaper"
    arch_dir.mkdir()
    (arch_dir / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    future = time.time() + 60
    os.utime(arch_dir, (future, future))
    assert mcp_jobs._resolve_completed_candidate("src.pdf") == ("OutPaper", "outputs")


def test_resolve_archives_metadata_when_no_outputs(tmp_workspace):
    """T6 inverse — when outputs has nothing, archives metadata wins."""
    from app.services import mcp_jobs
    from app.config import settings
    import json
    arch = settings.archives_dir / "ArchOnly"
    arch.mkdir()
    (arch / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    assert mcp_jobs._resolve_completed_candidate("src.pdf") == ("ArchOnly", "archives")


def test_resolve_archives_filesystem_when_no_meta_anywhere(tmp_workspace):
    """Step 4 fallback — archives filesystem-only."""
    from app.services import mcp_jobs
    from app.config import settings
    arch = settings.archives_dir / "ArchFS"
    arch.mkdir()
    (arch / "src.pdf").touch()
    assert mcp_jobs._resolve_completed_candidate("src.pdf") == ("ArchFS", "archives")


def test_resolve_returns_none_when_nothing_matches(tmp_workspace):
    from app.services import mcp_jobs
    assert mcp_jobs._resolve_completed_candidate("nope.pdf") is None


def test_paper_dir_for_outputs(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    assert mcp_jobs._paper_dir_for("Foo", "outputs") == settings.outputs_dir / "Foo"


def test_paper_dir_for_archives(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    assert mcp_jobs._paper_dir_for("Foo", "archives") == settings.archives_dir / "Foo"


def test_classify_completion_complete_with_ko(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    pdir = settings.outputs_dir / "Done"
    pdir.mkdir()
    (pdir / "Done.md").write_text("en")
    (pdir / "Done_ko.md").write_text("ko")
    (pdir / "src.pdf").touch()
    assert mcp_jobs._classify_completion("src.pdf") == "complete"


def test_classify_completion_partial_when_translation_required(tmp_workspace, monkeypatch):
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    pdir = _cfg.settings.outputs_dir / "Partial"
    pdir.mkdir()
    (pdir / "Partial.md").write_text("en")
    (pdir / "src.pdf").touch()
    assert mcp_jobs._classify_completion("src.pdf") == "partial"


def test_classify_completion_skip_when_translation_disabled(tmp_workspace, monkeypatch):
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "false")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    pdir = _cfg.settings.outputs_dir / "EnOnly"
    pdir.mkdir()
    (pdir / "EnOnly.md").write_text("en")
    (pdir / "src.pdf").touch()
    assert mcp_jobs._classify_completion("src.pdf") == "skip"


def test_classify_completion_missing(tmp_workspace):
    """No candidate folder anywhere → missing."""
    from app.services import mcp_jobs
    assert mcp_jobs._classify_completion("nope.pdf") == "missing"


def test_classify_completion_archives_always_complete(tmp_workspace):
    """archives are user-curated — never flagged as partial."""
    from app.services import mcp_jobs
    from app.config import settings
    arch = settings.archives_dir / "ArchEnOnly"
    arch.mkdir()
    (arch / "ArchEnOnly.md").write_text("en")
    (arch / "src.pdf").touch()
    # No _ko.md, but archives skip the partial check
    assert mcp_jobs._classify_completion("src.pdf") == "complete"


import asyncio


async def _persist_job(status: str, expected_filename: str = "src.pdf",
                       paper_name: str | None = None,
                       location: str | None = None):
    """Helper: write a JobRecord at the given status straight to the index."""
    from app.services import mcp_jobs
    rec = mcp_jobs.JobRecord(
        job_id="job1",
        input_type="url",
        source="https://example.com/p.pdf",
        expected_filename=expected_filename,
        import_method=None,
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status=status,
        stage=None,
        percent=100 if status == "complete" else 0,
        paper_name=paper_name,
        location=location,
        error=None,
        submitted_at="2026-05-24T10:00:00",
        completed_at=None,
        expires_at="2026-05-31T10:00:00",
    )
    async with mcp_jobs._index_lock:
        idx = await mcp_jobs._load_index()
        idx[rec.job_id] = rec.model_dump()
        await mcp_jobs._atomic_write_index(idx)


def _make_paper_folder(tmp_workspace, name: str, has_ko: bool, has_pdf: bool = True,
                        has_meta: bool = True, dest: str = "outputs"):
    from app.config import settings
    import json
    base = settings.outputs_dir if dest == "outputs" else settings.archives_dir
    pdir = base / name
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{name}.md").write_text("en")
    if has_ko:
        (pdir / f"{name}_ko.md").write_text("ko")
    if has_pdf:
        (pdir / "src.pdf").touch()
    if has_meta:
        (pdir / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    return pdir


async def test_reconcile_complete_with_ko_md_stays_complete(tmp_workspace):
    """T3 — complete + _ko.md present → status stays complete (regression)."""
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Good", has_ko=True)
    await _persist_job("complete", paper_name="Good", location="outputs")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "complete"


async def test_reconcile_complete_partial_downgrades_to_error(tmp_workspace, monkeypatch):
    """T1 — complete + _ko.md missing + REQUIRE=true → status=error."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Bad", has_ko=False)
    await _persist_job("complete", paper_name="Bad", location="outputs")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"
    assert "translation_missing" in rec.error
    assert "cancel_job(delete_file=true)" in rec.error
    assert "force_reprocess=true" in rec.error
    assert "MCP_REQUIRE_TRANSLATION=false" in rec.error


async def test_reconcile_complete_skip_when_translation_disabled(tmp_workspace, monkeypatch):
    """T2 — complete + _ko.md missing + REQUIRE=false → stays complete."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "false")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "EnOnly", has_ko=False)
    await _persist_job("complete", paper_name="EnOnly", location="outputs")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "complete"


async def test_reconcile_complete_archives_unchanged(tmp_workspace):
    """T4 — archives folder with no _ko.md → still complete."""
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Archived", has_ko=False, dest="archives")
    await _persist_job("complete", paper_name="Archived", location="archives")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "complete"


async def test_reconcile_complete_folder_disappeared_becomes_error(tmp_workspace):
    """T17 — folder was deleted externally → status=error 'no longer present'."""
    from app.services import mcp_jobs
    # Job persisted complete, but no folder exists anywhere
    await _persist_job("complete", paper_name="Vanished", location="outputs")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"
    assert "no longer present" in rec.error
    assert "translation_missing" not in rec.error


async def test_reconcile_legacy_complete_migration(tmp_workspace):
    """T14 — v1 partial job persisted complete → next reconcile call surfaces error."""
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Legacy", has_ko=False)
    # paper_name/location may even be missing on truly legacy records
    await _persist_job("complete", paper_name=None, location=None)
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"
    assert "translation_missing" in rec.error


async def test_reconcile_error_status_stays_error(tmp_workspace):
    """error remains terminal — no re-validation."""
    from app.services import mcp_jobs
    await _persist_job("error")
    # Even if the filesystem now looks valid, error stays
    _make_paper_folder(tmp_workspace, "DoesntMatter", has_ko=True)
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"


async def test_reconcile_cancelled_status_stays_cancelled(tmp_workspace):
    """cancelled remains terminal."""
    from app.services import mcp_jobs
    await _persist_job("cancelled")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "cancelled"


async def test_reconcile_queued_to_complete_with_ko(tmp_workspace):
    """Normal happy path: queued → outputs has _ko.md → status=complete."""
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Done", has_ko=True)
    await _persist_job("queued")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "complete"
    assert rec.paper_name == "Done"
    assert rec.location == "outputs"


async def test_reconcile_queued_to_partial_with_translation_required(tmp_workspace, monkeypatch):
    """T15 — queued + outputs/{paper}/ partial → status=error translation_missing."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Bad", has_ko=False, has_meta=False)  # fallback scan path
    await _persist_job("queued")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"
    assert "translation_missing" in rec.error


async def test_reconcile_queued_outputs_partial_with_archives_complete(tmp_workspace, monkeypatch):
    """T16 — outputs partial AND archives complete → outputs wins → status=error."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Both", has_ko=False, dest="outputs")
    _make_paper_folder(tmp_workspace, "Both", has_ko=True, dest="archives")
    await _persist_job("queued")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"
    assert "translation_missing" in rec.error


async def test_reconcile_queued_missing_after_candidate_resolved(tmp_workspace):
    """Race: resolver returned candidate then folder disappeared mid-classify."""
    from app.services import mcp_jobs
    pdir = _make_paper_folder(tmp_workspace, "Vanishing", has_ko=True)
    await _persist_job("queued")
    # Simulate disappearance by removing the entire folder
    import shutil
    shutil.rmtree(pdir)
    rec = await mcp_jobs.reconcile_job("job1")
    # Resolver finds nothing → status remains queued (race-tolerant)
    # OR: resolve+classify both empty → no completion path triggers.
    # Either way, the test guards against false "complete" on missing candidate.
    assert rec.status != "complete"


def test_cleanup_smart_renamed_outputs_match(tmp_workspace):
    from app.services import mcp_jobs
    pdir = _make_paper_folder(tmp_workspace, "SmartRenamed", has_ko=False)
    result = mcp_jobs._cleanup_smart_renamed_paper("src.pdf")
    assert result["attempted"] is True
    assert result["deleted_path"] == str(pdir)
    assert result["warning"] is None
    assert not pdir.exists()


def test_cleanup_smart_renamed_no_match(tmp_workspace):
    from app.services import mcp_jobs
    result = mcp_jobs._cleanup_smart_renamed_paper("nope.pdf")
    assert result == {"attempted": False, "deleted_path": None, "warning": None}


def test_cleanup_smart_renamed_archives_preserved(tmp_workspace):
    """T10 partial — archives match → cleanup refuses, archives untouched."""
    from app.services import mcp_jobs
    pdir = _make_paper_folder(tmp_workspace, "ArchOnly", has_ko=True, dest="archives")
    result = mcp_jobs._cleanup_smart_renamed_paper("src.pdf")
    assert result["attempted"] is False
    assert result["warning"] and "archives" in result["warning"]
    assert pdir.exists()  # archives intact
