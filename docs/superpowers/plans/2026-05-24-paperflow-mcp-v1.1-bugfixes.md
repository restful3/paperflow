# PaperFlow MCP v1.1 Bugfixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v1 MCP 서버의 3 Critical + 1 부수 버그 fix — large 논문 (50+ sections) 처리가 watch 2400s timeout 으로 SIGKILL 후 self-duplicate 루프에 빠져 `_ko.md` 가 없는 zip 을 사용자가 받게 되는 문제 해소.

**Architecture:** v1 무변경 제약 유지 — `main_terminal.py` / `run_batch_watch.sh` / `config.json` 0줄. 모든 fix 는 `viewer/app/services/mcp_jobs.py` 의 reconcile 정책 강화 + cancel cleanup 확장 + `mcp_router.py` 의 zip endpoint reconcile call + docker-compose env vars 로 한정.

**Tech Stack:** Python 3.12, FastAPI, mcp>=1.27, pydantic, asyncio, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-05-24-paperflow-mcp-v1.1-bugfixes-design.md` (rev4, codex final-approved R4)

---

## File Structure

```
viewer/
├── app/
│   ├── config.py                          # MODIFY: add MCP_REQUIRE_TRANSLATION field
│   ├── routers/
│   │   └── mcp_router.py                  # MODIFY: zip endpoint reconcile call + cancel_job response shape
│   └── services/
│       └── mcp_jobs.py                    # MODIFY: 8 new helpers, reconcile_job policy split, cancel_job augmentation
├── tests/
│   └── test_mcp_jobs.py                   # MODIFY: T5-T7, T20-T23 helper tests, T1-T19 reconcile/cancel tests
│   └── test_mcp_router.py                 # MODIFY: T13, T18, T19 router tests
docker-compose.yml                          # MODIFY: PROCESS_TIMEOUT_SECONDS=7200, MCP_REQUIRE_TRANSLATION=true
```

**papers.py is NOT modified.** v1.1 keeps the no-change constraint absolute — all logic that previously would have lived in `papers.py` lives in `mcp_jobs.py` instead (read-only paper_meta.json reads, outputs/archives scans).

---

## Task 1: `_is_safe_direct_child` helper

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py` (add helper near top of file, after imports)
- Test: `viewer/tests/test_mcp_jobs.py` (append new tests)

- [ ] **Step 1: Write the failing test**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
def test_is_safe_direct_child_accepts_direct_subdir(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    sub = settings.outputs_dir / "real_dir"
    sub.mkdir()
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, sub) is True


def test_is_safe_direct_child_rejects_nested(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    nested = settings.outputs_dir / "a" / "b"
    nested.mkdir(parents=True)
    # nested is a grandchild — not a direct child
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, nested) is False


def test_is_safe_direct_child_rejects_symlink_escape(tmp_workspace, tmp_path):
    from app.services import mcp_jobs
    from app.config import settings
    external = tmp_path / "external_target"
    external.mkdir()
    link = settings.outputs_dir / "evil_link"
    link.symlink_to(external)
    # symlink target is outside outputs_dir
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, link) is False


def test_is_safe_direct_child_rejects_missing(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    missing = settings.outputs_dir / "does_not_exist"
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, missing) is False


