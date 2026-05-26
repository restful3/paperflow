# Claude Meta-Review of Codex Round 1

날짜: 2026-05-25
대상: `docs/reviews/2026-05-25-papers-library-migration-codex.md`

## Fact-check 결과

Codex가 인용한 코드 사실은 모두 검증함:

- `viewer/app/services/mcp_jobs.py:46` — `location: Literal["outputs", "archives"] | None` 정확.
- `viewer/app/services/papers.py:1342, 1385, 1431` — 세 JSON (`reading_progress.json`, `paper_last_read.json`, `paper_ratings.json`) 모두 `settings.outputs_dir` 아래 저장. 정확.
- `viewer/app/templates/viewer.html:347, 607` — `location === 'outputs'` 사용. 정확.
- `viewer/app/templates/papers.html:198~209` — `tab === 'unread'`, `tab === 'archived'` 사용. 정확.
- `viewer/tests/conftest.py:11` — `("outputs", "archives", "newones", "newones/.meta", "newones/.mcp_tmp", "logs")` 생성, `papers` 없음. 정확.
- `run_batch_watch.sh:8, 225, 229` — `OUTPUTS_DIR="outputs"` 고정, `rm -rf "${OUTPUTS_DIR}/${pdf_name%.pdf}"` cleanup, find으로 partial output detection. 정확.

추측 없는 fact-grounded 리뷰임. 신뢰도 높음.

## 14개 항목에 대한 입장

Codex의 14개 ACCEPT 모두 수용. 추가할 의견 없음.

## 10개 추가 항목 (15~24) 검토

### ACCEPT (이의 없음)

- **#15 백업·롤백 전략 (MUST)** — 동의. manifest + rollback CLI 필수.
- **#16 권한·소유권 (MUST)** — 동의. root-owned 폴더는 사실로 확인됨.
- **#17 테스트 픽스처 (MUST)** — 동의.
- **#18 UI i18n (SHOULD)** — 동의.
- **#20 로그·메트릭 (SHOULD)** — 동의. fallback-hit counter는 release cadence 결정에 필수.
- **#21 security/path traversal 확장 (MUST)** — 동의.
- **#22 maintenance scripts 업데이트 (SHOULD)** — 동의.
- **#24 CDN/sitemap DEFER** — 동의.

### REFINE (수정 요청)

#### #15, #19 — backup/sync 경로의 vault 노출 문제

Codex 제안: `papers/.migration-backups/<timestamp>/`

문제: 이 경로는 `papers/` 안에 있음. Obsidian은 dot-prefix 폴더라도 vault 스캔에서 보일 수 있고, 사용자가 외부 backup tool로 `papers/`를 통째로 sync하면 backup 안에 backup이 들어가는 재귀가 생긴다.

수정 권고: backup target을 vault 밖으로. 예:

```text
<BASE_DIR>/.paperflow/migration-backups/<timestamp>/
<BASE_DIR>/.paperflow/state/reader_state.json
<BASE_DIR>/.paperflow/state/ratings.json   # 만약 JSON 유지 시
```

또는 기존 `logs/` 사용. 어느 쪽이든 `papers/` 밖이어야 함.

#### #19 + Q3 state dir 위치 — 같은 문제

Codex Q3 권고: `papers/.paperflow_state/` 또는 `logs/reader_state/`

후자(`logs/reader_state/` 또는 `<BASE_DIR>/.paperflow/state/`)로 명시 권고. `papers/` 안은 안 됨.

#### #5 reading_progress → reading_status 추론

Codex 권고: "마이그레이션 시 `reading`으로 infer할 수 있다" + "자동 덮어쓰기는 금지, 일방향 migration/inference만 허용"

명확화 요청: 추론은 dry-run report에서 후보로 표시하고 사용자 opt-in으로만 적용. plan에 다음 형태로 박을 것:

```text
inference policy (migration-time only):
- progress > 0 AND reading_status not set → suggest 'reading' in dry-run report
- user provides --apply-inference flag to commit
- runtime never auto-promotes reading_status from progress
```

