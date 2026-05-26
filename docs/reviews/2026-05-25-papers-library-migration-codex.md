# Codex Review — Papers Library Migration Plan Round 1

Date: 2026-05-25

Reviewed:

- `docs/superpowers/plans/2026-05-25-paperflow-papers-library-migration.md`
- `docs/reviews/2026-05-25-papers-library-migration-claude-review.md`

Scope: plan 보강 리뷰만 수행. 코드 수정 없음.

## Fact Check Summary

코드베이스 확인 결과 Claude 리뷰의 주요 전제는 사실이다.

- `viewer/app/config.py`는 현재 `outputs_dir`, `archives_dir`, `newones_dir`, `logs_dir`만 제공하고 `papers_dir`가 없다.
- `main_terminal.py`는 신규 출력 위치를 `os.path.join("outputs", base_name)`로 직접 만든다.
- `main_terminal.py`의 `check_duplicate_batch()`는 `("outputs", "outputs")`, `("archives", "archives")`만 검사한다.
- `run_batch_watch.sh`는 `OUTPUTS_DIR="outputs"`를 고정값으로 사용하고 cancel/delete cleanup도 `OUTPUTS_DIR`만 지운다.
- `viewer/app/services/papers.py`는 list, resolve, archive, restore, progress, last_read, ratings 모두 `outputs`/`archives` 모델에 강하게 묶여 있다.
- `viewer/app/services/mcp_jobs.py`의 `JobRecord.location`은 `Literal["outputs", "archives"] | None`이고 `_resolve_completed_candidate()`도 outputs -> archives만 탐색한다.
- `viewer/app/templates/viewer.html`와 `viewer/app/templates/papers.html`은 `location === 'outputs'`, `tab === 'unread'`, `tab === 'archived'` 조건 및 라벨을 사용한다.
- `viewer/tests/conftest.py`는 tmp workspace에 `outputs`, `archives`, `newones`, `logs`만 만든다.
- 실제 로컬 데이터에는 `outputs/`와 `archives/` 하위 다수 폴더가 `root:root` 소유다. 이는 마이그레이션/프론트매터 쓰기 계획에 권한 정책이 필요하다는 근거다.

## Claude 14개 항목에 대한 판단

### 1. Docker 마운트 및 컨테이너 경로 변경 누락

Decision: **ACCEPT**

Reason: plan은 viewer용 예시로 `./papers:/data/papers`만 적었지만, converter는 `docker-compose.yml`에서 `./outputs:/app/outputs`를 쓰고 `main_terminal.py`는 cwd-relative `outputs`에 쓴다. 신규 결과가 `papers/`에 가려면 converter에도 `./papers:/app/papers` 마운트가 필요하다. viewer와 converter의 내부 경로가 `/data`와 `/app`으로 다르므로 이 비대칭을 유지할지 명시해야 한다.

Plan change: Phase 1에 두 서비스의 마운트 정책을 명시하고, converter는 `PAPER_LIBRARY_DIR` 또는 별도 `OUTPUT_DIR` 환경변수를 통해 `/app/papers`에 쓰도록 적어야 한다.

### 2. `main_terminal.py` 출력 디렉터리 결정 로직 변경 누락

Decision: **ACCEPT**

Reason: `process_single_pdf()`가 `output_dir = os.path.join("outputs", base_name)`로 신규 처리 폴더를 직접 만든다. `check_duplicate_batch()`도 outputs/archives만 본다. Phase 3의 "land in papers/"는 구현 위치를 지정하지 않아 불충분하다.

Plan change: `main_terminal.py`의 output base 결정, rename parent 동작, duplicate scan order를 명시해야 한다. 새 처리 base는 `papers`이고 transition duplicate scan은 `papers -> outputs -> archives`여야 한다.

### 3. `run_batch_watch.sh`의 `OUTPUTS_DIR` 변수 처리 누락

Decision: **ACCEPT**

Reason: `run_batch_watch.sh`는 `OUTPUTS_DIR="outputs"`를 만들고, cancel/delete 시 `${OUTPUTS_DIR}/${pdf_name%.pdf}`와 source PDF를 포함한 partial output을 삭제한다. output base가 `papers`가 되면 timeout/cancel cleanup이 틀어진다.

Plan change: `OUTPUTS_DIR="${PAPER_LIBRARY_DIR:-papers}"` 같은 정책을 명시하되, transition 기간의 legacy cleanup은 `papers`와 `outputs` 둘 다 스캔해야 한다.

