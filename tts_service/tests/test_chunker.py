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
