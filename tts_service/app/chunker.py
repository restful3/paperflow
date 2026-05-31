import re

CHUNKER_VERSION = "paperflow-tts-chunker-v1"
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# R2-B2: 종결부호(+선택적 닫는 따옴표/괄호)를 '캡처'해 보존하고, 그 뒤에 sentinel(\x00)을 삽입한 뒤
# sentinel로 split → 닫는 따옴표가 split에 소비되지 않는다.
_SENT_BREAK = re.compile(r'([.!?…][”’"\')\]】」』]?)\s+')


def _slug(text, idx):
    s = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", text).strip("-").lower()
    return s or f"sec-{idx}"


def _split_sentences(para):
    marked = _SENT_BREAK.sub('\\1\x00', para.strip())   # 종결부호+따옴표 보존, 뒤에 sentinel(null)
    return [p.strip() for p in marked.split('\x00') if p.strip()]


def chunk_markdown(md: str):
    chunks = []
    section_id = "root"
    para_idx = 0
    n = 0
    # 블록 단위 분리(빈 줄 기준), 배너 blockquote(>) 제외
    blocks = re.split(r"\n\s*\n", md)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith(">"):  # 배너 blockquote → 합성 제외
            continue
        m = _HEADING.match(block)
        if m and "\n" not in block:
            text = m.group(2).strip()
            section_id = _slug(text, n)
            chunks.append({
                "id": n, "kind": "heading", "dom_id": f"tts-s-{n:06d}",
                "section_id": section_id, "paragraph_index": para_idx,
                "sentence_index": 0, "text": text,
            })
            n += 1
            continue
        # 문단: 문장 분할
        for s_i, sent in enumerate(_split_sentences(block)):
            chunks.append({
                "id": n, "kind": "text", "dom_id": f"tts-s-{n:06d}",
                "section_id": section_id, "paragraph_index": para_idx,
                "sentence_index": s_i, "text": sent,
            })
            n += 1
        para_idx += 1
    return chunks
