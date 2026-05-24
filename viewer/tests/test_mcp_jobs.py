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
