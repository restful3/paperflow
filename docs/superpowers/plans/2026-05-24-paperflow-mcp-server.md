# PaperFlow MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PaperFlow 의 PDF→Markdown(+이미지)→번역 파이프라인을 MCP (Model Context Protocol) tool 로 외부 노출. 클라이언트가 PDF 또는 URL 제출 → 비동기 처리 → zip 다운로드.

**Architecture:** viewer 컨테이너 안에 FastMCP (Streamable HTTP) 마운트. 기존 watch 파이프라인을 그대로 재사용 — MCP 는 `newones/` 에 PDF 떨구고 `processing_status.json` 폴링하는 얇은 orchestration 레이어. `main_terminal.py` 변경 0줄.

**Tech Stack:** Python 3.12, FastAPI, mcp>=1.27, pydantic, asyncio, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-05-24-paperflow-mcp-server-design.md` (rev5, codex final-approved)

---

## File Structure

```
viewer/
├── requirements.txt                       # MODIFY: add mcp, pytest, pytest-asyncio
├── Dockerfile                             # no change (requirements covers it)
├── app/
│   ├── main.py                            # MODIFY: lifespan + conditional MCP mount
│   ├── config.py                          # MODIFY: 4 MCP_* settings + properties
│   ├── routers/
│   │   ├── api.py                         # no change
│   │   ├── pages.py                       # no change
│   │   └── mcp_router.py                  # NEW: FastMCP tools + ASGI wrapper + zip endpoint
│   └── services/
│       ├── papers.py                      # MODIFY: extract _resolve_url_to_pdf_bytes helper
│       ├── mcp_jobs.py                    # NEW: JobRecord, submit/poll/cancel/cleanup
│       └── mcp_zip.py                     # NEW: zip stream builder
└── tests/                                 # NEW directory
    ├── __init__.py
    ├── conftest.py                        # pytest fixtures (tmp_path-based settings override)
    ├── test_papers_url_resolve.py         # extraction regression tests
    ├── test_mcp_jobs.py                   # unit tests for mcp_jobs
    └── test_mcp_router.py                 # integration tests for MCP endpoint

docker-compose.yml                          # MODIFY: viewer service env block

main_terminal.py                            # 0 line changes
run_batch_watch.sh                          # 0 line changes
config.json                                 # 0 line changes
```

**Total tasks: 13**

---

## Task 1: Add dependencies + test infrastructure

**Files:**
- Modify: `viewer/requirements.txt`
- Create: `viewer/tests/__init__.py`
- Create: `viewer/tests/conftest.py`

- [ ] **Step 1.1: Add dependencies**

Edit `viewer/requirements.txt` — append these three lines at the end:

```
mcp>=1.27,<2
pytest>=8
pytest-asyncio>=0.23
```

- [ ] **Step 1.2: Create test package marker**

Create `viewer/tests/__init__.py` (empty file).

- [ ] **Step 1.3: Create pytest config**

Create `viewer/pytest.ini` with:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 1.4: Create conftest with shared fixtures**

Create `viewer/tests/conftest.py`:

```python
"""Shared pytest fixtures for viewer tests."""
import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_workspace(tmp_path, monkeypatch):
    """Isolated PaperFlow workspace: outputs/, archives/, newones/, logs/."""
    for sub in ("outputs", "archives", "newones", "newones/.meta", "newones/.mcp_tmp", "logs"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("BASE_DIR", str(tmp_path))
    # JWT_SECRET_KEY required for config.validate_runtime in some flows
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 48)

    # Force a fresh Settings instance that reads the new env
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()

    yield tmp_path

    # Restore default settings after test
    _cfg.settings = _cfg.Settings()


@pytest.fixture
def mcp_enabled_workspace(tmp_workspace, monkeypatch):
    """tmp_workspace + MCP env vars set."""
    monkeypatch.setenv("MCP_API_KEY", "a" * 48)
    monkeypatch.setenv("MCP_PUBLIC_BASE_URL", "http://localhost:8090")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    return tmp_workspace
```

- [ ] **Step 1.5: Verify pytest discovers (no tests yet, should report 0)**

Run from `viewer/` directory:

```bash
cd viewer && python -m pytest -q
```

Expected: `no tests ran` (or similar) — confirms pytest is wired.

- [ ] **Step 1.6: Commit**

```bash
git add viewer/requirements.txt viewer/pytest.ini viewer/tests/__init__.py viewer/tests/conftest.py
git commit -m "test(viewer): add pytest infra + mcp+pytest-asyncio deps"
```

---

## Task 2: Add MCP_* config settings

**Files:**
- Modify: `viewer/app/config.py`
- Test: `viewer/tests/test_config_mcp.py`

- [ ] **Step 2.1: Write failing test**

Create `viewer/tests/test_config_mcp.py`:

```python
"""Tests for MCP_* config settings."""
import pytest


def test_mcp_disabled_when_key_empty(tmp_workspace, monkeypatch):
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    assert _cfg.settings.mcp_enabled is False


def test_mcp_enabled_requires_base_url(tmp_workspace, monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "k" * 48)
    monkeypatch.delenv("MCP_PUBLIC_BASE_URL", raising=False)
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    with pytest.raises(RuntimeError, match="MCP_PUBLIC_BASE_URL"):
        _ = _cfg.settings.mcp_enabled


def test_mcp_enabled_true_when_both_set(mcp_enabled_workspace):
    from app import config as _cfg
    assert _cfg.settings.mcp_enabled is True


def test_mcp_short_key_disabled(tmp_workspace, monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "short")
    monkeypatch.setenv("MCP_PUBLIC_BASE_URL", "http://localhost:8090")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    assert _cfg.settings.mcp_enabled is False


def test_origin_derive_default(mcp_enabled_workspace, monkeypatch):
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    origins = _cfg.settings.mcp_allowed_origins_set
    assert "http://localhost:8090" in origins
    assert "http://localhost" in origins
    assert "http://127.0.0.1" in origins
    assert "*" not in origins


def test_origin_explicit_wildcard(mcp_enabled_workspace, monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "*")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    assert _cfg.settings.mcp_allowed_origins_set == {"*"}


