# Papers Library Migration Plan — Supplement (Claude + Codex 합의안)

날짜: 2026-05-25
원본 계획: `2026-05-25-paperflow-papers-library-migration.md`
합의 라운드: Claude 비판 → Codex 리뷰 1 → Claude 메타-리뷰 → Codex `===CODEX_FINAL_APPROVAL===`
참여 리뷰 파일: `docs/reviews/2026-05-25-papers-library-migration-*.md`

본 문서는 원본 plan에 추가/확정되어야 할 항목만 정리한다. 원본 plan의 폐기/대체 없이 보강으로 적용.

## 1. 확정 결정 (원본 Open Decisions 답)

| Open Decision | 결정 |
|---|---|
| 마이그레이션 default reading status | `unread`. progress > 0인 경우 dry-run report에서 `reading` 후보로 표시하고 `--apply-inference` flag로만 적용. runtime 자동 승급 없음. |
| frontmatter primary 범위 | 단일 primary note. `*_ko.md`가 있으면 그것, 없으면 `*.md`. 나머지 variant는 `type: paper-variant`. |
| Archive 시 reading_status | 보존 (별도 `library_status: archived`로 분리). |
| `papers/` 경로 설정 가능성 | env var `PAPER_LIBRARY_DIR` (기본 `papers`). `settings.papers_dir = Path(BASE_DIR) / PAPER_LIBRARY_DIR`. |

## 2. 디렉터리 레이아웃 (확정)

```text
<BASE_DIR>/
├── newones/                     # 입력 큐
├── papers/                      # active library (Obsidian vault target)
├── archives/                    # 비활성 라이브러리
├── outputs/                     # legacy. transition 동안 fallback. 사용자 confirm 후 제거.
├── logs/
└── .paperflow/                  # PaperFlow 내부 state (vault 밖)
    ├── state/
    │   ├── reading_progress.json
    │   └── paper_last_read.json
    └── migration-backups/
        └── <timestamp>/         # rollback manifest + Markdown 원본
```

`papers/` 안에는 PaperFlow 내부 state, backup, 시스템 JSON 일체 두지 않는다. Obsidian vault의 청결성 보장.

## 3. Frontmatter 스키마 (확정)

### Primary note (`*_ko.md` 또는 fallback `*.md`)

```yaml
---
type: paper
reading_status: unread | reading | read
library_status: active | archived
rating:            # 1-5 또는 null
read_at:           # ISO8601 또는 null
title:             # 원본 제목 (sanitize 전)
authors: [...]
year:
venue:
doi:
source_url:
processed_at:
archived_at:
aliases:           # [folder_name, original_filename without .pdf]
tags:
  - paper
---
```

### Variant note (나머지 Markdown)

```yaml
---
type: paper-variant
paperflow_primary: "<primary file basename>"
paperflow_variant: "ko_explained" | "en" | "en_explained"
---
```

Dataview `FROM "papers" WHERE type = "paper"`는 primary만 카운트.

## 4. State 분리 정책 (Q3 확정)

| 데이터 | 위치 | 이유 |
|---|---|---|
| `rating` | frontmatter | Obsidian Dataview/Bases 조회 가치 높음, 변경 빈도 낮음 |
| `read_at` | frontmatter | `reading_status: read` 전환 시점 기록, stable |
| `reading_progress` | `.paperflow/state/reading_progress.json` | 스크롤마다 갱신, 파일 churn 회피 |
| `last_read_at` | `.paperflow/state/paper_last_read.json` | viewer open마다 갱신, file churn 회피 |

## 5. paper_meta.json ↔ frontmatter 정책 (확정)

**One-time projection**. 양방향 sync 없음.

- 마이그레이션 시: `paper_meta.json` 키 → frontmatter 1회 복사.
- 이후: `paper_meta.json`은 batch pipeline/MCP가 갱신 (re-process 시 덮어씀).
- 이후: frontmatter는 사용자가 Obsidian에서 편집.
- re-process가 일어날 때: 사용자 편집 frontmatter 키 (`rating`, `read_at`, `reading_status`, `library_status`, `aliases`, 사용자 추가 키)는 보존. 나머지 (`title`, `authors`, `year`, `venue`, `doi`, `source_url`, `processed_at`)는 paper_meta로부터 다시 projection.

