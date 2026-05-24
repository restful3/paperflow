# PaperFlow MCP — v1.1 Bug Fixes Design Spec

**Version**: v1.1 (spec rev 1)
**Date**: 2026-05-24
**Status**: Draft (pre-implementation, awaiting user sign-off)
**Owner**: restful3
**Predecessor**: `2026-05-24-paperflow-mcp-server-design.md` (v1, rev5)
**Trigger**: DeepSeek-V3 (arXiv 2412.19437) E2E surfaced 3 Critical bugs not caught by v1 codex Round 1–5 review. See `HANDOFF.md` § "🐛 v1 버그 — DeepSeek-V3 E2E 발견" for the incident log.

---

## 1. Goals

Fix the 3 Critical bugs surfaced by DeepSeek-V3 E2E without modifying converter-side code (`main_terminal.py`, `run_batch_watch.sh`, `config.json`). Make large-paper processing recoverable: the user can detect a partial run, clean up, and resubmit with a deterministic sequence of MCP calls.

## 2. Non-goals

- Automatic recovery (auto-retry, auto-cleanup): explicitly rejected during brainstorming. Recovery is a user-driven 2-step (`cancel_job` + `submit_paper(force_reprocess=true)`).
- Fixing `main_terminal.py`'s `check_duplicate_batch` self-duplicate logic: out of scope (no-change constraint). MCP layer instead breaks the chain by detecting partial outputs at reconcile time and surfacing them as `status=error`, prompting the user to clean up before retrying.
- New MCP tools. No additions to the v1 5-tool surface (`submit_paper`, `get_job_status`, `get_job_result`, `list_jobs`, `cancel_job`).
- Watch-loop self-recovery on its own retry path. Watch's `MAX_RETRIES=2` will continue to hit `Skipping translation` on a partial outputs folder; v1.1 does not fix this. The user can break the loop by canceling and resubmitting (force_reprocess).

## 3. No-change constraint (carried over from v1)

`main_terminal.py`, `run_batch_watch.sh`, `config.json`: **0 lines modified.** All behavior changes happen in:

- `docker-compose.yml` (env var addition only)
- `viewer/app/services/mcp_jobs.py` (reconcile, cancel_job)
- `viewer/app/services/papers.py` (one new read-only helper, no behavior change to existing functions)
- `viewer/app/config.py` (one new settings reader, optional)
- `viewer/tests/test_mcp_*.py` (new test cases)

If any fix would require touching the three protected files, it is deferred to v2.

## 4. Bug summary (from HANDOFF.md)

| # | Bug | Root cause file | v1.1 fix location |
|---|-----|-----------------|-------------------|
| 1 | `run_batch_watch.sh` SIGKILLs translation after 2400s; partial outputs left behind | `run_batch_watch.sh:14` (default 2400s) | `docker-compose.yml` env var |
| 2 | `main_terminal.py` retry sees self-folder, marks self-duplicate, skips translation forever | `main_terminal.py` `check_duplicate_batch` call site (line ~3041) | MCP `reconcile_job` detects partial → `status=error` + user-cleanup guidance |
| 3 | MCP `reconcile_job` returns `status=complete` even when `_ko.md` missing; zip endpoint serves English-only zip with HTTP 200 on `include_translation=true` | `viewer/app/services/mcp_jobs.py:reconcile_job` line ~326; `viewer/app/routers/mcp_router.py` zip endpoint | Same `reconcile_job` strengthening fixes both — zip endpoint already rejects non-complete status (verified inline in §5) |

A 4th issue surfaced during design exploration:

| # | Bug | v1.1 fix |
|---|-----|----------|
| 4 | `cancel_job(delete_file=true)` cleans `outputs/{stem}/` but not the smart-renamed folder (e.g., `outputs/DeepSeek-V3 Technical Report/`), so the partial outputs survive even after explicit user cleanup → next submit hits self-duplicate again | MCP `cancel_job` does a `find_processed_paper(expected_filename)` post-hook and rmtree's the outputs-side hit (archives preserved) |

## 5. Design

### 5.1 Fix #1 — Watch timeout default raised to 7200s (via env)

**Files**: `docker-compose.yml` only.

**Change** (paperflow-converter service `environment:` block):

```yaml
environment:
  # existing entries ...
  PROCESS_TIMEOUT_SECONDS: "7200"   # v1.1: 2400 → 7200 (2h) to cover ~50-section papers like DeepSeek-V3
```

