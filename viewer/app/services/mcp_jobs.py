"""MCP job orchestration: submit, reconcile, cancel, cleanup.

JobRecord index persisted to logs/mcp_jobs.json (atomic replace).
Single-worker viewer assumption — module-level asyncio.Lock for index access.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import re
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel


# ── Module state ──────────────────────────────────────────────────────────────
_active_download_tasks: dict[str, asyncio.Task] = {}
_index_lock = asyncio.Lock()


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


def _build_expected_filename(job_id: str, slug_source: str) -> str:
    """pfmcp-{job_id[:12]}-{safe_slug[:40]}.pdf — guaranteed unique per job_id."""
    short = job_id.replace("-", "")[:12]
    slug = _FILENAME_SAFE_RE.sub("-", (slug_source or "doc").strip().lower())[:40]
    slug = slug.strip("-") or "doc"
    return f"pfmcp-{short}-{slug}.pdf"