def test_origin_explicit_csv(mcp_enabled_workspace, monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://a.com, https://b.com")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    assert _cfg.settings.mcp_allowed_origins_set == {"https://a.com", "https://b.com"}
```

- [ ] **Step 2.2: Run tests — verify they fail**

```bash
cd viewer && python -m pytest tests/test_config_mcp.py -v
```

Expected: errors / failures about `mcp_enabled` not existing.

- [ ] **Step 2.3: Implement MCP_* settings**

Edit `viewer/app/config.py`. After the existing `BRAVE_SEARCH_API_KEY` field and before `HOST`:

```python
    BRAVE_SEARCH_API_KEY: str = ""

    # MCP server (opt-in: empty MCP_API_KEY → completely disabled)
    MCP_API_KEY: str = ""
    MCP_JOB_TTL_DAYS: int = 7
    MCP_PUBLIC_BASE_URL: str = ""        # required when MCP enabled, e.g. http://localhost:8090
    MCP_ALLOWED_ORIGINS: str = ""        # CSV. empty → derive. explicit "*" → permissive opt-out.

    HOST: str = "0.0.0.0"
```

And add two properties at the end of the `Settings` class, after `logs_dir`:

```python
    @property
    def mcp_enabled(self) -> bool:
        """Opt-in: MCP server is mounted only when MCP_API_KEY is set (>= 32 chars)
        AND MCP_PUBLIC_BASE_URL is configured."""
        if not (self.MCP_API_KEY and len(self.MCP_API_KEY) >= 32):
            return False
        if not self.MCP_PUBLIC_BASE_URL:
            raise RuntimeError(
                "MCP_API_KEY is set but MCP_PUBLIC_BASE_URL is missing. "
                "Set MCP_PUBLIC_BASE_URL (e.g. http://localhost:8090) or clear MCP_API_KEY."
            )
        return True

    @property
    def mcp_allowed_origins_set(self) -> set[str]:
        """DNS rebinding defense (MCP MUST).
        - explicit "*" → permissive opt-out
        - explicit CSV → exactly those
        - empty → derive MCP_PUBLIC_BASE_URL origin + localhost/127.0.0.1 (http/https)
        """
        from urllib.parse import urlparse

        raw = self.MCP_ALLOWED_ORIGINS.strip()
        if raw == "*":
            return {"*"}
        explicit = {o.strip() for o in raw.split(",") if o.strip()}
        if explicit:
            return explicit
        defaults: set[str] = set()
        if self.MCP_PUBLIC_BASE_URL:
            p = urlparse(self.MCP_PUBLIC_BASE_URL)
            if p.scheme and p.netloc:
                defaults.add(f"{p.scheme}://{p.netloc}")
        defaults.update({
            "http://localhost", "https://localhost",
            "http://127.0.0.1", "https://127.0.0.1",
        })
        return defaults
```

- [ ] **Step 2.4: Run tests — verify they pass**

```bash
cd viewer && python -m pytest tests/test_config_mcp.py -v
```

Expected: 7 passed.

- [ ] **Step 2.5: Commit**

```bash
git add viewer/app/config.py viewer/tests/test_config_mcp.py
git commit -m "config(viewer): add MCP_* settings + opt-in mcp_enabled property"
```

---

## Task 3: Extract `_resolve_url_to_pdf_bytes` from `import_url_as_paper`

**Goal:** Pull the URL → PDF bytes logic out as a reusable helper so `mcp_jobs` can use it without duplicating the chain. `import_url_as_paper` keeps the exact same external behavior.

**Files:**
- Modify: `viewer/app/services/papers.py:206-397` (import_url_as_paper body)
- Test: `viewer/tests/test_papers_url_resolve.py`

- [ ] **Step 3.1: Write failing test**

Create `viewer/tests/test_papers_url_resolve.py`:

```python
"""Regression tests for _resolve_url_to_pdf_bytes extraction."""
import pytest
from unittest.mock import patch


def test_invalid_url_raises_value_error(tmp_workspace):
    from app.services import papers
    with pytest.raises(ValueError, match="Invalid URL"):
        papers._resolve_url_to_pdf_bytes("not-a-url")


def test_invalid_scheme_raises_value_error(tmp_workspace):
    from app.services import papers
    with pytest.raises(ValueError, match="Invalid URL"):
        papers._resolve_url_to_pdf_bytes("ftp://example.com/foo.pdf")


def test_site_transform_returns_bytes(tmp_workspace, monkeypatch):
    """When _download_pdf succeeds on a transformed URL, helper returns its bytes."""
    from app.services import papers

    expected_bytes = b"%PDF-1.4 fake pdf content here"

    def fake_download(url, timeout=35):
        if url.endswith(".pdf"):
            return expected_bytes
        raise Exception("not a pdf")

    monkeypatch.setattr(papers, "_download_pdf", fake_download)

    pdf_bytes, final_url, method = papers._resolve_url_to_pdf_bytes("https://arxiv.org/abs/2301.12345")
    assert pdf_bytes == expected_bytes
    assert "arxiv.org" in final_url
    assert method in ("site_transform", "direct_pdf")
```

- [ ] **Step 3.2: Run tests — verify they fail**

```bash
cd viewer && python -m pytest tests/test_papers_url_resolve.py -v
```

Expected: `AttributeError: module 'app.services.papers' has no attribute '_resolve_url_to_pdf_bytes'`.

- [ ] **Step 3.3: Add the helper alongside `import_url_as_paper`**

Edit `viewer/app/services/papers.py`. Insert this **before** the `def import_url_as_paper(...)` line at line ~206:

```python
def _resolve_url_to_pdf_bytes(url: str) -> tuple[bytes, str, str]:
    """Resolve URL to PDF bytes. Used by import_url_as_paper and mcp_jobs.

    Returns: (pdf_bytes, final_url_after_redirects, import_method)
      import_method in {"site_transform", "direct_pdf", "html_fallback"}
    Raises: ValueError with concrete reason on failure.
    """
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError("Invalid URL. Use http(s) URL.")
    host = (urlparse(url).netloc or "").lower()
    if not host:
        raise ValueError("Invalid URL host.")

    # DOI pre-resolve
    effective_url = url
    if "doi.org/" in url:
        resolved = _resolve_doi_redirect(url)
        if resolved:
            effective_url = resolved

    download_errors: list[str] = []

    # Site transformer
    for cand in _site_transform_pdf_urls(effective_url):
        try:
            return _download_pdf(cand, timeout=35), effective_url, "site_transform"
        except Exception as e:
            download_errors.append(f"{cand}: {str(e)[:80]}")

    # HTML fetch + redirect re-transform + anchor discovery
    html_for_discovery = ""
    final_url = effective_url
    try:
        html_for_discovery, final_url = _fetch_url_html(effective_url)
    except Exception:
        pass

    if final_url and final_url != effective_url:
        effective_url = final_url
        for cand in _site_transform_pdf_urls(final_url):
            try:
                return _download_pdf(cand, timeout=35), effective_url, "site_transform"
            except Exception as e:
                download_errors.append(f"{cand}: {str(e)[:80]}")

    if html_for_discovery:
        for cand in _candidate_pdf_urls_from_page(effective_url, html_for_discovery):
            try:
                return _download_pdf(cand, timeout=35), effective_url, "direct_pdf"
            except Exception as e:
                download_errors.append(f"{cand}: {str(e)[:80]}")

    # strict_pdf_required check
    effective_host = (urlparse(effective_url).netloc or "").lower()
    _STRICT = (
        "arxiv.org", "openreview.net", "aclanthology.org", "proceedings.mlr.press",
        "biorxiv.org", "medrxiv.org", "acm.org", "ieeexplore.ieee.org",
        "springer.com", "nature.com", "sciencedirect.com",
    )
    if any(d in effective_host for d in _STRICT):
        detail = f" direct-download failed ({'; '.join(download_errors[:2])})" if download_errors else ""
        raise ValueError("이 논문 링크는 원문 PDF 직접 다운로드가 필요하지만 실패했습니다." + detail)

    # HTML fallback: chromium print-to-pdf → temp file in newones/.mcp_tmp/
    browser_bin = (
        shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    )
    if not browser_bin:
        msg = "No headless browser found (google-chrome/chromium)."
        if download_errors:
            msg += f" direct-download failed ({'; '.join(download_errors[:2])})"
        raise ValueError(msg)

    mcp_tmp_dir = settings.newones_dir / ".mcp_tmp"
    mcp_tmp_dir.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.NamedTemporaryFile(dir=mcp_tmp_dir, suffix=".pdf", delete=False) as tf:
        tmp_path = Path(tf.name)
    try:
        cmd = [
            browser_bin,
            "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--virtual-time-budget=30000",
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            f"--print-to-pdf={tmp_path}",
            url,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise ValueError("PDF 생성 타임아웃(60s).")
        except subprocess.CalledProcessError as e:
            err = (e.stderr or e.stdout or "").strip()
            raise ValueError(f"PDF 생성 실패: {err[:200]}")

        if not tmp_path.exists() or tmp_path.stat().st_size < 1024:
            raise ValueError("PDF 생성 결과가 비정상입니다.")

        # Quality gates (file-based)
        pdf_text = _extract_pdf_text_simple(tmp_path, max_pages=2)
        norm = re.sub(r"\s+", " ", (pdf_text or "")).strip().lower()
        bot_keywords = [
            "verifying the device", "verifying your browser", "verify you are human",
            "checking your browser", "device verification", "captcha", "are you a robot",
            "access denied", "just a moment", "ddos protection", "cloudflare",
            "attention required", "unusual traffic",
        ]
        norm_nospace = norm.replace(" ", "")
        if any(k in norm or k.replace(" ", "") in norm_nospace for k in bot_keywords) and len(norm) < 600:
            raise ValueError("사이트 봇 감지/인증 페이지가 캡처되었습니다. 자동 가져오기 미지원.")
        err_keywords = [
            "page not found", "404 not found", "403 forbidden", "no longer exists",
            "has been moved", "page you requested", "this page isn't available",
            "page doesn't exist", "requested url was not found", "server error", "500 internal",
        ]
        if any(k in norm or k.replace(" ", "") in norm_nospace for k in err_keywords) and len(norm) < 600:
            raise ValueError("에러 페이지(404/403 등)가 캡처되었습니다.")
        weak = ["privacy policy", "notify me", "owner login", "terms", "copyright", "built for agents"]
        if len(norm) < 220 or sum(1 for k in weak if k in norm) >= 3:
            raise ValueError("원문 본문이 아닌 푸터/배너만 인쇄되어 가져오기 실패.")

        return tmp_path.read_bytes(), effective_url, "html_fallback"
    finally:
        tmp_path.unlink(missing_ok=True)
```

- [ ] **Step 3.4: Refactor `import_url_as_paper` to use the helper**

Replace the body of `import_url_as_paper` (lines ~206-397) with this thin wrapper:

```python
def import_url_as_paper(url: str, title: str | None = None) -> tuple[bool, str, str | None]:
    """Import a web URL by creating a PDF in newones/ queue.

    Returns: (ok, message, queued_pdf_name)
    """
    try:
        pdf_bytes, _final_url, _method = _resolve_url_to_pdf_bytes(url)
    except ValueError as e:
        return False, str(e), None

    settings.newones_dir.mkdir(parents=True, exist_ok=True)
    host = (urlparse(url).netloc or "").lower()
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify_name(title or host)
    pdf_name = f"web-{slug}-{ts}.pdf"
    pdf_path = settings.newones_dir / pdf_name

    # Atomic publish: write to .part then rename
    part_path = pdf_path.with_suffix(pdf_path.suffix + ".part")
    try:
        part_path.write_bytes(pdf_bytes)
        os.replace(part_path, pdf_path)
    except Exception as e:
        part_path.unlink(missing_ok=True)
        return False, f"queue write failed: {e}", None

    try:
        _write_source_sidecar(pdf_name, url)
    except Exception:
        pass

    return True, f"URL queued as PDF: {pdf_name}", pdf_name
```

(Make sure `import os` is at the top of the module — check it's already imported, papers.py uses os via _atomic_write so it should be.)

- [ ] **Step 3.5: Run extraction tests + run existing viewer tests (smoke)**

```bash
cd viewer && python -m pytest tests/test_papers_url_resolve.py tests/test_config_mcp.py -v
```

Expected: all pass.

- [ ] **Step 3.6: Commit**

```bash
git add viewer/app/services/papers.py viewer/tests/test_papers_url_resolve.py
git commit -m "refactor(papers): extract _resolve_url_to_pdf_bytes helper

import_url_as_paper is now a thin wrapper around the new helper. behavior
preserved (returns same (ok, msg, name) tuple). new helper raises ValueError
and is reusable by upcoming mcp_jobs.

HTML fallback temp file now lives in newones/.mcp_tmp/ (watch is maxdepth 1
so subfolder is safe)."
```

---

## Task 4: `mcp_jobs.py` skeleton — JobRecord, index I/O

**Files:**
- Create: `viewer/app/services/mcp_jobs.py`
- Test: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 4.1: Write failing tests**

Create `viewer/tests/test_mcp_jobs.py`:

```python
"""Tests for mcp_jobs service."""
import json
import pytest


def test_job_record_roundtrip(tmp_workspace):
    from app.services import mcp_jobs
    rec = mcp_jobs.JobRecord(
        job_id="abc",
        input_type="url",
        source="https://arxiv.org/abs/1234.5678",
        expected_filename="pfmcp-abc-arxiv.pdf",
        import_method="site_transform",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="queued",
        stage=None,
        percent=0,
        paper_name=None,
        location=None,
        error=None,
        submitted_at="2026-05-24T10:00:00",
        completed_at=None,
        expires_at="2026-05-31T10:00:00",
    )
    payload = rec.model_dump()
    rec2 = mcp_jobs.JobRecord.model_validate(payload)
    assert rec2 == rec


async def test_load_index_creates_empty_when_missing(tmp_workspace):
    from app.services import mcp_jobs
    idx = await mcp_jobs._load_index()
    assert idx == {}


async def test_atomic_write_then_load(tmp_workspace):
    from app.services import mcp_jobs
    await mcp_jobs._atomic_write_index({"job1": {"job_id": "job1", "x": 1}})
    idx = await mcp_jobs._load_index()
    assert "job1" in idx
    assert idx["job1"]["x"] == 1


async def test_corrupt_index_quarantined(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    index_path = settings.logs_dir / "mcp_jobs.json"
    index_path.write_text("{not valid json")
    idx = await mcp_jobs._load_index()
    assert idx == {}
    # Quarantined file exists
    quarantined = list(settings.logs_dir.glob("mcp_jobs.corrupt.*.json"))
    assert len(quarantined) == 1


def test_build_expected_filename():
    from app.services import mcp_jobs
    name = mcp_jobs._build_expected_filename("abcdef1234567890", "arxiv.org")
    assert name.startswith("pfmcp-abcdef123456-")
    assert name.endswith(".pdf")
    assert len(name) <= 70  # reasonable bound
```

- [ ] **Step 4.2: Run — verify failure**

```bash
cd viewer && python -m pytest tests/test_mcp_jobs.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.mcp_jobs'`.

- [ ] **Step 4.3: Create `mcp_jobs.py` skeleton**

Create `viewer/app/services/mcp_jobs.py`:

```python
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

from ..config import settings


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
    return settings.logs_dir / "mcp_jobs.json"


async def _load_index() -> dict[str, dict]:
    """Load mcp_jobs.json. On corruption, quarantine + return empty."""
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
```

- [ ] **Step 4.4: Run tests — verify pass**

```bash
cd viewer && python -m pytest tests/test_mcp_jobs.py -v
```

Expected: 5 passed.

- [ ] **Step 4.5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp): mcp_jobs.py skeleton — JobRecord, atomic index I/O, filename helper"
```

---

## Task 5: `mcp_jobs.py` — file submit + 2-stage publish helpers

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Modify: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 5.1: Write failing tests (append to test_mcp_jobs.py)**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
import base64


def test_write_part_file_then_publish(tmp_workspace):
    from app.services import mcp_jobs
    dest = tmp_workspace / "newones" / "pfmcp-test.pdf"
    part = dest.with_suffix(dest.suffix + ".part")
    mcp_jobs._write_part_file(b"%PDF-1.4 test", part)
    assert part.exists()
    assert not dest.exists()    # publish not yet
    mcp_jobs._atomic_publish_part(part, dest)
    assert dest.exists()
    assert not part.exists()
    assert dest.read_bytes() == b"%PDF-1.4 test"


async def test_submit_job_file_invalid_base64(tmp_workspace):
    from app.services import mcp_jobs
    with pytest.raises(ValueError, match="base64"):
        await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
                                   pdf_bytes_b64="not-base64-!!!")


async def test_submit_job_file_oversized(tmp_workspace):
    from app.services import mcp_jobs
    huge = base64.b64encode(b"%PDF" + b"x" * (201 * 1024 * 1024)).decode()
    with pytest.raises(ValueError, match="200MB"):
        await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
                                   pdf_bytes_b64=huge)


async def test_submit_job_file_not_pdf(tmp_workspace):
    from app.services import mcp_jobs
    not_pdf = base64.b64encode(b"hello world").decode()
    with pytest.raises(ValueError, match="PDF"):
        await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
                                   pdf_bytes_b64=not_pdf)


async def test_submit_job_file_success(tmp_workspace):
    from app.services import mcp_jobs
    pdf_b64 = base64.b64encode(b"%PDF-1.4 hello").decode()
    rec = await mcp_jobs.submit_job("file", "mydoc.pdf", mcp_jobs.JobOptions(),
                                     pdf_bytes_b64=pdf_b64)
    assert rec.status == "queued"
    assert rec.expected_filename.startswith("pfmcp-")
    assert rec.input_type == "file"
    assert rec.import_method == "file_upload"
    # File landed in newones/
    landed = tmp_workspace / "newones" / rec.expected_filename
    assert landed.exists()
    assert landed.read_bytes() == b"%PDF-1.4 hello"
    # Index has it
    idx = await mcp_jobs._load_index()
    assert rec.job_id in idx
```

- [ ] **Step 5.2: Run — verify failure**

```bash
cd viewer && python -m pytest tests/test_mcp_jobs.py -v
```

Expected: errors about `_write_part_file`, `submit_job`, etc. not defined.

- [ ] **Step 5.3: Implement publish helpers + submit_job (file path)**

Append to `viewer/app/services/mcp_jobs.py`:

```python
import base64 as _b64
import uuid as _uuid

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

    job_id = str(_uuid.uuid4())
    expected_filename = _build_expected_filename(job_id, _slug_from_source(input_type, source))
    dest = settings.newones_dir / expected_filename

    if input_type == "file":
        # Decode + validate
        try:
            pdf_bytes = _b64.b64decode(pdf_bytes_b64, validate=True)
        except Exception as e:
            raise ValueError(f"invalid base64: {e}") from e
        if len(pdf_bytes) > 200 * 1024 * 1024:
            raise ValueError("file exceeds 200MB limit")
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError("not a PDF (magic byte mismatch)")

        # 2-stage publish: write .part (in thread), then short atomic replace
        part_path = dest.with_suffix(dest.suffix + ".part")
        await asyncio.to_thread(_write_part_file, pdf_bytes, part_path)
        _atomic_publish_part(part_path, dest)

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
        # URL: background task does the work, this returns immediately
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
```

- [ ] **Step 5.4: Run tests — verify pass**

```bash
cd viewer && python -m pytest tests/test_mcp_jobs.py -v
```

Expected: all (10 total now) pass.

- [ ] **Step 5.5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp): file submit + 2-stage publish + URL bg downloader skeleton"
```

---

## Task 6: `mcp_jobs.py` — URL submit cancel race test + force_reprocess + cached path

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Modify: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 6.1: Write failing tests**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
async def test_submit_url_returns_downloading(tmp_workspace, monkeypatch):
    """URL submit returns immediately with status=downloading; bg task does the work."""
    from app.services import mcp_jobs

    async def slow_resolve(url):
        await asyncio.sleep(0.05)
        return b"%PDF-1.4 fake", url, "site_transform"

    # mock the blocking helper indirectly via _download_and_publish
    monkeypatch.setattr(
        "app.services.papers._resolve_url_to_pdf_bytes",
        lambda u: (b"%PDF-1.4 fake", u, "site_transform"),
    )

    import asyncio
    rec = await mcp_jobs.submit_job("url", "https://arxiv.org/abs/1234.5678",
                                     mcp_jobs.JobOptions())
    assert rec.status == "downloading"
    assert rec.expected_filename.startswith("pfmcp-")

    # Wait for bg task to finish
    task = mcp_jobs._active_download_tasks.get(rec.job_id)
    if task:
        await task

    # Now should be queued + file landed
    final = await mcp_jobs.get_job(rec.job_id)
    assert final.status == "queued"
    assert final.import_method == "site_transform"
    landed = tmp_workspace / "newones" / rec.expected_filename
    assert landed.exists()


async def test_url_resolve_failure_marks_error(tmp_workspace, monkeypatch):
    from app.services import mcp_jobs

    def fail_resolve(url):
        raise ValueError("dead link")

    monkeypatch.setattr("app.services.papers._resolve_url_to_pdf_bytes", fail_resolve)

    rec = await mcp_jobs.submit_job("url", "https://bad.example.com/x",
                                     mcp_jobs.JobOptions())
    # Wait for bg task
    task = mcp_jobs._active_download_tasks.get(rec.job_id)
    if task:
        try:
            await task
        except Exception:
            pass

    final = await mcp_jobs.get_job(rec.job_id)
    assert final.status == "error"
    assert "dead link" in final.error


async def test_cancel_race_during_publish(tmp_workspace, monkeypatch):
    """Simulate cancel arriving between Stage 1 and Stage 2 — .pdf must not appear."""
    from app.services import mcp_jobs

    monkeypatch.setattr(
        "app.services.papers._resolve_url_to_pdf_bytes",
        lambda u: (b"%PDF-1.4 fake", u, "site_transform"),
    )

    rec = await mcp_jobs.submit_job("url", "https://arxiv.org/abs/9999.99999",
                                     mcp_jobs.JobOptions())
    # Flip status to cancelled BEFORE the bg task reaches Stage 2
    # (race window: between to_thread(write_part) return and the lock acquire)
    await mcp_jobs._set_job_fields(rec.job_id, status="cancelled",
                                    completed_at=mcp_jobs._now_iso())

    task = mcp_jobs._active_download_tasks.get(rec.job_id)
    if task:
        try:
            await task
        except Exception:
            pass

    # .pdf must NOT exist; .part must be cleaned
    dest = tmp_workspace / "newones" / rec.expected_filename
    part = dest.with_suffix(dest.suffix + ".part")
    assert not dest.exists(), "cancelled job's PDF was published"
    assert not part.exists(), "part file leaked"
```

- [ ] **Step 6.2: Run — verify pass (logic already in Task 5)**

```bash
cd viewer && python -m pytest tests/test_mcp_jobs.py -v -k "url or cancel_race"
```

Expected: 3 passed. If `test_cancel_race_during_publish` is flaky (timing-dependent), the publish window is intentionally narrow. The test passes when status flip happens before lock acquire — which `await` ordering in the test guarantees most of the time. If consistently failing, debug the race window.

- [ ] **Step 6.3: Commit**

```bash
git add viewer/tests/test_mcp_jobs.py
git commit -m "test(mcp): URL submit bg downloader + cancel race coverage"
```

---

## Task 7: `mcp_jobs.py` — reconcile (primary + fallback) + cancel + list

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Modify: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 7.1: Write failing tests**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
async def test_reconcile_fallback_when_metadata_skipped(tmp_workspace):
    """Primary find_processed_paper miss + outputs/<folder>/<expected_filename> present
    → status=complete via fallback scan."""
    from app.services import mcp_jobs

    # Create a job manually in the index
    rec = await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
        pdf_bytes_b64=__import__("base64").b64encode(b"%PDF-fake").decode())
    # Place "processed" output: outputs/whatever-paper/pfmcp-XXX.pdf
    out_folder = tmp_workspace / "outputs" / "WhatevPaper"
    out_folder.mkdir(parents=True)
    (out_folder / rec.expected_filename).write_bytes(b"%PDF-fake")
    # Bump mtime to be after submitted_at
    import time
    time.sleep(0.05)
    out_folder.touch()

    new_rec = await mcp_jobs.reconcile_job(rec.job_id)
    assert new_rec.status == "complete"
    assert new_rec.paper_name == "WhatevPaper"
    assert new_rec.location == "outputs"