`run_batch_watch.sh:14` is already `PROCESS_TIMEOUT_SECONDS="${PROCESS_TIMEOUT_SECONDS:-2400}"`, so this is a 1-line yaml change with zero script modification.

**Rationale**: DeepSeek-V3 (72 sections, ~25min observed translation time) needed > 40min. 2h gives headroom for slow LLM endpoints and chunk-level outliers. The `MAX_RETRIES=2` watch retry still applies for genuinely stuck runs.

### 5.2 Fix #2/#3 — `reconcile_job` detects partial translation

**File**: `viewer/app/services/mcp_jobs.py`.

#### 5.2.1 Helper additions

`reconcile_job` currently uses `papers.find_processed_paper(original_filename=...)` (line ~326) to confirm a paper folder exists, and on success unconditionally writes `status=complete`. v1.1 inserts a translation-completeness check between these two steps.

New module-level helpers (in `mcp_jobs.py`, lazy-loaded):

```python
def _config_translation_enabled() -> bool:
    """Read config.json (no caching — file is small and changes rare).
    Returns True if processing_pipeline.translate_to_korean is enabled.
    Fail-closed: on read error, return True so that partial-translation
    detection stays active (silent-corruption avoidance over false alarms)."""
    from ..config import settings
    cfg_path = settings.base_dir / "config.json"
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        return bool(cfg.get("processing_pipeline", {}).get("translate_to_korean", True))
    except Exception:
        return True  # fail-closed: assume translation required


def _paper_has_ko_md(paper_dir: Path) -> bool:
    """True if any *_ko.md file exists directly in paper_dir (non-recursive,
    excluding _ko_explained.md derivatives)."""
    try:
        for p in paper_dir.iterdir():
            name = p.name
            if (name.endswith("_ko.md")
                    and not name.endswith("_ko_explained.md")
                    and p.is_file()):
                return True
    except Exception:
        return False
    return False
```

#### 5.2.2 `reconcile_job` modified flow

Pseudo-diff at the `find_processed_paper` success branch (current line ~326-330):

```python
info = _papers.find_processed_paper(original_filename=rec.expected_filename)
if info:
    location = info["location"]   # "outputs" or "archives" (returned by find_processed_paper)
    name = info["name"]
    base = settings.outputs_dir if location == "outputs" else settings.archives_dir
    paper_dir = base / name
    # NEW: partial-translation detection
    if (location == "outputs"
            and _config_translation_enabled()
            and not _paper_has_ko_md(paper_dir)):
        msg = ("translation_missing — prior run was killed mid-translation. "
               "Call cancel_job(delete_file=true) to clear partial outputs, "
               "then resubmit with force_reprocess=true.")
        await _set_job_fields(job_id, status="error", error=msg,
                              completed_at=_now_iso())
        return await get_job(job_id)
    # existing path: status=complete with paper_name/location
    await _set_job_fields(job_id, status="complete",
                          paper_name=name, location=location,
                          completed_at=_now_iso())
    return await get_job(job_id)
```

