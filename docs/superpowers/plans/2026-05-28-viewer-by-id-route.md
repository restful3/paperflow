# `/viewer/by-id/{source_id}` Stable Identifier Route — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MCP `get_job_result` 가 반환하는 viewer 링크를 폴더명(`paper_name`) 대신 durable 한 `paperflow_source_id`(= `expected_filename`) 기반으로 만들어, 폴더 rename/archive 이동 후에도 깨지지 않게 한다.

**Architecture:** 새 라우트 `GET /viewer/by-id/{source_id}` 가 source_id 를 검증·해석해 현재 폴더의 `/viewer/{paper_name}` 으로 302 redirect 한다. 해석은 `mcp_jobs.py` 의 기존 `_resolve_completed_candidate` (4-step priority) 를 public wrapper 로 감싸 재사용한다. MCP `get_job_result.viewer_url` 도 이 by-id 형태로 교체한다.

**Tech Stack:** FastAPI/Starlette, pytest (`pytest-asyncio`), 기존 `tmp_workspace` / `mcp_enabled_workspace` fixtures.

**Spec:** `docs/superpowers/specs/2026-05-28-viewer-by-id-route-design.md` (Codex round-2 ACCEPT)

---

## File Structure

| File | 책임 | 변경 |
|------|------|------|
| `viewer/app/services/mcp_jobs.py` | source_id 검증 + 해석 | `_SOURCE_ID_SAFE_RE`, `_is_safe_source_id`, `resolve_paper_by_source_id` 추가 |
| `viewer/app/routers/pages.py` | by-id 라우트 | `_by_id_redirect` 헬퍼 + `viewer_by_id` 라우트 (catch-all **위**), `mcp_jobs` import |
| `viewer/app/routers/mcp_router.py` | viewer_url 계약 | viewer_url 한 줄 교체 + docstring |
| `viewer/tests/test_mcp_jobs.py` | resolver unit | T5a/T5b/T7 추가 |
| `viewer/tests/test_viewer_by_id.py` (신규) | route integration | T1–T6, T5c, T5d, T8, T11 |
| `viewer/tests/test_mcp_router.py` | viewer_url 계약 | T20/T22 갱신 + T9 추가 |
| `CLAUDE.md`, `README.md` | 문서 | gotcha #12/#14 + MCP contract 표 |

모든 테스트 명령은 `viewer/` 에서 실행: `cd viewer && python -m pytest ...`

---

## Task 1: source_id 검증 + 해석기 (`mcp_jobs.py`)

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py` (constant 추가는 `_FILENAME_SAFE_RE` 정의부 `:91` 근처, 함수는 `_resolve_completed_candidate` 끝 `:424` 직후)
- Test: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 1: Write the failing tests**

`viewer/tests/test_mcp_jobs.py` 끝에 추가:

```python
# ── T5a/T5b/T7: by-id source_id validation + resolution ──────────────────────

def test_is_safe_source_id_accepts_valid_pfmcp():
    from app.services.mcp_jobs import _is_safe_source_id
    assert _is_safe_source_id("pfmcp-abcdef123456-example.com.pdf") is True
    assert _is_safe_source_id("pfmcp-0-doc.pdf") is True


def test_is_safe_source_id_rejects_traversal_and_contract_violations():
    from app.services.mcp_jobs import _is_safe_source_id
    bad = [
        "",                         # empty
        ".", "..",                  # dot segments
        "../etc/passwd",            # traversal
        "a/b.pdf", "a\\b.pdf",      # separators
        "pfmcp-\x00-x.pdf",         # NUL
        "pfmcp-" + "a" * 200 + ".pdf",  # over length
        "paper_meta.json",          # contract: no pfmcp- prefix / .pdf suffix
        "foo.pdf",                  # contract: no pfmcp- prefix
        ".hidden",                  # contract
        "pfmcp-abc-x.txt",          # contract: wrong suffix
        "pfmcp-abc x.pdf",          # whitespace
        "pfmcp-abc%2e.pdf",         # percent char
    ]
    for s in bad:
        assert _is_safe_source_id(s) is False, s


