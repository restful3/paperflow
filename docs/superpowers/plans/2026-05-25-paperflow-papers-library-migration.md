# PaperFlow Papers Library Migration Plan

Date: 2026-05-25

## Goal

Move PaperFlow from a folder-as-reading-state model to a metadata-as-reading-state model:

```text
newones/  -> input queue only
papers/   -> active paper library: unread / reading / read
archives/ -> papers intentionally removed from active library
```

The main motivation is Obsidian compatibility. Processed Markdown papers should live in one active vault-friendly folder, while reading state is stored in YAML frontmatter that Obsidian Properties, Dataview, and Bases can query.

## Target Model

Processed papers live under `papers/` as paper-level folders:

```text
papers/DeepSeek-V3 Technical Report/
  DeepSeek-V3 Technical Report.md
  DeepSeek-V3 Technical Report_ko.md
  DeepSeek-V3 Technical Report_ko_explained.md
  paper_meta.json
  DeepSeek-V3 Technical Report.pdf
  images/
```

Reading state is stored in Markdown frontmatter, not by moving files between active folders:

```yaml
---
type: paper
reading_status: unread
library_status: active
title: DeepSeek-V3 Technical Report
authors:
  - DeepSeek-AI
year: 2024
venue: arXiv
doi:
source_url: https://arxiv.org/abs/2412.19437
processed_at: 2026-05-25
read_at:
archived_at:
tags:
  - paper
---
```

Recommended status fields:

- `reading_status`: `unread | reading | read`
- `library_status`: `active | archived`

Rationale: "Has this been read?" and "Should this remain in the active library?" are separate decisions. A read paper may still be active reference material.

## Product Rules

1. `newones/` is an input queue only.
2. New processed output goes to `papers/`.
3. `papers/` is the active library for unread, reading, and read papers.
4. Reading state changes update frontmatter only.
5. Archive is the only normal action that moves a processed paper folder out of `papers/`.
6. `archives/` means "not in active library", not "read".
7. `paper_meta.json` remains the machine/cache metadata file.
8. Obsidian-facing metadata is duplicated into Markdown frontmatter.
9. Existing image/PDF/cache colocated folder structure is preserved.

## Migration Phases

### Phase 1: Path Compatibility Layer

Add configuration without immediately deleting `outputs/` support.

- Add `PAPER_LIBRARY_DIR=papers`.
- Add `settings.papers_dir`.
- Keep `settings.outputs_dir` for backward compatibility.
- Read active library candidates in this order during transition:
  1. `papers/`
  2. `outputs/`
- Keep `archives/` as the archive location.
- Add Docker volume:

```yaml
- ./papers:/data/papers
```

Transition invariant: old installs with only `outputs/` must continue to work before migration is run.

### Phase 2: Frontmatter Utilities

Create a small service helper for Markdown frontmatter read/write.

Required behavior:

- Read YAML only when it appears at the very top of the file.
- Preserve existing non-PaperFlow frontmatter keys.
- Merge/update only PaperFlow-managed keys.
- Insert frontmatter if missing.
- Preserve body content exactly except for the frontmatter block.
- Handle invalid YAML conservatively: do not overwrite silently; surface an error or create a backup before repair.

Minimum PaperFlow-managed keys:

- `type`
- `reading_status`
- `library_status`
- `title`
- `authors`
- `year`
- `venue`
- `doi`
- `source_url`
- `processed_at`
- `read_at`
- `archived_at`
- `tags`

### Phase 3: New Output Destination

Change new processing completion so processed paper folders land in `papers/`.

Notes:

- Keep paper-level folder structure.
- On creation, set:

```yaml
reading_status: unread
library_status: active
```

- Write/repair frontmatter for the primary Markdown files:
  - `*.md`
  - `*_ko.md`
  - `*_explained.md`
  - `*_ko_explained.md`
- Prefer metadata from `paper_meta.json` when present.

### Phase 4: UI Model Change

Current model:

```text
Unread/Active = outputs/
Archived      = archives/
```

Target model:

```text
Unread  = papers/* where reading_status=unread
Reading = papers/* where reading_status=reading
Read    = papers/* where reading_status=read
Archive = archives/*
```