Note: `find_processed_paper` returns `{name, location, viewer_path}`; spec re-derives `paper_dir` from `name + location` (the function's internal candidate list uses the same convention).

**Why `location == "outputs"` guard**: archives folders are user-intentionally curated. If the user archived an English-only paper (translation explicitly disabled or skipped manually), v1.1 must not misclassify it as "partial." Only the outputs path triggers the new check.

**Why fail-closed in `_config_translation_enabled` on read error**: a corrupted/missing config.json should not let stale partial outputs masquerade as complete. False positives (claiming partial when translation actually disabled) are recoverable; false negatives (claiming complete when ko.md missing) leak silent corruption to the user.

#### 5.2.3 Zip endpoint — no code change

`mcp_router.py` zip handler currently rejects any job with `status != "complete"` (HTTP 404). Once Fix #2 turns partial jobs into `status=error`, the zip endpoint inherits the rejection automatically. **Verified inline (line 210-211):**

```python
# mcp_router.py zip endpoint (unchanged):
rec = await mcp_jobs.get_job(job_id)
if not rec or rec.status != "complete":
    raise HTTPException(status_code=404, detail="Job not complete or not found")
```

`get_job_result` follows the same pattern: raises `ValueError(f"job not complete (status={rec.status})")` for non-complete (line 71-72), which FastMCP converts to an error tool response. No further changes needed for Fix #3.

**Test addition required**: existing `test_mcp_router.py` covers missing-bearer/wrong-bearer/missing-job, but not "status=error rejection." v1.1 adds T12 below.

### 5.3 Fix #4 — `cancel_job` cleans smart-renamed folder

**File**: `viewer/app/services/mcp_jobs.py`.

**Current flow** (line 387–415):

1. If status terminal (complete/error/cancelled): idempotent return.
2. If status=downloading: cancel task + delete `.part`.
3. Else (queued/processing/stalled): delegate to `papers.request_cancel_processing(delete_file=True, force=True)` and set status=cancelled.

`request_cancel_processing` cleans `outputs/{stem}/` and any outputs folder containing the source PDF, but **does not find smart-renamed folders** (where `stem = "pfmcp-abc123-arxiv.org"` but the folder is now `outputs/DeepSeek-V3 Technical Report/`).

**v1.1 addition**: terminate the idempotent short-circuit guard for `status=error` (only) and add a post-hook that rmtrees the smart-renamed outputs folder.

```python
async def cancel_job(job_id: str, delete_file: bool = True) -> JobRecord | None:
    from . import papers as _papers
    from ..config import settings

    rec = await get_job(job_id)
    if not rec:
        return None

    # NEW: allow cleanup pass for already-error jobs (partial outputs recovery)
    if rec.status == "error" and delete_file:
        _cleanup_smart_renamed_paper(rec.expected_filename)
        # Also clean source PDF if still in newones/ (best-effort)
        src = settings.newones_dir / rec.expected_filename
        if src.exists():
            try:
                src.unlink()
            except Exception:
                pass
        return rec  # status stays "error" — the cancel is for cleanup, not state transition

    if rec.status in ("complete", "cancelled"):
        return rec  # idempotent (no cleanup for complete — user shouldn't bulk-delete by accident)

    # ... existing downloading / queued / processing paths unchanged ...

    # ALSO at the end of the queued/processing path, after request_cancel_processing returns:
    if delete_file:
        _cleanup_smart_renamed_paper(rec.expected_filename)


def _cleanup_smart_renamed_paper(expected_filename: str) -> None:
    """Find the smart-renamed paper folder (if any) and rmtree it.
    Only touches outputs/, never archives/."""
    from . import papers as _papers
    from ..config import settings
    import shutil

    info = _papers.find_processed_paper(original_filename=expected_filename)
    if not info:
        return
    if info["location"] != "outputs":
        return  # never delete archives
    paper_dir = settings.outputs_dir / info["name"]
    try:
        shutil.rmtree(paper_dir, ignore_errors=True)
    except Exception:
        pass  # best-effort
```

**Why allow `status=error` cancel to do work**: the v1 `cancel_job` is documented as idempotent on terminal states (rfc). v1.1 carves a narrow exception: when status is `error` AND `delete_file=True`, the call is a *cleanup intent*, not a state transition. The status stays `error` (no `cancelled` rewrite — preserves audit trail).

**Archives untouched**: `_cleanup_smart_renamed_paper` short-circuits if `location == "archives"`. Same rationale as 5.2.2.

### 5.4 Translation-disabled environments

If a deployment runs with `translate_to_korean: false` in `config.json`:

- Fix #1: still applied (timeout is independent of translation).
- Fix #2: `_config_translation_enabled()` returns False → `reconcile_job` skips the `_ko.md` check → existing behavior preserved (status=complete on English-only output).
- Fix #4: still applied (cleanup is translation-agnostic).

No regression for translation-disabled users.

## 6. Testing

TDD. New test cases in `viewer/tests/test_mcp_jobs.py` (extending existing module). All use the existing conftest fixtures (`_cfg.settings` override).

| # | Test name | Setup | Asserts |
|---|-----------|-------|---------|
| T1 | `test_reconcile_partial_translation_outputs_missing_ko` | outputs/{paper_dir}/ exists with `Title.md` only, config.json has `translate_to_korean=true` | status="error", error contains "translation_missing", error contains "cancel_job(delete_file=true)" guidance |
| T2 | `test_reconcile_partial_translation_disabled_passes` | Same as T1 but `translate_to_korean=false` in config | status="complete" (existing path preserved) |
| T3 | `test_reconcile_complete_with_ko_md` | outputs/{paper_dir}/ has both `Title.md` and `Title_ko.md` | status="complete" (regression guard) |
| T4 | `test_reconcile_partial_in_archives_passes` | archives/{paper_dir}/ has only `Title.md`, no `Title_ko.md` | status="complete" (archives skip the partial check) |
| T5 | `test_paper_has_ko_md_helper` | Directory fixtures: with/without `_ko.md`, with `_ko_explained.md` only | True / False / False respectively |
| T6 | `test_config_translation_enabled_helper` | config.json variants (true, false, missing key, missing file, corrupted JSON) | true / false / true (default) / true (fail-closed) / true (fail-closed) |
| T7 | `test_cancel_job_error_status_with_delete_cleans_smart_rename` | Job in status=error, outputs/{paper_dir}/ exists (smart-renamed) | After `cancel_job(job_id, delete_file=true)`: folder removed, status stays error |
| T8 | `test_cancel_job_error_status_without_delete_no_cleanup` | Same as T7 but `delete_file=False` | Folder still exists |
| T9 | `test_cancel_job_archives_preserved` | Job in status=error, archives/{paper_dir}/ exists | After cancel_job(delete_file=true): archives folder still exists |
| T10 | `test_cancel_job_complete_status_no_cleanup` | Job in status=complete with `_ko.md` present | cancel_job is idempotent no-op (existing behavior) |
| T11 | `test_cancel_job_queued_does_smart_rename_post_hook` | Job in queued, source PDF in newones/, smart-renamed folder in outputs/ | After cancel_job(delete_file=true): source PDF gone AND smart-renamed folder gone |
| T12 | `test_zip_endpoint_rejects_error_status` | Job persisted with status="error", call zip endpoint | HTTP 404 (existing behavior) — regression guard so reconcile-driven error states stay un-downloadable |
| T13 | `test_get_job_result_rejects_error_status` | Job persisted with status="error", call `get_job_result` tool | Raises (FastMCP error response) — same intent as T12 for the metadata path |

Regression sweep: existing 40 tests must still pass.

## 7. Implementation order (for plan)

1. T5 (helper) → implement `_paper_has_ko_md` → T5 green
2. T6 (helper) → implement `_config_translation_enabled` → T6 green
3. T1–T4 (reconcile) → modify `reconcile_job` → T1–T4 green + regression
4. T7–T11 (cancel_job) → modify `cancel_job` + add `_cleanup_smart_renamed_paper` → T7–T11 green + regression
5. T12–T13 (zip/get_result regression) → no code change, just add tests against existing 404/ValueError behavior → green
6. docker-compose.yml env var addition
7. Manual smoke: rebuild viewer, re-run DeepSeek-V3 E2E flow

## 8. Migration & rollout

- **No JobRecord schema change.** Existing `logs/mcp_jobs.json` index is forward/backward compatible.
- **No new env vars required** for the MCP server. `PROCESS_TIMEOUT_SECONDS` is read by the converter container only; setting it has zero impact on viewer.
- **Existing partial outputs (e.g., a Korean-translation-incomplete folder from a prior run)** will, on next `reconcile_job` call (next status query or next list_jobs), transition from `status=complete` to `status=error` with the user-cleanup message. Users who relied on the buggy behavior of receiving English-only zips on translation-enabled deployments will get a clear error instead — this is the intended fix, not a regression.

## 9. Codex review plan

1 round (per brainstorm). Submit this spec → codex review → address findings → if `===CODEX_APPROVAL===` token returned, proceed to plan. If significant unresolved issues, 1 more round. Hard cap at 2.

## 10. Open questions

None. Decisions captured:

- No-change constraint: **maintained** (4 files preserved).
- Partial state: `status=error` with guidance message.
- Auto-cleanup: rejected. User-driven (`cancel_job` + `submit_paper(force_reprocess=true)`).
- Timeout: 7200s.
- Codex rounds: 1–2.
- Archives untouched in both reconcile and cancel.
- `_config_translation_enabled` is uncached (per-call read, fail-closed on error).

## 11. Risks

- **Risk**: User does not realize `status=error` was a partial-translation case (vs a genuine processing error). **Mitigation**: error message is verbose and prescriptive ("call cancel_job(delete_file=true), then resubmit with force_reprocess=true").
- **Risk**: `_config_translation_enabled` reads `config.json` on every reconcile call; with high job churn, this is `O(reconcile_calls)` filesystem reads. **Mitigation**: config.json is small (< 1KB observed) and reconcile is not on the hot path. If profiling later shows this matters, add a TTL cache.
- **Risk**: Smart-rename folder discovery via `find_processed_paper` depends on per-folder `paper_meta.json` having the original filename recorded. If that file is missing/corrupted for a given paper, `cancel_job` cleanup will silently no-op. **Mitigation**: `papers.find_processed_paper` already implements a fallback scan (added in v1 Round 2 codex fix). v1.1 inherits that resilience.
