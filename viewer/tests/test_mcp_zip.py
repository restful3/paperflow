"""Tests for zip stream builder."""
import io
import zipfile
import pytest


@pytest.fixture
def fake_paper_dir(tmp_workspace):
    """Create outputs/FakePaper/ with md, md_ko, pdf, images."""
    paper = tmp_workspace / "outputs" / "FakePaper"
    paper.mkdir(parents=True)
    (paper / "fake.md").write_text("# english", encoding="utf-8")
    (paper / "fake_ko.md").write_text("# 한국어", encoding="utf-8")
    (paper / "fake.pdf").write_bytes(b"%PDF-1.4 dummy")
    (paper / "paper_meta.json").write_text('{"title":"Fake"}', encoding="utf-8")
    img_dir = paper / "images"
    img_dir.mkdir()
    (img_dir / "fig1.jpeg").write_bytes(b"\xff\xd8\xff\xe0")  # JPEG SOI
    return paper


def test_zip_default_no_pdf_with_translation(fake_paper_dir):
    from app.services import mcp_zip
    chunks = list(mcp_zip.build_zip_stream(
        fake_paper_dir, include_pdf=False, include_translation=True, job_meta={"job_id": "j1"}
    ))
    buf = io.BytesIO(b"".join(chunks))
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    assert "fake.md" in names
    assert "fake_ko.md" in names
    assert "paper_meta.json" in names
    assert "images/fig1.jpeg" in names
    assert "README.txt" in names
    assert "fake.pdf" not in names


def test_zip_with_pdf(fake_paper_dir):
    from app.services import mcp_zip
    chunks = list(mcp_zip.build_zip_stream(
        fake_paper_dir, include_pdf=True, include_translation=True, job_meta={"job_id": "j1"}
    ))
    buf = io.BytesIO(b"".join(chunks))
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    assert "fake.pdf" in names


def test_zip_without_translation(fake_paper_dir):
    from app.services import mcp_zip
    chunks = list(mcp_zip.build_zip_stream(
        fake_paper_dir, include_pdf=False, include_translation=False, job_meta={"job_id": "j1"}
    ))
    buf = io.BytesIO(b"".join(chunks))
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    assert "fake_ko.md" not in names
    assert "fake.md" in names  # english always
