"""TTS 청커 이미지 라인 스킵 테스트.

배경: paper-audio-korean 스킬은 뷰어 렌더링용으로 `![](경로)` 이미지를 본문에
임베딩한다(설명문은 직전 문단에 별도로 둠). 그런데 TTS 청커가 이 이미지 라인을
텍스트 청크로 넘기면 VoxCPM2 가 긴 hex 파일명에서 wedge(멈춤)해 합성이 통째로
실패한다. 이미지 라인은 낭독 대상이 아니므로 청커가 스킵해야 한다.
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.chunker import chunk_markdown


def _texts(md):
    return [c["text"] for c in chunk_markdown(md)]


def test_standalone_image_line_skipped():
    md = (
        "# 제목\n\n"
        "그림 일 번은 프레임워크 도식을 보여 줍니다.\n\n"
        "![](images/a8311bc7de0672b570f95a63d69f182830b1c55cadab6e29dc5b4c0767465600.jpg)\n\n"
        "이제 절차를 단계별로 따라가 봅니다.\n"
    )
    texts = _texts(md)
    # 어떤 청크에도 이미지 마크다운이 남으면 안 됨
    assert not any("![](" in t for t in texts), texts
    # 설명문/후속 문장은 보존
    assert any("프레임워크 도식" in t for t in texts)
    assert any("단계별로" in t for t in texts)


def test_image_with_alt_text_also_skipped():
    md = "본문 문장입니다.\n\n![figure 1](path/to/fig.png)\n\n다음 문장입니다.\n"
    texts = _texts(md)
    assert not any("![" in t for t in texts), texts
    assert any("본문 문장" in t for t in texts)
    assert any("다음 문장" in t for t in texts)


def test_image_inline_in_text_block_removed_text_preserved():
    # 이미지 라인이 빈 줄 없이 설명문 바로 다음 줄에 붙은 경우에도 텍스트는 보존
    md = "그림 이 번은 곡선을 보여 줍니다.\n![](_page_4_Figure_2.jpeg)\n"
    texts = _texts(md)
    assert not any("![](" in t for t in texts), texts
    assert any("곡선을 보여 줍니다" in t for t in texts)


def test_plain_paragraphs_unaffected():
    md = "# 머리말\n\n첫째 문장입니다. 둘째 문장입니다.\n\n다른 문단입니다.\n"
    texts = _texts(md)
    assert any("첫째 문장" in t for t in texts)
    assert any("둘째 문장" in t for t in texts)
    assert any("다른 문단" in t for t in texts)
    assert "머리말" in texts