async def test_reconcile_error_via_processing_status(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    import json as _json

    rec = await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
        pdf_bytes_b64=__import__("base64").b64encode(b"%PDF-fake").decode())
    # Converter wrote error status for our file
    (settings.logs_dir / "processing_status.json").write_text(_json.dumps({
        "current_file": rec.expected_filename, "stage": "error", "error": "OOM",
    }))
    new_rec = await mcp_jobs.reconcile_job(rec.job_id)
    assert new_rec.status == "error"
    assert "OOM" in new_rec.error


async def test_cancel_job_queued(tmp_workspace):
    from app.services import mcp_jobs

    rec = await mcp_jobs.submit_job("file", "doc.pdf", mcp_jobs.JobOptions(),
        pdf_bytes_b64=__import__("base64").b64encode(b"%PDF-fake").decode())
    # File is queued (in newones/)
    landed = tmp_workspace / "newones" / rec.expected_filename
    assert landed.exists()

    cancelled = await mcp_jobs.cancel_job(rec.job_id, delete_file=True)
    assert cancelled.status == "cancelled"
    # File should be removed
    assert not landed.exists()


async def test_list_jobs(tmp_workspace):
    from app.services import mcp_jobs
    import base64
    for i in range(3):
        await mcp_jobs.submit_job("file", f"doc{i}.pdf", mcp_jobs.JobOptions(),
            pdf_bytes_b64=base64.b64encode(b"%PDF-fake").decode())
    jobs = await mcp_jobs.list_jobs(limit=10)
    assert len(jobs) == 3
    statuses = {j.status for j in jobs}
    assert statuses == {"queued"}