Button behavior:

- `Mark as unread`: update frontmatter `reading_status: unread`; clear `read_at` if desired.
- `Mark as reading`: update frontmatter `reading_status: reading`.
- `Mark as read`: update frontmatter `reading_status: read`; set `read_at`.
- `Archive`: update `library_status: archived`, set `archived_at`, move folder `papers/ -> archives/`.
- `Restore`: move folder `archives/ -> papers/`, set `library_status: active`.

Important: read/unread actions must not move folders.

### Phase 5: MCP, ZIP, and RAG Updates

Update all result lookup paths to prefer `papers/`.

During transition, lookup order should be:

1. `papers/`
2. `outputs/`
3. `archives/`

Areas to update:

- MCP `reconcile_job()`
- MCP `get_job_result()`
- MCP zip endpoint
- Paper listing/search
- Archive/restore/delete operations
- Markdown edit save
- RAG chunk/cache lookup

RAG cache files can remain inside each paper folder:

- `chat_chunks.json`
- `chat_history.json`

### Phase 6: Migration Script

Add:

```text
scripts/migrate_outputs_to_papers.py
```

Required behavior:

1. Support `--dry-run`.
2. Create `papers/` if missing.
3. Move each `outputs/*` paper folder to `papers/*`.
4. Handle name collisions with suffixes, for example `Paper Title (2)`.
5. Add or repair frontmatter in Markdown files.
6. Extract metadata from `paper_meta.json`.
7. Default migrated active papers to:

```yaml
reading_status: unread
library_status: active
```

8. Do not move `archives/*`.
9. Optionally repair archive frontmatter in place:

```yaml
library_status: archived
```

10. Write a migration report under `logs/` or print a clear summary.

Safety:

- Never delete `outputs/`.
- Prefer move with explicit source/destination report.
- On any failed folder move, stop and report.
- Preserve backups for Markdown files before frontmatter rewrites if invalid YAML is encountered.

### Phase 7: Obsidian Documentation

Add README section with Dataview examples.

Unread:

```dataview
TABLE year, venue, authors
FROM "papers"
WHERE type = "paper" AND reading_status = "unread"
SORT processed_at DESC
```

Reading:

```dataview
TABLE year, venue, authors
FROM "papers"
WHERE type = "paper" AND reading_status = "reading"
SORT processed_at DESC
```

Read:

```dataview
TABLE read_at, year, venue
FROM "papers"
WHERE type = "paper" AND reading_status = "read"
SORT read_at DESC
```

Active references regardless of read state:

```dataview
TABLE reading_status, year, venue
FROM "papers"
WHERE type = "paper" AND library_status = "active"
SORT processed_at DESC
```

### Phase 8: Tests

Required test coverage:

- `papers/` is primary active library.
- `outputs/` fallback still works before migration.
- Frontmatter missing -> inserted.
- Existing valid YAML -> PaperFlow keys merged and unrelated keys preserved.
- Invalid YAML -> safe failure or backed-up repair path.
- `reading_status` update does not move folders.
- `Archive` moves `papers/ -> archives/`.
- `Restore` moves `archives/ -> papers/`.
- MCP result lookup succeeds in `papers/`.
- MCP zip export succeeds from `papers/`.
- RAG cache lookup works after migration.
- Markdown edit save preserves frontmatter.

## Recommended Implementation Order

1. Add path config and compatibility reads.
2. Add frontmatter helper with tests.
3. Update listing/status/archive/restore behavior.
4. Update MCP/zip/RAG lookup.
5. Add migration script with dry-run.
6. Update README with Obsidian workflow.
7. Run migration in dry-run mode.
8. Run migration for real.
9. Keep `outputs/` fallback for at least one release.
10. Remove `outputs/` fallback only after manual verification.

## Open Decisions

- Should migrated `outputs/` papers default to `unread`, or should PaperFlow infer `read` from existing reading progress?
- Should only the primary `*_ko.md` receive Obsidian frontmatter, or should every Markdown variant receive synchronized frontmatter?
- Should `Archive` keep `reading_status` unchanged or force a separate value such as `archived`?
- Should `papers/` be configurable per deployment, or hard-coded as the new standard path?