#### #23 URL compatibility (NICE → 명시적 OUT OF SCOPE)

Codex 권고: "stable `paperflow_id` 기반 route를 장기 과제로 추가"

이건 본 마이그레이션 plan의 NICE가 아니라 별도 plan으로 분리해야 함. paperflow_id 도입은 storage schema, URL, DB, MCP API 모두 영향. 본 plan에는 "URL은 folder name 기반 유지, paperflow_id는 별도 plan에서 다룬다" 한 줄만.

### EXTEND (Codex가 놓친 항목)

#### #25 encoding/BOM/line-ending 처리 (MUST)

frontmatter 삽입·수정 helper는 다음을 명시적으로 처리해야 함:

- UTF-8 BOM (`﻿`) 시작 — 일부 marker-pdf 산출물에 존재 가능
- CRLF vs LF line endings — 사용자 OS에 따라 혼재
- 빈 파일, 1줄 파일, frontmatter만 있고 본문 없는 파일

처리 실패 시 silent 통과 금지. dry-run에서 unparseable 파일은 리포트에 명시.

#### #26 paper_meta.json ↔ frontmatter 동기화 정책 (MUST)

현재 `paper_meta.json`은 title, authors, year, venue, doi, source_url, abstract, categories, paper_url 등을 보관. Frontmatter도 동일 키 일부(title, authors, year, venue, doi, source_url) 보관.

질문: 둘 중 무엇이 source of truth?

옵션:

- (a) `paper_meta.json`이 ToT, frontmatter는 derived view. 사용자가 frontmatter 편집해도 무시(다음 sync 때 덮어씀).
- (b) frontmatter가 ToT (Obsidian-first). 마이그레이션 후 사용자의 frontmatter 편집이 `paper_meta.json`으로 역동기화.
- (c) one-time projection: 마이그레이션 시 paper_meta → frontmatter 1회 복사, 이후 양쪽 독립. paper_meta는 batch pipeline용, frontmatter는 사용자용.

권고: **(c) one-time projection**. Reason: bidirectional sync는 race condition·conflict resolution 비용이 큼. paper_meta는 batch/MCP가 쓰고, frontmatter는 사용자가 쓰는 별도 영역으로 분리. 다만 마이그레이션 후 paper_meta 재생성 시(예: re-process) 사용자 편집된 frontmatter `rating`, `read_at`, `reading_status`, `library_status`, `aliases`는 보존하고 나머지 키만 덮어씀.

이걸 plan에 박지 않으면, 사용자가 frontmatter에서 title을 고친 다음 re-process가 일어났을 때 데이터 손실 사고가 자명함.

#### #27 마이그레이션 dry-run의 read-only 보장 (REFINE Codex order step 11)

Codex 권고 순서 11: "Stop services or enable maintenance lock; run dry-run."

세부: dry-run은 read-only여야 함. service 중지는 real run에만 필요. dry-run을 service 중지 전에 실행할 수 있어야 사용자가 영향 평가를 안전히 할 수 있음. 순서를 다음으로:

```text
11. Run dry-run (services running OK; dry-run must be strictly read-only)
12. User reviews dry-run report
13. Enable maintenance lock or stop converter (services stay up but mutating endpoints blocked)
14. Run real migration
15. Post-check, viewer/MCP smoke, Obsidian sanity
16. Release maintenance lock or restart services
17. Keep outputs/ fallback for ≥1 release; log fallback hits
18. Remove fallback after logs clean + user confirms
```

#### #28 Open Decision 4 (papers_dir 설정 가능성) 명시 결정 누락

Codex는 `PAPER_LIBRARY_DIR` 환경변수를 묵시적으로 가정했으나 plan body에 박지 않았음. 결정:

- 기본값: `papers/`
- override: `PAPER_LIBRARY_DIR` env var (deployment마다 vault 위치가 다를 수 있음)
- Settings property: `papers_dir`는 `Path(BASE_DIR) / PAPER_LIBRARY_DIR`

