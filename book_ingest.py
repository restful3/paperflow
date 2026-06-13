"""PaperFlow Books — 챕터 인제스천 (newbooks/<Book>/NN_chapter.pdf → books/<slug>/).

챕터당 fresh process(VRAM cleanup)로 main_terminal.process_pdf_to_output_dir(
mode="book_chapter") 를 호출하고, book_store 로 durable meta + cache state 를
갱신한다. dedup/충돌 정책으로 재투입을 안전 처리한다.
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import book_store


def chapter_order_from_filename(name: str):
    """Leading NN_ / NN- prefix → int order; None if absent (caller natural-sorts)."""
    m = re.match(r"^(\d+)[_\-]", name)
    return int(m.group(1)) if m else None


def chapter_id_from_pdf(pdf_path: str) -> str:
    base = os.path.basename(pdf_path)
    return base[:-4] if base.lower().endswith(".pdf") else base


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_signature(path):
    st = os.stat(path)
    return (st.st_size, st.st_mtime_ns)


def is_size_stable(path, settle: float = 2.0) -> bool:
    """True if (size, mtime) is unchanged across a `settle`-second window.

    Guards against processing a file still being copied into newbooks/.
    """
    s1 = file_signature(path)
    time.sleep(settle)
    return file_signature(path) == s1


def classify_chapter(meta: dict, chapter_id: str, new_sha: str, new_order):
    """Dedup/conflict decision: 'new' | 'skip' | 'needs_review' | 'order_conflict'."""
    if new_order is not None:
        for ch in meta.get("chapters", []):
            if ch["chapter_id"] != chapter_id and ch.get("order") == new_order:
                return "order_conflict"
    for ch in meta.get("chapters", []):
        if ch["chapter_id"] == chapter_id:
            return "skip" if ch.get("source_sha256") == new_sha else "needs_review"
    return "new"
