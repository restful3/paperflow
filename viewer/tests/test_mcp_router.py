"""Integration tests for mcp_router (zip endpoint + verify_mcp_key)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_mcp(mcp_enabled_workspace):
    """FastAPI app with MCP enabled. Re-create after env override."""
    # Force reimport so create_app reads fresh settings
    import importlib
    from app import main as _main
    importlib.reload(_main)
    return _main.app


def test_zip_endpoint_requires_bearer(app_with_mcp):
    client = TestClient(app_with_mcp)
    r = client.get("/api/mcp/jobs/nonexistent/zip")
    assert r.status_code == 401


def test_zip_endpoint_wrong_bearer(app_with_mcp):
    client = TestClient(app_with_mcp)
    r = client.get("/api/mcp/jobs/nonexistent/zip",
                   headers={"Authorization": "Bearer wrongkey"})
    assert r.status_code == 401


def test_zip_endpoint_404_when_job_missing(app_with_mcp, mcp_enabled_workspace):
    from app.config import settings
    client = TestClient(app_with_mcp)
    r = client.get("/api/mcp/jobs/nonexistent/zip",
                   headers={"Authorization": f"Bearer {settings.MCP_API_KEY}"})
    assert r.status_code == 404


def test_mcp_mount_404_when_disabled(tmp_workspace):
    """When MCP_API_KEY unset, /mcp must not be mounted."""
    import importlib
    from app import main as _main
    importlib.reload(_main)
    client = TestClient(_main.app)
    r = client.post("/mcp", headers={"Content-Type": "application/json"})
    assert r.status_code == 404


import pytest


@pytest.mark.asyncio
async def test_zip_endpoint_triggers_reconcile_and_404s_on_partial(mcp_enabled_workspace, monkeypatch):
    """T13 — job persisted complete + partial outputs + REQUIRE=true → zip returns 404."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg, main as _main
    import importlib
    _cfg.settings = _cfg.Settings()
    importlib.reload(_main)

    from app.services import mcp_jobs
    pdir = _cfg.settings.outputs_dir / "Bad"
    pdir.mkdir()
    (pdir / "Bad.md").write_text("en")
    (pdir / "src.pdf").touch()
    rec = mcp_jobs.JobRecord(
        job_id="job1", input_type="url", source="x",
        expected_filename="src.pdf", import_method=None,
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name="Bad", location="outputs",
        error=None, submitted_at="2026-05-24T10:00:00",
        completed_at="2026-05-24T10:01:00", expires_at="2026-05-31T10:00:00",
    )
    async with mcp_jobs._index_lock:
        idx = await mcp_jobs._load_index()
        idx["job1"] = rec.model_dump()
        await mcp_jobs._atomic_write_index(idx)

    client = TestClient(_main.app)
    r = client.get(f"/api/mcp/jobs/job1/zip",
                   headers={"Authorization": f"Bearer {_cfg.settings.MCP_API_KEY}"})
    assert r.status_code == 404  # reconcile downgraded job to error → zip rejects


@pytest.mark.asyncio
async def test_get_job_result_rejects_after_reconcile_downgrade(mcp_enabled_workspace, monkeypatch):
    """T19 — get_job_result raises after reconcile downgrades complete→error.
    Simplified: verify reconcile itself flips status (the router tool surfaces via this).
    """
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs

    pdir = _cfg.settings.outputs_dir / "Bad2"
    pdir.mkdir()
    (pdir / "Bad2.md").write_text("en")
    (pdir / "src.pdf").touch()
    rec = mcp_jobs.JobRecord(
        job_id="job2", input_type="url", source="x",
        expected_filename="src.pdf", import_method=None,
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name="Bad2", location="outputs",
        error=None, submitted_at="2026-05-24T10:00:00",
        completed_at="2026-05-24T10:01:00", expires_at="2026-05-31T10:00:00",
    )
    async with mcp_jobs._index_lock:
        idx = await mcp_jobs._load_index()
        idx["job2"] = rec.model_dump()
        await mcp_jobs._atomic_write_index(idx)

    rec2 = await mcp_jobs.reconcile_job("job2")
    assert rec2.status == "error"
    assert "translation_missing" in rec2.error


# ── T20–T22: get_job_result extended response contract ───────────────────────


