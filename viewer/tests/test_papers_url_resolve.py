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


def test_chromium_filenotfound_raises_value_error(tmp_workspace, monkeypatch):
    """If chromium binary disappears between which() and exec, must raise ValueError not leak FileNotFoundError."""
    from app.services import papers
    import subprocess

    # Force fallback path: no site_transform candidates succeed
    monkeypatch.setattr(papers, "_site_transform_pdf_urls", lambda url: [])
    monkeypatch.setattr(papers, "_fetch_url_html", lambda url, **kw: ("", url))
    monkeypatch.setattr(papers, "_candidate_pdf_urls_from_page", lambda url, html: [])
    # shutil.which finds chromium
    monkeypatch.setattr(papers.shutil, "which", lambda name: "/nonexistent/chromium")
    # subprocess.run raises FileNotFoundError
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("no such file")
    monkeypatch.setattr(papers.subprocess, "run", fake_run)

    # Use non-academic host so we don't hit the strict_pdf_required ValueError first
    with pytest.raises(ValueError, match="Headless browser executable missing"):
        papers._resolve_url_to_pdf_bytes("https://example.com/some-paper")