```

- [ ] **Step 7.2: Run — verify failure**

```bash
cd viewer && python -m pytest tests/test_mcp_jobs.py -v -k "reconcile or cancel_job or list"
```

Expected: AttributeError for `reconcile_job`, `cancel_job`, `list_jobs`.

- [ ] **Step 7.3: Implement reconcile + cancel + list**

Append to `viewer/app/services/mcp_jobs.py`:

```python
# ── Reconcile ─────────────────────────────────────────────────────────────────
def _scan_outputs_for_filename(expected_filename: str) -> tuple[str, Literal["outputs", "archives"]] | None:
    """Fallback: scan outputs/ and archives/ for any folder containing expected_filename."""
    for loc_name, base in (("outputs", settings.outputs_dir), ("archives", settings.archives_dir)):
        if not base.exists():
            continue
        for sub in base.iterdir():
            if sub.is_dir() and (sub / expected_filename).is_file():
                return sub.name, loc_name
    return None


async def reconcile_job(job_id: str) -> JobRecord | None:
    """Refresh status by inspecting filesystem + processing_status.json."""
    from . import papers as _papers

    rec = await get_job(job_id)
    if not rec:
        return None
    if rec.status in ("complete", "error", "cancelled"):
        return rec

    # Downloading: bg task interrupted (viewer restart)?
    if rec.status == "downloading" and job_id not in _active_download_tasks:
        await _set_job_fields(job_id, status="error",
                               error="download interrupted, retry submit",
                               completed_at=_now_iso())
        return await get_job(job_id)

    # Primary complete lookup (metadata-backed)
    info = _papers.find_processed_paper(original_filename=rec.expected_filename)
    if info:
        # Verify freshness — paper_meta.json mtime > submitted_at if it exists
        await _set_job_fields(job_id, status="complete",
                               paper_name=info["name"], location=info["location"],
                               completed_at=_now_iso())
        return await get_job(job_id)

    # Fallback scan
    scan = _scan_outputs_for_filename(rec.expected_filename)
    if scan:
        await _set_job_fields(job_id, status="complete",
                               paper_name=scan[0], location=scan[1],
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

            # stalled detection: mtime > 30min + still processing
            import time as _time
            if rec.status == "processing":
                age = _time.time() - ps_path.stat().st_mtime
                if age > 30 * 60:
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
async def cancel_job(job_id: str, delete_file: bool = True) -> JobRecord | None:
    """Cancel job. Behavior depends on current status."""
    from . import papers as _papers

    rec = await get_job(job_id)
    if not rec:
        return None
    if rec.status in ("complete", "error", "cancelled"):
        return rec  # idempotent

    if rec.status == "downloading":
        task = _active_download_tasks.get(job_id)
        if task:
            task.cancel()
        # cleanup .part if exists
        part = settings.newones_dir / (rec.expected_filename + ".part")
        part.unlink(missing_ok=True)
        await _set_job_fields(job_id, status="cancelled",
                               completed_at=_now_iso())
        return await get_job(job_id)

    # queued/processing/stalled: delegate to existing helper
    ok, msg = _papers.request_cancel_processing(rec.expected_filename,
                                                  delete_file=delete_file, force=True)
    await _set_job_fields(job_id, status="cancelled",
                           error=None if ok else msg,
                           completed_at=_now_iso())
    return await get_job(job_id)


# ── List ──────────────────────────────────────────────────────────────────────
async def list_jobs(limit: int = 50, status: str | None = None) -> list[JobRecord]:
    async with _index_lock:
        idx = await _load_index()
    records = [JobRecord.model_validate(v) for v in idx.values()]
    if status:
        records = [r for r in records if r.status == status]
    records.sort(key=lambda r: r.submitted_at, reverse=True)
    return records[:limit]


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
```

- [ ] **Step 7.4: Run tests — verify pass**

```bash
cd viewer && python -m pytest tests/test_mcp_jobs.py -v
```

Expected: all (15+ total) pass.

- [ ] **Step 7.5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp): reconcile (primary+fallback), cancel, list_jobs, cancel_all"
```

---

## Task 8: `mcp_jobs.py` — cleanup + cached short-circuit

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Modify: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 8.1: Write failing tests**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
async def test_cleanup_expired_jobs(tmp_workspace):
    from app.services import mcp_jobs
    import datetime as dt
    # Inject an expired complete + a fresh queued
    expired_at = (dt.datetime.now() - dt.timedelta(days=1)).isoformat(timespec="seconds")
    async with mcp_jobs._index_lock:
        idx = await mcp_jobs._load_index()
        idx["expired"] = {
            "job_id": "expired", "input_type": "file", "source": "x.pdf",
            "expected_filename": "pfmcp-expired-x.pdf",
            "import_method": "file_upload",
            "options": {"force_reprocess": False},
            "status": "complete", "stage": None, "percent": 100,
            "paper_name": "x", "location": "outputs", "error": None,
            "submitted_at": "2020-01-01T00:00:00",
            "completed_at": "2020-01-01T00:01:00",
            "expires_at": expired_at,
        }
        idx["fresh"] = {
            "job_id": "fresh", "input_type": "file", "source": "y.pdf",
            "expected_filename": "pfmcp-fresh-y.pdf",
            "import_method": "file_upload",
            "options": {"force_reprocess": False},
            "status": "queued", "stage": None, "percent": 0,
            "paper_name": None, "location": None, "error": None,
            "submitted_at": "2020-01-01T00:00:00",
            "completed_at": None,
            "expires_at": (dt.datetime.now() + dt.timedelta(days=7)).isoformat(timespec="seconds"),
        }
        await mcp_jobs._atomic_write_index(idx)

    deleted = await mcp_jobs.cleanup_expired_jobs()
    assert deleted == 1
    assert await mcp_jobs.get_job("expired") is None
    assert await mcp_jobs.get_job("fresh") is not None


def test_cleanup_stale_mcp_tmp(tmp_workspace):
    from app.services import mcp_jobs
    import time, os as _os
    tmp_dir = tmp_workspace / "newones" / ".mcp_tmp"
    old_file = tmp_dir / "old.pdf"
    new_file = tmp_dir / "new.pdf"
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")
    # Make old_file mtime 2 hours ago
    two_hours_ago = time.time() - 7200
    _os.utime(old_file, (two_hours_ago, two_hours_ago))

    removed = mcp_jobs._cleanup_stale_mcp_tmp(max_age_seconds=3600)
    assert removed == 1
    assert not old_file.exists()
    assert new_file.exists()


async def test_submit_cached_url_returns_complete(tmp_workspace, monkeypatch):
    """If find_processed_paper returns hit on URL, submit returns status=complete (no download)."""
    from app.services import mcp_jobs
    from app.services import papers as _papers

    def fake_find(*, original_filename=None, source_url=None):
        if source_url:
            return {"name": "AlreadyHere", "location": "outputs", "viewer_path": "/viewer/AlreadyHere"}
        return None

    monkeypatch.setattr(_papers, "find_processed_paper", fake_find)

    rec = await mcp_jobs.submit_job("url", "https://arxiv.org/abs/0000.00000",
                                     mcp_jobs.JobOptions(force_reprocess=False))
    assert rec.status == "complete"
    assert rec.paper_name == "AlreadyHere"
    assert rec.location == "outputs"


async def test_force_reprocess_skips_cache(tmp_workspace, monkeypatch):
    from app.services import mcp_jobs
    from app.services import papers as _papers

    def fake_find(*, original_filename=None, source_url=None):
        return {"name": "AlreadyHere", "location": "outputs", "viewer_path": "x"}

    def fake_resolve(url):
        return b"%PDF-1.4 fake", url, "site_transform"

    monkeypatch.setattr(_papers, "find_processed_paper", fake_find)
    monkeypatch.setattr(_papers, "_resolve_url_to_pdf_bytes", fake_resolve)

    rec = await mcp_jobs.submit_job("url", "https://arxiv.org/abs/0000.00000",
                                     mcp_jobs.JobOptions(force_reprocess=True))
    assert rec.status == "downloading"  # cache bypassed
```

- [ ] **Step 8.2: Run — verify failure**

```bash
cd viewer && python -m pytest tests/test_mcp_jobs.py -v -k "cleanup or cached or force_reprocess"
```

Expected: AttributeError for `cleanup_expired_jobs`, `_cleanup_stale_mcp_tmp`, and assertion failures.

- [ ] **Step 8.3: Add cleanup helpers + cached short-circuit in submit_job**

Add to `viewer/app/services/mcp_jobs.py`:

```python
# ── Cleanup ───────────────────────────────────────────────────────────────────
def _cleanup_stale_mcp_tmp(max_age_seconds: int = 3600) -> int:
    """Remove files in newones/.mcp_tmp older than max_age_seconds. Returns count removed."""
    tmp_dir = settings.newones_dir / ".mcp_tmp"
    if not tmp_dir.exists():
        return 0
    import time as _time
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
```

Now modify `submit_job` to short-circuit on cached URL hits. Find the URL branch (`else:` after file branch) and replace its top with:

```python
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
```

- [ ] **Step 8.4: Run tests — verify pass**

```bash
cd viewer && python -m pytest tests/test_mcp_jobs.py -v
```

Expected: all pass.

- [ ] **Step 8.5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp): cleanup_expired_jobs + .mcp_tmp cleanup + cached URL short-circuit"
```

---

## Task 9: `mcp_zip.py` — zip stream builder

**Files:**
- Create: `viewer/app/services/mcp_zip.py`
- Test: `viewer/tests/test_mcp_zip.py`

- [ ] **Step 9.1: Write failing tests**

Create `viewer/tests/test_mcp_zip.py`:

```python
"""Tests for zip stream builder."""
import io
import zipfile
import pytest


@pytest.fixture
def fake_paper_dir(tmp_workspace):
    """Create outputs/FakePaper/ with md, md_ko, pdf, images."""
    paper = tmp_workspace / "outputs" / "FakePaper"
    paper.mkdir(parents=True)
    (paper / "fake.md").write_text("# english", encoding="utf-8")
    (paper / "fake_ko.md").write_text("# 한국어", encoding="utf-8")
    (paper / "fake.pdf").write_bytes(b"%PDF-1.4 dummy")
    (paper / "paper_meta.json").write_text('{"title":"Fake"}', encoding="utf-8")
    img_dir = paper / "images"
    img_dir.mkdir()
    (img_dir / "fig1.jpeg").write_bytes(b"\xff\xd8\xff\xe0")  # JPEG SOI
    return paper


def test_zip_default_no_pdf_with_translation(fake_paper_dir):
    from app.services import mcp_zip
    chunks = list(mcp_zip.build_zip_stream(
        fake_paper_dir, include_pdf=False, include_translation=True, job_meta={"job_id": "j1"}
    ))
    buf = io.BytesIO(b"".join(chunks))
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    assert "fake.md" in names
    assert "fake_ko.md" in names
    assert "paper_meta.json" in names
    assert "images/fig1.jpeg" in names
    assert "README.txt" in names
    assert "fake.pdf" not in names


def test_zip_with_pdf(fake_paper_dir):
    from app.services import mcp_zip
    chunks = list(mcp_zip.build_zip_stream(
        fake_paper_dir, include_pdf=True, include_translation=True, job_meta={"job_id": "j1"}
    ))
    buf = io.BytesIO(b"".join(chunks))
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    assert "fake.pdf" in names


def test_zip_without_translation(fake_paper_dir):
    from app.services import mcp_zip
    chunks = list(mcp_zip.build_zip_stream(
        fake_paper_dir, include_pdf=False, include_translation=False, job_meta={"job_id": "j1"}
    ))
    buf = io.BytesIO(b"".join(chunks))
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    assert "fake_ko.md" not in names
    assert "fake.md" in names  # english always
```

- [ ] **Step 9.2: Run — verify failure**

```bash
cd viewer && python -m pytest tests/test_mcp_zip.py -v
```

Expected: `ModuleNotFoundError: app.services.mcp_zip`.

- [ ] **Step 9.3: Implement zip stream builder**

Create `viewer/app/services/mcp_zip.py`:

```python
"""Stream-build a zip of a processed paper folder."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Iterator


_CHUNK_SIZE = 64 * 1024


def build_zip_stream(
    paper_dir: Path,
    *,
    include_pdf: bool,
    include_translation: bool,
    job_meta: dict,
) -> Iterator[bytes]:
    """Yield zip bytes in chunks. Caller provides StreamingResponse wrapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # README first
        readme = (
            "PaperFlow MCP zip export\n"
            f"job_id: {job_meta.get('job_id','?')}\n"
            f"paper: {paper_dir.name}\n"
            f"include_pdf: {include_pdf}\n"
            f"include_translation: {include_translation}\n"
        )
        zf.writestr("README.txt", readme)

        for entry in sorted(paper_dir.iterdir()):
            if entry.is_file():
                name = entry.name
                # Skip backup files and source sidecars
                if "_backup_" in name or name.endswith(".url.txt") or name.endswith(".mcp.json"):
                    continue
                # PDF gated
                if name.lower().endswith(".pdf") and not include_pdf:
                    continue
                # _ko.md and _ko_explained.md gated by include_translation
                lower = name.lower()
                if lower.endswith("_ko.md") and not include_translation:
                    continue
                if lower.endswith("_ko_explained.md") and not include_translation:
                    continue
                zf.write(entry, arcname=name)
            elif entry.is_dir() and entry.name in ("images",):
                for img in sorted(entry.iterdir()):
                    if img.is_file():
                        zf.write(img, arcname=f"{entry.name}/{img.name}")

    # Stream the in-memory buffer in chunks
    buf.seek(0)
    while True:
        chunk = buf.read(_CHUNK_SIZE)
        if not chunk:
            return
        yield chunk
```

- [ ] **Step 9.4: Run tests — verify pass**

```bash
cd viewer && python -m pytest tests/test_mcp_zip.py -v
```

Expected: 3 passed.

- [ ] **Step 9.5: Commit**

```bash
git add viewer/app/services/mcp_zip.py viewer/tests/test_mcp_zip.py
git commit -m "feat(mcp): mcp_zip.py — stream-build paper folder as zip"
```

---

## Task 10: `mcp_router.py` — FastMCP tools + zip endpoint + ASGI wrapper

**Files:**
- Create: `viewer/app/routers/mcp_router.py`
- Test: `viewer/tests/test_mcp_router.py`

- [ ] **Step 10.1: Write failing tests**

Create `viewer/tests/test_mcp_router.py`:

```python
"""Integration tests for mcp_router (zip endpoint + verify_mcp_key)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_mcp(mcp_enabled_workspace):
    """FastAPI app with MCP enabled. Re-create after env override."""
    # Force reimport so create_app reads fresh settings
    import importlib
    from app import main as _main
    importlib.reload(_main)
    return _main.app


def test_zip_endpoint_requires_bearer(app_with_mcp):
    client = TestClient(app_with_mcp)
    r = client.get("/api/mcp/jobs/nonexistent/zip")
    assert r.status_code == 401


def test_zip_endpoint_wrong_bearer(app_with_mcp):
    client = TestClient(app_with_mcp)
    r = client.get("/api/mcp/jobs/nonexistent/zip",
                   headers={"Authorization": "Bearer wrongkey"})
    assert r.status_code == 401


def test_zip_endpoint_404_when_job_missing(app_with_mcp, mcp_enabled_workspace):
    from app.config import settings
    client = TestClient(app_with_mcp)
    r = client.get("/api/mcp/jobs/nonexistent/zip",
                   headers={"Authorization": f"Bearer {settings.MCP_API_KEY}"})
    assert r.status_code == 404


def test_mcp_mount_404_when_disabled(tmp_workspace):
    """When MCP_API_KEY unset, /mcp must not be mounted."""
    import importlib
    from app import main as _main
    importlib.reload(_main)
    client = TestClient(_main.app)
    r = client.post("/mcp", headers={"Content-Type": "application/json"})
    assert r.status_code == 404
```

- [ ] **Step 10.2: Run — verify failure**

```bash
cd viewer && python -m pytest tests/test_mcp_router.py -v
```

Expected: ModuleNotFoundError or 404 errors because mcp_router doesn't exist yet.

- [ ] **Step 10.3: Implement mcp_router.py**

Create `viewer/app/routers/mcp_router.py`:

```python
"""MCP server: FastMCP tools + ASGI auth wrapper + zip download endpoint.

Only mounted when settings.mcp_enabled is True (see main.py).
"""
from __future__ import annotations

import base64
import contextlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from mcp.server.fastmcp import FastMCP

from ..config import settings
from ..services import mcp_jobs, mcp_zip
from ..services import papers as paper_svc


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
    """Get processed paper metadata + download URL. Only valid when status=complete."""
    rec = await mcp_jobs.reconcile_job(job_id)
    if not rec:
        raise ValueError(f"job not found: {job_id}")
    if rec.status != "complete":
        raise ValueError(f"job not complete (status={rec.status})")

    paper_dir = paper_svc.safe_paper_dir(rec.paper_name)
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

    base = settings.MCP_PUBLIC_BASE_URL.rstrip("/")
    download_url = (
        f"{base}/api/mcp/jobs/{job_id}/zip"
        f"?include_pdf={'true' if include_pdf else 'false'}"
        f"&include_translation={'true' if include_translation else 'false'}"
    )

    return {
        "job_id": job_id,
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
        "download_url": download_url,
        "expires_at": rec.expires_at,
    }


@mcp.tool()
async def cancel_job(job_id: str, delete_file: bool = True) -> dict:
    """Cancel a job. Idempotent."""
    rec = await mcp_jobs.cancel_job(job_id, delete_file=delete_file)
    if not rec:
        raise ValueError(f"job not found: {job_id}")
    return {"job_id": job_id, "status": rec.status}


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
    if not authorization.startswith("Bearer ") or authorization[7:] != settings.MCP_API_KEY:
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
    rec = await mcp_jobs.get_job(job_id)
    if not rec or rec.status != "complete":
        raise HTTPException(status_code=404, detail="Job not complete or not found")
    paper_dir = paper_svc.safe_paper_dir(rec.paper_name)
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
```

- [ ] **Step 10.4: Run integration tests (one will still fail — need main.py mount)**

```bash
cd viewer && python -m pytest tests/test_mcp_router.py -v
```

Expected: `test_mcp_mount_404_when_disabled` and `test_zip_endpoint_*` may fail because main.py doesn't mount the router yet. That's expected — fixed in Task 11.

- [ ] **Step 10.5: Commit**

```bash
git add viewer/app/routers/mcp_router.py viewer/tests/test_mcp_router.py
git commit -m "feat(mcp): mcp_router.py — FastMCP 5 tools + ASGI auth wrapper + zip endpoint"
```

---

## Task 11: `main.py` — lifespan + conditional MCP mount

**Files:**
- Modify: `viewer/app/main.py`

- [ ] **Step 11.1: Update main.py**

Replace `viewer/app/main.py` entirely with:

```python
import asyncio
import contextlib
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import api, pages


async def _periodic_mcp_cleanup():
    from .services import mcp_jobs as _mcp_jobs
    while True:
        try:
            await asyncio.sleep(3600)
            await _mcp_jobs.cleanup_expired_jobs()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


@contextlib.asynccontextmanager
async def app_lifespan(app: FastAPI):
    cleanup_task: asyncio.Task | None = None

    if settings.mcp_enabled:
        from .routers import mcp_router as _mcp_router
        from .services import mcp_jobs as _mcp_jobs

        async with _mcp_router.mcp_lifespan():
            # startup cleanup pass
            await _mcp_jobs.cleanup_expired_jobs()
            cleanup_task = asyncio.create_task(_periodic_mcp_cleanup())
            try:
                yield
            finally:
                if cleanup_task is not None:
                    cleanup_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await cleanup_task
                await _mcp_jobs.cancel_all_active_downloads(reason="shutdown")
    else:
        yield


def create_app() -> FastAPI:
    settings.validate_runtime()
    application = FastAPI(
        title="PaperFlow Viewer",
        docs_url=None,
        redoc_url=None,
        lifespan=app_lifespan,
    )

    # Routers (always)
    application.include_router(api.router)
    application.include_router(pages.router)

    # MCP (opt-in: only when MCP_API_KEY is set + base URL configured)
    if settings.mcp_enabled:
        from .routers import mcp_router as _mcp_router
        application.include_router(_mcp_router.mcp_zip_router)
        _mcp_router.mount_mcp(
            application,
            api_key=settings.MCP_API_KEY,
            allowed_origins=settings.mcp_allowed_origins_set,
        )

    # Static files
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return application


app = create_app()
```

- [ ] **Step 11.2: Run integration tests — verify all pass**

```bash
cd viewer && python -m pytest tests/test_mcp_router.py -v
```

Expected: all 4 pass.

- [ ] **Step 11.3: Run the full test suite**

```bash
cd viewer && python -m pytest -v
```

Expected: all green.

- [ ] **Step 11.4: Commit**

```bash
git add viewer/app/main.py
git commit -m "feat(mcp): main.py lifespan + conditional MCP mount (opt-in via MCP_API_KEY)"
```

---

## Task 12: Docker Compose env wiring

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 12.1: Inspect current viewer service**

```bash
grep -A 30 "paperflow-viewer:" docker-compose.yml
```

Note the existing `environment:` block under `paperflow-viewer:`. We add 4 vars without changing anything else.

- [ ] **Step 12.2: Add MCP env vars**

In `docker-compose.yml`, under the `paperflow-viewer` service's `environment:` block, append:

```yaml
      - MCP_API_KEY=${MCP_API_KEY:-}
      - MCP_PUBLIC_BASE_URL=${MCP_PUBLIC_BASE_URL:-}
      - MCP_JOB_TTL_DAYS=${MCP_JOB_TTL_DAYS:-7}
      - MCP_ALLOWED_ORIGINS=${MCP_ALLOWED_ORIGINS:-}
```

(Empty defaults preserve current opt-in behavior — without `MCP_API_KEY` in `.env`, MCP stays disabled.)

- [ ] **Step 12.3: Validate compose file**

```bash
docker compose config -q
```

Expected: no output (success).

- [ ] **Step 12.4: Commit**

```bash
git add docker-compose.yml
git commit -m "infra: wire MCP_* env vars into paperflow-viewer service (opt-in defaults)"
```

---

## Task 13: Build image + smoke test + register MCP

**Files:** None new. Run-only.

- [ ] **Step 13.1: Generate a strong key + add to .env**

```bash
echo "MCP_API_KEY=$(openssl rand -hex 32)" >> .env
echo "MCP_PUBLIC_BASE_URL=http://localhost:8090" >> .env
```

- [ ] **Step 13.2: Rebuild viewer image**

```bash
docker compose build paperflow-viewer && docker compose up -d paperflow-viewer
```

Wait ~10s for startup.

- [ ] **Step 13.3: Confirm MCP enabled — check viewer logs**

```bash
docker compose logs paperflow-viewer | tail -30
```

Expected: no "MCP_PUBLIC_BASE_URL missing" RuntimeError; uvicorn started cleanly.

- [ ] **Step 13.4: Smoke test — unauthorized**

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8090/mcp \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Expected: `401`

- [ ] **Step 13.5: Smoke test — authorized list_tools**

```bash
MCP_KEY=$(grep ^MCP_API_KEY= .env | cut -d= -f2)
curl -s -X POST http://localhost:8090/mcp \
    -H "Authorization: Bearer $MCP_KEY" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
    | head -c 2000
```

Expected: JSON response containing 5 tools: `submit_paper`, `get_job_status`, `get_job_result`, `cancel_job`, `list_jobs`.

- [ ] **Step 13.6: Register with Claude Code**

```bash
claude mcp add paperflow --transport http \
    --url http://localhost:8090/mcp \
    --header "Authorization: Bearer $MCP_KEY"
```

Then in Claude Code, run `/mcp` and confirm `paperflow` is listed with 5 tools.

- [ ] **Step 13.7: E2E — submit an arXiv URL through Claude Code**

In Claude Code session, ask Claude to call `submit_paper` with an arXiv URL (e.g., `https://arxiv.org/abs/1706.03762`), then poll `get_job_status` until `complete`, then call `get_job_result` and download the zip.

Expected behaviors to verify:
- submit returns `{status: "downloading", job_id: ...}` immediately (< 1s)
- get_job_status progresses: downloading → queued → processing → complete (5-15 min total)
- get_job_result returns `download_url`
- `curl -H "Authorization: Bearer $MCP_KEY" $DOWNLOAD_URL -o /tmp/paper.zip` downloads a valid zip
- `unzip -l /tmp/paper.zip` shows `README.txt`, `paper_meta.json`, `*.md`, `*_ko.md`, `images/*.jpeg`

- [ ] **Step 13.8: Cached re-submit test**

Repeat the same arXiv URL submit. Expected: `{status: "complete", cached: true}` within 1 second.

- [ ] **Step 13.9: Final smoke commit (no code changes, just doc)**

If you noticed any discrepancies or wrote down setup notes, commit them:

```bash
git add .env.example  # if you created/updated one
git commit -m "docs: example .env entries for MCP server"
```

(Skip if no doc changes needed.)

---

## Post-Implementation Checklist

- [ ] All viewer tests green (`cd viewer && pytest -v`)
- [ ] Watch mode still picks up PDFs from `newones/` (drop a real PDF, confirm processing)
- [ ] viewer UI still loads `/login`, `/papers`, `/viewer/<name>` (no regressions)
- [ ] `docker compose logs paperflow-viewer | grep -i error` → no MCP-related errors
- [ ] Claude Code `/mcp` shows `paperflow` server connected
- [ ] arXiv URL E2E completed successfully (submit → poll → result → zip download → unzip)
- [ ] Cached re-submit < 1s

If any item fails, debug before declaring the v1 ship done.