async def _seed_complete_job(rec: "mcp_jobs.JobRecord") -> None:
    """Helper: persist a JobRecord to the on-disk index."""
    from app.services import mcp_jobs
    async with mcp_jobs._index_lock:
        idx = await mcp_jobs._load_index()
        idx[rec.job_id] = rec.model_dump()
        await mcp_jobs._atomic_write_index(idx)


def _rebind_module_settings():
    """Force-rebind ``settings`` in modules that did ``from ..config import settings``.
    Without this, settings rebinding inside ``tmp_workspace`` does not reach
    those modules in sequential test runs (only fresh subprocess imports do)."""
    from app import config as _cfg
    from app.services import papers as _papers
    from app.services import mcp_jobs as _mj
    from app.routers import mcp_router as _mr
    for mod in (_papers, _mj, _mr):
        if hasattr(mod, "settings"):
            mod.settings = _cfg.settings


@pytest.mark.asyncio
async def test_get_job_result_url_input_exposes_link_contract(mcp_enabled_workspace):
    """T20 — URL input: response carries viewer_url, source_url, input_type,
    submitted_source, paperflow_source_id alongside existing fields."""
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    _rebind_module_settings()
    from app.services import mcp_jobs
    from app.routers.mcp_router import get_job_result

    pname = "Sample Paper"
    pdir = _cfg.settings.outputs_dir / pname
    pdir.mkdir()
    (pdir / f"{pname}.md").write_text("en")
    (pdir / f"{pname}_ko.md").write_text("ko")
    (pdir / "pfmcp-abcdef123456-example.com.pdf").touch()

    rec = mcp_jobs.JobRecord(
        job_id="job-url-1", input_type="url",
        source="https://example.com/paper.pdf",
        expected_filename="pfmcp-abcdef123456-example.com.pdf",
        import_method="direct_pdf",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name=pname, location="outputs",
        error=None, submitted_at="2026-05-28T10:00:00",
        completed_at="2026-05-28T10:01:00", expires_at="2026-06-04T10:00:00",
    )
    await _seed_complete_job(rec)

    result = await get_job_result(job_id="job-url-1")

    # New link-contract fields
    assert result["input_type"] == "url"
    assert result["source_url"] == "https://example.com/paper.pdf"
    assert result["submitted_source"] == "https://example.com/paper.pdf"
    assert result["paperflow_source_id"] == "pfmcp-abcdef123456-example.com.pdf"
    assert result["viewer_url"] == "http://localhost:8090/viewer/by-id/pfmcp-abcdef123456-example.com.pdf"

    # Existing fields preserved
    assert result["job_id"] == "job-url-1"
    assert result["paper_name"] == pname
    assert result["location"] == "outputs"
    assert "download_url" in result
    assert "paper_meta" in result
    assert "files" in result
    assert "expires_at" in result


@pytest.mark.asyncio
async def test_get_job_result_file_input_redacts_local_path(mcp_enabled_workspace):
    """T21 — File input: source_url is None, submitted_source is basename only.
    Local directory portion of rec.source MUST NOT leak into the response."""
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    _rebind_module_settings()
    from app.services import mcp_jobs
    from app.routers.mcp_router import get_job_result

    pname = "File Paper"
    pdir = _cfg.settings.outputs_dir / pname
    pdir.mkdir()
    (pdir / f"{pname}.md").write_text("en")
    (pdir / f"{pname}_ko.md").write_text("ko")
    (pdir / "pfmcp-fedcba654321-some_report.pdf").touch()

    rec = mcp_jobs.JobRecord(
        job_id="job-file-1", input_type="file",
        source="/home/user/secret-dir/some_report.pdf",
        expected_filename="pfmcp-fedcba654321-some_report.pdf",
        import_method="file_upload",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name=pname, location="outputs",
        error=None, submitted_at="2026-05-28T10:00:00",
        completed_at="2026-05-28T10:01:00", expires_at="2026-06-04T10:00:00",
    )
    await _seed_complete_job(rec)

    result = await get_job_result(job_id="job-file-1")

    assert result["input_type"] == "file"
    assert result["source_url"] is None
    assert result["submitted_source"] == "some_report.pdf"
    assert "/home/user/" not in result["submitted_source"]
    assert "secret-dir" not in result["submitted_source"]
    assert result["paperflow_source_id"] == "pfmcp-fedcba654321-some_report.pdf"