### 4. `chat_history.json` / `chat_chunks.json` 마이그레이션 행동 미정

Decision: **ACCEPT**

Reason: 이 파일들은 paper folder 내부에 있으므로 폴더 이동 시 함께 이동한다. 다만 frontmatter 삽입은 Markdown 본문 앞부분을 바꾸기 때문에 현재 `save_markdown()`이 Markdown 저장 후 `chat_chunks.json`을 삭제하는 것과 같은 invalidation 원칙을 적용할지 정해야 한다.

Recommendation: 마이그레이션의 frontmatter 삽입은 content hash를 바꾸므로 `chat_chunks.json`은 삭제하는 것이 안전하다. `chat_history.json`은 대화 기록이므로 보존한다.

### 5. `reading_status: reading`과 기존 `reading_progress` 관계

Decision: **ACCEPT**

Reason: 현재 `reading_progress.json`은 `settings.outputs_dir` 아래에 있고 API `/api/progress` 및 viewer/list UI가 사용한다. plan은 `reading_status: reading`을 도입하지만 progress와의 규칙을 정의하지 않는다.

Recommendation: progress는 frontmatter에 흡수하지 말고 별도 runtime/user-state JSON으로 유지하되 저장 위치를 library state path로 옮긴다. 파생 규칙만 둔다: `reading_status=unread`이고 progress > 0이면 UI가 `reading` 전환을 제안하거나 마이그레이션 시 `reading`으로 infer할 수 있다. 단, 자동으로 계속 덮어쓰면 사용자가 명시한 상태와 충돌하므로 일방향 migration/inference만 허용한다.

### 6. Last-read 타임스탬프 처리 미정

Decision: **ACCEPT**

Reason: `touch_last_read()`는 `paper_last_read.json`을 `settings.outputs_dir`에 저장하고 viewer 페이지 진입 때 호출된다. plan의 `read_at`과 `last_read`는 의미가 다르다. `read_at`은 완료 시각이고 `last_read_at`은 최근 열람 시각이다.

Recommendation: `read_at`은 frontmatter로 관리한다. `last_read_at`은 자주 변하는 UI 상태이므로 글로벌 JSON으로 유지하되 새 library state 위치로 옮긴다. 둘을 같은 필드로 합치면 "읽음 완료"와 "마지막으로 열어봄"이 섞인다.

### 7. `progress.json`/`ratings.json`/`last_read.json` 위치 및 ratings frontmatter 여부

Decision: **ACCEPT**

Reason: 실제 파일명은 `reading_progress.json`, `paper_last_read.json`, `paper_ratings.json`이고 모두 `settings.outputs_dir` 아래에 저장된다. `rating`은 Obsidian에서 유용한 정적/사용자 메타데이터라 frontmatter 후보지만, progress/last_read는 잦은 UI-write 데이터다.

Recommendation: `rating`은 frontmatter에 흡수한다. `reading_progress`와 `last_read_at`은 JSON으로 유지하되 위치를 `papers/.paperflow_state/` 또는 `logs/` 등으로 분리해야 한다. 현재처럼 library content root에 글로벌 JSON을 두면 Obsidian vault에 잡음 파일이 보인다.

### 8. MCP 결과 `location` 문자열 호환성

Decision: **ACCEPT**

Reason: `JobRecord.location` 타입이 `Literal["outputs", "archives"]`이고 MCP `get_job_result()`가 `location`을 그대로 반환한다. `"papers"`를 추가하면 스키마 변경이다. 반대로 내부 `papers/`를 `"outputs"`로 라벨링하면 사용자와 Obsidian 모델에서 용어가 거짓말이 된다.

Recommendation: 새 location은 `"papers"`를 추가하는 breaking-compatible migration으로 가되, transition 기간에는 응답에 `location: "papers"`와 `legacy_location: "outputs"` 또는 `library_status`를 병기한다. 타입과 테스트를 명시적으로 갱신한다.

### 9. viewer 컨테이너 신규 볼륨 마운트가 plan에 절반만 있음

Decision: **ACCEPT**

Reason: viewer의 `BASE_DIR=/data` 기준으로 `./papers:/data/papers`는 맞지만 converter에도 `/app/papers` 마운트가 필요하다. Claude의 1번과 중복되지만 운영상 별도 MUST로 유지할 가치가 있다.