def test_is_safe_direct_child_rejects_file(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    f = settings.outputs_dir / "plain.txt"
    f.write_text("hi")
    assert mcp_jobs._is_safe_direct_child(settings.outputs_dir, f) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "is_safe_direct_child"`
Expected: 5 errors with `AttributeError: module 'app.services.mcp_jobs' has no attribute '_is_safe_direct_child'`

- [ ] **Step 3: Add the helper to `viewer/app/services/mcp_jobs.py`**

Locate the existing `_scan_outputs_for_filename` definition (around line 295). Add the new helper immediately before it:

```python
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
    except (FileNotFoundError, OSError):
        return False
    if cand_resolved.parent != base_resolved:
        return False
    if not cand_resolved.is_dir():
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "is_safe_direct_child"`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): _is_safe_direct_child helper for symlink-escape guard"
```

---

## Task 2: `_paper_has_ko_md` helper (tri-state)

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Test: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 1: Write the failing test (T5 in spec)**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
def test_paper_has_ko_md_with_ko(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    pdir = settings.outputs_dir / "WithKo"
    pdir.mkdir()
    (pdir / "WithKo.md").write_text("en")
    (pdir / "WithKo_ko.md").write_text("ko")
    assert mcp_jobs._paper_has_ko_md(pdir) is True


def test_paper_has_ko_md_without_ko(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    pdir = settings.outputs_dir / "NoKo"
    pdir.mkdir()
    (pdir / "NoKo.md").write_text("en only")
    assert mcp_jobs._paper_has_ko_md(pdir) is False


def test_paper_has_ko_md_missing_folder(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    pdir = settings.outputs_dir / "DoesNotExist"
    assert mcp_jobs._paper_has_ko_md(pdir) is None


def test_paper_has_ko_md_only_ko_explained(tmp_workspace):
    """*_ko_explained.md must NOT satisfy the _ko.md requirement."""
    from app.services import mcp_jobs
    from app.config import settings
    pdir = settings.outputs_dir / "OnlyExplained"
    pdir.mkdir()
    (pdir / "OnlyExplained.md").write_text("en")
    (pdir / "OnlyExplained_ko_explained.md").write_text("ko_explained")
    assert mcp_jobs._paper_has_ko_md(pdir) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "paper_has_ko_md"`
Expected: 4 errors with `AttributeError: module 'app.services.mcp_jobs' has no attribute '_paper_has_ko_md'`

- [ ] **Step 3: Add the helper**

In `viewer/app/services/mcp_jobs.py`, place immediately after `_is_safe_direct_child`:

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "paper_has_ko_md"`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): _paper_has_ko_md tri-state helper"
```

---

## Task 3: outputs-only / archives-only scan helpers

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Test: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 1: Write the failing tests (T7 partial, T23 symlink)**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
def test_scan_outputs_dir_only_finds_match(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    sub = settings.outputs_dir / "MyPaper"
    sub.mkdir()
    (sub / "src.pdf").touch()
    assert mcp_jobs._scan_outputs_dir_only("src.pdf") == "MyPaper"


def test_scan_outputs_dir_only_ignores_archives(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    arch = settings.archives_dir / "ArchPaper"
    arch.mkdir()
    (arch / "src.pdf").touch()
    assert mcp_jobs._scan_outputs_dir_only("src.pdf") is None


def test_scan_archives_dir_only_finds_match(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    arch = settings.archives_dir / "ArchPaper"
    arch.mkdir()
    (arch / "src.pdf").touch()
    assert mcp_jobs._scan_archives_dir_only("src.pdf") == "ArchPaper"


def test_scan_outputs_dir_only_rejects_symlink_escape(tmp_workspace, tmp_path):
    """T23 — scan helpers ignore symlinks that escape the base dir."""
    from app.services import mcp_jobs
    from app.config import settings
    # External target contains the file the scan would otherwise find
    external = tmp_path / "external_paper_dir"
    external.mkdir()
    (external / "src.pdf").touch()
    # Symlink inside outputs/ points at the external dir
    (settings.outputs_dir / "evil_link").symlink_to(external)
    assert mcp_jobs._scan_outputs_dir_only("src.pdf") is None


def test_scan_outputs_dir_only_no_outputs_dir(tmp_workspace):
    """Defensive: function returns None when outputs/ does not exist."""
    from app.services import mcp_jobs
    from app.config import settings
    import shutil
    shutil.rmtree(settings.outputs_dir)
    assert mcp_jobs._scan_outputs_dir_only("anything.pdf") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "scan_outputs_dir_only or scan_archives_dir_only"`
Expected: errors — helpers not defined

- [ ] **Step 3: Add the helpers**

In `viewer/app/services/mcp_jobs.py`, immediately after `_paper_has_ko_md`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "scan_outputs_dir_only or scan_archives_dir_only"`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): outputs-only / archives-only scan helpers with symlink guard"
```

---

## Task 4: `_find_metadata_match_in_dir` helper

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Test: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 1: Write the failing tests (T22 metadata-only, T23 metadata-symlink)**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
def test_find_metadata_match_in_dir_outputs_only(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    import json
    sub = settings.outputs_dir / "PaperA"
    sub.mkdir()
    (sub / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    assert mcp_jobs._find_metadata_match_in_dir(settings.outputs_dir, "src.pdf") == "PaperA"
    # archives/ does NOT match when outputs has the meta
    assert mcp_jobs._find_metadata_match_in_dir(settings.archives_dir, "src.pdf") is None


def test_find_metadata_match_ignores_corrupt_meta(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    sub = settings.outputs_dir / "Corrupt"
    sub.mkdir()
    (sub / "paper_meta.json").write_text("{not valid json")
    assert mcp_jobs._find_metadata_match_in_dir(settings.outputs_dir, "src.pdf") is None


def test_find_metadata_match_ignores_unrelated_meta(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    import json
    sub = settings.outputs_dir / "Other"
    sub.mkdir()
    (sub / "paper_meta.json").write_text(json.dumps({"original_filename": "different.pdf"}))
    assert mcp_jobs._find_metadata_match_in_dir(settings.outputs_dir, "src.pdf") is None


def test_find_metadata_match_rejects_symlink_escape(tmp_workspace, tmp_path):
    """T23 metadata path — same containment guard as scan helpers."""
    from app.services import mcp_jobs
    from app.config import settings
    import json
    external = tmp_path / "external_paper_dir"
    external.mkdir()
    (external / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    (settings.outputs_dir / "evil_link").symlink_to(external)
    assert mcp_jobs._find_metadata_match_in_dir(settings.outputs_dir, "src.pdf") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "find_metadata_match"`
Expected: 4 errors — helper not defined

- [ ] **Step 3: Add the helper**

In `viewer/app/services/mcp_jobs.py`, immediately after `_scan_archives_dir_only`:

```python
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
```

Verify `import json` is already present at the top of `mcp_jobs.py` (v1 already imports it for index handling — confirm with `grep "^import json" viewer/app/services/mcp_jobs.py`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "find_metadata_match"`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): _find_metadata_match_in_dir read-only meta scan helper"
```

---

## Task 5: `_resolve_completed_candidate` with strict 4-step priority

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Test: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 1: Write the failing tests (T6, T21, T22)**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
def test_resolve_outputs_metadata_wins_over_archives_metadata(tmp_workspace):
    """T22 — outputs metadata beats archives metadata, even if archives is newer."""
    from app.services import mcp_jobs
    from app.config import settings
    import json, os, time
    out_dir = settings.outputs_dir / "OutPaper"
    out_dir.mkdir()
    (out_dir / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    # No source PDF in outputs — only metadata
    arch_dir = settings.archives_dir / "ArchPaper"
    arch_dir.mkdir()
    (arch_dir / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    (arch_dir / "ArchPaper_ko.md").write_text("ko")
    # Make archives strictly newer
    future = time.time() + 60
    os.utime(arch_dir, (future, future))
    res = mcp_jobs._resolve_completed_candidate("src.pdf")
    assert res == ("OutPaper", "outputs")


def test_resolve_outputs_filesystem_beats_archives_metadata(tmp_workspace):
    """T21 — outputs filesystem scan (step 2) beats archives metadata (step 3)."""
    from app.services import mcp_jobs
    from app.config import settings
    import json, os, time
    out_dir = settings.outputs_dir / "OutPaper"
    out_dir.mkdir()
    (out_dir / "src.pdf").touch()  # filesystem only — no paper_meta
    arch_dir = settings.archives_dir / "ArchPaper"
    arch_dir.mkdir()
    (arch_dir / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    future = time.time() + 60
    os.utime(arch_dir, (future, future))
    assert mcp_jobs._resolve_completed_candidate("src.pdf") == ("OutPaper", "outputs")


def test_resolve_archives_metadata_when_no_outputs(tmp_workspace):
    """T6 inverse — when outputs has nothing, archives metadata wins."""
    from app.services import mcp_jobs
    from app.config import settings
    import json
    arch = settings.archives_dir / "ArchOnly"
    arch.mkdir()
    (arch / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    assert mcp_jobs._resolve_completed_candidate("src.pdf") == ("ArchOnly", "archives")


def test_resolve_archives_filesystem_when_no_meta_anywhere(tmp_workspace):
    """Step 4 fallback — archives filesystem-only."""
    from app.services import mcp_jobs
    from app.config import settings
    arch = settings.archives_dir / "ArchFS"
    arch.mkdir()
    (arch / "src.pdf").touch()
    assert mcp_jobs._resolve_completed_candidate("src.pdf") == ("ArchFS", "archives")


def test_resolve_returns_none_when_nothing_matches(tmp_workspace):
    from app.services import mcp_jobs
    assert mcp_jobs._resolve_completed_candidate("nope.pdf") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "resolve_outputs_metadata or resolve_outputs_filesystem or resolve_archives_metadata or resolve_archives_filesystem or resolve_returns_none"`
Expected: 5 errors — `_resolve_completed_candidate` not defined

- [ ] **Step 3: Add the helper**

In `viewer/app/services/mcp_jobs.py`, immediately after `_find_metadata_match_in_dir`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "resolve_outputs_metadata or resolve_outputs_filesystem or resolve_archives_metadata or resolve_archives_filesystem or resolve_returns_none"`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): _resolve_completed_candidate strict 4-step outputs-first priority"
```

---

## Task 6: `_paper_dir_for` utility

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Test: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
def test_paper_dir_for_outputs(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    assert mcp_jobs._paper_dir_for("Foo", "outputs") == settings.outputs_dir / "Foo"


def test_paper_dir_for_archives(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    assert mcp_jobs._paper_dir_for("Foo", "archives") == settings.archives_dir / "Foo"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "paper_dir_for"`
Expected: 2 errors

- [ ] **Step 3: Add the helper**

In `viewer/app/services/mcp_jobs.py`, immediately after `_resolve_completed_candidate`:

```python
def _paper_dir_for(name: str, location: str) -> Path:
    from ..config import settings
    base = settings.outputs_dir if location == "outputs" else settings.archives_dir
    return base / name
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "paper_dir_for"`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): _paper_dir_for path utility"
```

---

## Task 7: `MCP_REQUIRE_TRANSLATION` config field

**Files:**
- Modify: `viewer/app/config.py`
- Test: `viewer/tests/test_config_mcp.py`

- [ ] **Step 1: Write the failing tests**

Append to `viewer/tests/test_config_mcp.py`:

```python
def test_mcp_require_translation_default_true(tmp_workspace):
    from app.config import Settings
    s = Settings()
    assert s.MCP_REQUIRE_TRANSLATION is True


def test_mcp_require_translation_env_false(tmp_workspace, monkeypatch):
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "false")
    from app.config import Settings
    s = Settings()
    assert s.MCP_REQUIRE_TRANSLATION is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_config_mcp.py -v -k "require_translation"`
Expected: 2 errors with `AttributeError` on `MCP_REQUIRE_TRANSLATION`

- [ ] **Step 3: Add the field**

In `viewer/app/config.py`, add to the `Settings` class — locate the existing MCP block (around line 32-36) and add the new field at the end:

```python
    MCP_API_KEY: str = ""
    MCP_JOB_TTL_DAYS: int = 7
    MCP_PUBLIC_BASE_URL: str = ""        # required when MCP enabled, e.g. http://localhost:8090
    MCP_ALLOWED_ORIGINS: str = ""        # CSV. empty → derive. explicit "*" → permissive opt-out.
    MCP_REQUIRE_TRANSLATION: bool = True  # rev4: reconcile downgrades complete→error when _ko.md missing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_config_mcp.py -v -k "require_translation"`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add viewer/app/config.py viewer/tests/test_config_mcp.py
git commit -m "feat(mcp v1.1): MCP_REQUIRE_TRANSLATION setting (default true)"
```

---

## Task 8: `_classify_completion` four-state verdict

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Test: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 1: Write the failing tests (T20)**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
def test_classify_completion_complete_with_ko(tmp_workspace):
    from app.services import mcp_jobs
    from app.config import settings
    pdir = settings.outputs_dir / "Done"
    pdir.mkdir()
    (pdir / "Done.md").write_text("en")
    (pdir / "Done_ko.md").write_text("ko")
    (pdir / "src.pdf").touch()
    assert mcp_jobs._classify_completion("src.pdf") == "complete"


def test_classify_completion_partial_when_translation_required(tmp_workspace, monkeypatch):
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    pdir = _cfg.settings.outputs_dir / "Partial"
    pdir.mkdir()
    (pdir / "Partial.md").write_text("en")
    (pdir / "src.pdf").touch()
    assert mcp_jobs._classify_completion("src.pdf") == "partial"


def test_classify_completion_skip_when_translation_disabled(tmp_workspace, monkeypatch):
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "false")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    pdir = _cfg.settings.outputs_dir / "EnOnly"
    pdir.mkdir()
    (pdir / "EnOnly.md").write_text("en")
    (pdir / "src.pdf").touch()
    assert mcp_jobs._classify_completion("src.pdf") == "skip"


def test_classify_completion_missing(tmp_workspace):
    """No candidate folder anywhere → missing."""
    from app.services import mcp_jobs
    assert mcp_jobs._classify_completion("nope.pdf") == "missing"


def test_classify_completion_archives_always_complete(tmp_workspace):
    """archives are user-curated — never flagged as partial."""
    from app.services import mcp_jobs
    from app.config import settings
    arch = settings.archives_dir / "ArchEnOnly"
    arch.mkdir()
    (arch / "ArchEnOnly.md").write_text("en")
    (arch / "src.pdf").touch()
    # No _ko.md, but archives skip the partial check
    assert mcp_jobs._classify_completion("src.pdf") == "complete"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "classify_completion"`
Expected: 5 errors — `_classify_completion` not defined

- [ ] **Step 3: Add the helper**

In `viewer/app/services/mcp_jobs.py`, immediately after `_paper_dir_for`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "classify_completion"`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): _classify_completion four-state verdict helper"
```

---

## Task 9: `reconcile_job` policy — complete-branch re-validation

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Test: `viewer/tests/test_mcp_jobs.py`

This task changes `reconcile_job` early-return policy: `error` and `cancelled` remain terminal idempotent, but `complete` is re-validated through `_classify_completion`.

- [ ] **Step 1: Write the failing tests (T1, T2, T3, T4, T13, T14, T17)**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
import asyncio


async def _persist_job(status: str, expected_filename: str = "src.pdf",
                       paper_name: str | None = None,
                       location: str | None = None):
    """Helper: write a JobRecord at the given status straight to the index."""
    from app.services import mcp_jobs
    rec = mcp_jobs.JobRecord(
        job_id="job1",
        input_type="url",
        source="https://example.com/p.pdf",
        expected_filename=expected_filename,
        import_method=None,
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status=status,
        stage=None,
        percent=100 if status == "complete" else 0,
        paper_name=paper_name,
        location=location,
        error=None,
        submitted_at="2026-05-24T10:00:00",
        completed_at=None,
        expires_at="2026-05-31T10:00:00",
    )
    async with mcp_jobs._index_lock:
        idx = await mcp_jobs._load_index()
        idx[rec.job_id] = rec.model_dump()
        await mcp_jobs._atomic_write_index(idx)


def _make_paper_folder(tmp_workspace, name: str, has_ko: bool, has_pdf: bool = True,
                        has_meta: bool = True, dest: str = "outputs"):
    from app.config import settings
    import json
    base = settings.outputs_dir if dest == "outputs" else settings.archives_dir
    pdir = base / name
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{name}.md").write_text("en")
    if has_ko:
        (pdir / f"{name}_ko.md").write_text("ko")
    if has_pdf:
        (pdir / "src.pdf").touch()
    if has_meta:
        (pdir / "paper_meta.json").write_text(json.dumps({"original_filename": "src.pdf"}))
    return pdir


async def test_reconcile_complete_with_ko_md_stays_complete(tmp_workspace):
    """T3 — complete + _ko.md present → status stays complete (regression)."""
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Good", has_ko=True)
    await _persist_job("complete", paper_name="Good", location="outputs")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "complete"


async def test_reconcile_complete_partial_downgrades_to_error(tmp_workspace, monkeypatch):
    """T1 — complete + _ko.md missing + REQUIRE=true → status=error."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Bad", has_ko=False)
    await _persist_job("complete", paper_name="Bad", location="outputs")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"
    assert "translation_missing" in rec.error
    assert "cancel_job(delete_file=true)" in rec.error
    assert "force_reprocess=true" in rec.error
    assert "MCP_REQUIRE_TRANSLATION=false" in rec.error


async def test_reconcile_complete_skip_when_translation_disabled(tmp_workspace, monkeypatch):
    """T2 — complete + _ko.md missing + REQUIRE=false → stays complete."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "false")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "EnOnly", has_ko=False)
    await _persist_job("complete", paper_name="EnOnly", location="outputs")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "complete"


async def test_reconcile_complete_archives_unchanged(tmp_workspace):
    """T4 — archives folder with no _ko.md → still complete."""
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Archived", has_ko=False, dest="archives")
    await _persist_job("complete", paper_name="Archived", location="archives")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "complete"


async def test_reconcile_complete_folder_disappeared_becomes_error(tmp_workspace):
    """T17 — folder was deleted externally → status=error 'no longer present'."""
    from app.services import mcp_jobs
    # Job persisted complete, but no folder exists anywhere
    await _persist_job("complete", paper_name="Vanished", location="outputs")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"
    assert "no longer present" in rec.error
    assert "translation_missing" not in rec.error


async def test_reconcile_legacy_complete_migration(tmp_workspace):
    """T14 — v1 partial job persisted complete → next reconcile call surfaces error."""
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Legacy", has_ko=False)
    # paper_name/location may even be missing on truly legacy records
    await _persist_job("complete", paper_name=None, location=None)
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"
    assert "translation_missing" in rec.error


async def test_reconcile_error_status_stays_error(tmp_workspace):
    """error remains terminal — no re-validation."""
    from app.services import mcp_jobs
    await _persist_job("error")
    # Even if the filesystem now looks valid, error stays
    _make_paper_folder(tmp_workspace, "DoesntMatter", has_ko=True)
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"


async def test_reconcile_cancelled_status_stays_cancelled(tmp_workspace):
    """cancelled remains terminal."""
    from app.services import mcp_jobs
    await _persist_job("cancelled")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "cancelled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "reconcile_complete or reconcile_legacy or reconcile_error_status or reconcile_cancelled_status"`
Expected: failures — current `reconcile_job` returns the persisted record without re-validation, so the partial / missing / legacy cases all wrongly stay at "complete".

- [ ] **Step 3: Modify `reconcile_job` complete branch**

In `viewer/app/services/mcp_jobs.py`, find the `reconcile_job` function (around line 307). Replace the early-return block at the top:

```python
    # OLD:
    if rec.status in ("complete", "error", "cancelled"):
        return rec
```

with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "reconcile_complete or reconcile_legacy or reconcile_error_status or reconcile_cancelled_status"`
Expected: 8 passed

- [ ] **Step 5: Regression sweep**

Run: `cd viewer && pytest tests/ -v`
Expected: all existing tests still pass (no test name should now be failing that was previously passing).

- [ ] **Step 6: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): reconcile_job re-validates complete-status jobs"
```

---

## Task 10: `reconcile_job` policy — queued/processing branch missing handling

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Test: `viewer/tests/test_mcp_jobs.py`

This task switches the queued/processing completion-discovery branch to use `_resolve_completed_candidate` + `_classify_completion`, and explicitly handles `"partial"`, `"missing"`, and `"skip" / "complete"` verdicts (no fall-through).

- [ ] **Step 1: Write the failing tests (T15, T16)**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
async def test_reconcile_queued_to_complete_with_ko(tmp_workspace):
    """Normal happy path: queued → outputs has _ko.md → status=complete."""
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Done", has_ko=True)
    await _persist_job("queued")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "complete"
    assert rec.paper_name == "Done"
    assert rec.location == "outputs"


async def test_reconcile_queued_to_partial_with_translation_required(tmp_workspace, monkeypatch):
    """T15 — queued + outputs/{paper}/ partial → status=error translation_missing."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Bad", has_ko=False, has_meta=False)  # fallback scan path
    await _persist_job("queued")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"
    assert "translation_missing" in rec.error


async def test_reconcile_queued_outputs_partial_with_archives_complete(tmp_workspace, monkeypatch):
    """T16 — outputs partial AND archives complete → outputs wins → status=error."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    _make_paper_folder(tmp_workspace, "Both", has_ko=False, dest="outputs")
    _make_paper_folder(tmp_workspace, "Both", has_ko=True, dest="archives")
    await _persist_job("queued")
    rec = await mcp_jobs.reconcile_job("job1")
    assert rec.status == "error"
    assert "translation_missing" in rec.error


async def test_reconcile_queued_missing_after_candidate_resolved(tmp_workspace):
    """Race: resolver returned candidate then folder disappeared mid-classify."""
    from app.services import mcp_jobs
    pdir = _make_paper_folder(tmp_workspace, "Vanishing", has_ko=True)
    await _persist_job("queued")
    # Simulate disappearance by monkey-deleting after resolve — easiest is
    # to remove the entire folder between two reconcile calls.
    import shutil
    shutil.rmtree(pdir)
    rec = await mcp_jobs.reconcile_job("job1")
    # Resolver finds nothing → status remains queued (race-tolerant)
    # OR: resolve+classify both empty → no completion path triggers.
    # Either way, the test guards against false "complete" on missing candidate.
    assert rec.status != "complete"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "reconcile_queued"`
Expected: failures — current branch saves complete on candidate hit regardless of verdict.

- [ ] **Step 3: Modify the queued/processing completion-lookup branch**

In `viewer/app/services/mcp_jobs.py`, find the existing block immediately after `if rec.status == "downloading" ...` (around line 325-339). Replace the primary + fallback lookup:

```python
    # OLD (rev2/v1 — lines ~325-339):
    info = _papers.find_processed_paper(original_filename=rec.expected_filename)
    if info:
        await _set_job_fields(job_id, status="complete",
                               paper_name=info["name"], location=info["location"],
                               completed_at=_now_iso())
        return await get_job(job_id)

    scan = _scan_outputs_for_filename(rec.expected_filename)
    if scan:
        await _set_job_fields(job_id, status="complete",
                               paper_name=scan[0], location=scan[1],
                               completed_at=_now_iso())
        return await get_job(job_id)
```

with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "reconcile_queued"`
Expected: 4 passed

- [ ] **Step 5: Regression sweep**

Run: `cd viewer && pytest tests/ -v`
Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): reconcile_job queued/processing branch uses _classify_completion"
```

---

## Task 11: `_cleanup_smart_renamed_paper` outputs-only cleanup helper

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Test: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 1: Write the failing tests (T8, T9, T10 partial)**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
def test_cleanup_smart_renamed_outputs_match(tmp_workspace):
    from app.services import mcp_jobs
    pdir = _make_paper_folder(tmp_workspace, "SmartRenamed", has_ko=False)
    result = mcp_jobs._cleanup_smart_renamed_paper("src.pdf")
    assert result["attempted"] is True
    assert result["deleted_path"] == str(pdir)
    assert result["warning"] is None
    assert not pdir.exists()


def test_cleanup_smart_renamed_no_match(tmp_workspace):
    from app.services import mcp_jobs
    result = mcp_jobs._cleanup_smart_renamed_paper("nope.pdf")
    assert result == {"attempted": False, "deleted_path": None, "warning": None}


def test_cleanup_smart_renamed_archives_preserved(tmp_workspace):
    """T10 partial — archives match → cleanup refuses, archives untouched."""
    from app.services import mcp_jobs
    pdir = _make_paper_folder(tmp_workspace, "ArchOnly", has_ko=True, dest="archives")
    result = mcp_jobs._cleanup_smart_renamed_paper("src.pdf")
    assert result["attempted"] is False
    assert result["warning"] and "archives" in result["warning"]
    assert pdir.exists()  # archives intact
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "cleanup_smart_renamed"`
Expected: 3 errors — helper not defined

- [ ] **Step 3: Add the helper**

In `viewer/app/services/mcp_jobs.py`, add immediately after `_classify_completion`:

```python
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
```

Verify `import shutil` is already present at the top of `mcp_jobs.py` (v1 already imports it — confirm with `grep "^import shutil" viewer/app/services/mcp_jobs.py`; if missing, the function imports it locally, which is fine).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "cleanup_smart_renamed"`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): _cleanup_smart_renamed_paper outputs-only cleanup helper"
```

---

## Task 12: `cancel_job` augmentation + dict response shape

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`
- Modify: `viewer/tests/test_mcp_jobs.py` (update existing `cancelled.status` access)
- Test: `viewer/tests/test_mcp_jobs.py`

- [ ] **Step 1: Write the failing tests (T8 full, T9 full, T10 full, T11, T12, T18)**

Append to `viewer/tests/test_mcp_jobs.py`:

```python
async def test_cancel_job_error_status_with_delete_cleans_outputs(tmp_workspace):
    """T8 — error status + delete_file=true → outputs folder removed, response shape correct."""
    from app.services import mcp_jobs
    pdir = _make_paper_folder(tmp_workspace, "Recovering", has_ko=False)
    await _persist_job("error", paper_name="Recovering", location="outputs")
    res = await mcp_jobs.cancel_job("job1", delete_file=True)
    assert res["job_id"] == "job1"
    assert res["status"] == "error"
    assert res["cleanup"]["attempted"] is True
    assert res["cleanup"]["deleted_path"] == str(pdir)
    assert res["cleanup"]["warning"] is None
    assert not pdir.exists()


async def test_cancel_job_error_status_no_delete_no_cleanup(tmp_workspace):
    """T9 — error status + delete_file=false → no cleanup."""
    from app.services import mcp_jobs
    pdir = _make_paper_folder(tmp_workspace, "Keep", has_ko=False)
    await _persist_job("error", paper_name="Keep", location="outputs")
    res = await mcp_jobs.cancel_job("job1", delete_file=False)
    assert res["status"] == "error"
    assert res["cleanup"]["attempted"] is False
    assert pdir.exists()


async def test_cancel_job_archives_preserved(tmp_workspace):
    """T10 — error status, only archives match → archives untouched."""
    from app.services import mcp_jobs
    pdir = _make_paper_folder(tmp_workspace, "Archived", has_ko=True, dest="archives")
    await _persist_job("error", paper_name="Archived", location="archives")
    res = await mcp_jobs.cancel_job("job1", delete_file=True)
    assert res["cleanup"]["attempted"] is False
    assert "archives" in (res["cleanup"]["warning"] or "")
    assert pdir.exists()


async def test_cancel_job_complete_idempotent_no_cleanup(tmp_workspace):
    """T11 — complete status → cancel is idempotent no-op, no fs change."""
    from app.services import mcp_jobs
    pdir = _make_paper_folder(tmp_workspace, "Done", has_ko=True)
    await _persist_job("complete", paper_name="Done", location="outputs")
    res = await mcp_jobs.cancel_job("job1", delete_file=True)
    assert res["status"] == "complete"
    assert res["cleanup"]["attempted"] is False
    assert pdir.exists()


async def test_cancel_job_response_shape(tmp_workspace):
    """T18 — return shape contract: {job_id, status, cleanup:{attempted,deleted_path,warning}}."""
    from app.services import mcp_jobs
    await _persist_job("error")
    res = await mcp_jobs.cancel_job("job1", delete_file=False)
    assert set(res.keys()) == {"job_id", "status", "cleanup"}
    assert set(res["cleanup"].keys()) == {"attempted", "deleted_path", "warning"}


async def test_cancel_job_not_found_returns_none(tmp_workspace):
    from app.services import mcp_jobs
    res = await mcp_jobs.cancel_job("does_not_exist")
    assert res is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "cancel_job"`
Expected: failures — v1 `cancel_job` returns a `JobRecord` (or `None`), not a dict with cleanup info.

- [ ] **Step 3: Modify `cancel_job`**

In `viewer/app/services/mcp_jobs.py`, find the existing `cancel_job` (around line 387). Replace the entire function body:

```python
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
```

- [ ] **Step 4: Update the existing `cancelled.status` test (T18 source)**

Find the existing test in `viewer/tests/test_mcp_jobs.py` that reads `cancelled.status`. Search:

```bash
grep -n "cancelled.status\|\.status$" viewer/tests/test_mcp_jobs.py | head
```

The matching test (around line 265-266) accesses the return value as a JobRecord attribute. Update to dict access — e.g., replace `assert cancelled.status == "cancelled"` with `assert cancelled["status"] == "cancelled"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_jobs.py -v -k "cancel_job"`
Expected: 6 new tests passed + existing cancel test passes (after update).

- [ ] **Step 6: Regression sweep**

Run: `cd viewer && pytest tests/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add viewer/app/services/mcp_jobs.py viewer/tests/test_mcp_jobs.py
git commit -m "feat(mcp v1.1): cancel_job dict response + outputs-only cleanup on error+delete"
```

---

## Task 13: Update `mcp_router.py` — cancel_job wrapper + zip endpoint reconcile

**Files:**
- Modify: `viewer/app/routers/mcp_router.py`
- Test: `viewer/tests/test_mcp_router.py`

This task updates the FastMCP tool wrapper for `cancel_job` to return the new dict shape, and switches the zip endpoint from `get_job` to `reconcile_job`.

- [ ] **Step 1: Write the failing tests (T13, T19)**

Append to `viewer/tests/test_mcp_router.py`:

```python
async def test_zip_endpoint_triggers_reconcile_and_404s_on_partial(mcp_enabled_workspace, monkeypatch):
    """T13 — job persisted complete + partial outputs + REQUIRE=true → zip returns 404."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg, main as _main
    import importlib
    _cfg.settings = _cfg.Settings()
    importlib.reload(_main)

    from app.services import mcp_jobs
    pdir = _cfg.settings.outputs_dir / "Bad"
    pdir.mkdir()
    (pdir / "Bad.md").write_text("en")
    (pdir / "src.pdf").touch()
    rec = mcp_jobs.JobRecord(
        job_id="job1", input_type="url", source="x",
        expected_filename="src.pdf", import_method=None,
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name="Bad", location="outputs",
        error=None, submitted_at="2026-05-24T10:00:00",
        completed_at="2026-05-24T10:01:00", expires_at="2026-05-31T10:00:00",
    )
    async with mcp_jobs._index_lock:
        idx = await mcp_jobs._load_index()
        idx["job1"] = rec.model_dump()
        await mcp_jobs._atomic_write_index(idx)

    from fastapi.testclient import TestClient
    client = TestClient(_main.app)
    r = client.get(f"/api/mcp/jobs/job1/zip",
                   headers={"Authorization": f"Bearer {_cfg.settings.MCP_API_KEY}"})
    assert r.status_code == 404  # reconcile downgraded job to error → zip rejects


async def test_get_job_result_rejects_after_reconcile_downgrade(mcp_enabled_workspace, monkeypatch):
    """T19 — get_job_result raises after reconcile downgrades complete→error."""
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "true")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    from app.services import mcp_jobs
    from app.routers import mcp_router

    pdir = _cfg.settings.outputs_dir / "Bad2"
    pdir.mkdir()
    (pdir / "Bad2.md").write_text("en")
    (pdir / "src.pdf").touch()
    rec = mcp_jobs.JobRecord(
        job_id="job2", input_type="url", source="x",
        expected_filename="src.pdf", import_method=None,
        options=mcp_jobs.JobOptions(force_reprocess=False),
        status="complete", stage=None, percent=100,
        paper_name="Bad2", location="outputs",
        error=None, submitted_at="2026-05-24T10:00:00",
        completed_at="2026-05-24T10:01:00", expires_at="2026-05-31T10:00:00",
    )
    async with mcp_jobs._index_lock:
        idx = await mcp_jobs._load_index()
        idx["job2"] = rec.model_dump()
        await mcp_jobs._atomic_write_index(idx)

    import pytest
    with pytest.raises(ValueError) as excinfo:
        await mcp_router.get_job_result.__wrapped__(job_id="job2",
                                                      include_pdf=False,
                                                      include_translation=True)
    assert "not complete" in str(excinfo.value)
```

(Note: `mcp_router.get_job_result.__wrapped__` accesses the underlying coroutine — FastMCP decorates with `.tool()`. If `__wrapped__` is not exposed, call `await mcp_jobs.reconcile_job("job2")` directly and assert `rec.status == "error"` as a simpler invariant.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd viewer && pytest tests/test_mcp_router.py -v -k "zip_endpoint_triggers_reconcile or get_job_result_rejects"`
Expected: failures — zip endpoint currently calls `get_job` (not `reconcile_job`), so it returns 200 + zip even on partial state.

- [ ] **Step 3: Modify zip endpoint**

In `viewer/app/routers/mcp_router.py`, find the `download_zip` handler (around line 204-211). Change one line:

```python
    # OLD:
    rec = await mcp_jobs.get_job(job_id)
    # NEW:
    rec = await mcp_jobs.reconcile_job(job_id)
```

- [ ] **Step 4: Modify cancel_job tool wrapper response**

In `viewer/app/routers/mcp_router.py`, find the `cancel_job` tool (around line 127-133). It currently builds a 2-key dict. Replace the body to return the service-layer dict directly:

```python
@mcp.tool()
async def cancel_job(job_id: str, delete_file: bool = True) -> dict:
    """Cancel a job. Idempotent. Returns dict with cleanup details."""
    res = await mcp_jobs.cancel_job(job_id, delete_file=delete_file)
    if res is None:
        raise ValueError(f"job not found: {job_id}")
    return res
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd viewer && pytest tests/test_mcp_router.py -v`
Expected: all pass (including new T13/T19 + existing 4 tests in test_mcp_router.py).

- [ ] **Step 6: Regression sweep**

Run: `cd viewer && pytest tests/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add viewer/app/routers/mcp_router.py viewer/tests/test_mcp_router.py
git commit -m "feat(mcp v1.1): zip endpoint calls reconcile_job + cancel_job dict shape"
```

---

## Task 14: Remove dead `_scan_outputs_for_filename`

**Files:**
- Modify: `viewer/app/services/mcp_jobs.py`

- [ ] **Step 1: Verify no callers**

Run:

```bash
grep -rn "_scan_outputs_for_filename" viewer/
```

Expected: only one occurrence — the definition itself in `viewer/app/services/mcp_jobs.py` (the call site at line 334 was replaced in Task 10).

If any other caller appears, **stop** and re-examine that caller before deleting.

- [ ] **Step 2: Delete the function**

In `viewer/app/services/mcp_jobs.py`, find the definition (originally line 295-304):

```python
def _scan_outputs_for_filename(expected_filename: str) -> tuple[str, Literal["outputs", "archives"]] | None:
    """Fallback: scan outputs/ and archives/ for any folder containing expected_filename."""
    from ..config import settings
    for loc_name, base in (("outputs", settings.outputs_dir), ("archives", settings.archives_dir)):
        if not base.exists():
            continue
        for sub in base.iterdir():
            if sub.is_dir() and (sub / expected_filename).is_file():
                return sub.name, loc_name
    return None
```

Delete the whole block. If `Literal` is no longer used elsewhere in the file (`grep "Literal" viewer/app/services/mcp_jobs.py`), the import can stay (already used for status type annotation).

- [ ] **Step 3: Run full test sweep**

Run: `cd viewer && pytest tests/ -v`
Expected: all pass (no caller broken by removal).

- [ ] **Step 4: Commit**

```bash
git add viewer/app/services/mcp_jobs.py
git commit -m "chore(mcp v1.1): remove dead _scan_outputs_for_filename (replaced by split helpers)"
```

---

## Task 15: docker-compose env vars

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add `PROCESS_TIMEOUT_SECONDS` to the converter service**

In `docker-compose.yml`, locate the `paperflow-converter` service `environment:` block (around line 19-22). Append a new entry:

```yaml
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,utility
      - OPENAI_BASE_URL=http://host.docker.internal:8317/v1
      - PROCESS_TIMEOUT_SECONDS=${PROCESS_TIMEOUT_SECONDS:-7200}
```

- [ ] **Step 2: Add `MCP_REQUIRE_TRANSLATION` to the viewer service**

In the `paperflow-viewer` service `environment:` block (around line 50-56), append:

```yaml
    environment:
      - BASE_DIR=/data
      - OPENAI_BASE_URL=http://host.docker.internal:8317/v1
      - MCP_API_KEY=${MCP_API_KEY:-}
      - MCP_PUBLIC_BASE_URL=${MCP_PUBLIC_BASE_URL:-}
      - MCP_JOB_TTL_DAYS=${MCP_JOB_TTL_DAYS:-7}
      - MCP_ALLOWED_ORIGINS=${MCP_ALLOWED_ORIGINS:-}
      - MCP_REQUIRE_TRANSLATION=${MCP_REQUIRE_TRANSLATION:-true}
```

- [ ] **Step 3: Validate yaml**

Run: `docker compose config | grep -E "PROCESS_TIMEOUT_SECONDS|MCP_REQUIRE_TRANSLATION"`
Expected:

```
      PROCESS_TIMEOUT_SECONDS: "7200"
      MCP_REQUIRE_TRANSLATION: "true"
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "infra(mcp v1.1): PROCESS_TIMEOUT_SECONDS=7200 (converter) + MCP_REQUIRE_TRANSLATION=true (viewer)"
```

---

## Task 16: Rebuild + smoke verify

**Files:**
- (none — infra-only step)

- [ ] **Step 1: Rebuild viewer container**

```bash
docker compose build paperflow-viewer
```

Expected: build completes without errors.

- [ ] **Step 2: Restart services**

```bash
docker compose up -d paperflow-viewer paperflow-converter
```

Expected: both containers reach healthy state.

- [ ] **Step 3: Verify env vars inside containers**

```bash
docker compose exec paperflow-converter sh -lc 'echo PROCESS_TIMEOUT_SECONDS=$PROCESS_TIMEOUT_SECONDS'
docker compose exec paperflow-viewer sh -lc 'echo MCP_REQUIRE_TRANSLATION=$MCP_REQUIRE_TRANSLATION'
```

Expected:
- `PROCESS_TIMEOUT_SECONDS=7200`
- `MCP_REQUIRE_TRANSLATION=true`

- [ ] **Step 4: Verify MCP still mounted (regression)**

```bash
MCP_KEY=$(grep ^MCP_API_KEY= .env | cut -d= -f2)
curl -sI -H "Authorization: Bearer $MCP_KEY" http://localhost:8090/mcp/ | head -3
```

Expected: HTTP 200 or 405 (not 401, not 404). MCP server is reachable.

- [ ] **Step 5: Re-run DeepSeek-V3 retry as integration smoke**

If the user wants an end-to-end check (not required for the plan to be considered complete — TDD coverage T1-T23 + Task 16 step 3 is sufficient), submit DeepSeek-V3 again via MCP. Expected behavior with v1.1 deployed:

1. submit → status=downloading → processing → translating (now under 7200s timeout)
2. If translation still hits a snag and SIGKILL occurs again (env timeout still finite), the partial outputs are *now detected*: next `get_job_status` returns `status=error` with `translation_missing` guidance.
3. User runs `cancel_job(job_id, delete_file=true)` → outputs/{paper_dir}/ is cleaned (smart-rename aware).
4. User resubmits with `force_reprocess=true` → pipeline runs fresh, no self-duplicate, completes with `_ko.md`.

Report the actual stage durations and whether `status=error` was correctly returned for a partial run if it occurred.

This step is **manual / user-driven**; no commit needed.

---

## Self-Review Notes

- All 23 tests from spec §6 are covered: T1-T4 (reconcile complete branch, Task 9), T5 (Task 2), T6/T21/T22 (Task 5), T7 (Task 3), T8-T12 (Task 12), T13/T19 (Task 13), T14/T17 (Task 9), T15/T16 (Task 10), T18 (Task 12), T20 (Task 8), T23 (Tasks 1, 3, 4).
- Spec §7 implementation order is preserved (helpers before consumers; reconcile before cancel; cancel before router; router before infra).
- Spec §3 no-change constraint maintained: `main_terminal.py` / `run_batch_watch.sh` / `config.json` / `viewer/app/services/papers.py` all untouched.
- Spec §11 risks are acknowledged via Task 16 manual smoke (in particular, `MCP_REQUIRE_TRANSLATION=false` operator-mismatch case is testable by the same flow).
- Dead-code removal (`_scan_outputs_for_filename`) deferred to Task 14 so all helper + reconcile + cleanup tests run against the legacy function present, then it is removed after grep verification.