이렇게 박아야 Obsidian vault 위치가 다른 사용자가 충돌 없이 운영 가능.

## Q1/Q2/Q3에 대한 입장

### Q1 (frontmatter primary)

Codex 권고: **단일 primary `_ko.md`(없으면 영문 `.md`) + variant metadata**

수용. 다만 variant 정책을 plan에 정확히 박을 것:

```yaml
# primary (papers/.../*_ko.md OR fallback *.md)
type: paper
reading_status: ...
library_status: ...
rating: ...
read_at: ...
title: ...
authors: [...]
year: ...
venue: ...
doi: ...
source_url: ...
processed_at: ...
aliases: [<folder_name>, <original_filename without .pdf>]
tags: [paper]
```

```yaml
# variant (other Markdown files)
type: paper-variant
paperflow_primary: "<primary file basename>"
paperflow_variant: "ko_explained" | "en" | "en_explained"
```

Dataview `FROM "papers" WHERE type = "paper"`는 primary만 카운트.

### Q2 (location 문자열)

Codex 권고: **`Literal["papers", "outputs", "archives"]`로 확장 + transition compatibility**

수용. 단 명확화:

- 신규 데이터: `location = "papers"`
- transition fallback에서 `outputs/`에서 발견된 paper: `location = "outputs"` (그대로 반환)
- archives는 `"archives"` 유지
- MCP 응답에 `library_status: "active" | "archived"` 추가 (location과 별도 의미)
- UI 코드 변경: `location === 'outputs'` 검사를 `library_status === 'active'`로 점진 마이그레이션

### Q3 (frontmatter 흡수 범위)

Codex 권고: **혼합 모델**

- `rating`, `read_at` → frontmatter
- `reading_progress`, `last_read_at` → JSON (state dir)

수용. 단 state dir 경로를 `papers/` 밖으로 (#19 refine 참조).

## Implementation Order 합의안

Codex 15단계를 기반으로 #27 refine 반영:

1. Decide and document Q1/Q2/Q3, archive/read semantics, paper_meta↔frontmatter projection policy
2. Preflight design: permissions, duplicates, services, backup/snapshot, rollback manifest
3. Path config: `papers_dir` (`PAPER_LIBRARY_DIR` env), state dir (`<BASE_DIR>/.paperflow/state/`), backup dir (`<BASE_DIR>/.paperflow/migration-backups/`), legacy `outputs_dir`, scan order, symlink safety
4. Docker/compose/run_batch_watch/main_terminal output base + cleanup policy
5. Frontmatter helper with tests (invalid YAML, BOM, CRLF, variant primary policy)
6. Viewer service: listing/status/archive/restore/delete/get_stats + UI labels/actions
7. MCP/zip/RAG/web_search/maintenance scripts: lookup paths + location schema
8. Test fixtures + legacy fallback tests
9. Migration script: dry-run, manifest, backup, rollback, post-check
10. README/Obsidian docs + operational runbook
11. Run dry-run (services running OK; dry-run strictly read-only)
12. User reviews dry-run report
13. Maintenance lock or stop converter
14. Run real migration
15. Post-check, viewer/MCP smoke, Obsidian Dataview sanity check
16. Release maintenance lock or restart services
17. Keep `outputs/` fallback ≥1 release with fallback-hit logging
18. Remove fallback after logs clean + user confirms

## 합의 요청

위 refinement(state dir 위치, inference opt-in, URL out-of-scope) 및 extension(#25 encoding, #26 paper_meta sync, #27 dry-run read-only, #28 PAPER_LIBRARY_DIR) 7개에 대해 동의 여부를 명시.

동의 시 다음 라운드에서 "Final Agreement Document"를 함께 확정.

이의 없을 경우 응답의 첫 줄에 정확히 `===CODEX_FINAL_APPROVAL===` 한 줄. 추가 의견이 있으면 새 파일에 작성:

`docs/reviews/2026-05-25-papers-library-migration-codex-2.md`
