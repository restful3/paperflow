"""URL-first 랜딩페이지 스크랩 감지 가드 테스트.

배경: process_single_pdf 의 URL-first 경로가 arXiv `/abs/` 페이지 HTML 을 긁어
1200자만 넘으면 "성공"으로 보고 실제 PDF 변환을 건너뛰는 버그가 있었다.
그 결과 본문이 초록 랜딩페이지 보일러플레이트로 채워졌다. 이 가드는 그런 스크랩을
감지해 거부하고 PDF 변환으로 폴백시킨다.
"""
import main_terminal as mt


# 실제로 문제가 됐던 arXiv /abs/ 랜딩페이지 스크랩의 대표 조각
LANDING = """# [2606.02357v1] Do Multimodal Agents Really Benefit from Tool Use?

View a PDF of the paper titled Do Multimodal Agents Really Benefit from Tool Use, by Garvin Guo and 8 other authors

Abstract: Tool-augmented multimodal agents show strong benchmark gains ...

### Submission history
From: Jiawei Guo [ view email ] [v1] Mon, 1 Jun 2026 15:04:25 UTC (1,002 KB)

Connected Papers Toggle
Bibliographic Explorer ( What is the Explorer? )

### arXivLabs: experimental projects with community collaborators
Which authors of this paper are endorsers? | Disable MathJax
"""

# 정상 논문 본문(랜딩페이지 마커 없음)
REAL_PAPER = """# Attention Is All You Need

## Abstract
The dominant sequence transduction models are based on complex recurrent or
convolutional neural networks. We propose the Transformer, based solely on
attention mechanisms.

## 1 Introduction
Recurrent neural networks, long short-term memory and gated recurrent neural
networks in particular, have been firmly established as state of the art.

## 2 Background
The goal of reducing sequential computation also forms the foundation of the
Extended Neural GPU, ByteNet and ConvS2S.
"""


def test_detects_arxiv_landing_page_scrape():
    assert mt._looks_like_paper_landing_page(LANDING) is True


def test_real_paper_body_not_flagged():
    assert mt._looks_like_paper_landing_page(REAL_PAPER) is False


def test_empty_or_short_not_flagged():
    assert mt._looks_like_paper_landing_page("") is False
    assert mt._looks_like_paper_landing_page("# Title\n\nA short note.") is False


def test_single_incidental_marker_not_flagged():
    # 본문에 우연히 한 문구만 등장(예: 관련연구에서 'Submission history' 언급)해도
    # 오탐하지 않도록 — 2개 이상 마커일 때만 랜딩페이지로 판정
    text = REAL_PAPER + "\nSee the Submission history for details.\n"
    assert mt._looks_like_paper_landing_page(text) is False
