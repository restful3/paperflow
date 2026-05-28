"""MCP server: FastMCP tools + ASGI auth wrapper + zip download endpoint.

Only mounted when settings.mcp_enabled is True (see main.py).
"""
from __future__ import annotations

import contextlib
import json
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from mcp.server.fastmcp import FastMCP

from ..config import settings
from ..services import mcp_jobs, mcp_zip
from ..services import papers as paper_svc


def _sanitize_submitted_source(input_type: str, source: str) -> str:
    """Public-safe label for the request that produced the job.
    - URL input: the URL itself (already public).
    - File input: basename only — never leak the caller's local directory layout.
    """
    if input_type == "url":
        return source
    return source.replace("\\", "/").rsplit("/", 1)[-1] or source


# ── FastMCP server ────────────────────────────────────────────────────────────
mcp = FastMCP(
    "paperflow",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",   # mount root → /mcp resolves correctly
)


@mcp.tool()
async def submit_paper(
    input_type: Literal["url", "file"],
    source: str,
    file_base64: str | None = None,
    force_reprocess: bool = False,
) -> dict:
    """Submit a PDF (file) or web URL to the PaperFlow pipeline. Returns job_id immediately."""
    opts = mcp_jobs.JobOptions(force_reprocess=force_reprocess)
    rec = await mcp_jobs.submit_job(input_type, source, opts, pdf_bytes_b64=file_base64)
    return {
        "job_id": rec.job_id,
        "status": rec.status,
        "cached": rec.status == "complete",
        "expected_filename": rec.expected_filename,
    }


@mcp.tool()
async def get_job_status(job_id: str) -> dict:
    """Get current status of a submitted job."""
    rec = await mcp_jobs.reconcile_job(job_id)
    if not rec:
        raise ValueError(f"job not found: {job_id}")
    return rec.model_dump(include={
        "job_id", "status", "stage", "percent", "error",
        "submitted_at", "completed_at", "expires_at",
    })


@mcp.tool()
async def get_job_result(
    job_id: str,
    include_pdf: bool = False,
    include_translation: bool = True,
) -> dict:
    """Return the link-contract dict for a completed job.

    Only valid when status==complete; raises ValueError otherwise.

    Response fields:
      job_id                — short-lived MCP debug key (subject to TTL cleanup)
      paperflow_source_id   — durable per-job identifier (== expected_filename)
      input_type            — "url" | "file"
      submitted_source      — public-safe label (URL kept as-is, file reduced
                              to basename so local directories never leak)
      source_url            — original URL for URL input; None for file input
      paper_name            — current PaperFlow folder name; convenience key,
                              not a permanent id (smart rename / archive /
                              same-title reprocess can shift it)
      location              — "outputs" | "archives" — store with
                              paperflow_source_id for collision-safe resolution
      paper_meta            — title / authors / abstract / venue / year / doi /
                              categories from the paper's paper_meta.json
      files                 — {md_en, md_ko, pdf, images_count} availability
      viewer_url            — {base}/viewer/by-id/{paperflow_source_id} stable
                              link. Survives folder rename / archive because it
                              resolves by durable source_id, not paper_name.
                              OPAQUE — consumers must NOT parse paper_name out of
                              it, and reaching the viewer requires following the
                              302 redirect. AUTH-REQUIRED: anonymous clicks
                              redirect to /login. Host-local only when base is
                              localhost.
      download_url          — zip endpoint. AUTH-REQUIRED: caller must send
                              Authorization: Bearer <MCP_API_KEY>. Agent-only
                              retrieval URL — do NOT embed in human reports
      expires_at            — MCP job-index TTL (~7 days). The zip endpoint
                              also 410s once the paper folder is gone, even
                              before this expiry.

    For long-lived report links, the safe pair is
    `source_url` (original) + `paperflow_source_id` + `location`; download the
    zip and stash it in your own artifact store rather than linking
    `download_url` directly.
    """
    from ..config import settings as _settings

    rec = await mcp_jobs.reconcile_job(job_id)
    if not rec:
        raise ValueError(f"job not found: {job_id}")
    if rec.status != "complete":
        raise ValueError(f"job not complete (status={rec.status})")

    paper_dir = paper_svc.safe_paper_dir_at_location(rec.paper_name, rec.location)
    if not paper_dir:
        raise ValueError("paper folder no longer exists")

    # Build paper_meta + file summary
    meta = {}
    meta_path = paper_dir / "paper_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    files = {"md_en": False, "md_ko": False, "pdf": False, "images_count": 0}
    for f in paper_dir.iterdir():
        if f.is_file():
            n = f.name.lower()
            if n.endswith("_ko.md") and not n.endswith("_ko_explained.md"):
                files["md_ko"] = True
            elif n.endswith(".md") and not n.endswith("_ko.md") and not n.endswith("_explained.md"):
                files["md_en"] = True
            elif n.endswith(".pdf"):
                files["pdf"] = True
    img_dir = paper_dir / "images"
    if img_dir.is_dir():
        files["images_count"] = sum(1 for _ in img_dir.iterdir() if _.is_file())

    base = _settings.MCP_PUBLIC_BASE_URL.rstrip("/")
    download_url = (
        f"{base}/api/mcp/jobs/{job_id}/zip"
        f"?include_pdf={'true' if include_pdf else 'false'}"
        f"&include_translation={'true' if include_translation else 'false'}"
    )
    viewer_url = f"{base}/viewer/by-id/{quote(rec.expected_filename, safe='')}"
    source_url = rec.source if rec.input_type == "url" else None
    submitted_source = _sanitize_submitted_source(rec.input_type, rec.source)

    return {
        "job_id": job_id,
        "paperflow_source_id": rec.expected_filename,
        "input_type": rec.input_type,
        "submitted_source": submitted_source,
        "source_url": source_url,
        "paper_name": rec.paper_name,
        "location": rec.location,
        "paper_meta": {
            "title": meta.get("title"),
            "authors": meta.get("authors"),
            "abstract": meta.get("abstract"),
            "venue": meta.get("venue"),
            "year": meta.get("year"),
            "doi": meta.get("doi"),
            "categories": meta.get("categories"),
        },
        "files": files,
        "viewer_url": viewer_url,
        "download_url": download_url,
        "expires_at": rec.expires_at,
    }


