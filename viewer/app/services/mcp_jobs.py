"""MCP job orchestration: submit, reconcile, cancel, cleanup.

JobRecord index persisted to logs/mcp_jobs.json (atomic replace).
Single-worker viewer assumption — module-level asyncio.Lock for index access.
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
from typing import Iterator, Literal

from pydantic import BaseModel


# ── Module state ──────────────────────────────────────────────────────────────
_active_download_tasks: dict[str, asyncio.Task] = {}
_index_lock = asyncio.Lock()

_MAX_FILE_BYTES = 200 * 1024 * 1024  # 200MB hard limit for file submit
_STALLED_AFTER_SECONDS = 30 * 60  # converter must have moved off this job for 30 min


# ── Models ────────────────────────────────────────────────────────────────────
class JobOptions(BaseModel):
    force_reprocess: bool = False


class JobRecord(BaseModel):
    job_id: str
    input_type: Literal["url", "file"]
    source: str
    expected_filename: str
    import_method: Literal["direct_pdf", "html_fallback", "site_transform", "file_upload"] | None
    options: JobOptions
    status: Literal["downloading", "queued", "processing", "complete", "error", "cancelled", "stalled"]
    stage: str | None
    percent: int
    paper_name: str | None
    location: Literal["outputs", "archives"] | None
    error: str | None
    submitted_at: str
    completed_at: str | None
    expires_at: str


# ── Index I/O ─────────────────────────────────────────────────────────────────
def _index_path() -> Path:
    from ..config import settings
    return settings.logs_dir / "mcp_jobs.json"


async def _load_index() -> dict[str, dict]:
    """Load mcp_jobs.json. On corruption, quarantine + return empty."""
    from ..config import settings
    p = _index_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        quarantine = settings.logs_dir / f"mcp_jobs.corrupt.{ts}.json"
        try:
            p.rename(quarantine)
        except Exception:
            pass
        return {}


async def _atomic_write_index(jobs: dict[str, dict]) -> None:
    """tmp write → fsync → os.replace."""
    p = _index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    data = json.dumps(jobs, ensure_ascii=False, indent=2).encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


# ── Filename helper ───────────────────────────────────────────────────────────
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

# by-id route: source_id == paperflow_source_id == expected_filename,
# 형식이 항상 pfmcp-{job_id[:12]}-{slug[:40]}.pdf 로 고정 (_build_expected_filename).
# contract 까지 검증해 임의 안전 파일명(paper_meta.json, foo.pdf, .hidden) probing 차단.
_SOURCE_ID_SAFE_RE = re.compile(r"^pfmcp-[A-Za-z0-9._-]{1,120}\.pdf$")


def _build_expected_filename(job_id: str, slug_source: str) -> str:
    """pfmcp-{job_id[:12]}-{safe_slug[:40]}.pdf — guaranteed unique per job_id."""
    short = job_id.replace("-", "")[:12]
    slug = _FILENAME_SAFE_RE.sub("-", (slug_source or "doc").strip().lower())[:40]
    slug = slug.strip("-") or "doc"
    return f"pfmcp-{short}-{slug}.pdf"


# ── Publish helpers ───────────────────────────────────────────────────────────
def _write_part_file(pdf_bytes: bytes, part_path: Path) -> None:
    """Sync helper called via asyncio.to_thread. Write .part + fsync. NO replace."""
    part_path.parent.mkdir(parents=True, exist_ok=True)
    with open(part_path, "wb") as f:
        f.write(pdf_bytes)
        f.flush()
        os.fsync(f.fileno())


def _atomic_publish_part(part_path: Path, dest_path: Path) -> None:
    """Sync 1ms atomic call — separate from _write_part_file so cancel can intervene."""
    os.replace(part_path, dest_path)


# ── Submit ────────────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _expires_at_iso() -> str:
    from ..config import settings
    return (_dt.datetime.now() + _dt.timedelta(days=settings.MCP_JOB_TTL_DAYS)).isoformat(timespec="seconds")


def _slug_from_source(input_type: str, source: str) -> str:
    if input_type == "url":
        try:
            from urllib.parse import urlparse
            host = urlparse(source).netloc.lower()
            return host or source
        except Exception:
            return source
    # file
    return Path(source).stem or source


async def submit_job(
    input_type: Literal["url", "file"],
    source: str,
    options: JobOptions,
    *,
    pdf_bytes_b64: str | None = None,
) -> JobRecord:
    """Create a new job. URL = background download. File = synchronous publish."""
    if input_type not in ("url", "file"):
        raise ValueError(f"input_type must be url or file, got {input_type!r}")
    if input_type == "file" and not pdf_bytes_b64:
        raise ValueError("file submission requires pdf_bytes_b64")

    from ..config import settings

    job_id = str(_uuid.uuid4())
    expected_filename = _build_expected_filename(job_id, _slug_from_source(input_type, source))
    dest = settings.newones_dir / expected_filename

    if input_type == "file":
        # Decode + validate
        try:
            pdf_bytes = _b64.b64decode(pdf_bytes_b64, validate=True)
        except Exception as e:
            raise ValueError(f"invalid base64: {e}") from e
        if len(pdf_bytes) > _MAX_FILE_BYTES:
            raise ValueError("file exceeds 200MB limit")
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError("not a PDF (magic byte mismatch)")

        # 2-stage publish: write .part (in thread), then short atomic replace
        part_path = dest.with_suffix(dest.suffix + ".part")
        try:
            await asyncio.to_thread(_write_part_file, pdf_bytes, part_path)
            _atomic_publish_part(part_path, dest)
        except BaseException:
            part_path.unlink(missing_ok=True)
            raise

        rec = JobRecord(
            job_id=job_id, input_type="file", source=source,
            expected_filename=expected_filename,
            import_method="file_upload",
            options=options, status="queued", stage=None, percent=0,
            paper_name=None, location=None, error=None,
            submitted_at=_now_iso(), completed_at=None,
            expires_at=_expires_at_iso(),
        )
    else:
        # URL: check cache first unless force_reprocess
        from . import papers as _papers
        if not options.force_reprocess:
            hit = _papers.find_processed_paper(source_url=source)
            if hit and not (hit.get("original_filename", "") or "").startswith("web-"):
                # cached complete — synthesize a complete record
                rec = JobRecord(
                    job_id=job_id, input_type="url", source=source,
                    expected_filename=expected_filename,
                    import_method=None,
                    options=options, status="complete", stage=None, percent=100,
                    paper_name=hit["name"], location=hit["location"],
                    error=None,
                    submitted_at=_now_iso(),
                    completed_at=_now_iso(),
                    expires_at=_expires_at_iso(),
                )
                async with _index_lock:
                    idx = await _load_index()
                    idx[job_id] = rec.model_dump()
                    await _atomic_write_index(idx)
                return rec

        # Not cached: URL background task does the work
        rec = JobRecord(
            job_id=job_id, input_type="url", source=source,
            expected_filename=expected_filename,
            import_method=None,
            options=options, status="downloading", stage=None, percent=0,
            paper_name=None, location=None, error=None,
            submitted_at=_now_iso(), completed_at=None,
            expires_at=_expires_at_iso(),
        )

    async with _index_lock:
        idx = await _load_index()
        idx[job_id] = rec.model_dump()
        await _atomic_write_index(idx)

    # URL: spawn bg downloader after index write
    if input_type == "url":
        task = asyncio.create_task(_download_and_publish(job_id, source, expected_filename))
        _active_download_tasks[job_id] = task
        task.add_done_callback(lambda _t: _active_download_tasks.pop(job_id, None))

    return rec


async def get_job(job_id: str) -> JobRecord | None:
    async with _index_lock:
        idx = await _load_index()
    raw = idx.get(job_id)
    return JobRecord.model_validate(raw) if raw else None


# ── URL background downloader (Stage 1 + Stage 2) ─────────────────────────────
async def _set_job_fields(job_id: str, **fields) -> None:
    """Update specific fields on a JobRecord under lock."""
    async with _index_lock:
        idx = await _load_index()
        if job_id not in idx:
            return
        idx[job_id].update(fields)
        await _atomic_write_index(idx)


async def _download_and_publish(job_id: str, url: str, expected_filename: str) -> None:
    """Background task: resolve URL → write .part → atomic publish under lock."""
    from . import papers as _papers
    from ..config import settings
    dest = settings.newones_dir / expected_filename
    part_path = dest.with_suffix(dest.suffix + ".part")
    try:
        # Stage 0: blocking URL resolve in worker thread
        pdf_bytes, _final_url, import_method = await asyncio.to_thread(
            _papers._resolve_url_to_pdf_bytes, url
        )
        # Stage 1: blocking .part write in worker thread (cancellable between stages)
        await asyncio.to_thread(_write_part_file, pdf_bytes, part_path)
        # Stage 2: lock + status re-check + atomic publish (race-free)
        async with _index_lock:
            idx = await _load_index()
            rec = idx.get(job_id)
            if not rec or rec["status"] != "downloading":
                # cancelled/error/superseded — abort publish
                part_path.unlink(missing_ok=True)
                return
            _atomic_publish_part(part_path, dest)
            idx[job_id]["status"] = "queued"
            idx[job_id]["import_method"] = import_method
            await _atomic_write_index(idx)
        # Source sidecar (best effort)
        try:
            _papers._write_source_sidecar(expected_filename, url)
        except Exception:
            pass
    except asyncio.CancelledError:
        part_path.unlink(missing_ok=True)
        # status update handled by canceller (cancel_job or cancel_all_active_downloads)
        raise
    except Exception as e:
        part_path.unlink(missing_ok=True)
        await _set_job_fields(job_id, status="error", error=str(e)[:400],
                               completed_at=_now_iso())


# ── Reconcile ─────────────────────────────────────────────────────────────────
def _is_safe_direct_child(base: Path, candidate: Path) -> bool:
    """True iff `candidate` is a direct child of `base` and resolves within `base`
    (symlink-resolved). Prevents scan helpers from following symlinks that
    escape outputs/ or archives/.

    Mirrors `papers._safe_child_dir` containment logic without depending on
    papers.py internals (v1.1 keeps papers.py untouched).
    """
    try:
        base_resolved = base.resolve(strict=True)
        cand_resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError):
        return False
    if cand_resolved.parent != base_resolved:
        return False
    if not cand_resolved.is_dir():
        return False
    return True


def _paper_has_ko_md(paper_dir: Path) -> bool | None:
    """Returns:
      - True  if paper_dir exists and contains *_ko.md (excluding _ko_explained.md)
      - False if paper_dir exists but has no qualifying *_ko.md
      - None  if paper_dir does not exist or is inaccessible (race / external cleanup)
    """
    try:
        if not paper_dir.is_dir():
            return None
        for p in paper_dir.iterdir():
            name = p.name
            if (name.endswith("_ko.md")
                    and not name.endswith("_ko_explained.md")
                    and p.is_file()):
                return True
        return False
    except (PermissionError, OSError):
        return None


def _scan_outputs_dir_only(expected_filename: str) -> str | None:
    """Scan outputs/ ONLY for a direct-child folder containing expected_filename.
    Returns the folder name (str) or None. archives/ is never touched.
    Symlinks that escape outputs/ are rejected by `_is_safe_direct_child`.
    """
    from ..config import settings
    base = settings.outputs_dir
    if not base.exists():
        return None
    for sub in base.iterdir():
        if not _is_safe_direct_child(base, sub):
            continue
        if (sub / expected_filename).is_file():
            return sub.name
    return None


def _scan_archives_dir_only(expected_filename: str) -> str | None:
    """Same as _scan_outputs_dir_only but for archives/."""
    from ..config import settings
    base = settings.archives_dir
    if not base.exists():
        return None
    for sub in base.iterdir():
        if not _is_safe_direct_child(base, sub):
            continue
        if (sub / expected_filename).is_file():
            return sub.name
    return None


def _find_metadata_match_in_dir(base: Path, expected_filename: str) -> str | None:
    """Scan a single directory (outputs/ XOR archives/) for a direct-child
    folder whose paper_meta.json records original_filename == expected_filename.
    Returns the folder name (str) or None. Read-only — never writes or follows
    symlinks out of `base`.

    rev4 R3 H#1: replaces `papers.find_processed_paper` in the MCP reconcile
    path so outputs metadata can be discovered independently of newest-wins sort.
    """
    if not base.exists():
        return None
    for sub in base.iterdir():
        if not _is_safe_direct_child(base, sub):
            continue
        meta_path = sub / "paper_meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("original_filename") == expected_filename:
            return sub.name
    return None


def _resolve_completed_candidate(expected_filename: str) -> tuple[str, str] | None:
    """Locate the paper folder that should correspond to expected_filename.
    Returns (paper_name, location) or None.

    Strict 4-step priority — outputs always wins:
      1. outputs metadata match
      2. outputs filesystem scan (source PDF presence)
      3. archives metadata match
      4. archives filesystem scan

    Steps 1–2 use MCP-internal helpers that ignore archives entirely, so
    outputs always wins regardless of newest-wins sort, mtime, or whether
    the source PDF was moved.
    """
    from ..config import settings

    name = _find_metadata_match_in_dir(settings.outputs_dir, expected_filename)
    if name:
        return name, "outputs"

    name = _scan_outputs_dir_only(expected_filename)
    if name:
        return name, "outputs"

    name = _find_metadata_match_in_dir(settings.archives_dir, expected_filename)
    if name:
        return name, "archives"

    name = _scan_archives_dir_only(expected_filename)
    if name:
        return name, "archives"

    return None


def _is_safe_source_id(source_id: str) -> bool:
    """Validate a by-id route source_id before any filesystem access.

    Rejects path traversal (separators, dot segments, NUL) and non-contract
    filenames. Accepts only the pfmcp-...pdf shape that MCP jobs produce.
    """
    if not source_id or source_id in (".", ".."):
        return False
    if "/" in source_id or "\\" in source_id or "\x00" in source_id:
        return False
    return bool(_SOURCE_ID_SAFE_RE.fullmatch(source_id))


def resolve_paper_by_source_id(source_id: str) -> tuple[str, str] | None:
    """Map a durable paperflow_source_id (== expected_filename) to
    (paper_name, location). Validates source_id against path traversal + the
    pfmcp-...pdf contract, then reuses the 4-step _resolve_completed_candidate
    priority. Disk-based — works beyond the MCP job-index TTL.
    """
    if not _is_safe_source_id(source_id):
        return None
    return _resolve_completed_candidate(source_id)


def _paper_dir_for(name: str, location: str) -> Path:
    from ..config import settings
    base = settings.outputs_dir if location == "outputs" else settings.archives_dir
    return base / name


def _classify_completion(
    expected_filename: str,
    _precomputed: tuple[str, str] | None = None,
) -> str:
    """Decide the post-reconcile state for a job whose work appears finished.

    Returns one of:
      - "complete":  paper folder present AND (_ko.md present OR translation not required OR archives)
      - "partial":   paper folder present in outputs/, translation required, _ko.md missing
      - "missing":   no paper folder found at all (race / archived / externally deleted)
      - "skip":      paper folder present in outputs/, translation NOT required, no _ko.md

    The `_precomputed` argument lets callers reuse a candidate tuple from
    `_resolve_completed_candidate` to avoid a second lookup.
    """
    from ..config import settings

    if _precomputed:
        name, location = _precomputed
    else:
        cand = _resolve_completed_candidate(expected_filename)
        if not cand:
            return "missing"
        name, location = cand

    # archives is user-curated; never flag as partial.
    if location == "archives":
        return "complete"

    paper_dir = _paper_dir_for(name, location)
    has_ko = _paper_has_ko_md(paper_dir)
    if has_ko is None:
        return "missing"  # race: folder vanished between resolve and classify
    if has_ko:
        return "complete"
    if settings.MCP_REQUIRE_TRANSLATION:
        return "partial"
    return "skip"


def _cleanup_smart_renamed_paper(expected_filename: str) -> dict:
    """Find the smart-renamed paper folder in outputs/ (if any) and rmtree it.
    Archives are never touched.

    Returns:
      {"attempted": bool, "deleted_path": str | None, "warning": str | None}
    """
    import shutil

    cand = _resolve_completed_candidate(expected_filename)
    if not cand:
        return {"attempted": False, "deleted_path": None, "warning": None}
    name, location = cand
    if location != "outputs":
        return {"attempted": False, "deleted_path": None,
                "warning": "archives match found but skipped (never deletes archives)"}
    paper_dir = _paper_dir_for(name, location)
    if not paper_dir.exists():
        return {"attempted": True, "deleted_path": None,
                "warning": "candidate folder disappeared before cleanup"}
    try:
        shutil.rmtree(paper_dir)
        return {"attempted": True, "deleted_path": str(paper_dir), "warning": None}
    except Exception as e:
        return {"attempted": True, "deleted_path": None,
                "warning": f"rmtree failed: {e}"}


async def reconcile_job(job_id: str) -> JobRecord | None:
    """Refresh status by inspecting filesystem + processing_status.json."""
    from ..config import settings

    rec = await get_job(job_id)
    if not rec:
        return None
    # rev4: error/cancelled remain terminal idempotent; complete is re-validated.
    if rec.status in ("error", "cancelled"):
        return rec

    if rec.status == "complete":
        verdict = _classify_completion(rec.expected_filename)
        if verdict == "complete":
            return rec
        if verdict == "partial":
            await _set_job_fields(job_id, status="error",
                error=("translation_missing — prior run was killed mid-translation. "
                       "Call cancel_job(delete_file=true) to clear partial outputs, "
                       "then resubmit with force_reprocess=true. "
                       "If this deployment intentionally disables Korean translation, "
                       "set MCP_REQUIRE_TRANSLATION=false."),
                completed_at=_now_iso())
            return await get_job(job_id)
        if verdict == "missing":
            await _set_job_fields(job_id, status="error",
                error="paper folder no longer present (archived or deleted externally)",
                completed_at=_now_iso())
            return await get_job(job_id)
        # "skip" — translation not required; leave complete as-is
        return rec

    # Downloading: bg task interrupted (viewer restart)?
    if rec.status == "downloading" and job_id not in _active_download_tasks:
        await _set_job_fields(job_id, status="error",
                               error="download interrupted, retry submit",
                               completed_at=_now_iso())
        return await get_job(job_id)

    cand = _resolve_completed_candidate(rec.expected_filename)
    if cand:
        name, location = cand
        verdict = _classify_completion(rec.expected_filename, _precomputed=(name, location))
        if verdict == "partial":
            await _set_job_fields(job_id, status="error",
                error=("translation_missing — prior run was killed mid-translation. "
                       "Call cancel_job(delete_file=true) to clear partial outputs, "
                       "then resubmit with force_reprocess=true. "
                       "If this deployment intentionally disables Korean translation, "
                       "set MCP_REQUIRE_TRANSLATION=false."),
                completed_at=_now_iso())
            return await get_job(job_id)
        if verdict == "missing":
            await _set_job_fields(job_id, status="error",
                error="paper folder no longer present (archived or deleted externally)",
                completed_at=_now_iso())
            return await get_job(job_id)
        # complete or skip — both legitimate complete
        await _set_job_fields(job_id, status="complete",
                               paper_name=name, location=location,
                               completed_at=_now_iso())
        return await get_job(job_id)

    # processing_status.json
    ps_path = settings.logs_dir / "processing_status.json"
    if ps_path.exists():
        try:
            ps = json.loads(ps_path.read_text(encoding="utf-8"))
            if ps.get("current_file") == rec.expected_filename:
                stage = ps.get("stage", "idle")
                if stage == "error":
                    await _set_job_fields(job_id, status="error",
                                           error=ps.get("error") or "converter error",
                                           completed_at=_now_iso())
                    return await get_job(job_id)
                if stage not in ("idle", "complete"):
                    pct = 0
                    try:
                        cur = int(ps.get("current_stage", 0))
                        tot = int(ps.get("total_stages", 1)) or 1
                        pct = min(100, int(cur * 100 / tot))
                    except Exception:
                        pass
                    await _set_job_fields(job_id, status="processing",
                                           stage=stage, percent=pct)
                    return await get_job(job_id)

            # stalled detection: converter moved off our job + mtime old
            if rec.status == "processing" and ps.get("current_file") != rec.expected_filename:
                age = _time.time() - ps_path.stat().st_mtime
                if age > _STALLED_AFTER_SECONDS:
                    await _set_job_fields(job_id, status="stalled")
                    return await get_job(job_id)
        except Exception:
            pass

    # Final fallback: file still in newones/ → queued; otherwise error
    if (settings.newones_dir / rec.expected_filename).exists():
        if rec.status != "queued":
            await _set_job_fields(job_id, status="queued")
        return await get_job(job_id)

    await _set_job_fields(job_id, status="error",
                           error="file disappeared from queue with no output",
                           completed_at=_now_iso())
    return await get_job(job_id)


# ── Cancel ────────────────────────────────────────────────────────────────────
async def cancel_job(job_id: str, delete_file: bool = True) -> dict | None:
    """Cancel job. Behavior depends on current status.
    Returns:
      - dict {"job_id", "status", "cleanup": {attempted, deleted_path, warning}}
      - None if job_id not found
    """
    from . import papers as _papers
    from ..config import settings

    rec = await get_job(job_id)
    if not rec:
        return None

    cleanup = {"attempted": False, "deleted_path": None, "warning": None}

    # rev4: error-status + delete is a cleanup-intent call (not a state transition).
    if rec.status == "error" and delete_file:
        cleanup = _cleanup_smart_renamed_paper(rec.expected_filename)
        # Also clean source PDF if still in newones/
        src = settings.newones_dir / rec.expected_filename
        if src.exists():
            try:
                src.unlink()
            except Exception:
                pass
        return {"job_id": job_id, "status": "error", "cleanup": cleanup}

    if rec.status in ("error", "complete", "cancelled"):
        return {"job_id": job_id, "status": rec.status, "cleanup": cleanup}

    if rec.status == "downloading":
        task = _active_download_tasks.get(job_id)
        if task:
            task.cancel()
        part = settings.newones_dir / (rec.expected_filename + ".part")
        part.unlink(missing_ok=True)
        await _set_job_fields(job_id, status="cancelled",
                               completed_at=_now_iso())
        return {"job_id": job_id, "status": "cancelled", "cleanup": cleanup}

    # queued/processing/stalled — delegate to papers helper + post-hook cleanup
    ok, msg = _papers.request_cancel_processing(rec.expected_filename,
                                                  delete_file=delete_file, force=True)
    if delete_file:
        cleanup = _cleanup_smart_renamed_paper(rec.expected_filename)
    await _set_job_fields(job_id, status="cancelled",
                           error=None if ok else msg,
                           completed_at=_now_iso())
    return {"job_id": job_id, "status": "cancelled", "cleanup": cleanup}


# ── List ──────────────────────────────────────────────────────────────────────
async def list_jobs(limit: int = 50, status: str | None = None) -> list[JobRecord]:
    async with _index_lock:
        idx = await _load_index()
    records = []
    for v in idx.values():
        try:
            records.append(JobRecord.model_validate(v))
        except Exception:
            pass  # skip malformed entry
    records.sort(key=lambda r: r.submitted_at, reverse=True)

    reconciled = []
    for rec in records:
        refreshed = await reconcile_job(rec.job_id)
        if refreshed:
            reconciled.append(refreshed)

    if status:
        reconciled = [r for r in reconciled if r.status == status]
    reconciled.sort(key=lambda r: r.submitted_at, reverse=True)
    return reconciled[:limit]


async def cancel_all_active_downloads(
    reason: Literal["shutdown", "user"] = "shutdown"
) -> int:
    """Cancel every active download task. Used by lifespan shutdown."""
    count = 0
    for job_id, task in list(_active_download_tasks.items()):
        task.cancel()
        if reason == "shutdown":
            await _set_job_fields(job_id, status="error",
                                   error="download interrupted, retry submit",
                                   completed_at=_now_iso())
        else:
            await _set_job_fields(job_id, status="cancelled",
                                   completed_at=_now_iso())
        count += 1
    return count


# ── Cleanup ───────────────────────────────────────────────────────────────────
def _cleanup_stale_mcp_tmp(max_age_seconds: int = 3600) -> int:
    """Remove files in newones/.mcp_tmp older than max_age_seconds. Returns count removed."""
    from ..config import settings
    tmp_dir = settings.newones_dir / ".mcp_tmp"
    if not tmp_dir.exists():
        return 0
    cutoff = _time.time() - max_age_seconds
    removed = 0
    for p in tmp_dir.iterdir():
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except Exception:
            pass
    return removed


async def cleanup_expired_jobs() -> int:
    """Remove expired terminal jobs from index. Also cleanup stale .mcp_tmp files."""
    _cleanup_stale_mcp_tmp(max_age_seconds=3600)

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
    return removed
