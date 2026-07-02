"""URL-first 경로의 논문 랜딩페이지 우회 가드 테스트 (Fix A + Fix B).

배경: 토리보드에서 import 된 arXiv 논문이 초록만 등록되는 버그.
1차 HTML 추출은 마커 가드(_looks_like_paper_landing_page)에 걸렸지만,
browser fallback(r.jina.ai)이 같은 abs URL 을 재시도해 마커가 제거된
제목+저자+초록(2k~5.9k chars)을 본문으로 채택했다 (2026-07-01 로그).

Fix B: 알려진 논문 랜딩 URL 이면 URL-first 경로 자체를 스킵 (결정적 1차 방어)
Fix A: 1차 추출이 랜딩페이지로 판정되어 폐기됐으면 같은 URL 의 browser
       fallback 을 시도하지 않고 PDF 변환으로 폴백 (제어흐름 2차 방어)
"""
import os

import main_terminal as mt


# ---------------------------------------------------------------------------
# Fix B: _is_paper_landing_url — route-scoped predicate
# ---------------------------------------------------------------------------

def test_is_paper_landing_url_arxiv():
    assert mt._is_paper_landing_url("https://arxiv.org/abs/2606.12344v1") is True
    assert mt._is_paper_landing_url("http://arxiv.org/abs/2606.12344") is True
    assert mt._is_paper_landing_url("https://www.arxiv.org/pdf/2606.12344v1") is True
    # 논문 상세 route 가 아니면 제외
    assert mt._is_paper_landing_url("https://arxiv.org/help/api") is False
    assert mt._is_paper_landing_url("https://arxiv.org/list/cs.AI/recent") is False


def test_is_paper_landing_url_other_hosts():
    assert mt._is_paper_landing_url("https://doi.org/10.1145/3512345") is True
    assert mt._is_paper_landing_url("https://dx.doi.org/10.1145/3512345") is True
    assert mt._is_paper_landing_url("https://openreview.net/forum?id=abc123") is True
    assert mt._is_paper_landing_url("https://openreview.net/pdf?id=abc123") is True
    assert mt._is_paper_landing_url("https://www.biorxiv.org/content/10.1101/2026.01.01.123456v1") is True
    assert mt._is_paper_landing_url("https://www.medrxiv.org/content/10.1101/2026.01.01.123456v1") is True
    assert mt._is_paper_landing_url("https://huggingface.co/papers/2606.12344") is True
    assert mt._is_paper_landing_url("https://www.alphaxiv.org/abs/2606.12344") is True


def test_is_paper_landing_url_general_web_not_flagged():
    # 일반 웹 아티클은 URL-first 유지 대상
    assert mt._is_paper_landing_url("https://news.hada.io/topic?id=30872") is False
    assert mt._is_paper_landing_url("https://huggingface.co/blog/some-post") is False
    assert mt._is_paper_landing_url("https://huggingface.co/meta-llama/Llama-4") is False
    assert mt._is_paper_landing_url("https://www.theregister.com/security/2026/06/15/story") is False
    assert mt._is_paper_landing_url("") is False
    assert mt._is_paper_landing_url("not a url") is False


# ---------------------------------------------------------------------------
# 제어흐름: _try_url_first_extraction
# ---------------------------------------------------------------------------

LANDING_MD = """# [2606.12344v1] Some Paper

View a PDF of the paper titled Some Paper, by A. Author

Abstract: ...

### Submission history
From: A. Author [v1] Mon, 1 Jun 2026 15:04:25 UTC

### arXivLabs: experimental projects with community collaborators
"""

PIPELINE = {"url_html_first": True, "browser_fallback": True}


def _write_md(output_dir, base_name, text):
    path = os.path.join(output_dir, f"{base_name}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def test_paper_landing_url_skips_url_first_entirely(tmp_path, monkeypatch):
    """Fix B: arXiv abs 사이드카면 추출기 자체가 호출되지 않고 즉시 None(PDF 변환)."""
    def fail_primary(*a, **k):
        raise AssertionError("primary extractor must not be called for paper landing URL")

    def fail_fallback(*a, **k):
        raise AssertionError("browser fallback must not be called for paper landing URL")

    monkeypatch.setattr(mt, "_url_to_markdown_html_first", fail_primary)
    monkeypatch.setattr(mt, "_url_to_markdown_browser_fallback", fail_fallback)

    got = mt._try_url_first_extraction(
        "http://arxiv.org/abs/2606.24855v1", str(tmp_path), "base", PIPELINE)
    assert got is None


def test_landing_rejection_skips_browser_fallback(tmp_path, monkeypatch):
    """Fix A: 1차 결과가 랜딩페이지로 폐기되면 같은 URL 의 fallback 을 재시도하지 않는다."""
    def fake_primary(source_url, output_dir, base_name, timeout=20):
        return _write_md(output_dir, base_name, LANDING_MD), {"ok": True, "chars": len(LANDING_MD)}

    def fail_fallback(*a, **k):
        raise AssertionError("browser fallback must not retry a condemned landing URL")

    monkeypatch.setattr(mt, "_url_to_markdown_html_first", fake_primary)
    monkeypatch.setattr(mt, "_url_to_markdown_browser_fallback", fail_fallback)

    # predicate 에 없는 신규 논문 사이트를 가정 (Fix B 미적용 → Fix A 가 막아야 함)
    got = mt._try_url_first_extraction(
        "https://papers.example.org/view/123", str(tmp_path), "base", PIPELINE)
    assert got is None
    assert not os.path.exists(os.path.join(str(tmp_path), "base.md"))


def test_generic_failure_still_tries_browser_fallback(tmp_path, monkeypatch):
    """일반 웹 아티클 회귀 방지: 1차가 평범하게 실패하면 fallback 은 그대로 탄다."""
    good_md_text = "# A Blog Post\n\n" + ("Real article body. " * 100)

    def fake_primary(source_url, output_dir, base_name, timeout=20):
        return None, {"ok": False, "reason": "too-short extracted text (300 chars)"}

    def fake_fallback(source_url, output_dir, base_name, timeout=25):
        return _write_md(output_dir, base_name, good_md_text), {"ok": True, "chars": len(good_md_text)}

    monkeypatch.setattr(mt, "_url_to_markdown_html_first", fake_primary)
    monkeypatch.setattr(mt, "_url_to_markdown_browser_fallback", fake_fallback)

    got = mt._try_url_first_extraction(
        "https://blog.example.com/post", str(tmp_path), "base", PIPELINE)
    assert got == os.path.join(str(tmp_path), "base.md")


def test_fallback_landing_result_is_discarded(tmp_path, monkeypatch):
    """fallback 결과가 랜딩페이지 스크랩이면 역시 폐기하고 PDF 변환으로 (기존 동작 유지)."""
    def fake_primary(source_url, output_dir, base_name, timeout=20):
        return None, {"ok": False, "reason": "HTTP Error 403: Forbidden"}

    def fake_fallback(source_url, output_dir, base_name, timeout=25):
        return _write_md(output_dir, base_name, LANDING_MD), {"ok": True, "chars": len(LANDING_MD)}

    monkeypatch.setattr(mt, "_url_to_markdown_html_first", fake_primary)
    monkeypatch.setattr(mt, "_url_to_markdown_browser_fallback", fake_fallback)

    got = mt._try_url_first_extraction(
        "https://papers.example.org/view/123", str(tmp_path), "base", PIPELINE)
    assert got is None
    assert not os.path.exists(os.path.join(str(tmp_path), "base.md"))