Plan change: `docker-compose.yml`에서 converter/viewer 둘 다 `papers`를 마운트하고, transition 기간에는 `outputs`도 read-only 또는 read/write fallback으로 유지할지 결정해야 한다.

### 10. frontmatter primary 정의 모호

Decision: **ACCEPT**

Reason: plan 본문은 "primary Markdown files" 전체에 쓰라고 하고 Open Decisions는 단일 primary 여부를 다시 묻는다. 그대로 구현하면 Dataview에서 `type: paper`가 같은 논문에 여러 번 나타날 위험이 있다.

Recommendation: Obsidian primary note는 단일 파일로 정한다. 추천 primary는 `*_ko.md`이고 없으면 영문 `*.md` fallback이다. 나머지 변종에는 `type: paper-variant`, `paperflow_variant: en|ko_explained|en_explained`처럼 구분하거나 PaperFlow-managed minimal frontmatter만 넣되 `type: paper`는 넣지 않는다.

### 11. title frontmatter와 폴더명/파일명 sync 정책 없음

Decision: **ACCEPT**

Reason: `sanitize_folder_name()`은 폴더명을 잘라내고 정리하지만 frontmatter `title`은 원문 제목이어야 한다. Obsidian에서 파일명과 `title`이 다를 수 있으므로 alias/link 정책이 필요하다.

Recommendation: `title`은 원본 제목, `aliases`에는 sanitized folder name, original filename, Korean title이 있으면 추가한다. 폴더명은 stable storage key로 취급하고 title source of truth는 `paper_meta.json`/frontmatter이다.

### 12. migration dry-run 검증 방식 부재

Decision: **ACCEPT**

Reason: plan은 `--dry-run`과 report만 말하고 사용자 confirm, post-check, 실패 기준이 없다. 이 작업은 대량 이동과 YAML rewrite를 포함하므로 dry-run -> 사용자 승인 -> 실행 -> post-check가 필수다.

Plan change: dry-run report는 move map, collision, permission problem, invalid YAML, root-owned folder, expected frontmatter diff count를 포함해야 한다. real run은 dry-run report id 또는 `--yes --from-report` 같은 확인 장치를 요구해야 한다.

### 13. 동시성/락 정책 부재

Decision: **ACCEPT**

Reason: converter/watch, viewer archive/restore/delete, MCP reconcile/cancel이 같은 폴더 집합을 다룬다. 현재 plan에는 migration 중 프로세스 중지나 app-level maintenance mode가 없다.

Recommendation: migration 실행 전 `docker compose stop paperflow-converter paperflow-viewer` 또는 최소 converter 중지를 요구한다. 더 나은 방식은 migration lock file(`logs/library_migration.lock`)을 두고 viewer mutating API와 MCP submit/cancel을 거부하도록 하는 것이다.

### 14. `papers` 1순위 / `outputs` 2순위 fallback의 dual-source 진단 문제

Decision: **ACCEPT**

Reason: 같은 folder name 또는 같은 `paper_meta.original_filename`이 `papers/`와 `outputs/`에 동시에 있을 수 있다. 우선순위만 두면 중복이 숨고 archive/restore/delete가 다른 copy를 건드릴 수 있다.

Recommendation: migration dry-run에서 duplicate folder name, duplicate `original_filename`, duplicate `source_url_original`, duplicate title을 검사하고 hard fail해야 한다. Runtime fallback도 conflict 발견 시 한쪽을 조용히 선택하지 말고 error 또는 diagnostics를 반환해야 한다.

## Claude가 놓친 부가 항목

### 15. 백업·롤백 전략이 "outputs 보존"만으로는 부족

Decision: **ADD / MUST**

Reason: plan은 "Never delete outputs"라고 하지만 실제 migration은 move와 Markdown rewrite를 수행한다. `outputs/`에서 `papers/`로 이동한 뒤 frontmatter rewrite가 실패하면 원래 경로, 수정 전 Markdown, global JSON 상태를 복원할 방법이 필요하다.

Required plan change:

- migration manifest 작성: source path, dest path, files rewritten, backups created, old/new checksums.
- real run 전 `papers/.migration-backups/<timestamp>/` 또는 외부 backup dir에 Markdown 원본을 보존.
- `--rollback <manifest>` 명령을 요구.
- rollback은 moved folders를 되돌리고 rewritten Markdown을 backup에서 복원해야 한다.

### 16. 권한·소유권 정책

