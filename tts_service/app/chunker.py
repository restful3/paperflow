import re

CHUNKER_VERSION = "paperflow-tts-chunker-v1"
SENTENCE_CHAR_CAP = 85   # Task 0 실측값 (docs/research/2026-05-31-hls-tts-measurement.md)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# 이미지 전용 라인(![](경로) / ![alt](경로)) — 낭독 대상이 아니므로 청킹 전 제거한다.
# 스킬이 그림 설명문을 직전 문단에 따로 두므로 정보 손실 없음. (남기면 TTS 가 긴 hex
# 파일명에서 wedge 해 합성이 통째로 실패함.)
_IMAGE_LINE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
# R2-B2: 종결부호(+선택적 닫는 따옴표/괄호)를 '캡처'해 보존하고, 그 뒤에 sentinel(\x00)을 삽입한 뒤
# sentinel로 split → 닫는 따옴표가 split에 소비되지 않는다.
_SENT_BREAK = re.compile(r'([.!?…][”’"\')\]】」』]?)\s+')


def _slug(text, idx):
    s = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", text).strip("-").lower()
    return s or f"sec-{idx}"


def _split_sentences(para):
    marked = _SENT_BREAK.sub('\\1\x00', para.strip())   # 종결부호+따옴표 보존, 뒤에 sentinel(null)
    return [p.strip() for p in marked.split('\x00') if p.strip()]


def _subsplit(sent):
    """SENTENCE_CHAR_CAP 초과 문장을 구두점/공백 경계로 분할(없으면 강제 슬라이스)."""
    if len(sent) <= SENTENCE_CHAR_CAP:
        return [sent]
    parts, buf = [], ""
    for tok in re.split(r"(?<=[,;:、，])\s+|\s+", sent):
        cand = (buf + " " + tok).strip() if buf else tok
        if len(cand) <= SENTENCE_CHAR_CAP:
            buf = cand
        else:
            if buf:
                parts.append(buf)
            while len(tok) > SENTENCE_CHAR_CAP:        # 단일 토큰도 초과면 강제 슬라이스
                parts.append(tok[:SENTENCE_CHAR_CAP]); tok = tok[SENTENCE_CHAR_CAP:]
            buf = tok
    if buf:
        parts.append(buf)
    return parts


def chunk_markdown(md: str):
    # 이미지 전용 라인 제거(낭독 비대상 + TTS wedge 방지)
    md = "\n".join(ln for ln in md.splitlines() if not _IMAGE_LINE.match(ln))
    chunks = []
    section_id = "root"
    para_idx = 0
    n = 0
    group_seq = 0   # UI 문장 그룹 id(heading/문장 단위로 증가, sub-chunk가 공유)
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
            level = len(m.group(1))          # '#' 개수
            section_id = _slug(text, n)
            chunks.append({
                "id": n, "kind": "heading", "level": level, "dom_id": f"tts-s-{n:06d}",
                "section_id": section_id, "paragraph_index": para_idx,
                "sentence_index": 0,
                "sentence_group_id": group_seq, "sub_index": 0, "sub_count": 1,
                "display_sentence_index": group_seq,
                "start_sec": None, "end_sec": None, "text": text,
            })
            n += 1
            group_seq += 1
            continue
        # 문단: 문장 분할 → 긴 문장은 sub-split(같은 group 공유)
        for s_i, sent in enumerate(_split_sentences(block)):
            subs = _subsplit(sent)
            for j, sub in enumerate(subs):
                chunks.append({
                    "id": n, "kind": "text", "dom_id": f"tts-s-{n:06d}",
                    "section_id": section_id, "paragraph_index": para_idx,
                    "sentence_index": s_i,
                    "sentence_group_id": group_seq, "sub_index": j, "sub_count": len(subs),
                    "display_sentence_index": group_seq,
                    "start_sec": None, "end_sec": None, "text": sub,
                })
                n += 1
            group_seq += 1
        para_idx += 1
    return chunks
