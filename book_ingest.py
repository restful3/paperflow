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


import main_terminal as mt   # heavy converter deps — imported at module load of the ingest entry


def _chapter_title(chapter_dir, chapter_id: str) -> str:
    """Chapter title: extracted paper_meta.json title, else the chapter_id."""
    pm = Path(chapter_dir) / "paper_meta.json"
    if pm.is_file():
        try:
            with open(pm, encoding="utf-8") as f:
                return json.load(f).get("title") or chapter_id
        except Exception:
            pass
    return chapter_id


def ingest_chapter(chapter_pdf, config=None, prompt=None, replace=False) -> dict:
    """Ingest one chapter PDF into books/<slug>/<chapter_id>/.

    Returns {"status": ..., "chapter_id": ...}. status ∈
    {complete, converted, error, skip, needs_review, order_conflict}.
    (dedup branching is wired in Task 6; this base path always processes.)
    """
    chapter_pdf = Path(chapter_pdf)
    slug = mt.sanitize_folder_name(chapter_pdf.parent.name) or chapter_pdf.parent.name
    book_dir = Path("books") / slug
    book_dir.mkdir(parents=True, exist_ok=True)

    book_store.init_book_meta(book_dir, slug)
    chapter_id = chapter_id_from_pdf(str(chapter_pdf))
    order = chapter_order_from_filename(chapter_pdf.name)
    new_sha = sha256_of(chapter_pdf)

    chapter_dir = book_dir / chapter_id
    chapter_dir.mkdir(parents=True, exist_ok=True)

    mt.process_pdf_to_output_dir(str(chapter_pdf), str(chapter_dir), chapter_id,
                                 config, prompt, mode="book_chapter")

    # durable meta upsert (under lock)
    with book_store.book_lock(book_dir):
        meta = book_store.load_book_meta(book_dir)
        title = _chapter_title(chapter_dir, chapter_id)
        book_store.upsert_chapter_meta(meta, chapter_id, order, title,
                                       chapter_pdf.name, new_sha)
        book_store.save_book_meta(book_dir, meta)

    # cache state (own lock — do NOT nest inside the meta lock above)
    fmts = book_store.detect_chapter_formats(chapter_dir)
    status = "complete" if fmts["ko"] else ("converted" if fmts["en"] else "error")
    book_store.update_chapter_state(book_dir, chapter_id, status, fmts)
    return {"status": status, "chapter_id": chapter_id}