@pytest.mark.asyncio
async def test_resolve_paper_by_source_id_rejects_unsafe_without_fs_access(tmp_workspace, monkeypatch):
    """Unsafe input returns None and never touches the filesystem scan."""
    from app.services import mcp_jobs
    called = {"n": 0}
    def _boom(*a, **k):
        called["n"] += 1
        return None
    monkeypatch.setattr(mcp_jobs, "_resolve_completed_candidate", _boom)
    assert mcp_jobs.resolve_paper_by_source_id("../etc") is None
    assert mcp_jobs.resolve_paper_by_source_id("foo.pdf") is None
    assert called["n"] == 0  # validation rejected before resolver call


@pytest.mark.asyncio
async def test_resolve_paper_by_source_id_outputs_scan(tmp_workspace):
    """Valid source_id present as source PDF in outputs/ resolves to (name, 'outputs')."""
    from app.services import mcp_jobs
    sid = "pfmcp-aaaaaaaaaaaa-doc.pdf"
    out = tmp_workspace / "outputs" / "Some Paper"
    out.mkdir()
    (out / sid).touch()
    assert mcp_jobs.resolve_paper_by_source_id(sid) == ("Some Paper", "outputs")


@pytest.mark.asyncio
async def test_resolve_paper_by_source_id_archives_only(tmp_workspace):
    """Source PDF only in archives/ → resolves to (name, 'archives')."""
    from app.services import mcp_jobs
    sid = "pfmcp-bbbbbbbbbbbb-doc.pdf"
    arc = tmp_workspace / "archives" / "Archived Paper"
    arc.mkdir()
    (arc / sid).touch()
    assert mcp_jobs.resolve_paper_by_source_id(sid) == ("Archived Paper", "archives")


@pytest.mark.asyncio
async def test_resolve_paper_by_source_id_outputs_wins_over_archives(tmp_workspace):
    """4-step priority: outputs match wins even when archives also has it."""
    from app.services import mcp_jobs
    sid = "pfmcp-cccccccccccc-doc.pdf"
    (tmp_workspace / "outputs" / "P").mkdir()
    (tmp_workspace / "outputs" / "P" / sid).touch()
    (tmp_workspace / "archives" / "P").mkdir()
    (tmp_workspace / "archives" / "P" / sid).touch()
    assert mcp_jobs.resolve_paper_by_source_id(sid) == ("P", "outputs")


@pytest.mark.asyncio
async def test_resolve_paper_by_source_id_not_found(tmp_workspace):
    from app.services import mcp_jobs
    assert mcp_jobs.resolve_paper_by_source_id("pfmcp-dddddddddddd-missing.pdf") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && python -m pytest tests/test_mcp_jobs.py -k "source_id" -v`
Expected: FAIL — `AttributeError: module 'app.services.mcp_jobs' has no attribute '_is_safe_source_id'` (and `resolve_paper_by_source_id`).

- [ ] **Step 3: Implement the validator + wrapper**

`viewer/app/services/mcp_jobs.py` 의 `_FILENAME_SAFE_RE` 정의 (`:91`) 바로 아래에 상수 추가:

```python
# by-id route: source_id == paperflow_source_id == expected_filename,
# 형식이 항상 pfmcp-{job_id[:12]}-{slug[:40]}.pdf 로 고정 (_build_expected_filename).
# contract 까지 검증해 임의 안전 파일명(paper_meta.json, foo.pdf, .hidden) probing 차단.
_SOURCE_ID_SAFE_RE = re.compile(r"^pfmcp-[A-Za-z0-9._-]{1,120}\.pdf$")
```

`_resolve_completed_candidate` 함수 끝 (`:424` `return None` 직후) 에 추가:

```python
def _is_safe_source_id(source_id: str) -> bool:
    """Validate a by-id route source_id before any filesystem access.

    Rejects path traversal (separators, dot segments, NUL) and non-contract
    filenames. Accepts only the pfmcp-...pdf shape that MCP jobs produce.
    """
    if not source_id or source_id in (".", ".."):
        return False
    if "/" in source_id or "\\" in source_id or "\x00" in source_id:
        return False
    return bool(_SOURCE_ID_SAFE_RE.match(source_id))