## 6. MCP location 스키마 (Q2 확정)

```python
JobRecord.location: Literal["papers", "outputs", "archives"] | None
```

- 신규 결과: `"papers"`
- transition fallback에서 `outputs/`에서 발견: `"outputs"` (legacy 라벨로 그대로 반환)
- archives: `"archives"`
- 응답에 `library_status: "active" | "archived"` 병기
- UI: `location === 'outputs'` 검사를 `library_status === 'active'`로 점진 마이그레이션 (transition 동안 둘 다 OK)

## 7. Frontmatter helper 요구사항 (확정)

- UTF-8 BOM(`﻿`) 처리: 인식 후 보존 또는 정규화 정책 명시
- CRLF vs LF: 입력 line ending 보존
- 빈 파일, 1줄 파일, frontmatter만 있고 본문 없는 파일: 안전 처리
- Invalid YAML: silent 통과 금지. dry-run report에 unparseable로 기록. backup 후 repair 또는 skip.
- 기존 non-PaperFlow frontmatter 키 보존
- PaperFlow-managed 키만 merge/update

## 8. Docker 변경 (확정)

```yaml
services:
  paperflow-converter:
    volumes:
      - ./newones:/app/newones
      - ./papers:/app/papers              # NEW
      - ./outputs:/app/outputs            # legacy, transition 기간 유지
      - ./archives:/app/archives          # 신규 (현재 누락)
      - ./logs:/app/logs
      - ./.paperflow:/app/.paperflow      # NEW (state + backup)
    environment:
      - PAPER_LIBRARY_DIR=${PAPER_LIBRARY_DIR:-papers}

  paperflow-viewer:
    volumes:
      - ./papers:/data/papers             # NEW
      - ./outputs:/data/outputs           # legacy
      - ./archives:/data/archives
      - ./newones:/data/newones
      - ./logs:/data/logs
      - ./.paperflow:/data/.paperflow     # NEW
    environment:
      - PAPER_LIBRARY_DIR=${PAPER_LIBRARY_DIR:-papers}
```

비대칭 내부 경로(`/app/...` vs `/data/...`)는 기존 패턴 유지.

## 9. 코드 변경 표면 (확정 hot list)

### main_terminal.py
- `output_dir = os.path.join("outputs", base_name)` → env-aware base
- `check_duplicate_batch()` scan order: `papers → outputs → archives`
- final log message ("Results are available in 'outputs'") 갱신

### run_batch_watch.sh
- `OUTPUTS_DIR="${PAPER_LIBRARY_DIR:-papers}"`
- cancel/delete cleanup: `papers`와 `outputs` 둘 다 스캔 (transition)

### viewer/app/config.py
- `papers_dir` property 추가
- `state_dir`, `migration_backup_dir` properties 추가

### viewer/app/services/papers.py
- list_papers, safe_paper_dir, archive_paper, restore_paper, get_paper_info, _get_existing_papers_summary: scan order 적용
- progress/last_read JSON 경로 → `settings.state_dir`로 이동
- rating은 frontmatter writer로 이동 + 기존 JSON migration

### viewer/app/services/mcp_jobs.py
- `JobRecord.location` Literal 확장
- `_resolve_completed_candidate` 4단계 → 6단계 (papers metadata, papers scan, outputs metadata, outputs scan, archives metadata, archives scan)
- `_paper_dir_for` location → base 매핑 확장

### viewer/app/templates/
- `papers.html`: tab `unread` / `reading` / `read` / `archived` 4탭
- `viewer.html`: `location === 'outputs'` 검사를 `library_status === 'active'`로 변경 (line 347, 607)
- 사용자 가시 라벨 i18n (한국어/영어 모두)

### scripts/
- `backfill_doc_type.py`, `fix_ocr_math_batch.py`, `quality_baseline_report.py`: scan order 적용
- 신규 `scripts/migrate_outputs_to_papers.py`

