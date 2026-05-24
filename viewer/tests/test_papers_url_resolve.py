"""Regression tests for _resolve_url_to_pdf_bytes extraction."""
import pytest
from unittest.mock import patch


def test_invalid_url_raises_value_error(tmp_workspace):
    from app.services import papers
    with pytest.raises(ValueError, match="Invalid URL"):
        papers._resolve_url_to_pdf_bytes("not-a-url")


def test_invalid_scheme_raises_value_error(tmp_workspace):
    from app.services import papers
    with pytest.raises(ValueError, match="Invalid URL"):
        papers._resolve_url_to_pdf_bytes("ftp://example.com/foo.pdf")


def test_site_transform_returns_bytes(tmp_workspace, monkeypatch):
    """When _download_pdf succeeds on a transformed URL, helper returns its bytes."""
    from app.services import papers

    expected_bytes = b"%PDF-1.4 fake pdf content here"

    def fake_download(url, timeout=35):
        if url.endswith(".pdf"):
            return expected_bytes
        raise Exception("not a pdf")

    monkeypatch.setattr(papers, "_download_pdf", fake_download)

    pdf_bytes, final_url, method = papers._resolve_url_to_pdf_bytes("https://arxiv.org/abs/2301.12345")
    assert pdf_bytes == expected_bytes
    assert "arxiv.org" in final_url
    assert method in ("site_transform", "direct_pdf")
