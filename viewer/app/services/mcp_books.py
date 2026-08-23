"""MCP book job orchestration.

Book jobs intentionally use a separate index from paper jobs because the job
shape is batch/chapter-oriented and reconciles against book_meta/book_state.
"""
from __future__ import annotations

import asyncio
import base64 as _b64
import datetime as _dt
import json
import os
import re
import time as _time
import uuid as _uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..config import settings
from . import books as book_svc
from . import papers as paper_svc


_index_lock = asyncio.Lock()
_CHAPTER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}$")
_MAX_CHAPTER_BYTES = 200 * 1024 * 1024
_MAX_BATCH_BYTES = 1024 * 1024 * 1024


class BookChapterSubmit(BaseModel):
    chapter_id: str
    file_base64: str
    order: int | None = None
    filename: str | None = None
    title: str | None = None


class BookChapterJob(BaseModel):
    chapter_id: str
    order: int
    source_filename: str
    title: str | None = None
    status: str = "queued"
    formats: dict = Field(default_factory=dict)


class BookJobRecord(BaseModel):
    job_id: str
    book_id: str
    book_slug: str
    title: str
    author: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    status: Literal["queued", "processing", "partial", "complete", "error", "cancelled", "stalled"]
    stage: str | None = None
    percent: int = 0
    chapters: list[BookChapterJob]
    error: str | None = None
    submitted_at: str
    completed_at: str | None = None
    expires_at: str


def _index_path() -> Path:
    return settings.logs_dir / "mcp_book_jobs.json"


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _expires_at_iso() -> str:
    return (_dt.datetime.now() + _dt.timedelta(days=settings.MCP_JOB_TTL_DAYS)).isoformat(timespec="seconds")


async def _load_index() -> dict[str, dict]:
    p = _index_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        quarantine = settings.logs_dir / f"mcp_book_jobs.corrupt.{ts}.json"
        try:
            p.rename(quarantine)
        except Exception:
            pass
        return {}


async def _atomic_write_index(jobs: dict[str, dict]) -> None:
    p = _index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    data = json.dumps(jobs, ensure_ascii=False, indent=2).encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


async def _set_job_fields(job_id: str, **fields) -> None:
    async with _index_lock:
        idx = await _load_index()
        if job_id not in idx:
            return
        idx[job_id].update(fields)
        await _atomic_write_index(idx)


def _validate_chapter_id(chapter_id: str) -> str:
    chapter_id = (chapter_id or "").strip()
    if not _CHAPTER_ID_RE.fullmatch(chapter_id):
        raise ValueError(f"invalid chapter_id: {chapter_id!r}")
    if "/" in chapter_id or "\\" in chapter_id or "\x00" in chapter_id:
        raise ValueError(f"invalid chapter_id: {chapter_id!r}")
    return chapter_id


def _decode_pdf(chapter: BookChapterSubmit) -> bytes:
    try:
        data = _b64.b64decode(chapter.file_base64, validate=True)
    except Exception as e:
        raise ValueError(f"invalid base64 for chapter {chapter.chapter_id}: {e}") from e
    if len(data) > _MAX_CHAPTER_BYTES:
        raise ValueError(f"chapter {chapter.chapter_id} exceeds 200MB limit")
    if not data.startswith(b"%PDF-"):
        raise ValueError(f"chapter {chapter.chapter_id} is not a PDF")
    return data


def _chapter_filename(chapter: BookChapterSubmit) -> str:
    safe_id = _validate_chapter_id(chapter.chapter_id)
    candidate = chapter.filename or f"{safe_id}.pdf"
    safe = paper_svc._safe_filename(candidate) or f"{safe_id}.pdf"
    if not safe.lower().endswith(".pdf"):
        safe = f"{safe}.pdf"
    return safe


def _read_processing_status() -> dict:
    p = settings.logs_dir / "processing_status.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _chapter_formats(chapter_dir: Path) -> dict:
    if not chapter_dir.is_dir():
        return {}
    try:
        return paper_svc.paper_info_from_dir(chapter_dir, "books")["formats"]
    except Exception:
        return {}


def _status_from_formats(formats: dict) -> str | None:
    if formats.get("md_ko"):
        return "complete"
    if formats.get("md_en"):
        return "converted"
    return None


async def submit_book_chapters(
    *,
    title: str,
    chapters: list[dict | BookChapterSubmit],
    author: str | None = None,
    authors: list[str] | None = None,
    year: int | None = None,
    metadata: dict | None = None,
) -> BookJobRecord:
    """Validate the whole batch, then publish it atomically under newbooks/."""
    if not title or not title.strip():
        raise ValueError("title is required")
    if not chapters:
        raise ValueError("at least one chapter is required")

    parsed = [c if isinstance(c, BookChapterSubmit) else BookChapterSubmit.model_validate(c)
              for c in chapters]
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    normalized: list[tuple[BookChapterSubmit, bytes, int, str]] = []
    total_bytes = 0
    for pos, ch in enumerate(parsed, 1):
        safe_id = _validate_chapter_id(ch.chapter_id)
        if safe_id in seen_ids:
            raise ValueError(f"duplicate chapter_id: {safe_id}")
        seen_ids.add(safe_id)
        order = ch.order if ch.order is not None else pos
        if order < 1:
            raise ValueError(f"invalid order for chapter {safe_id}: {order}")
        if order in seen_orders:
            raise ValueError(f"duplicate chapter order: {order}")
        seen_orders.add(order)
        data = _decode_pdf(ch)
        total_bytes += len(data)
        if total_bytes > _MAX_BATCH_BYTES:
            raise ValueError("book batch exceeds 1GB limit")
        normalized.append((ch, data, order, _chapter_filename(ch)))

    normalized.sort(key=lambda item: item[2])
    ordered_files = [(filename, data) for ch, data, _order, filename in normalized]
    book_id = f"book-{_uuid.uuid4().hex}"
    ok, msg, slug, saved_book_id = await asyncio.to_thread(
        book_svc.save_book_upload_atomic,
        title,
        author,
        year,
        ordered_files,
        book_id=book_id,
        authors=authors,
        extra_meta=metadata,
    )
    if not ok or not slug or not saved_book_id:
        raise ValueError(msg)

    chapter_jobs = [
        BookChapterJob(
            chapter_id=f"{i:02d}_{Path(filename).stem}",
            order=i,
            source_filename=f"{i:02d}_{Path(filename).stem}.pdf",
            title=ch.title,
        )
        for i, (ch, _data, _order, filename) in enumerate(normalized, 1)
    ]
    rec = BookJobRecord(
        job_id=str(_uuid.uuid4()),
        book_id=saved_book_id,
        book_slug=slug,
        title=title.strip(),
        author=author.strip() if author and author.strip() else None,
        authors=[a.strip() for a in (authors or []) if a and a.strip()],
        year=year,
        status="queued",
        stage=None,
        percent=0,
        chapters=chapter_jobs,
        error=None,
        submitted_at=_now_iso(),
        completed_at=None,
        expires_at=_expires_at_iso(),
    )
    async with _index_lock:
        idx = await _load_index()
        idx[rec.job_id] = rec.model_dump()
        await _atomic_write_index(idx)
    return rec


