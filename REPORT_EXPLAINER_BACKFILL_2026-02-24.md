# Explainer Backfill Report (2026-02-24)

- Project path: PaperFlow repository root at run time
- Skill reference found: `.claude/skills/paper-explainer/SKILL.md`
- Policy: generated only missing `*_ko_explained.md`; existing explained files were left untouched.
- Missing targets found: **4**

## Generated Files

- Source: `archives/A Guide to Fine-Tuning FunctionGemma/A Guide to Fine-Tuning FunctionGemma_ko.md`
  - Output: `archives/A Guide to Fine-Tuning FunctionGemma/A Guide to Fine-Tuning FunctionGemma_ko_explained.md`
  - Lines: 165 -> 268 (x1.62)
- Source: `archives/Real-World Agent Examples with Gemini 3/Real-World Agent Examples with Gemini 3_ko.md`
  - Output: `archives/Real-World Agent Examples with Gemini 3/Real-World Agent Examples with Gemini 3_ko_explained.md`
  - Lines: 135 -> 210 (x1.56)
- Source: `outputs/Gapfaith and Memory The Bridge Across the Void/Gapfaith and Memory The Bridge Across the Void_ko.md`
  - Output: `outputs/Gapfaith and Memory The Bridge Across the Void/Gapfaith and Memory The Bridge Across the Void_ko_explained.md`
  - Lines: 167 -> 284 (x1.70)
- Source: `outputs/Under the Hood Universal Commerce Protocol (UCP)/Under the Hood Universal Commerce Protocol (UCP)_ko.md`
  - Output: `outputs/Under the Hood Universal Commerce Protocol (UCP)/Under the Hood Universal Commerce Protocol (UCP)_ko_explained.md`
  - Lines: 207 -> 340 (x1.64)

## Summary

- scanned_roots: 2 (`outputs/`, `archives/`)
- generated: 4
- skipped_existing: all other `*_ko.md` with existing explained pair
- failures: 0

## Notes

- Existing explained files were not modified.
- This run backfilled only files that were missing a matching `*_ko_explained.md`.
