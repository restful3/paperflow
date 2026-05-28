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
    assert result["viewer_url"] == "http://localhost:8090/viewer/Sample%20Paper"

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
async def test_get_job_result_viewer_url_quotes_spaces_and_korean(mcp_enabled_workspace):
    """T22 — viewer_url must be URL-quoted so paper_name with spaces / Korean
    yields a single path segment that the viewer route can resolve."""
    from urllib.parse import unquote
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    _rebind_module_settings()
    from app.services import mcp_jobs
    from app.routers.mcp_router import get_job_result

    pname = "한글 제목 With Spaces"
    pdir = _cfg.settings.outputs_dir / pname
    pdir.mkdir()
    (pdir / f"{pname}.md").write_text("en")
    (pdir / f"{pname}_ko.md").write_text("ko")
    (pdir / "pfmcp-koreantest1-example.com.pdf").touch()

    rec = mcp_jobs.JobRecord(
        job_id="job-kr-1", input_type="url",
        source="https://example.com/x",
        expected_filename="pfmcp-koreantest1-example.com.pdf",
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
    assert viewer_url.startswith("http://localhost:8090/viewer/")
    # No raw spaces or non-ASCII characters in the URL
    assert " " not in viewer_url
    assert "한" not in viewer_url
    # The encoded segment must round-trip back to the original paper_name
    encoded_segment = viewer_url.split("/viewer/", 1)[1]
    assert unquote(encoded_segment) == pname