Decision: **ADD / MUST**

Reason: 실제 `outputs/`와 `archives/` 하위 다수 폴더가 `root:root` 소유다. 현 사용자로 frontmatter 삽입, folder move, backup 생성이 실패할 수 있다.

Required plan change:

- dry-run에서 write permission, owner/group, chmod/chown 필요 여부를 검사.
- Docker가 root로 쓴 산출물에 대한 소유권 정상화 방안 명시: 예를 들어 migration 전 `sudo chown -R $(id -u):$(id -g) outputs archives papers` 또는 컨테이너 `user:` 설정 검토.
- 권한 오류는 partial migration 전에 hard fail.

### 17. 테스트 픽스처 영향

Decision: **ADD / MUST**

Reason: `viewer/tests/conftest.py`는 `outputs`, `archives`, `newones`, `logs`만 만든다. MCP 테스트 다수는 `settings.outputs_dir`와 `location == "outputs"`를 assert한다. plan의 test phase는 새 테스트만 나열하고 기존 fixture/test rewrite 비용을 명시하지 않는다.

Required plan change:

- conftest에 `papers/`와 legacy `outputs/` 둘 다 포함.
- `JobRecord.location` 타입 확장 테스트.
- 기존 outputs 우선순위 테스트를 papers 우선순위 테스트로 갱신하되 legacy fallback 테스트를 별도 유지.

### 18. UI i18n 및 사용자 가시 텍스트

Decision: **ADD / SHOULD**

Reason: templates에는 "Unread", "Archived", "Archive", "Restore", "in outputs/archives" 식 표시가 박혀 있다. plan의 UI model은 상태 탭을 바꾸지만 라벨/문구 변경 범위가 없다.

Required plan change:

- 탭: `Unread`, `Reading`, `Read`, `Archived` 추가.
- card/list action: `Mark reading`, `Mark read`, `Mark unread`, `Archive`, `Restore` 문구 정의.
- location 표시에서 `"outputs"`를 사용자에게 노출하지 않기.
- 한국어/영어 UI 토글이 있으므로 새 문구의 i18n key 또는 현재 방식에 맞춘 번역 정책 포함.

### 19. 외부 백업/스냅샷 정책

Decision: **ADD / SHOULD**

Reason: 사용자가 현재 `outputs/`를 Obsidian vault 또는 외부 backup target으로 보고 있을 수 있다. `papers/`로 이동하면 backup/include path가 바뀐다.

Required plan change:

- migration 전 "external sync/backup consumers" 체크리스트 추가.
- `outputs/` deprecation notice와 symlink compatibility option 검토: `outputs -> papers` symlink는 코드와 Obsidian에는 편하지만 dual-source confusion을 키울 수 있으므로 기본값은 비추천, 명시적 opt-in.

### 20. 로그·메트릭 수집

Decision: **ADD / SHOULD**

Reason: migration 후 실제로 `papers/`가 primary로 사용되는지, fallback `outputs/`가 얼마나 호출되는지 알아야 fallback 제거 시점을 판단할 수 있다.

Required plan change:

- fallback hit counter/logging 추가.
- migration summary: total active papers, migrated, skipped, archived repaired, permission failures, duplicate conflicts.
- post-migration health check endpoint 또는 script 추가.

### 21. security/path traversal threat model 확장

Decision: **ADD / MUST**

Reason: 기존 `safe_paper_dir()`와 MCP scan helper는 outputs/archives symlink escape를 막는다. `papers/` 추가 시 같은 containment 검사를 모든 helper에 반영해야 한다. plan은 symlink/escape 보안 요구를 테스트에 일부만 암시하고 있다.

Required plan change:

- `papers/`도 `_is_within`/`_safe_child_dir` 대상.
- duplicate scan, migration move, archive/restore, asset serving, zip export 모두 symlink escape 테스트 포함.

### 22. script ecosystem 업데이트

Decision: **ADD / SHOULD**

Reason: `scripts/backfill_doc_type.py`, `scripts/fix_ocr_math_batch.py`, `scripts/quality_baseline_report.py`는 outputs/archives를 직접 순회한다. plan은 새 migration script만 언급하고 기존 maintenance scripts 업데이트를 누락했다.

Required plan change:

- maintenance scripts가 `papers/`를 primary로 보고, transition 동안 `outputs/` fallback을 optional로 보도록 갱신.
- README 명령 예시도 `--outputs papers` 또는 새 `--library papers`로 바꾼다.

