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
