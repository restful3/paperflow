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
