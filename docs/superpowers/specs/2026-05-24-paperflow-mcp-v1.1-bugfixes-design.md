# PaperFlow MCP — v1.1 Bug Fixes Design Spec

**Version**: v1.1 (spec rev 2)
**Date**: 2026-05-24
**Status**: Draft (pre-implementation, awaiting user sign-off + codex Round 2)
**Owner**: restful3
**Predecessor**: `2026-05-24-paperflow-mcp-server-design.md` (v1, rev5)
**Prior reviews**:
- `docs/reviews/2026-05-24-paperflow-mcp-v1.1-bugfixes-codex.md` (Round 1 — 3 Critical, 4 High, 5 Medium)
**Trigger**: DeepSeek-V3 (arXiv 2412.19437) E2E surfaced 3 Critical bugs not caught by v1 codex Round 1–5 review. See `HANDOFF.md` § "🐛 v1 버그 — DeepSeek-V3 E2E 발견" for the incident log.

---

## Change Log (rev2 vs rev1 — addresses Round 1 codex review)

| 변경 | 이유 (Round 1 항목) |
|------|---------------------|
| `reconcile_job` early-return 정책 변경: `error` / `cancelled` 만 terminal idempotent. `complete` 는 partial-check 재검증을 거치도록 분기 추가. | Critical #1 — line 315-316 의 `if rec.status in ("complete", "error", "cancelled"): return rec` 가 v1 에서 저장된 stale `complete` partial job 의 재검증을 차단. 즉 v1.1 fix 가 legacy 잡에 적용 안 됨. |
| `zip endpoint` 도 `mcp_jobs.reconcile_job(job_id)` 호출하도록 변경 (현재는 `get_job` 만 호출). | Critical #2 — `mcp_router.py:209-214` 가 reconcile 우회 → stale complete 잡이 direct zip 다운로드 가능. |
| `_config_translation_enabled()` 를 폐기. **MCP_REQUIRE_TRANSLATION** env var (default `true`) 로 대체. viewer 의 config.json mount 의존성 제거. | Critical #3 — `settings.base_dir` 부재 (`BASE_DIR` 만 존재) + viewer 컨테이너에 config.json mount 부재. fail-closed 도 misclassification 위험 (Medium #2 동시 해소). |
| `_resolve_completed_candidate(expected_filename)` 통합 helper 도입 — outputs 우선, fallback scan 포함, partial gate 단일 적용. | High #1 — primary 와 fallback path 양쪽에 partial 검사 필요. High #3 — outputs / archives 동시 매치 시 outputs 우선 정책. |
| `_cleanup_smart_renamed_paper` 도 `_resolve_completed_candidate` 의 outputs-only scan 을 재사용. | High #2 — paper_meta 손상 시 cleanup 이 no-op. |
| spec §8 migration 문구에서 "list_jobs 에서 transition" 표현 제거. list_jobs 는 reconcile 하지 않으며, stale 가능 명시. | High #4 — `list_jobs` 는 index read-through. 사용자가 status query / zip / get_job_result 로 trigger 시점에 reconcile 됨. |
| `_paper_has_ko_md` 가 folder-disappeared 와 folder-present-but-no-ko 를 구분 (Optional[bool] 반환). reconcile 은 disappeared 케이스를 별도 분기 ("paper_missing" error) 로 처리. | Medium #1 — race 로 폴더 소멸 시 "translation_missing" 으로 오분류 방지. |
| `cancel_job` 응답에 `cleanup` 필드 추가 (`{"attempted", "deleted_path", "warning"}`). | Medium #3 — cleanup 성공/실패 가시화. recovery protocol 투명성. |
| Test plan T14–T18 추가 (legacy complete migration, zip stale direct call, fallback scan partial, outputs+archives 동시 매치, race folder disappearance). | Medium #4 — 회귀 경계 보강. |
| Implementation order §7 에 smoke verify 단계 추가 (`docker compose exec` 로 PROCESS_TIMEOUT_SECONDS 확인). | Medium #5. |