def resolve_paper_by_source_id(source_id: str) -> tuple[str, str] | None:
    """Map a durable paperflow_source_id (== expected_filename) to
    (paper_name, location). Validates source_id against path traversal + the
    pfmcp-...pdf contract, then reuses the 4-step _resolve_completed_candidate
    priority. Disk-based — works beyond the MCP job-index TTL.
    """
    if not _is_safe_source_id(source_id):
        return None
    return _resolve_completed_candidate(source_id)
```

(`re` 는 이미 `mcp_jobs.py:13` 에서 import 됨 — 확인만.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && python -m pytest tests/test_mcp_jobs.py -k "source_id" -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "$(cat <<'EOF'
feat(mcp): add resolve_paper_by_source_id with pfmcp contract validation

Public wrapper over _resolve_completed_candidate for the upcoming
/viewer/by-id route. Validates source_id against path traversal and the
pfmcp-...pdf contract before any filesystem scan.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `/viewer/by-id/{source_id}` 라우트 (`pages.py`)

**Files:**
- Modify: `viewer/app/routers/pages.py` (import `:8` 근처, 헬퍼+라우트는 기존 `/viewer/{paper_name:path}` 라우트 `:36` **앞**)
- Test: `viewer/tests/test_viewer_by_id.py` (신규)

- [ ] **Step 1: Write the failing tests**

`viewer/tests/test_viewer_by_id.py` 신규 생성:

```python
"""Integration tests for /viewer/by-id/{source_id} (T1-T11)."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def page_app(tmp_workspace):
    """Fresh app under an isolated workspace. pages.router is always included."""
    from app import main as _main
    importlib.reload(_main)
    return _main.app


def _authed_client(app):
    from app.dependencies import get_current_user_page
    app.dependency_overrides[get_current_user_page] = lambda: "tester"
    return TestClient(app, follow_redirects=False)


def _anon_client(app):
    from app.dependencies import get_current_user_page
    app.dependency_overrides[get_current_user_page] = lambda: None
    return TestClient(app, follow_redirects=False)


def _make_paper(tmp_workspace, location, folder, source_id):
    d = tmp_workspace / location / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / source_id).touch()
    return d


def test_by_id_valid_redirects_to_viewer(page_app, tmp_workspace):
    """T1 — valid source_id, authed → 302 /viewer/{quoted name} + no-store."""
    sid = "pfmcp-aaaaaaaaaaaa-doc.pdf"
    _make_paper(tmp_workspace, "outputs", "Some Paper", sid)
    client = _authed_client(page_app)
    r = client.get(f"/viewer/by-id/{sid}")
    assert r.status_code == 302
    assert r.headers["location"] == "/viewer/Some%20Paper"
    assert r.headers["cache-control"] == "no-store"


def test_by_id_archives_location(page_app, tmp_workspace):
    """T2 — source only in archives/ resolves and redirects to that folder."""
    sid = "pfmcp-bbbbbbbbbbbb-doc.pdf"
    _make_paper(tmp_workspace, "archives", "Archived Paper", sid)
    client = _authed_client(page_app)
    r = client.get(f"/viewer/by-id/{sid}")
    assert r.status_code == 302
    assert r.headers["location"] == "/viewer/Archived%20Paper"


def test_by_id_anonymous_redirects_login(page_app, tmp_workspace):
    """T3 — unauthenticated → 302 /login + no-store."""
    sid = "pfmcp-aaaaaaaaaaaa-doc.pdf"
    _make_paper(tmp_workspace, "outputs", "Some Paper", sid)
    client = _anon_client(page_app)
    r = client.get(f"/viewer/by-id/{sid}")
    assert r.status_code == 302
    assert r.headers["location"] == "/login"
    assert r.headers["cache-control"] == "no-store"


def test_by_id_unresolved_redirects_papers(page_app, tmp_workspace):
    """T4 — unknown source_id → 302 /papers + no-store."""
    client = _authed_client(page_app)
    r = client.get("/viewer/by-id/pfmcp-zzzzzzzzzzzz-missing.pdf")
    assert r.status_code == 302
    assert r.headers["location"] == "/papers"
    assert r.headers["cache-control"] == "no-store"


def test_by_id_encoded_dot_segment_rejected(page_app, tmp_workspace):
    """T5c — %2e%2e decodes to '..' (single segment), reaches handler,
    validator rejects → 302 /papers."""
    client = _authed_client(page_app)
    r = client.get("/viewer/by-id/%2e%2e")
    assert r.status_code == 302
    assert r.headers["location"] == "/papers"


def test_by_id_encoded_slash_not_processed_by_resolver(page_app, tmp_workspace, monkeypatch):
    """T5d — encoded slash is absorbed by the catch-all /viewer/{path} route,
    NOT processed by the by-id resolver. Env-confirmed: authed → 302 /papers."""
    from app.services import mcp_jobs
    spy = {"called_with": []}
    real = mcp_jobs.resolve_paper_by_source_id
    def _spy(s):
        spy["called_with"].append(s)
        return real(s)
    monkeypatch.setattr(mcp_jobs, "resolve_paper_by_source_id", _spy)

    client = _authed_client(page_app)
    r = client.get("/viewer/by-id/a%2Fb.pdf")
    # by-id resolver must never receive a slashed multi-segment value
    assert all("/" not in s for s in spy["called_with"])
    assert r.status_code == 302
    assert r.headers["location"] == "/papers"


def test_by_id_rename_durability(page_app, tmp_workspace):
    """T6 — same source_id resolves to the new folder after a rename."""
    sid = "pfmcp-cccccccccccc-doc.pdf"
    old = _make_paper(tmp_workspace, "outputs", "Old Name", sid)
    client = _authed_client(page_app)
    r1 = client.get(f"/viewer/by-id/{sid}")
    assert r1.headers["location"] == "/viewer/Old%20Name"

    old.rename(tmp_workspace / "outputs" / "New Name")
    r2 = client.get(f"/viewer/by-id/{sid}")
    assert r2.status_code == 302
    assert r2.headers["location"] == "/viewer/New%20Name"


def test_by_id_route_order_resolver_is_invoked(page_app, tmp_workspace, monkeypatch):
    """T8 — a valid pfmcp source_id reaches the by-id handler (resolver called),
    proving the route is registered ABOVE the catch-all /viewer/{path}."""
    from app.services import mcp_jobs
    sid = "pfmcp-eeeeeeeeeeee-doc.pdf"
    _make_paper(tmp_workspace, "outputs", "Routed", sid)
    spy = {"n": 0}
    real = mcp_jobs.resolve_paper_by_source_id
    def _spy(s):
        spy["n"] += 1
        return real(s)
    monkeypatch.setattr(mcp_jobs, "resolve_paper_by_source_id", _spy)

    client = _authed_client(page_app)
    r = client.get(f"/viewer/by-id/{sid}")
    assert spy["n"] == 1  # by-id handler ran; not absorbed by catch-all
    assert r.headers["location"] == "/viewer/Routed"


def test_existing_viewer_route_still_redirects_unknown(page_app, tmp_workspace):
    """T11 — existing /viewer/{paper_name} regression: unknown paper → /papers,
    anonymous → /login (auth override isolates the two cases)."""
    authed = _authed_client(page_app)
    r1 = authed.get("/viewer/Nonexistent%20Paper")
    assert r1.status_code == 302
    assert r1.headers["location"] == "/papers"

    anon = _anon_client(page_app)
    r2 = anon.get("/viewer/Nonexistent%20Paper")
    assert r2.status_code == 302
    assert r2.headers["location"] == "/login"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && python -m pytest tests/test_viewer_by_id.py -v`
Expected: T1–T6/T8 FAIL with 404 (route not defined yet) or wrong location; T11 (existing route) may PASS already. The by-id cases must fail.

- [ ] **Step 3: Implement the route**

`viewer/app/routers/pages.py` import 블록 (`:8` `from ..services import papers as paper_svc` 아래) 에 추가:

```python
from ..services import mcp_jobs
```

기존 `@router.get("/viewer/{paper_name:path}", ...)` 데코레이터 (`:36`) **바로 앞** 에 삽입:

```python
def _by_id_redirect(target: str) -> RedirectResponse:
    resp = RedirectResponse(target, status_code=302)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get("/viewer/by-id/{source_id}", response_class=HTMLResponse)
async def viewer_by_id(source_id: str, request: Request,
                       user: str | None = Depends(get_current_user_page)):
    if not user:
        return _by_id_redirect("/login")
    resolved = mcp_jobs.resolve_paper_by_source_id(source_id)
    if not resolved:
        return _by_id_redirect("/papers")
    paper_name, _location = resolved
    return _by_id_redirect(f"/viewer/{quote(paper_name, safe='')}")
```

(`quote` 는 이미 `pages.py:1` 에서 import 됨. 라우트 등록 순서: `viewer_by_id` 가 `viewer_page` **위**에 있어야 catch-all `{paper_name:path}` 가 `by-id/...` 를 흡수하지 않음.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && python -m pytest tests/test_viewer_by_id.py -v`
Expected: PASS (9 tests).

만약 T5d 의 `location == "/papers"` 가 설치된 Starlette 버전에서 다르게 나오면(예: 404), 그것은 spec 4.2 가 설명한 catch-all fallback 동작과 환경이 다르다는 신호다. 그 경우 보안 핵심 불변식(`resolver 가 슬래시 값을 받지 않음` + `2xx 로 임의 파일을 렌더하지 않음`) 만 유지되면 location assertion 을 실제 동작에 맞춰 조정하고, 차이를 spec 4.2 에 메모로 남긴다.

- [ ] **Step 5: Commit**

```bash
git add viewer/app/routers/pages.py viewer/tests/test_viewer_by_id.py
git commit -m "$(cat <<'EOF'
feat(viewer): add /viewer/by-id/{source_id} stable-identifier route

Resolves a durable paperflow_source_id to the current paper folder and
302-redirects to /viewer/{paper_name}, surviving folder rename/archive.
Registered above the catch-all /viewer/{path}. All redirects set no-store.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: MCP `get_job_result.viewer_url` 계약 교체 (`mcp_router.py`)

**Files:**
- Modify: `viewer/app/routers/mcp_router.py` (viewer_url `:151`, docstring `:96-103`)
- Test: `viewer/tests/test_mcp_router.py` (T20 `:179` 갱신, T22 `:232-271` 재작성, T9 신규)

- [ ] **Step 1: Update existing tests (T20/T22) + add T9 — failing**

`viewer/tests/test_mcp_router.py` T20 의 단언 (`:179`) 교체:

```python
    assert result["viewer_url"] == "http://localhost:8090/viewer/by-id/pfmcp-abcdef123456-example.com.pdf"
```

T22 `test_get_job_result_viewer_url_quotes_spaces_and_korean` (`:231-271`) 전체를 by-id 계약 테스트로 재작성:

```python
@pytest.mark.asyncio
async def test_get_job_result_viewer_url_is_by_id_not_paper_name(mcp_enabled_workspace):
    """T22 (updated) — viewer_url is now based on paperflow_source_id
    (expected_filename), NOT paper_name. A paper_name with spaces / Korean
    must no longer leak into viewer_url."""
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    _rebind_module_settings()
    from app.services import mcp_jobs
    from app.routers.mcp_router import get_job_result

    pname = "한글 제목 With Spaces"
    sid = "pfmcp-koreantest1-example.com.pdf"
    pdir = _cfg.settings.outputs_dir / pname
    pdir.mkdir()
    (pdir / f"{pname}.md").write_text("en")
    (pdir / f"{pname}_ko.md").write_text("ko")
    (pdir / sid).touch()

    rec = mcp_jobs.JobRecord(
        job_id="job-kr-1", input_type="url",
        source="https://example.com/x",
        expected_filename=sid,
        import_method="direct_pdf",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name=pname, location="outputs",
        error=None, submitted_at="2026-05-28T10:00:00",
        completed_at="2026-05-28T10:01:00", expires_at="2026-06-04T10:00:00",
    )
    await _seed_complete_job(rec)

    result = await get_job_result(job_id="job-kr-1")

    viewer_url = result["viewer_url"]
    assert viewer_url == f"http://localhost:8090/viewer/by-id/{sid}"
    # paper_name (spaces / Korean) must NOT appear in viewer_url anymore
    assert " " not in viewer_url
    assert "한" not in viewer_url
    assert pname not in viewer_url
```

T22 재작성 블록 끝에 T9 신규 추가:

```python
@pytest.mark.asyncio
async def test_get_job_result_viewer_url_quotes_source_id(mcp_enabled_workspace):
    """T9 — viewer_url uses quote() on expected_filename for path safety."""
    from urllib.parse import quote
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    _rebind_module_settings()
    from app.services import mcp_jobs
    from app.routers.mcp_router import get_job_result

    pname = "Plain Paper"
    sid = "pfmcp-abcdef123456-example.com.pdf"
    pdir = _cfg.settings.outputs_dir / pname
    pdir.mkdir()
    (pdir / f"{pname}.md").write_text("en")
    (pdir / sid).touch()

    rec = mcp_jobs.JobRecord(
        job_id="job-q-1", input_type="url",
        source="https://example.com/x",
        expected_filename=sid, import_method="direct_pdf",
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name=pname, location="outputs",
        error=None, submitted_at="2026-05-28T10:00:00",
        completed_at="2026-05-28T10:01:00", expires_at="2026-06-04T10:00:00",
    )
    await _seed_complete_job(rec)

    result = await get_job_result(job_id="job-q-1")
    assert result["viewer_url"] == f"http://localhost:8090/viewer/by-id/{quote(sid, safe='')}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && python -m pytest tests/test_mcp_router.py -k "viewer_url or link_contract or by_id or source_id" -v`
Expected: FAIL — T20/T22/T9 expect `/viewer/by-id/...` but current code still emits `/viewer/{paper_name}`.

- [ ] **Step 3: Implement the viewer_url change + docstring**

`viewer/app/routers/mcp_router.py:151` 교체:

```python
    viewer_url = f"{base}/viewer/by-id/{quote(rec.expected_filename, safe='')}"
```

(`quote` 는 이미 `mcp_router.py:10` 에서 import 됨.)

docstring 의 `viewer_url` 설명 (`:96-103` 블록) 교체:

```python
      viewer_url            — {base}/viewer/by-id/{paperflow_source_id} stable
                              link. Survives folder rename / archive because it
                              resolves by durable source_id, not paper_name.
                              OPAQUE — consumers must NOT parse paper_name out of
                              it, and reaching the viewer requires following the
                              302 redirect. AUTH-REQUIRED: anonymous clicks
                              redirect to /login. Host-local only when base is
                              localhost.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && python -m pytest tests/test_mcp_router.py -v`
Expected: PASS (T20/T21/T22/T9 + all existing T23–T25 etc).

- [ ] **Step 5: Commit**

```bash
git add viewer/app/routers/mcp_router.py viewer/tests/test_mcp_router.py
git commit -m "$(cat <<'EOF'
feat(mcp): viewer_url uses stable /viewer/by-id/{source_id}

get_job_result.viewer_url now points at the durable paperflow_source_id
route so report links survive folder rename / archive. Breaking change:
viewer_url is opaque (no paper_name to parse) and requires redirect-follow.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 문서 보강 (`CLAUDE.md`, `README.md`)

**Files:**
- Modify: `CLAUDE.md` (Implementation Gotchas #12, #14)
- Modify: `README.md` (MCP contract 표의 viewer_url 행)

테스트 없음 (문서 전용).

- [ ] **Step 1: CLAUDE.md gotcha #12 갱신**

`CLAUDE.md` 의 gotcha #12 (`MCP viewer_url is auth-required`) 본문에 다음 문장 추가:

```
viewer_url is now `/viewer/by-id/{paperflow_source_id}` — a 302 redirect to the
current `/viewer/{paper_name}`, so it survives folder rename / archive. The
auth-required nature is unchanged (anonymous → /login), and it is still
host-local when MCP_PUBLIC_BASE_URL is localhost.
```

- [ ] **Step 2: CLAUDE.md gotcha #14 갱신**

`CLAUDE.md` 의 gotcha #14 (`paper_name is a convenience key`) 끝에 추가:

```
`get_job_result.viewer_url` is now built from `paperflow_source_id` via
`/viewer/by-id/{source_id}` → 302 → current folder, so the human/agent link no
longer breaks on rename. `viewer_url` is opaque — do not parse `paper_name` out
of it; use the `paper_name` / `paperflow_source_id` fields directly.
```

- [ ] **Step 3: README.md MCP 표 갱신**

`README.md:295` 의 `viewer_url` 행 (현재):

```
| `viewer_url` | `/viewer/{quote(paper_name)}` 사내 편의 링크 | ⚠️ PaperFlow 로그인 필요, 비로그인은 `/login` 리다이렉트. `localhost` base면 host-local only |
```

를 다음으로 교체 (3-열 구조 유지):

```
| `viewer_url` | `/viewer/by-id/{source_id}` 안정 링크 → 302 → 현재 `/viewer/{paper_name}` (rename/archive 에도 유지) | ⚠️ opaque(paper_name 파싱 금지)·redirect-follow 필요·PaperFlow 로그인 필요(비로그인 `/login`)·`localhost` base면 host-local only |
```

- [ ] **Step 4: 전체 테스트 재실행 (회귀 확인)**

Run: `cd viewer && python -m pytest -q`
Expected: 기존 139 (T20/T22 갱신 반영) + 신규(Task1 7 + Task2 9 + Task3 1 = 17) 모두 PASS, 회귀 0건. 실제 합계는 실행으로 확정.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "$(cat <<'EOF'
docs: document /viewer/by-id stable link in gotchas + MCP contract

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 검증 체크리스트 (구현 후)

- [ ] `cd viewer && python -m pytest -q` 전체 PASS, 회귀 0건
- [ ] 라우트 등록 순서: `viewer_by_id` 가 `viewer_page` 위 (T8 가 보장)
- [ ] viewer_url 이 by-id 형태 (T9/T20/T22 가 보장)
- [ ] 컨테이너 rebuild 후 라이브 확인 (사용자 요청 시): `docker compose build paperflow-viewer && docker compose up -d paperflow-viewer`, MCP `get_job_result` 호출해 `viewer_url` 이 `/viewer/by-id/pfmcp-...pdf` 인지, 브라우저에서 그 URL 이 로그인 후 올바른 폴더로 redirect 되는지
```