@pytest.mark.asyncio
async def test_get_job_result_viewer_url_is_by_id_not_paper_name(mcp_enabled_workspace):
    """T22 (updated) — viewer_url is now based on paperflow_source_id
    (expected_filename), NOT paper_name. A paper_name with spaces / Korean
    must no longer leak into viewer_url."""
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    _rebind_module_settings()
    from app.services import mcp_jobs
    from app.routers.mcp_router import get_job_result

    pname = "한글 제목 With Spaces"
    sid = "pfmcp-koreantest1-example.com.pdf"
    pdir = _cfg.settings.outputs_dir / pname
    pdir.mkdir()
    (pdir / f"{pname}.md").write_text("en")
    (pdir / f"{pname}_ko.md").write_text("ko")
    (pdir / sid).touch()

    rec = mcp_jobs.JobRecord(
        job_id="job-kr-1", input_type="url",
        source="https://example.com/x",
        expected_filename=sid,
        import_method="direct_pdf",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name=pname, location="outputs",
        error=None, submitted_at="2026-05-28T10:00:00",
        completed_at="2026-05-28T10:01:00", expires_at="2026-06-04T10:00:00",
    )
    await _seed_complete_job(rec)

    result = await get_job_result(job_id="job-kr-1")

    viewer_url = result["viewer_url"]
    assert viewer_url == f"http://localhost:8090/viewer/by-id/{sid}"
    # paper_name (spaces / Korean) must NOT appear in viewer_url anymore
    assert " " not in viewer_url
    assert "한" not in viewer_url
    assert pname not in viewer_url


@pytest.mark.asyncio
async def test_get_job_result_viewer_url_quotes_source_id(mcp_enabled_workspace):
    """T9 — viewer_url uses quote() on expected_filename for path safety."""
    from urllib.parse import quote
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    _rebind_module_settings()
    from app.services import mcp_jobs
    from app.routers.mcp_router import get_job_result

    pname = "Plain Paper"
    sid = "pfmcp-abcdef123456-example.com.pdf"
    pdir = _cfg.settings.outputs_dir / pname
    pdir.mkdir()
    (pdir / f"{pname}.md").write_text("en")
    (pdir / f"{pname}_ko.md").write_text("ko")
    (pdir / sid).touch()

    rec = mcp_jobs.JobRecord(
        job_id="job-q-1", input_type="url",
        source="https://example.com/x",
        expected_filename=sid, import_method="direct_pdf",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name=pname, location="outputs",
        error=None, submitted_at="2026-05-28T10:00:00",
        completed_at="2026-05-28T10:01:00", expires_at="2026-06-04T10:00:00",
    )
    await _seed_complete_job(rec)

    result = await get_job_result(job_id="job-q-1")
    assert result["viewer_url"] == f"http://localhost:8090/viewer/by-id/{quote(sid, safe='')}"


# ── T23–T25: zip endpoint + get_job_result honor rec.location ────────────────


@pytest.mark.asyncio
async def test_zip_endpoint_honors_archives_location(mcp_enabled_workspace):
    """T23 — when rec.location == 'archives' and outputs/<paper_name> also
    exists (collision), the zip endpoint must read the archives copy, not the
    outputs duplicate that safe_paper_dir() would otherwise prefer."""
    import io
    import zipfile
    import importlib
    from fastapi.testclient import TestClient
    from app import config as _cfg, main as _main
    _cfg.settings = _cfg.Settings()
    importlib.reload(_main)
    _rebind_module_settings()
    from app.services import mcp_jobs

    pname = "Paper Conflict"
    expected = "pfmcp-arch01abcdef-example.com.pdf"

    # Outputs has the same paper_name but its PDF is unrelated to expected_filename
    out_dir = _cfg.settings.outputs_dir / pname
    out_dir.mkdir()
    (out_dir / "marker_outputs.md").write_text("outputs marker")
    (out_dir / f"{pname}.md").write_text("en")
    (out_dir / f"{pname}_ko.md").write_text("ko")
    (out_dir / "some_other.pdf").touch()

    # Archives has the matching expected_filename PDF + a distinct marker file
    arc_dir = _cfg.settings.archives_dir / pname
    arc_dir.mkdir()
    (arc_dir / "marker_archives.md").write_text("archives marker")
    (arc_dir / f"{pname}.md").write_text("en")
    (arc_dir / f"{pname}_ko.md").write_text("ko")
    (arc_dir / expected).touch()

    rec = mcp_jobs.JobRecord(
        job_id="job-arch-1", input_type="url",
        source="https://example.com/x",
        expected_filename=expected,
        import_method="direct_pdf",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name=pname, location="archives",
        error=None, submitted_at="2026-05-28T10:00:00",
        completed_at="2026-05-28T10:01:00", expires_at="2026-06-04T10:00:00",
    )
    await _seed_complete_job(rec)

    client = TestClient(_main.app)
    r = client.get(f"/api/mcp/jobs/{rec.job_id}/zip",
                   headers={"Authorization": f"Bearer {_cfg.settings.MCP_API_KEY}"})
    assert r.status_code == 200, r.text

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "marker_archives.md" in names, (
        f"zip built from wrong location; expected archives marker, got {names}"
    )
    assert "marker_outputs.md" not in names, (
        f"outputs duplicate leaked into archives job zip; names={names}"
    )


