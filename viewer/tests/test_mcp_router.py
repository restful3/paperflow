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
