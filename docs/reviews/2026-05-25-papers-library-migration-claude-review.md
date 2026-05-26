# Claude의 비판적 검토 — Papers Library Migration Plan

날짜: 2026-05-25
대상 계획: `docs/superpowers/plans/2026-05-25-paperflow-papers-library-migration.md`
검토자: Claude (Opus 4.7, 1M ctx)

## 검토 방식

코드베이스의 실제 현황을 grep/read로 확인한 뒤, 계획이 충돌하거나 누락한 지점을 식별. 본 검토는 비판 위주이며, 계획의 큰 방향(폴더 모델 → frontmatter 모델, Obsidian 호환) 자체에는 동의함.

## 코드베이스에서 확인한 현재 사실

- `outputs/`/`archives/` 경로는 `viewer/app/config.py` `Settings.outputs_dir`/`archives_dir` 프로퍼티로 노출. 하드코딩된 문자열 `"outputs"`는 `main_terminal.py:2871` (`output_dir = os.path.join("outputs", base_name)`), `main_terminal.py:1397` (`check_duplicate_batch`), `main_terminal.py:3299` (로그 메시지), `run_batch_watch.sh` (`OUTPUTS_DIR="outputs"`), `docker-compose.yml` (converter `./outputs:/app/outputs`, viewer `./outputs:/data/outputs`).
- `viewer/app/services/papers.py` 내 location 필드는 `"outputs"`/`"archives"` 두 값을 사용 (`_paper_info`, `safe_paper_dir`, `_get_existing_papers_summary`, `get_paper_info`, `list_papers`).
- `viewer/app/services/mcp_jobs.py` 의 `_resolve_completed_candidate`는 outputs→archives 우선순위로 4단계 탐색하고 location 문자열도 동일. `_scan_outputs_dir_only`, `_scan_archives_dir_only` 양쪽 모두 존재.
- `viewer/app/routers/pages.py:53` 의 viewer 페이지는 `info["location"] if info else "outputs"`로 default가 `"outputs"`.
- `viewer/app/services/web_search.py:173` 와 `viewer/app/services/papers.py:723` docstring 등 다수 주석/문자열도 outputs/archives 명명 가정.
- `scripts/quality_baseline_report.py`, `scripts/fix_ocr_math_batch.py` 가 outputs/archives를 디렉터리 명으로 직접 사용.
- 컨테이너 안 경로: converter는 `/app/outputs`, viewer는 `/data/outputs`로 마운트가 비대칭. `BASE_DIR=/data` 환경변수는 viewer 측에만 설정.

## 비판적 검토 — 14개 항목

### A. 누락된 영역 (Plan에 없거나 부족)

**1) Docker 마운트 및 컨테이너 경로 변경이 누락**
- 계획 Phase 1은 `papers` 볼륨 추가만 언급. 그러나 `converter` 서비스도 `./outputs:/app/outputs`를 마운트하고 `main_terminal.py`가 `os.path.join("outputs", base_name)`로 컨테이너 내부 상대경로에 쓰기 때문에, converter에도 `./papers:/app/papers` 마운트 + 코드 변경이 필요. converter는 viewer와 달리 `BASE_DIR` 환경변수를 안 쓰고 cwd 상대경로를 사용함.
- 비대칭 마운트(converter `/app/...`, viewer `/data/...`)는 그대로 유지할 것인지, 통일할 것인지 결정 필요.

**2) `main_terminal.py` 의 출력 디렉터리 결정 로직 변경 누락**
- `process_single_pdf()`는 `output_dir = os.path.join("outputs", base_name)` 하드코딩. 신규 처리 결과를 `papers/`로 보내려면 이 한 줄을 환경변수 또는 config 기반으로 바꿔야 함. 계획 Phase 3은 "land in papers/"라고만 적었지 어디를 어떻게 바꿔야 하는지 명시 없음.
- `rename_output_directory()`는 `parent = os.path.dirname(old_output_dir)`를 신뢰하므로 parent만 정확하면 자동 이전. OK.
- `check_duplicate_batch()` 의 `for base_dir, location in [("outputs", "outputs"), ("archives", "archives")]` 는 새 폴더(`papers/`) 추가 + outputs 폴백 시 명시적 갱신 필요.