@mcp.tool()
async def cancel_job(job_id: str, delete_file: bool = True) -> dict:
    """Cancel a job. Idempotent. Returns dict with cleanup details."""
    res = await mcp_jobs.cancel_job(job_id, delete_file=delete_file)
    if res is None:
        raise ValueError(f"job not found: {job_id}")
    return res


@mcp.tool()
async def list_jobs(
    limit: int = 20,
    status: str | None = None,
) -> dict:
    """List recent jobs. Single-tenant — all jobs visible to caller."""
    if limit > 100:
        limit = 100
    recs = await mcp_jobs.list_jobs(limit=limit, status=status)
    return {"jobs": [r.model_dump() for r in recs]}


# ── ASGI wrapper: Bearer + Origin ─────────────────────────────────────────────
async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _make_auth_wrapper(inner_asgi, api_key: str, allowed_origins: set[str]):
    """Raw ASGI middleware — wraps mcp.streamable_http_app() without mutating Starlette internals."""
    async def authenticated(scope, receive, send):
        if scope.get("type") != "http":
            await inner_asgi(scope, receive, send)
            return
        headers = {k.decode("latin1").lower(): v.decode("latin1")
                   for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != api_key:
            await _send_json(send, 401, {"error": "unauthorized"})
            return
        origin = headers.get("origin")
        if origin and "*" not in allowed_origins and origin not in allowed_origins:
            await _send_json(send, 403, {"error": "origin not allowed"})
            return
        await inner_asgi(scope, receive, send)
    return authenticated


@contextlib.asynccontextmanager
async def mcp_lifespan():
    """Caller (main.py app_lifespan) wraps this around app startup."""
    async with mcp.session_manager.run():
        yield


def mount_mcp(app, api_key: str, allowed_origins: set[str], path: str = "/mcp") -> None:
    inner = mcp.streamable_http_app()
    wrapped = _make_auth_wrapper(inner, api_key, allowed_origins)
    app.mount(path, wrapped)


# ── Zip download endpoint (FastAPI route with Depends auth) ──────────────────
async def verify_mcp_key(authorization: str = Header(default="")) -> None:
    from ..config import settings as _settings
    if not authorization.startswith("Bearer ") or authorization[7:] != _settings.MCP_API_KEY:
        raise HTTPException(status_code=401, detail="unauthorized")


mcp_zip_router = APIRouter(
    prefix="/api/mcp",
    dependencies=[Depends(verify_mcp_key)],
)


@mcp_zip_router.get("/jobs/{job_id}/zip")
async def download_zip(
    job_id: str,
    include_pdf: bool = False,
    include_translation: bool = True,
):
    rec = await mcp_jobs.reconcile_job(job_id)
    if not rec or rec.status != "complete":
        raise HTTPException(status_code=404, detail="Job not complete or not found")
    paper_dir = paper_svc.safe_paper_dir_at_location(rec.paper_name, rec.location)
    if not paper_dir:
        raise HTTPException(status_code=410, detail="Paper folder no longer exists")
    stream = mcp_zip.build_zip_stream(
        paper_dir,
        include_pdf=include_pdf,
        include_translation=include_translation,
        job_meta={"job_id": job_id},
    )
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{rec.paper_name}.zip"'},
    )