### viewer/tests/conftest.py
- tmp_workspace에 `papers`, `.paperflow/state`, `.paperflow/migration-backups` 추가
- 기존 outputs assertion 테스트는 legacy fallback 테스트로 분리 + papers 우선 테스트 신규

## 10. 마이그레이션 워크플로 (확정)

```text
1.  preflight: scan permissions, root-owned folders, duplicate folder names, duplicate original_filename, duplicate title
2.  dry-run (READ-ONLY, services running OK)
3.  user reviews dry-run report (move map, conflicts, permission issues, inference candidates, expected frontmatter diff count)
4.  enable maintenance lock OR stop converter
5.  real migration (manifest written to .paperflow/migration-backups/<ts>/)
6.  post-check (paper_meta integrity, frontmatter consistency, RAG cache state, viewer/MCP smoke, Obsidian Dataview sanity)
7.  release maintenance lock OR restart services
8.  keep outputs/ fallback ≥1 release with fallback-hit logging
9.  remove fallback after logs clean AND user confirms
```

### rollback
- `scripts/migrate_outputs_to_papers.py --rollback <manifest>`
- moved folders 원위치
- rewritten Markdown은 backup에서 복원
- state JSON 위치 원복

### duplicate hard-fail
- preflight에서 동일 folder name 또는 동일 `paper_meta.original_filename`이 papers/outputs 양쪽에 존재 시 hard fail
- runtime fallback에서도 conflict 발견 시 error/diagnostics 반환 (silent 선택 금지)

## 11. Implementation Order (확정 18단계)

1. Decide Q1/Q2/Q3, archive/read semantics, paper_meta projection (본 문서)
2. Preflight design: permissions, duplicates, services, backup/snapshot, rollback manifest
3. Path config: papers_dir, state_dir, backup_dir, legacy outputs_dir, scan order, symlink safety
4. Docker/compose + run_batch_watch + main_terminal output base + cleanup
5. Frontmatter helper with tests (BOM, CRLF, invalid YAML, variant primary)
6. Viewer service: listing/status/archive/restore/delete/get_stats + UI labels/actions/i18n
7. MCP/zip/RAG/web_search/maintenance scripts: lookup paths + location schema
8. Test fixtures + legacy fallback tests
9. Migration script: dry-run, manifest, backup, rollback, post-check
10. README/Obsidian docs + operational runbook
11. Run dry-run (services up, read-only)
12. User reviews dry-run report
13. Maintenance lock or stop converter
14. Run real migration
15. Post-check, viewer/MCP smoke, Obsidian Dataview sanity
16. Release maintenance lock or restart services
17. Keep outputs/ fallback ≥1 release with fallback-hit logging
18. Remove fallback after logs clean + user confirms

## 12. Test 커버리지 추가 (원본 Phase 8 보강)

- 권한·소유권 preflight 실패 케이스
- 중복 폴더명 hard fail
- BOM/CRLF/invalid YAML edge case
- frontmatter primary 단일 보장 (variant는 `type: paper`로 안 나옴)
- state dir 위치 확정 (`papers/` 밖)
- migration manifest 생성 + rollback로 원복 가능
- fallback-hit counter 정확성
- `JobRecord.location = "papers"` 직렬화/역직렬화
- UI 4탭 라벨 한국어/영어
- symlink escape: `papers/`, `archives/`, `.paperflow/` 모두 보호

## 13. Out of Scope (확정)

- `paperflow_id` 기반 stable route — 별도 plan 필요
- CDN/HTTPS/sitemap — 현재 코드에 없음
- 양방향 frontmatter ↔ paper_meta sync — 본 plan에서 거부

## 14. 합의 요약

- Claude 14개 비판 항목 → Codex 14개 모두 ACCEPT
- Codex 10개 추가 항목 → Claude 8개 ACCEPT, 4개 REFINE (state dir/inference/URL/scope), 4개 EXTEND (encoding/projection/dry-run/env var)
- Q1/Q2/Q3 합의 완료
- Implementation order 18단계 합의 완료
- 추가 비판 없음 — 구현 단계 진행 가능

---

본 문서를 원본 plan의 사실상 v2로 취급. 구현 PR은 본 supplement의 결정을 source of truth로 한다.