**3) `run_batch_watch.sh` 의 `OUTPUTS_DIR` 변수 처리 누락**
- watch 스크립트는 `OUTPUTS_DIR="outputs"`를 그대로 사용. 셸 측 변경 정책(예: 환경변수 우선)도 plan에 추가해야 일관성 보장.

**4) `chat_history.json` / `chat_chunks.json` 의 마이그레이션 시 행동 미정**
- 이 파일들은 paper 폴더 안에 있으므로 폴더 move와 함께 이동. 다만 `chat_chunks.json`은 RAG cache invalidation 정책상 frontmatter 추가/수정 시 자동 삭제할지(편집 시 `save_markdown()` 동작과 동일하게) plan이 정해야 함.
- Phase 6 "frontmatter 추가/수정"이 `chat_chunks.json` 삭제를 트리거할지 여부를 명시.

**5) `reading_status: reading` 상태 도입과 기존 reading_progress의 관계**
- 기존에 `viewer/app/services/papers.py` 에 reading progress 시스템(`get_all_progress/save_progress`, JSON 파일)이 존재. plan은 "reading" 상태를 신규 도입하면서, 기존 progress(0-100 %)와의 관계를 정의하지 않음. 두 가지 모델이 공존하면 UX·데이터 모순 발생.
- 옵션: (a) progress > 0 인 경우 자동으로 `reading`, (b) progress와 status를 독립 유지, (c) progress를 deprecate. plan은 (c)에 가까운데 명시 없음.

**6) Last-read 타임스탬프 처리 미정**
- `get_all_last_read`/`save_last_read` 또한 별도 JSON. `reading_status: read` 로 갱신 시 last_read도 갱신해야 하는가? 별도인가? 마이그레이션 시 last_read 기록을 `read_at`으로 옮길지 plan이 정의해야 함.

**7) `progress.json`/`ratings.json`/`last_read.json` 같은 글로벌 JSON 파일의 위치**
- 이들은 paper 폴더가 아닌 `BASE_DIR` 루트에 있다고 추정됨(읽지는 않았지만 함수 시그니처상). papers/로 이동 후에도 글로벌 JSON 키가 폴더명이므로 그대로 동작하지만, Obsidian 친화 모델로 가는 길이면 ratings도 frontmatter로 옮길지 plan이 답해야 함. 현재 plan의 frontmatter 키엔 `rating`이 없음 — 일관성 미흡.

### B. 모호 / 정밀화 필요

**8) MCP 결과 location 문자열 호환성**
- `_resolve_completed_candidate`는 `"outputs"`/`"archives"`를 location으로 반환. plan대로면 새 location 값은 `"papers"`가 자연스러우나, MCP 클라이언트가 `"outputs"`를 가정한 코드를 갖고 있을 수 있음. 호환성 결정 필요:
  - (a) location 문자열을 `"papers"`로 바꾸고 MCP 응답 스키마 BREAKING CHANGE 공지
  - (b) location 문자열은 `"outputs"`/`"archives"`로 유지하고, 내부적으로 `papers/` 폴더를 `"outputs"`로 라벨링 (호환 우선)
  - (c) location에 `"papers"` 신규 + outputs 폴백 정보를 메타로 병기

**9) viewer 컨테이너의 신규 볼륨 마운트가 plan에 절반만 있음**
- `- ./papers:/data/papers` 만 적혀 있는데 `BASE_DIR=/data` 하에서 `settings.papers_dir`은 `Path("/data") / "papers"`가 되므로 일치. 다만 converter 측 마운트가 plan에 없음 → 신규 처리 결과를 어디에 쓰는지 모순. 명시적으로 두 서비스 모두 마운트를 추가해야 한다고 적어야 함.

**10) frontmatter "primary" 정의 모호**
- "Prefer metadata from `paper_meta.json` when present" + "primary Markdown files: *.md, *_ko.md, *_explained.md, *_ko_explained.md" — 4개 모두에 frontmatter를 쓴다는 의미인가, 1개만에 쓴다는 의미인가? Open Decisions 두 번째 항목도 같은 미결정. 결론을 plan 본문에 적어야 구현이 명확해짐.
- 권장: `_ko.md` 또는 `_ko_explained.md`를 Obsidian "primary"로 단일 지정. 나머지는 frontmatter 미주입 또는 type:`paper-source`/`paper-explainer` 등 종속 키로 차별화. 그래야 Dataview "type=paper"가 중복 카운트되지 않음.