---

## 1. Goals

Fix the 3 Critical bugs surfaced by DeepSeek-V3 E2E without modifying converter-side code (`main_terminal.py`, `run_batch_watch.sh`, `config.json`). Make large-paper processing recoverable: the user can detect a partial run, clean up, and resubmit with a deterministic sequence of MCP calls. v1.1 must also migrate legacy `status=complete` partial jobs from v1 — they cannot remain falsely complete.

## 2. Non-goals

- Automatic recovery (auto-retry, auto-cleanup): explicitly rejected during brainstorming. Recovery is a user-driven 2-step (`cancel_job` + `submit_paper(force_reprocess=true)`).
- Fixing `main_terminal.py`'s `check_duplicate_batch` self-duplicate logic: out of scope (no-change constraint). MCP layer instead breaks the chain by detecting partial outputs at reconcile time and surfacing them as `status=error`, prompting the user to clean up before retrying.
- New MCP tools. No additions to the v1 5-tool surface.
- Watch-loop self-recovery on its own retry path. Watch's `MAX_RETRIES=2` will continue to hit `Skipping translation` on a partial outputs folder; v1.1 does not fix this. The user can break the loop by canceling and resubmitting (force_reprocess).
- `list_jobs` does not reconcile. The function returns the index as-stored. Users wanting fresh state per-job should call `get_job_status`, `get_job_result`, or the zip endpoint, all of which trigger reconcile.

## 3. No-change constraint (carried over from v1)

`main_terminal.py`, `run_batch_watch.sh`, `config.json`: **0 lines modified.** All behavior changes happen in:

- `docker-compose.yml` (env var additions: `PROCESS_TIMEOUT_SECONDS=7200` for converter, `MCP_REQUIRE_TRANSLATION=true` for viewer; no new volume mounts)
- `viewer/app/services/mcp_jobs.py` (reconcile_job policy change, _resolve_completed_candidate helper, cancel_job augmentation, _cleanup_smart_renamed_paper)
- `viewer/app/services/papers.py`: **0 lines modified** (rev2 abandons spec rev1's "helper addition there" — v1.1 keeps papers.py purely read-only)
- `viewer/app/config.py` (one new field: `MCP_REQUIRE_TRANSLATION: bool = True`)
- `viewer/app/routers/mcp_router.py` (zip endpoint reconcile call, cancel_job response shape)
- `viewer/tests/test_mcp_*.py` (new test cases)

If any fix would require touching the three protected files, it is deferred to v2.

## 4. Bug summary

| # | Bug | Root cause file | v1.1 fix location |
|---|-----|-----------------|-------------------|
| 1 | `run_batch_watch.sh` SIGKILLs translation after 2400s; partial outputs left behind | `run_batch_watch.sh:14` (default 2400s) | `docker-compose.yml` env var |
| 2 | `main_terminal.py` retry sees self-folder, marks self-duplicate, skips translation forever | `main_terminal.py` `check_duplicate_batch` call site | MCP `reconcile_job` detects partial → `status=error` + user-cleanup guidance |
| 3 | MCP `reconcile_job` returns `status=complete` even when `_ko.md` missing; downstream tools (`get_job_status`, `get_job_result`) call reconcile but receive the same stale state via early-return | `viewer/app/services/mcp_jobs.py:reconcile_job` line 315-316 (early return) + line 326-339 (no partial gate) | reconcile early-return policy change + unified completeness helper |
| 4 | `cancel_job(delete_file=true)` does not clean smart-renamed folders; subsequent submit hits self-duplicate again | `cancel_job` delegates to `papers.request_cancel_processing`, which only cleans `outputs/{stem}/` (not smart-renamed) | MCP `cancel_job` post-hook with `_cleanup_smart_renamed_paper` |
| 5 (Round 1 C#2) | zip endpoint `mcp_router.py:209-214` calls only `get_job` (skips reconcile) → stale `complete` zip ships HTTP 200 | same line | zip endpoint switches to `reconcile_job` |
| 6 (Round 1 C#3) | viewer cannot read converter `config.json` (`BASE_DIR` is `/data`, mount is converter-side only) | docker-compose + config.py | viewer-side `MCP_REQUIRE_TRANSLATION` env var, no config.json mount |

## 5. Design

### 5.1 Fix #1 — Watch timeout default raised to 7200s (via env)

**Files**: `docker-compose.yml` only.

```yaml
paperflow-converter:
  environment:
    # ... existing entries ...
    - PROCESS_TIMEOUT_SECONDS=7200   # v1.1: 2400 → 7200 (2h)
```

`run_batch_watch.sh:14` is already `PROCESS_TIMEOUT_SECONDS="${PROCESS_TIMEOUT_SECONDS:-2400}"`, so this is a yaml-only change.

### 5.2 Fix #2/#3/#5 — Unified `reconcile_job` partial gate

**Files**: `viewer/app/services/mcp_jobs.py`, `viewer/app/routers/mcp_router.py`, `viewer/app/config.py`.

#### 5.2.1 New config field

`viewer/app/config.py`, add to `Settings`:

```python
# When True, reconcile_job downgrades complete jobs to error if `_ko.md` is missing.
# Set to "false" only in deployments that disable Korean translation in config.json
# (otherwise the v1 self-duplicate bug surfaces silently as partial zips).
MCP_REQUIRE_TRANSLATION: bool = True
```

`docker-compose.yml` viewer service:

```yaml
environment:
  # ... existing ...
  - MCP_REQUIRE_TRANSLATION=${MCP_REQUIRE_TRANSLATION:-true}
```

**Rationale for env over config.json mount**: viewer already takes `MCP_*` settings via env. Adding a config.json mount to the viewer container creates a hidden coupling on a file owned by the converter — if its schema changes, viewer parsing breaks silently. An explicit boolean env makes the dependency one-way and obvious. Operators that disable translation set `MCP_REQUIRE_TRANSLATION=false`.

#### 5.2.2 Helpers

```python
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


def _resolve_completed_candidate(expected_filename: str) -> tuple[str, str] | None:
    """Locate the paper folder that should correspond to expected_filename.
    Returns (paper_name, location) or None.

    Outputs is preferred over archives — if BOTH match, outputs wins so that
    partial-detection / cleanup operates on the active folder.
    """
    from . import papers as _papers
    from ..config import settings

    # Primary: metadata-backed
    info = _papers.find_processed_paper(original_filename=expected_filename)
    if info and info["location"] == "outputs":
        return info["name"], "outputs"

    # Outputs-side fallback scan (paper_meta missing / corrupt)
    scan = _scan_outputs_for_filename(expected_filename)
    if scan:
        return scan[0], "outputs"

    # No outputs match — fall back to whatever primary found (may be archives)
    if info:
        return info["name"], info["location"]

    return None


def _paper_dir_for(name: str, location: str) -> Path:
    from ..config import settings
    base = settings.outputs_dir if location == "outputs" else settings.archives_dir
    return base / name
```

`_scan_outputs_for_filename` already exists in `mcp_jobs.py` (v1 line 295-304); rev2 reuses it.

#### 5.2.3 `reconcile_job` modified flow

```python
async def reconcile_job(job_id: str) -> JobRecord | None:
    """Refresh status by inspecting filesystem + processing_status.json."""
    from . import papers as _papers
    from ..config import settings

    rec = await get_job(job_id)
    if not rec:
        return None

    # Terminal idempotent for error/cancelled only.
    if rec.status in ("error", "cancelled"):
        return rec

    # NEW: complete jobs are re-validated against the filesystem.
    # If partial (missing _ko.md when translation required), downgrade to error.
    if rec.status == "complete":
        verdict = _classify_completion(rec.expected_filename)
        # verdict ∈ {"complete", "partial", "missing", "skip"}
        if verdict == "complete":
            return rec
        if verdict == "partial":
            await _set_job_fields(job_id, status="error",
                error=("translation_missing — prior run was killed mid-translation. "
                       "Call cancel_job(delete_file=true) to clear partial outputs, "
                       "then resubmit with force_reprocess=true."),
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

    # === Primary completion lookup (queued / processing / stalled) ===
    cand = _resolve_completed_candidate(rec.expected_filename)
    if cand:
        name, location = cand
        verdict = _classify_completion(rec.expected_filename, _precomputed=(name, location))
        if verdict == "partial":
            await _set_job_fields(job_id, status="error",
                error=("translation_missing — prior run was killed mid-translation. "
                       "Call cancel_job(delete_file=true) to clear partial outputs, "
                       "then resubmit with force_reprocess=true."),
                completed_at=_now_iso())
            return await get_job(job_id)
        # complete or skip (translation not required) — both legitimate complete
        await _set_job_fields(job_id, status="complete",
                               paper_name=name, location=location,
                               completed_at=_now_iso())
        return await get_job(job_id)

    # === Active-processing inspection unchanged from v1 ===
    # (processing_status.json branch, stalled detection, etc.)
    # ... (omitted — no rev2 changes from v1)
```

```python
def _classify_completion(
    expected_filename: str,
    _precomputed: tuple[str, str] | None = None,
) -> Literal["complete", "partial", "missing", "skip"]:
    """Decide the post-reconcile state for a job whose work appears finished.

    Returns:
      - "complete":  paper folder present AND (_ko.md present OR translation not required)
      - "partial":   paper folder present, translation required, _ko.md missing
      - "missing":   no paper folder found at all (race / archived / externally deleted)
      - "skip":      paper folder present, translation NOT required, no _ko.md (legitimate English-only)
    """
    from ..config import settings

    if _precomputed:
        name, location = _precomputed
    else:
        cand = _resolve_completed_candidate(expected_filename)
        if not cand:
            return "missing"
        name, location = cand

    # Archives are user-curated; never flag as partial.
    if location == "archives":
        return "complete"

    paper_dir = _paper_dir_for(name, location)
    has_ko = _paper_has_ko_md(paper_dir)
    if has_ko is None:
        return "missing"
    if has_ko:
        return "complete"
    # has_ko == False — folder exists but no _ko.md
    if settings.MCP_REQUIRE_TRANSLATION:
        return "partial"
    return "skip"
```

**Why split `_classify_completion` from `reconcile_job`**: the `complete` branch (verifying an already-stored status) and the primary lookup branch (discovering completion from queued/processing) need the same decision tree. Factoring it makes the policy single-sourced and testable in isolation.

**Why expose `_precomputed`**: the primary lookup just computed `(name, location)`; passing it avoids a second `find_processed_paper` round-trip.

#### 5.2.4 Zip endpoint reconcile

`viewer/app/routers/mcp_router.py` zip handler (line ~204-211):

```python
@mcp_zip_router.get("/jobs/{job_id}/zip")
async def download_zip(job_id: str, include_pdf: bool = False, include_translation: bool = True, ...):
    rec = await mcp_jobs.reconcile_job(job_id)   # ← v1 was: get_job(job_id)
    if not rec or rec.status != "complete":
        raise HTTPException(status_code=404, detail="Job not complete or not found")
    # ... rest unchanged ...
```

Single-line semantic change. `get_job_status` (line 50) and `get_job_result` (line 68) already call `reconcile_job` — the rev2 policy change in 5.2.3 fixes them automatically.

### 5.3 Fix #4 — `cancel_job` cleans smart-renamed folder + structured response

**File**: `viewer/app/services/mcp_jobs.py` + `viewer/app/routers/mcp_router.py`.

#### 5.3.1 Outputs-only cleanup helper

```python
def _cleanup_smart_renamed_paper(expected_filename: str) -> dict:
    """Find the smart-renamed paper folder in outputs/ (if any) and rmtree it.
    Archives are never touched.

    Returns:
      {"attempted": bool, "deleted_path": str | None, "warning": str | None}
    """
    from ..config import settings
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
```

`_resolve_completed_candidate` already incorporates fallback scan (H#2 fix). No separate scan call needed here.

#### 5.3.2 `cancel_job` augmentation

```python
async def cancel_job(job_id: str, delete_file: bool = True) -> dict | None:
    """Cancel job. Behavior depends on current status.
    Returns:
      - dict {"job_id", "status", "cleanup": {attempted, deleted_path, warning}}
      - None if job_id not found (caller — mcp_router — raises ValueError("job not found"))
    """
    from . import papers as _papers
    from ..config import settings

    rec = await get_job(job_id)
    if not rec:
        return None

    cleanup = {"attempted": False, "deleted_path": None, "warning": None}

    # NEW: error-status cleanup pass (recovery from partial)
    if rec.status == "error" and delete_file:
        cleanup = _cleanup_smart_renamed_paper(rec.expected_filename)
        # Also clean source PDF if still in newones/ (best-effort)
        src = settings.newones_dir / rec.expected_filename
        if src.exists():
            try:
                src.unlink()
            except Exception:
                pass
        return {"job_id": job_id, "status": "error", "cleanup": cleanup}

    if rec.status in ("complete", "cancelled"):
        return {"job_id": job_id, "status": rec.status, "cleanup": cleanup}

    # Downloading branch — unchanged from v1.
    if rec.status == "downloading":
        # ... existing logic ...
        return {"job_id": job_id, "status": "cancelled", "cleanup": cleanup}

    # queued/processing/stalled: delegate + post-hook cleanup
    ok, msg = _papers.request_cancel_processing(rec.expected_filename,
                                                  delete_file=delete_file, force=True)
    if delete_file:
        cleanup = _cleanup_smart_renamed_paper(rec.expected_filename)
    await _set_job_fields(job_id, status="cancelled",
                           error=None if ok else msg,
                           completed_at=_now_iso())
    return {"job_id": job_id, "status": "cancelled", "cleanup": cleanup}
```

#### 5.3.3 MCP router response shape

`mcp_router.py` `cancel_job` tool wrapper (line 127-133) — change return from `{"job_id", "status"}` to the dict produced by `mcp_jobs.cancel_job`. Update the FastMCP tool signature accordingly.

**Backward compatibility note**: callers that were dict-accessing `["job_id"]` / `["status"]` still work. New consumers can read `["cleanup"]`.

### 5.4 Translation-disabled environments

If a deployment runs with `MCP_REQUIRE_TRANSLATION=false`:

- Fix #1: still applied (timeout is independent of translation).
- Fix #2/3/5: `_classify_completion` returns `"skip"` for English-only outputs → status remains `complete`. No regression.
- Fix #4: still applied (cleanup is translation-agnostic).

If the operator forgets to set `MCP_REQUIRE_TRANSLATION=false` while running with translation disabled, English-only complete jobs will downgrade to `status=error` on next reconcile. This is an explicit operator configuration error, not a silent corruption — the error message tells the user to "resubmit with force_reprocess=true," which would re-run the disabled-translation pipeline and succeed again.

## 6. Testing

TDD. New test cases in `viewer/tests/test_mcp_jobs.py` (extending existing module) and `viewer/tests/test_mcp_router.py`. All use the existing conftest fixtures (`_cfg.settings` override, plus monkeypatch for `MCP_REQUIRE_TRANSLATION`).

| # | Test name | Setup | Asserts |
|---|-----------|-------|---------|
| T1 | `test_reconcile_partial_outputs_missing_ko` | Job stored as queued. outputs/{paper_dir}/ with `Title.md` only. `MCP_REQUIRE_TRANSLATION=true`. | After reconcile: status="error", error contains "translation_missing", error contains "cancel_job(delete_file=true)" |
| T2 | `test_reconcile_skip_translation_disabled` | Same outputs as T1 but `MCP_REQUIRE_TRANSLATION=false` | status="complete" |
| T3 | `test_reconcile_complete_has_ko_md_unchanged` | outputs/{paper_dir}/ has both Title.md and Title_ko.md, job stored as queued | status="complete" (regression) |
| T4 | `test_reconcile_archives_skipped_from_partial_check` | archives/{paper_dir}/ has only Title.md; no outputs match | status="complete" (archives are user-curated) |
| T5 | `test_paper_has_ko_md_helper_three_states` | (a) folder w/ _ko.md, (b) folder w/o _ko.md, (c) folder absent, (d) folder w/ only _ko_explained.md | True / False / None / False |
| T6 | `test_resolve_completed_candidate_outputs_wins` | Both outputs/{paper_dir}/ and archives/{paper_dir}/ contain matching meta. | Returns (name, "outputs") |
| T7 | `test_resolve_completed_candidate_fallback_scan` | paper_meta.json absent/corrupt in outputs/{paper_dir}/, source PDF present | Returns (name, "outputs") via _scan_outputs_for_filename |
| T8 | `test_cancel_job_error_status_with_delete_cleans_smart_rename` | Job status=error, outputs/{paper_dir}/ exists smart-renamed | After cancel_job(delete_file=true): folder removed, response.cleanup.attempted=True, deleted_path set |
| T9 | `test_cancel_job_error_status_no_delete_no_cleanup` | Same as T8 but delete_file=False | Folder still exists, cleanup.attempted=False |
| T10 | `test_cancel_job_archives_preserved` | Job status=error, archives/{paper_dir}/ exists, no outputs | cleanup.attempted=False, cleanup.warning mentions archives; archives folder intact |
| T11 | `test_cancel_job_complete_status_no_cleanup` | Job status=complete with _ko.md present | cancel_job idempotent, no fs change |
| T12 | `test_cancel_job_queued_post_hook` | Job status=queued, source PDF in newones/, smart-renamed folder in outputs/ | After cancel_job(delete_file=true): source PDF gone AND smart-renamed folder gone, cleanup populated |
| T13 | `test_zip_endpoint_calls_reconcile_and_rejects_partial` | Job stored as `status=complete` with paper_dir present, no _ko.md, MCP_REQUIRE_TRANSLATION=true | Calling /jobs/{id}/zip triggers reconcile → status=error → HTTP 404 |
| T14 | `test_legacy_complete_partial_migration_via_get_job_status` | Job persisted at `status=complete` (v1 schema), filesystem has partial outputs | First `get_job_status` call after rev2: status flips to error with translation_missing msg |
| T15 | `test_fallback_scan_path_partial_detected` | paper_meta absent in outputs folder; reconcile falls through to _scan_outputs_for_filename | _classify_completion returns "partial" → status=error |
| T16 | `test_outputs_partial_with_archives_complete_both_present` | outputs/{paper_dir}/ partial AND archives/{same-name}/ has _ko.md | `_resolve_completed_candidate` returns outputs hit; reconcile flags partial (outputs wins) |
| T17 | `test_reconcile_paper_folder_missing_after_complete` | Job persisted complete, outputs/{paper_dir}/ deleted between reconcile calls (race) | status="error", error contains "no longer present" — NOT translation_missing |
| T18 | `test_cancel_job_response_shape` | Various cancel scenarios | Response always has shape `{job_id, status, cleanup: {attempted, deleted_path, warning}}` |
| T19 | `test_get_job_result_rejects_error_after_reconcile_downgrade` | Job persisted complete, partial fs state. Call get_job_result. | reconcile downgrades to error; get_job_result raises (FastMCP tool error response) |

Regression sweep: existing 40 tests must still pass.

## 7. Implementation order (for plan)

1. **T5, T6, T7 (helpers)** → implement `_paper_has_ko_md`, `_resolve_completed_candidate`, `_paper_dir_for` → green
2. **T15 (fallback partial detection)** → implement `_classify_completion` → green
3. **T1–T4, T13, T14, T16, T17 (reconcile policy)** → modify `reconcile_job` per §5.2.3 → green + regression
4. **T18 (cancel response shape), T8–T12 (cancel cleanup)** → modify `cancel_job` + add `_cleanup_smart_renamed_paper` per §5.3 → green + regression
5. **T19 (zip + get_job_result downstream)** → modify zip endpoint per §5.2.4 + add test → green
6. **docker-compose.yml** → add `PROCESS_TIMEOUT_SECONDS=7200` (converter) and `MCP_REQUIRE_TRANSLATION=${MCP_REQUIRE_TRANSLATION:-true}` (viewer)
7. **config.py** → add `MCP_REQUIRE_TRANSLATION: bool = True`
8. **Smoke verify** (manual):
   - `docker compose exec paperflow-converter sh -lc 'echo $PROCESS_TIMEOUT_SECONDS'` → must print 7200
   - `docker compose exec paperflow-viewer sh -lc 'echo $MCP_REQUIRE_TRANSLATION'` → must print true (or operator-set value)
   - Re-run DeepSeek-V3 E2E flow: confirm partial detection → cancel_job(delete_file=true) cleans smart-renamed folder → resubmit with force_reprocess=true completes successfully

## 8. Migration & rollout

- **No JobRecord schema change.** Existing `logs/mcp_jobs.json` index is forward/backward compatible.
- **Legacy `status=complete` partial jobs**: on next `get_job_status`, `get_job_result`, or `/zip` call (these route through `reconcile_job`), the job will transition from `complete` → `error` with the user-cleanup message. `list_jobs` returns the index as-stored and does NOT trigger this migration — so list_jobs results for unreconciled jobs may still show `complete` until the user accesses one of the reconcile-triggering endpoints. This is intentional (list_jobs stays a cheap read-through), and documented for users.
- **No new mounts**. v1.1 adds env vars only.

## 9. Codex review plan

Round 1 returned 3 Critical + 4 High + 5 Medium (all valid, all addressed in rev2). Round 2 expected — submit rev2, request approval. If high-severity findings remain, Round 3. Hard cap at 3 (was 2 in rev1; relaxed because rev1 scope expansion warranted).

## 10. Open questions

None — all rev1 ambiguities resolved.

## 11. Risks

- **Risk**: User sets `MCP_REQUIRE_TRANSLATION=true` but actually runs `config.json` with `translate_to_korean: false`. English-only complete jobs all downgrade to `status=error`. **Mitigation**: error message tells the user to `cancel_job(delete_file=true)` + resubmit, which would loop back into the same disabled-translation pipeline and produce another English-only result. This loop is *visible* (status=error on every reconcile) — operator notices and corrects MCP_REQUIRE_TRANSLATION. Not silent corruption.
- **Risk**: Reconcile cost. v1.1 makes `complete` re-validate the filesystem on every status query. Filesystem stat / iterdir on a paper folder is sub-ms, but high-frequency polling clients pay it per call. **Mitigation**: paper folders contain few files (< 50 typical); `_paper_has_ko_md` early-exits on first match. If profiling shows this matters, add an in-memory `(job_id, mtime) → verdict` cache with TTL ≤ 60s.
- **Risk**: Concurrent reconcile races: two simultaneous status queries on the same job both pass the partial check and both write `status=error`. **Mitigation**: writes go through `_set_job_fields` which acquires `_index_lock`; the last write wins but both write the same error — idempotent. No correctness issue.
- **Risk**: Smart-rename folder discovery via `_resolve_completed_candidate` depends on `_scan_outputs_for_filename` finding the source PDF inside the folder. If main_terminal.py moved the PDF *out* of the folder (a behavior change in some pipelines), the fallback misses. **Mitigation**: current main_terminal.py keeps the source PDF in `outputs/{paper_dir}/` after duplicate-skip cleanup (verified in DeepSeek-V3 logs). If this ever changes, the test suite (T15) catches the regression. Mention in `HANDOFF.md` for awareness.