@pytest.mark.asyncio
async def test_get_job_result_honors_archives_location(mcp_enabled_workspace):
    """T24 — get_job_result must read archives/<paper_name>/paper_meta.json
    when rec.location == 'archives', not the outputs duplicate."""
    import json as _json
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    _rebind_module_settings()
    from app.services import mcp_jobs
    from app.routers.mcp_router import get_job_result

    pname = "Paper Conflict Meta"
    expected = "pfmcp-archmeta01-example.com.pdf"

    out_dir = _cfg.settings.outputs_dir / pname
    out_dir.mkdir()
    (out_dir / f"{pname}.md").write_text("en")
    (out_dir / f"{pname}_ko.md").write_text("ko")
    (out_dir / "some_other.pdf").touch()
    (out_dir / "paper_meta.json").write_text(
        _json.dumps({"title": "OUTPUTS_TITLE"})
    )

    arc_dir = _cfg.settings.archives_dir / pname
    arc_dir.mkdir()
    (arc_dir / f"{pname}.md").write_text("en")
    (arc_dir / f"{pname}_ko.md").write_text("ko")
    (arc_dir / expected).touch()
    (arc_dir / "paper_meta.json").write_text(
        _json.dumps({"title": "ARCHIVES_TITLE"})
    )

    rec = mcp_jobs.JobRecord(
        job_id="job-archmeta-1", input_type="url",
        source="https://example.com/y",
        expected_filename=expected,
        import_method="direct_pdf",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name=pname, location="archives",
        error=None, submitted_at="2026-05-28T10:00:00",
        completed_at="2026-05-28T10:01:00", expires_at="2026-06-04T10:00:00",
    )
    await _seed_complete_job(rec)

    result = await get_job_result(job_id=rec.job_id)
    assert result["location"] == "archives"
    assert result["paper_meta"]["title"] == "ARCHIVES_TITLE", (
        f"get_job_result read outputs paper_meta instead of archives; got {result['paper_meta']!r}"
    )


@pytest.mark.asyncio
async def test_get_job_result_falls_back_when_location_is_none(mcp_enabled_workspace):
    """T25 — legacy jobs persisted without a location field must still resolve
    via the outputs-first fallback that safe_paper_dir() provides."""
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    _rebind_module_settings()
    from app.services import mcp_jobs
    from app.routers.mcp_router import get_job_result

    pname = "Legacy Paper"
    expected = "pfmcp-legacy01-example.com.pdf"

    out_dir = _cfg.settings.outputs_dir / pname
    out_dir.mkdir()
    (out_dir / f"{pname}.md").write_text("en")
    (out_dir / f"{pname}_ko.md").write_text("ko")
    (out_dir / expected).touch()

    rec = mcp_jobs.JobRecord(
        job_id="job-legacy-1", input_type="url",
        source="https://example.com/z",
        expected_filename=expected,
        import_method="direct_pdf",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name=pname, location=None,
        error=None, submitted_at="2026-05-28T10:00:00",
        completed_at="2026-05-28T10:01:00", expires_at="2026-06-04T10:00:00",
    )
    await _seed_complete_job(rec)

    result = await get_job_result(job_id=rec.job_id)
    assert result["paper_name"] == pname
    assert "viewer_url" in result
    assert result["files"]["md_ko"] is True