**11) Title을 frontmatter에 박을 때 폴더명/파일명과의 sync 정책 없음**
- 폴더명은 sanitize되어 80자 잘림. 그러나 frontmatter `title`은 원본일 가능성. Obsidian에서 노트 이름 vs Properties.title 가 어긋나면 검색/링크가 혼란. plan은 어느 쪽을 source of truth로 둘 것인지 정해야 함.
- 권장: `title` = 원본(sanitize 전), `aliases`에 폴더명을 넣어 Obsidian backlink과 호환.

**12) 마이그레이션 dry-run 결과의 검증 방식 부재**
- "write a migration report" 까지만 적혀 있고, 사용자가 그 보고를 어떻게 검증하고 confirm해야 다음 단계로 가는지 워크플로 부재. 위험한 대량 move 작업은 (a) dry-run, (b) 사용자 검토, (c) 실 실행, (d) post-check 의 4단계가 자명한 best practice.
- post-check: 이동 후 각 폴더의 paper_meta.json 무결성, frontmatter 삽입 결과, RAG cache 상태 일관성 확인.

**13) 동시성/락 정책 부재**
- watch 스크립트가 newones를 폴링하면서 converter가 papers/에 새 폴더를 만들고 있을 때, 사용자가 viewer에서 archive 버튼을 누르면 동일 폴더에 대해 두 프로세스가 동시에 작업. 현재 plan에 락/원자성 정책 없음. 최소한 "마이그레이션 실행 중 converter 중지" 같은 운영 지침은 README에 명시 필요.

### C. 위험 / 회귀 가능성

**14) "papers fallback 1순위, outputs fallback 2순위" 가 듀얼-소스 진단 문제 야기**
- 같은 folder name이 papers/와 outputs/에 동시에 존재할 수 있음 (잘못 이주, 부분 이주, 또는 외부 sync). MCP `_resolve_completed_candidate`처럼 우선순위로 결정해도, 사용자가 archive에서 restore할 때 papers/ vs outputs/ 둘 중 하나로 가야 함. plan은 restore destination을 `papers/`로 정의했지만 outputs/ 잔존 동안에는 "papers/에 동명 폴더가 있으면 어떻게?" 가 미정.
- 권장: dry-run 단계에서 outputs/와 papers/ 사이 중복 폴더명 발견 시 hard fail + 보고.

## 우선순위 권장 (Plan에 반드시 반영해야 할 변경)

1. **MUST**: Phase 1에 converter 컨테이너 마운트 + `main_terminal.py:2871` 출력 경로 변경 + `run_batch_watch.sh` 변수 정책 명시.
2. **MUST**: Open Decisions의 4개 항목을 plan 작성 시점에 결정해서 본문에 박을 것 (아니면 구현 PR이 의사결정 권한 없이 막힘). 특히 "primary markdown 1개" 와 "location 문자열 호환성"은 코드 변경 면적이 가장 큰 두 결정.
3. **MUST**: reading_progress / last_read / ratings 의 frontmatter 일원화 정책. 셋 다 글로벌 JSON으로 남길지, frontmatter로 옮길지, 일부만 옮길지. Obsidian 우선이라면 모두 frontmatter가 자연스러움 — 그러나 마이그레이션 코드 면적이 커짐.
4. **SHOULD**: dry-run → 사용자 confirm → 실행 → post-check 의 4단계 마이그레이션 워크플로 명시. 중복 폴더명 hard-fail.
5. **SHOULD**: title vs 폴더명 sync 정책 (`aliases` 활용).
6. **NICE**: 마이그레이션 실행 중 converter watch 중지 운영 지침.

## 합의 요청 (Codex에게)

위 14개 항목 중 어떤 것이 plan에 반드시 추가되어야 하고 어떤 것이 PR 단계에서 자연스레 해결되는지, 그리고 4개 Open Decisions에 대한 의견을 달라.

특히 다음 3개 결정에 대한 Codex의 입장을 요청:

- (Q1) frontmatter primary: `_ko.md` 단일 vs 모든 변종 sync
- (Q2) location 문자열 호환성: BREAKING vs 호환 라벨링
- (Q3) reading_progress/ratings/last_read의 frontmatter 흡수 여부

답변은 본 파일과 같은 디렉터리(`docs/reviews/`)에 저장.
