"""Regression tests for _resolve_url_to_pdf_bytes extraction."""
import re

import pytest
from unittest.mock import patch


def test_invalid_url_raises_value_error(tmp_workspace):
    from app.services import papers
    with pytest.raises(ValueError, match="Rejected URL"):
        papers._resolve_url_to_pdf_bytes("not-a-url")


def test_invalid_scheme_raises_value_error(tmp_workspace):
    from app.services import papers
    with pytest.raises(ValueError, match="Rejected URL"):
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


# ── Fix 1: arXiv "Download PDF" link form (/pdf/) must be recognized ──────────


def test_arxiv_pdf_link_form_is_recognized(tmp_workspace):
    """arxiv.org/pdf/<id> (the 'Download PDF' button URL, no .pdf extension)
    must transform to a downloadable PDF URL — previously dead-ended."""
    from app.services import papers
    assert papers._site_transform_pdf_urls("https://arxiv.org/pdf/2508.14052") == [
        "https://arxiv.org/pdf/2508.14052.pdf"
    ]


def test_arxiv_pdf_link_versioned_is_recognized(tmp_workspace):
    from app.services import papers
    assert papers._site_transform_pdf_urls("https://arxiv.org/pdf/2508.14052v1") == [
        "https://arxiv.org/pdf/2508.14052v1.pdf"
    ]


def test_arxiv_old_style_pdf_link_is_recognized(tmp_workspace):
    from app.services import papers
    assert papers._site_transform_pdf_urls("https://arxiv.org/pdf/hep-ph/0512345") == [
        "https://arxiv.org/pdf/hep-ph/0512345.pdf"
    ]


# ── Fix 2: direct-download path must use a real browser User-Agent ────────────


def test_download_pdf_uses_browser_user_agent(tmp_workspace, monkeypatch):
    from app.services import papers

    captured = {}

    class _FakeResp:
        headers = {"Content-Type": "application/pdf"}

        def read(self):
            return b"%PDF-1.4 fake"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["ua"] = req.get_header("User-agent")
        return _FakeResp()

    monkeypatch.setattr(papers, "urlopen", fake_urlopen)
    papers._download_pdf("https://arxiv.org/pdf/2508.14052.pdf")
    assert "Chrome/" in (captured["ua"] or "")


def test_fetch_url_html_uses_browser_user_agent(tmp_workspace, monkeypatch):
    from app.services import papers

    captured = {}

    class _FakeResp:
        headers = {"Content-Type": "text/html"}

        def geturl(self):
            return "https://example.com/article"

        def read(self):
            return b"<html>ok</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["ua"] = req.get_header("User-agent")
        return _FakeResp()

    monkeypatch.setattr(papers, "urlopen", fake_urlopen)
    papers._fetch_url_html("https://example.com/article")
    assert "Chrome/" in (captured["ua"] or "")


# ── Fix 3: strict-domain failure message must be actionable ───────────────────


def test_strict_domain_failure_message_is_actionable(tmp_workspace, monkeypatch):
    from app.services import papers

    monkeypatch.setattr(papers, "_is_safe_public_host", lambda url: (True, None))
    monkeypatch.setattr(papers, "_site_transform_pdf_urls", lambda url: [])
    monkeypatch.setattr(papers, "_fetch_url_html", lambda url, **kw: ("", url))
    monkeypatch.setattr(papers, "_candidate_pdf_urls_from_page", lambda url, html: [])

    with pytest.raises(ValueError, match="페이월|차단|직접 링크"):
        papers._resolve_url_to_pdf_bytes("https://ieeexplore.ieee.org/document/123")


# ── Fix 4: capture quality gate must not reject long real articles ────────────


def test_long_article_with_footer_terms_not_rejected(tmp_workspace):
    """A full article that merely contains footer words (terms/copyright/privacy)
    must NOT be rejected just because weak_hit >= 3."""
    from app.services import papers
    body = "This paper presents a novel method for agentic reasoning. " * 200
    footer = " Privacy Policy Terms Copyright 2026 "
    assert papers._capture_rejection_reason(body + footer) is None


def test_footer_only_short_capture_is_rejected(tmp_workspace):
    from app.services import papers
    reason = papers._capture_rejection_reason("Privacy Policy Terms Copyright Notify me")
    assert reason is not None
    assert "푸터" in reason or "본문" in reason


def test_bot_challenge_capture_is_rejected(tmp_workspace):
    from app.services import papers
    reason = papers._capture_rejection_reason("Just a moment... Checking your browser before access. Cloudflare")
    assert reason is not None
    assert "봇" in reason or "인증" in reason


def test_error_page_capture_is_rejected(tmp_workspace):
    from app.services import papers
    reason = papers._capture_rejection_reason("404 Not Found — the page you requested does not exist")
    assert reason is not None


def test_healthy_article_without_footer_words_not_rejected(tmp_workspace):
    """A real article body (well above the 220-char floor, no footer words)
    must pass the gate."""
    from app.services import papers
    text = ("We study tool-use efficiency in language-model agents and report "
            "consistent gains across three benchmarks under controlled ablations. "
            "Our analysis isolates the contribution of entropy-guided exploration "
            "and shows that reward shaping interacts with the harness in ways prior "
            "work did not anticipate. ") * 4
    assert len(re.sub(r"\s+", " ", text).strip()) >= 220
    assert papers._capture_rejection_reason(text) is None


# ── Fix 2 + 4: headless command hardening ─────────────────────────────────────


def test_headless_command_uses_browser_ua_and_no_header_footer(tmp_workspace, monkeypatch):
    from app.services import papers

    monkeypatch.setattr(papers, "_is_safe_public_host", lambda url: (True, None))
    monkeypatch.setattr(papers, "_site_transform_pdf_urls", lambda url: [])
    monkeypatch.setattr(papers, "_fetch_url_html", lambda url, **kw: ("", url))
    monkeypatch.setattr(papers, "_candidate_pdf_urls_from_page", lambda url, html: [])
    monkeypatch.setattr(papers.shutil, "which",
                        lambda name: "/usr/bin/chromium" if name == "chromium" else None)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        raise papers.subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(papers.subprocess, "run", fake_run)

    with pytest.raises(ValueError):
        papers._resolve_url_to_pdf_bytes("https://example.com/some-article")

    cmd = captured["cmd"]
    assert any("--no-pdf-header-footer" in c for c in cmd)
    assert any(c.startswith("--user-agent=") and "Chrome/" in c for c in cmd)