async def get_book_job(job_id: str) -> BookJobRecord | None:
    async with _index_lock:
        idx = await _load_index()
    raw = idx.get(job_id)
    return BookJobRecord.model_validate(raw) if raw else None


async def reconcile_book_job(job_id: str) -> BookJobRecord | None:
    rec = await get_book_job(job_id)
    if not rec:
        return None
    if rec.status in ("error", "cancelled"):
        return rec

    processing_status = _read_processing_status()
    current = processing_status.get("current_file")
    current_stem = Path(str(current)).stem if current else None
    current_stage = processing_status.get("stage")
    newbook_dir = settings.newbooks_dir / rec.book_slug
    book_dir = settings.books_dir / rec.book_slug
    meta = book_svc.load_book_meta(book_dir) if book_dir.is_dir() else None
    state = book_svc.load_book_state(book_dir) if book_dir.is_dir() else None
    state_chapters = (state or {}).get("chapters") or {}

    refreshed: list[BookChapterJob] = []
    status_counts: dict[str, int] = {}
    for ch in rec.chapters:
        cid = ch.chapter_id
        chapter_dir = book_dir / cid
        formats = _chapter_formats(chapter_dir)
        if current_stem == cid and current_stage not in ("idle", "complete", "error"):
            status = "processing"
        else:
            state_status = (state_chapters.get(cid) or {}).get("pipeline_status")
            status = state_status or _status_from_formats(formats)
            if not status and (newbook_dir / ch.source_filename).is_file():
                status = "queued"
            status = status or "queued"
        status_counts[status] = status_counts.get(status, 0) + 1
        refreshed.append(ch.model_copy(update={"status": status, "formats": formats}))

    total = len(refreshed) or 1
    complete_count = status_counts.get("complete", 0)
    percent = int(complete_count * 100 / total)
    terminal_bad = {"error", "needs_review", "order_conflict"}
    if any(c.status in terminal_bad for c in refreshed):
        overall = "error"
        err = "one or more chapters failed or need review"
    elif complete_count == len(refreshed) and meta:
        overall = "complete"
        err = None
        percent = 100
    elif any(c.status in ("processing", "translating") for c in refreshed):
        overall = "processing"
        err = None
    elif any(c.status == "converted" for c in refreshed):
        overall = "partial"
        err = "one or more chapters are converted but missing Korean translation"
    else:
        overall = "queued"
        err = None

    updates = {
        "status": overall,
        "stage": current_stage if overall == "processing" else None,
        "percent": percent,
        "chapters": [c.model_dump() for c in refreshed],
        "error": err,
    }
    if overall in ("complete", "error") and not rec.completed_at:
        updates["completed_at"] = _now_iso()
    await _set_job_fields(job_id, **updates)
    return await get_book_job(job_id)


async def list_book_jobs(limit: int = 50, status: str | None = None) -> list[BookJobRecord]:
    async with _index_lock:
        idx = await _load_index()
    records: list[BookJobRecord] = []
    for raw in idx.values():
        try:
            records.append(BookJobRecord.model_validate(raw))
        except Exception:
            pass
    records.sort(key=lambda r: r.submitted_at, reverse=True)
    reconciled = []
    for rec in records:
        refreshed = await reconcile_book_job(rec.job_id)
        if refreshed:
            reconciled.append(refreshed)
    if status:
        reconciled = [r for r in reconciled if r.status == status]
    reconciled.sort(key=lambda r: r.submitted_at, reverse=True)
    return reconciled[: min(limit, 100)]


async def cleanup_expired_book_jobs() -> int:
    now = _dt.datetime.now().isoformat(timespec="seconds")
    removed = 0
    async with _index_lock:
        idx = await _load_index()
        for job_id in list(idx.keys()):
            rec = idx[job_id]
            if rec.get("status") in ("complete", "error", "cancelled") \
               and rec.get("expires_at") and rec["expires_at"] < now:
                del idx[job_id]
                removed += 1
        if removed:
            await _atomic_write_index(idx)

    tmp_dir = settings.newbooks_dir / ".mcp_tmp"
    cutoff = _time.time() - 3600
    if tmp_dir.exists():
        for p in tmp_dir.iterdir():
            try:
                if p.is_dir() and p.stat().st_mtime < cutoff:
                    import shutil
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
    return removed
