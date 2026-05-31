from app.chunker import chunk_markdown


def test_heading_and_sentences():
    md = "# 서론\n\n첫 문장입니다. 둘째 문장이에요.\n\n## 방법\n\n셋째 문장."
    chunks = chunk_markdown(md)
    kinds = [(c["kind"], c["text"]) for c in chunks]
    assert kinds == [
        ("heading", "서론"),
        ("text", "첫 문장입니다."),
        ("text", "둘째 문장이에요."),
        ("heading", "방법"),
        ("text", "셋째 문장."),
    ]
    assert chunks[0]["dom_id"] == "tts-s-000000"
    assert chunks[4]["dom_id"] == "tts-s-000004"
    assert chunks[3]["section_id"] == chunks[4]["section_id"]  # 둘 다 "방법" 섹션


def test_banner_blockquote_excluded():
    md = "# 제목 — 듣기판\n\n> 이 글은 듣기판입니다.\n\n본문 문장."
    chunks = chunk_markdown(md)
    assert all("듣기판입니다" not in c["text"] for c in chunks)
    assert [c["kind"] for c in chunks] == ["heading", "text"]


def test_short_sentence_is_own_chunk():
    # MVP: 1문장=1합성단위 (짧아도 묶지 않음)
    md = "네. 아니요. 그렇습니다."
    chunks = chunk_markdown(md)
    assert [c["text"] for c in chunks] == ["네.", "아니요.", "그렇습니다."]


def test_closing_quote_after_period_splits():   # nit#1
    md = '그는 "좋다." 라고 말했다. 다음 문장.'
    texts = [c["text"] for c in chunk_markdown(md)]
    assert texts == ['그는 "좋다."', "라고 말했다.", "다음 문장."]


def test_heading_level_captured():
    chunks = chunk_markdown("# A\n\n본문.\n\n### B\n\n또 본문.")
    headings = [c for c in chunks if c["kind"] == "heading"]
    assert headings[0]["level"] == 1
    assert headings[1]["level"] == 3


# ── HLS sub-split (Task 2) ────────────────────────────────────────────────────
from app.chunker import SENTENCE_CHAR_CAP


def test_short_sentence_single_subchunk():
    chunks = chunk_markdown("짧은 문장입니다.")
    assert chunks[0]["sub_count"] == 1
    assert chunks[0]["sub_index"] == 0
    assert chunks[0]["sentence_group_id"] == chunks[0]["display_sentence_index"]


def test_long_sentence_subsplit_shares_group():
    long = "가" * (SENTENCE_CHAR_CAP * 2) + "."     # cap 2배 → 최소 2 sub-chunk
    chunks = [c for c in chunk_markdown(long) if c["kind"] == "text"]
    assert len(chunks) >= 2
    gids = {c["sentence_group_id"] for c in chunks}
    assert len(gids) == 1                            # 같은 UI 문장 그룹
    assert [c["sub_index"] for c in chunks] == list(range(len(chunks)))
    assert all(c["sub_count"] == len(chunks) for c in chunks)
    assert all(len(c["text"]) <= SENTENCE_CHAR_CAP for c in chunks)


def test_subsplit_on_punctuation_boundary():
    # 공백/구두점 경계로 분할되는지 (강제 슬라이스 아닌 케이스)
    sent = ("문장 " * 60).strip() + "."           # 공백 많은 긴 문장 (>85자)
    chunks = [c for c in chunk_markdown(sent) if c["kind"] == "text"]
    assert len(chunks) >= 2
    assert all(len(c["text"]) <= SENTENCE_CHAR_CAP for c in chunks)