### 23. API compatibility for old URLs

Decision: **ADD / NICE**

Reason: viewer URL은 `/viewer/{paper_name}`라 folder name만 쓰므로 대체로 유지되지만, archive/restore 후 같은 이름이 `outputs`/`papers`/`archives`에 공존하면 URL resolve가 달라질 수 있다.

Required plan change:

- duplicate conflict 시 URL resolve policy 명시.
- 가능하면 stable `paperflow_id` 기반 route를 장기 과제로 추가.

### 24. CDN/HTTPS/sitemap/external links

Decision: **DEFER**

Reason: 현재 확인한 코드에는 sitemap 생성, CDN asset host, HTTPS canonical URL 생성 로직이 없다. 외부 링크는 `paper_url/source_url` 메타데이터와 MCP public base URL 정도다. 이 migration의 직접 위험은 낮다.

Plan note: "현재 해당 기능 없음. 공개 배포/정적 사이트 export를 도입하면 별도 검토" 정도면 충분하다.

## Q1/Q2/Q3 결정 권고

### Q1. frontmatter primary — `_ko.md` 단일 vs 모든 변종

Recommendation: **단일 Obsidian primary + variant metadata**

구체안:

- Primary note: `*_ko.md`가 있으면 그것이 Obsidian primary.
- `*_ko.md`가 없으면 영문 `*.md`가 fallback primary.
- Primary only:
  - `type: paper`
  - `reading_status`
  - `library_status`
  - `rating`
  - Obsidian Dataview 대상 필드
- Variants:
  - frontmatter를 넣더라도 `type: paper-variant`
  - `paperflow_primary: [[...]]` 또는 `paperflow_parent_id`
  - `paperflow_variant: en | ko_explained | en_explained`

Reason: 모든 변종에 `type: paper`를 넣으면 Dataview/Bases에서 한 논문이 2~4개로 중복 집계된다. Obsidian 사용 목적은 "논문 단위" 관리이므로 단일 primary가 맞다.

### Q2. location 문자열 — BREAKING ("papers") vs 호환 라벨링

Recommendation: **`location: "papers"` 추가 + transition compatibility**

구체안:

- `JobRecord.location`을 `Literal["papers", "outputs", "archives"]`로 확장.
- 신규 결과는 `"papers"` 반환.
- legacy fallback에서 `outputs/`를 찾은 경우만 `"outputs"` 반환.
- MCP/API 응답에 transition field 추가:
  - `library_status`
  - `legacy_location` 또는 `storage_location`
- UI는 location 문자열 대신 `library_status`와 `reading_status`로 버튼을 결정한다.

Reason: 내부가 `papers/`인데 외부에 `"outputs"`라고 계속 말하면 plan의 Obsidian/library 용어 개선 목표와 충돌한다. 다만 기존 records와 fallback을 위해 `"outputs"`는 한 release 이상 읽을 수 있어야 한다.

### Q3. reading_progress/ratings/last_read의 frontmatter 흡수 여부

Recommendation: **혼합 모델**

- `rating`: frontmatter로 흡수. Obsidian에서 조회/정렬 가치가 높고 변경 빈도가 낮다.
- `read_at`: frontmatter로 흡수. `reading_status: read` 전환 시 설정한다.
- `reading_progress`: JSON 유지. 스크롤에 따라 자주 쓰이며 Obsidian metadata로 계속 rewrite하면 git/vault noise가 크다.
- `last_read_at`: JSON 유지. viewer open 때마다 바뀌는 recency state이므로 frontmatter에 쓰면 파일 churn이 과하다.
- 저장 위치: 현재 `settings.outputs_dir`가 아니라 `papers/.paperflow_state/` 또는 `logs/reader_state/` 같은 명시적 state dir로 이동.

Reason: Obsidian에서 관리하고 싶은 stable metadata와 PaperFlow UI runtime state를 분리해야 한다.

## Recommended Implementation Order에 대한 지적

현재 순서:

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

Problems:

- **운영 preflight가 없다.** 실제 permission, duplicate, running converter, backup target 확인이 migration script 전후가 아니라 implementation 초기에 필요하다.
- **converter output 변경이 너무 늦거나 불명확하다.** listing/status보다 먼저 new writes가 `papers/`로 가는 경로와 watch cleanup을 정해야 한다.
- **state model 결정이 구현 순서에 없다.** Q1/Q2/Q3를 결정하지 않고 frontmatter helper/listing/MCP를 구현하면 테스트와 API shape가 흔들린다.
- **Docker/compose 변경 단계가 없다.** path config만으로는 converter/viewer 컨테이너가 같은 host `papers/`를 공유하지 않는다.
- **migration lock/maintenance mode가 migration 실행 직전에 없다.**
- **post-check와 rollback이 없다.** dry-run/real-run만으로는 대량 이동 실패를 다룰 수 없다.
- **existing tests rewrite가 숨어 있다.** fixture와 MCP tests의 `outputs` assertions를 갱신하는 단계가 필요하다.

Recommended order:

1. Decide and document Q1/Q2/Q3 plus archive/read semantics.
2. Add preflight design: permissions, duplicates, running services, backup/snapshot, rollback manifest.
3. Add path config: `papers_dir`, state dir, legacy `outputs_dir`, scan order, symlink safety.
4. Update Docker/compose/run_batch_watch/main_terminal output base and cleanup policy.
5. Add frontmatter helper with tests, including invalid YAML and variant primary policy.
6. Update viewer service listing/status/archive/restore/delete/get_stats and UI labels/actions.
7. Update MCP/zip/RAG/web_search/maintenance scripts lookup paths and location schema.
8. Update test fixtures and legacy fallback tests.
9. Add migration script with dry-run, manifest, backup, rollback, post-check.
10. Update README/Obsidian docs and operational migration runbook.
11. Stop services or enable maintenance lock; run dry-run.
12. User reviews dry-run report; run real migration.
13. Run post-check, viewer tests, MCP smoke, and Obsidian Dataview sanity check.
14. Keep `outputs/` fallback for at least one release with fallback-hit logging.
15. Remove fallback only after logs show no legacy hits and user confirms.

## Plan에 즉시 반영해야 할 변경 사항

### MUST

- Define Q1/Q2/Q3 in the plan body, not Open Decisions.
- Add converter-side changes: `main_terminal.py` output base, `check_duplicate_batch()`, final log message, `run_batch_watch.sh OUTPUTS_DIR` and cleanup.
- Add Docker changes for both services: `./papers:/app/papers` and `./papers:/data/papers`; state whether `./outputs` remains mounted during transition.
- Add `settings.papers_dir` and a separate state dir for reader runtime JSON.
- Add explicit scan order and conflict behavior: `papers -> outputs -> archives`, with duplicate/conflict hard fail in migration and diagnostics at runtime.
- Add frontmatter primary policy: one `type: paper` primary note, variants not counted as papers.
- Add progress/last_read/rating policy: rating/read_at frontmatter, progress/last_read JSON state.
- Add migration preflight, backup, manifest, rollback, dry-run approval, and post-check.
- Add permission/ownership preflight; root-owned folders must be detected before writes.
- Add migration locking or service-stop requirement.
- Add symlink/path traversal requirements for `papers/` across listing, serving, archive/restore, zip, migration.
- Add test fixture rewrite requirements and existing MCP/location tests update.

### SHOULD

- Add UI label/i18n plan for `Unread`, `Reading`, `Read`, `Archived`, and action labels.
- Add title/filename policy: original title in `title`, sanitized folder/file names in `aliases`.
- Add fallback-hit logging and migration metrics.
- Update maintenance scripts: `backfill_doc_type.py`, `fix_ocr_math_batch.py`, `quality_baseline_report.py`.
- Add external backup/sync checklist for users currently targeting `outputs/`.
- Add Obsidian Dataview examples that avoid variant duplication.

### NICE

- Add stable `paperflow_id` or route id to decouple URLs from folder names.
- Add optional compatibility symlink discussion (`outputs -> papers`) but keep it opt-in and discouraged by default.
- Add note that CDN/HTTPS/sitemap impacts are currently not applicable because the app has no sitemap/CDN path logic in the reviewed code.

## Final Position

Claude의 14개 항목은 모두 **ACCEPT**한다. 일부는 중복되지만 실제 코드 영향 범위가 넓어서 plan에 분명히 반영해야 한다. 특히 converter/write path, run_batch_watch cleanup, MCP `location` schema, frontmatter primary policy, progress/rating/last_read state split, migration rollback/permission/lock 정책은 PR 단계에서 "자연스럽게 해결"될 문제가 아니라 plan 단계의 결정 사항이다.

