# Papers Library Migration — Final Agreement Summary

**Date**: 2026-05-25
**Outcome**: ✅ Approved (Codex `===CODEX_FINAL_APPROVAL===` on Round 2)
**Total rounds**: 2 (Claude review → Codex Round 1 → Claude meta-review → Codex approval)

## Files produced

| Round | Author | File |
|---|---|---|
| 1 | Claude | `docs/reviews/2026-05-25-papers-library-migration-claude-review.md` (14 critical items, 3 decision Qs) |
| 1 | Codex  | `docs/reviews/2026-05-25-papers-library-migration-codex.md` (all 14 ACCEPT, +10 items, Q1/Q2/Q3 recs, 15-step order) |
| 2 | Claude | `docs/reviews/2026-05-25-papers-library-migration-claude-meta-review.md` (fact-check passed, 8 ACCEPT + 4 REFINE + 4 EXTEND) |
| 2 | Codex  | `docs/reviews/2026-05-25-papers-library-migration-codex-2.md` (`===CODEX_FINAL_APPROVAL===`) |
| Final | Claude | `docs/superpowers/plans/2026-05-25-paperflow-papers-library-migration-supplement.md` (consolidated decisions) |

## Convergence quality

- Codex's 14 Round-1 ACCEPTs were grounded in verified code reads (JobRecord typing, JSON locations, UI template strings, conftest, watch script). Independently fact-checked by Claude — all correct.
- 0 disagreements remained at termination.
- All 4 Open Decisions in the original plan are now settled in the supplement.
- 7 plan-blocking items added during meta-review (state dir location, inference opt-in, paperflow_id scope, BOM/CRLF, paper_meta projection, dry-run read-only, env var) — all ACCEPTed by Codex.

## Out of scope (explicitly carved out)

- `paperflow_id`-based stable URLs → future plan
- CDN/HTTPS/sitemap → no code path exists
- Bidirectional frontmatter ↔ paper_meta sync → rejected (one-time projection only)

## Total changed lines forecast (rough)

| Area | Files | Estimated LOC delta |
|---|---|---|
| `config.py` paths | 1 | +30 |
| `main_terminal.py` output base + duplicate scan | 1 | +50 |
| `run_batch_watch.sh` cleanup | 1 | +20 |
| `papers.py` listing/archive/restore + state JSON move | 1 | +200 |
| `mcp_jobs.py` location schema + 6-step resolver | 1 | +80 |
| Frontmatter helper + tests | 2 | +400 |
| UI templates (papers.html, viewer.html) tab + labels | 2 | +200 |
| `scripts/migrate_outputs_to_papers.py` + rollback | 1 | +500 |
| conftest + new tests | ~5 | +400 |
| Docker compose | 1 | +10 |
| Maintenance scripts (3 files) | 3 | +30 |
| README/Obsidian docs | 1 | +200 |
| **TOTAL** | ~20 files | **~2,120 LOC** |

This is a multi-PR effort — recommend splitting per implementation-order step.

## Next action for the user

1. Review the supplement file: `docs/superpowers/plans/2026-05-25-paperflow-papers-library-migration-supplement.md`
2. Approve or adjust any specific decision before implementation begins
3. Implementation should follow the 18-step order; each step is a candidate PR boundary
