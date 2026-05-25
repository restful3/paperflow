# 세션 핸드오프 — PaperFlow MCP 서버 v1 / v1.1
_최종 갱신: 2026-05-25 (세션 종료 시점)_
_업데이트: 2026-05-24 — **E2E 검증 완료** (arXiv 1706.03762 full pipeline + cache hit). v1 ship-ready._
_업데이트: 2026-05-24 — **DeepSeek-V3 E2E 에서 v1 Critical 버그 3개 발견** (translation timeout + self-duplicate skip + reconcile false-positive). 상세는 § "🐛 v1 버그" 참조._
_업데이트: 2026-05-24 — **v1.1 spec rev4 codex 4라운드 final approval** + **구현 16/16 task TDD 완료**, 96/96 tests pass, ship-ready. 무변경 제약 유지 (main_terminal.py / run_batch_watch.sh / config.json / papers.py 0줄). 상세는 § "✅ v1.1 구현 완료" 참조._
_업데이트: 2026-05-25 — **v1.1 실전 E2E 검증 완료** (DeepSeek-V3 2412.19437 60분 처리, fix #1\~#6 모두 검증, zip 에 `_ko.md` 162KB 포함). MCP 서버화 **already-shipped**. 사이드 작업: Attention/DeepSeek-V3 한국어 해설판 + HTML 변환. 상세는 § "✅ v1.1 실전 E2E (2026-05-25)" 참조._

## 🎯 목표
PaperFlow의 PDF→Markdown(+이미지)→번역 파이프라인을 MCP (Model Context Protocol) 도구로 노출. 외부 클라이언트가 PDF/URL 제출 → 비동기 처리 → zip 다운로드. **기존 PaperFlow 기능 무변경 보장** (`main_terminal.py` 0줄, `run_batch_watch.sh` 0줄, `config.json` 0줄).

## ✅ 완료

### 설계
- Spec **rev1 → rev5** (5라운드 codex 리뷰 끝에 `===CODEX_FINAL_APPROVAL===` 획득)
- 위치: `docs/superpowers/specs/2026-05-24-paperflow-mcp-server-design.md`
- 리뷰 기록 5개: `docs/reviews/2026-05-24-paperflow-mcp-server-codex{,-2,-3,-4,-5}.md`

### 구현
- Plan: `docs/superpowers/plans/2026-05-24-paperflow-mcp-server.md` (13 task, TDD)
- **13/13 task 완료, 40/40 테스트 그린**
- 17 커밋 (b91bf09 → 8c49494), 모두 main 브랜치
- 신규 파일: `viewer/app/services/{mcp_jobs,mcp_zip}.py`, `viewer/app/routers/mcp_router.py`, `viewer/tests/{conftest.py,test_mcp_*.py,test_papers_url_resolve.py,test_config_mcp.py}`, `viewer/pytest.ini`
- 수정 파일: `viewer/app/{config.py,main.py}`, `viewer/app/services/papers.py` (helper 추출 + `request_cancel_processing` lazy settings), `viewer/requirements.txt`, `docker-compose.yml`

### 배포
- `.env` 에 `MCP_API_KEY` (64자 hex) + `MCP_PUBLIC_BASE_URL=http://localhost:8090` 추가 (gitignored)
- Docker 이미지 재빌드 + `paperflow-viewer` 재시작 완료. `"StreamableHTTP session manager started"` 로그 확인
- Smoke test 통과:
  - 401 unauthorized
  - 200 + initialize handshake (server=paperflow, sdk=1.27.1)
  - tools/list → 5개 tool 확인
  - `list_jobs` tool 호출 → `{"jobs": []}` 정상 응답

### 최종 코드 리뷰
- Opus 모델로 전체 검토 — **ship-ready** 판정
- 발견된 3개 Minor (logging 누락 2개, late-stage cancel race 1개) — 비차단, v1.1 follow-up

## 🔄 진행 중

없음. v1 모든 task 완료.

## ✅ E2E 검증 (2026-05-24)

arXiv `https://arxiv.org/abs/1706.03762` (Attention Is All You Need) 로 full pipeline + cache hit 검증.

| # | 단계 | 결과 |
|---|---|---|
| 1 | `list_jobs` (sanity) | `{"jobs": []}` 정상 |
| 2 | `submit_paper` (url) | job_id 즉시 반환, status=downloading, expected_filename=`pfmcp-{job_id[:12]}-arxiv.org.pdf` |
| 3 | 폴링 (downloading → processing → complete) | 총 ~27분 (06:10:39 → 06:37:15). MinerU 변환 1분, metadata/web/duplicate ~30s, 번역 26 section ~25분 |
| 4 | `get_job_result` | paper_meta (title/authors/abstract/venue/DOI/categories) + files flags + download_url 반환 |
| 5 | zip 다운로드 (`include_pdf=false&include_translation=true`) | 694KB / 19 files (md_en + md_ko + 14 images + paper_meta.json + json + README.txt). 옵션 준수 (PDF 제외) |
| 6 | 같은 URL `submit_paper` 재호출 | **cached=true status=complete** 즉시 반환 (< 1초) |

**파이프라인 무변경 제약**: `main_terminal.py` / `run_batch_watch.sh` / `config.json` 0줄 수정으로 작동.

**유일한 관측치 (MCP 무관)**: Section 2 (427 chars) 번역에 607초 — translation LLM (`gpt-5.5 @ host.docker.internal:8317`) 일시 지연. 다른 section 은 2\~10초로 정상. MCP 서버 자체 이슈 아님.

## ⏭️ 다음 단계

### ✅ 완료 — Claude Code 에 paperflow MCP 등록 (2026-05-24)

실제 등록 명령 (HANDOFF 원본의 `--url` 옵션은 현재 CLI 에서 deprecated — URL 은 positional 인자):

```bash
cd /media/restful3/data/workspace/paperflow
MCP_KEY=$(grep ^MCP_API_KEY= .env | cut -d= -f2)
claude mcp add --transport http paperflow http://localhost:8090/mcp/ \
    --header "Authorization: Bearer $MCP_KEY"
```

**중요**: URL 끝의 슬래시 `/` 필수 — 없으면 307 redirect 발생 (Streamable HTTP 의 mount path 동작).

등록 확인: `claude mcp list` → `paperflow: http://localhost:8090/mcp/ (HTTP) - ✓ Connected`

### ✅ 완료 — E2E (2026-05-24)

위 "E2E 검증" 섹션 참조. 5/5 단계 통과, v1 ship-ready 재확인.

### Optional v1.1 follow-ups (최종 리뷰 발견)

- `_load_index` corrupt JSON quarantine 시 WARN 로그 추가
- `_periodic_mcp_cleanup` swallowed Exception 에 로그 추가
- `cancel_job(downloading)` 의 late-stage race: cancel + Stage 2 publish 동시 발생 시 PDF 가 publish 될 수 있음 (확률 낮음). lock 안으로 task.cancel() 옮기면 닫힘.
- `mcp.client.streamable_http` 로 5개 tool in-process 통합 테스트
- Multi-worker 사용 시 `flock(2)` enforce (현재는 single-worker 가정만 문서화)

### 🐛 v1 버그 — DeepSeek-V3 E2E 발견 (2026-05-24, **Critical**)

**증상**: 큰 논문 (DeepSeek-V3 2412.19437, 50p / 72 sections) submit → 번역 44/72 (57%)에서 멈춤. MCP는 `status=complete` 반환하지만 zip 에는 **`_ko.md` 누락** (영문 .md + meta + images 만).

**연쇄 메커니즘** (3 버그가 결합해서 사용자에게 잘못된 결과 노출):

1. **watch SIGKILL on translation timeout** (`run_batch_watch.sh`)
   - 청크별 timeout이 아닌 *PDF 전체 처리* 2400s (40min) hard timeout
   - DeepSeek-V3 처럼 큰 논문은 정상 처리에 40분 초과 가능 → SIGKILL
   - 결과: 영문 MD/metadata/images 만 outputs/ 에 남고 `_ko.md` 저장 전에 죽음 (번역은 마지막에 한 번에 저장)
   - **fix 방향**: timeout 값 환경변수화 + 청크별 timeout으로 분할, 또는 진행 중 중간 저장

2. **self-duplicate skip on retry** (`main_terminal.py` duplicate check)
   - SIGKILL 후 newones/PDF 남아있어 watch retry 1/2 시작
   - 새 폴더 `DeepSeek-V3 Technical Report-2` 임시 생성
   - duplicate check: 자기 자신의 첫 시도 결과 `DeepSeek-V3 Technical Report/` 를 같은 title duplicate으로 인식 → **"Skipping translation to save resources"** + `-2` 폴더 삭제
   - 결과: `_ko.md` 영영 생성되지 않음, 다음 retry도 동일 결과 (영구 미완)
   - **fix 방향**: duplicate check 시 기존 폴더의 `_ko.md` 부재 → "incomplete prior run" 으로 분기 (skip 대신 force reprocess)

3. **MCP reconcile false-positive complete** (`mcp_jobs.py`)
   - `expected_filename` 기반 reconcile 이 outputs/ 폴더 + .md 존재만으로 status=complete 판정
   - translation pipeline enabled 인데 `_ko.md` 없는 케이스 미체크
   - zip endpoint도 `include_translation=true` 요청에 `_ko.md` 누락 시 경고 없이 200 + 영문만 zip 반환
   - **fix 방향**:
     - reconcile: 서버 config에서 translation enabled 면 `_ko.md` 필수 → 없으면 status=error / partial
     - zip endpoint: `include_translation=true` 인데 `_ko.md` 없으면 422 또는 응답 헤더에 `X-Paperflow-Warnings: translation_missing`

**재현 조건**: 번역 청크 수가 많아 watch 2400s timeout 초과하는 모든 논문 (대략 50+ sections 또는 LLM 응답이 평균보다 느린 경우).

**우회 수단 (사용자 대응)**: 큰 논문은 일단 PDF 를 newones/ 에 직접 복사 (watch 처리) 후 다시 MCP submit (cached 경유). 또는 `force_reprocess=true` 후 timeout 늘림.

**관련 파일**:
- `run_batch_watch.sh` (timeout 정의)
- `main_terminal.py` (duplicate check, lines ~3050+)
- `viewer/app/services/mcp_jobs.py` (reconcile 로직)
- `viewer/app/routers/mcp_router.py` (zip endpoint 검증)

## ✅ v1.1 구현 완료 (2026-05-24)

### 설계
- **spec rev1 → rev4** (codex 4라운드 리뷰 끝에 `===CODEX_FINAL_APPROVAL===`)
- 위치: `docs/superpowers/specs/2026-05-24-paperflow-mcp-v1.1-bugfixes-design.md`
- 리뷰 기록: `docs/reviews/2026-05-24-paperflow-mcp-v1.1-bugfixes-codex{,-2,-3,-4}.md`

### Plan
- `docs/superpowers/plans/2026-05-24-paperflow-mcp-v1.1-bugfixes.md` (16 TDD task, 1714 줄)

### 구현 (subagent-driven-development)
- 16/16 task 완료, **96/96 tests pass** (v1 40 baseline + 56 new)
- 17 커밋 (2d702b7 → 4c3a34b), 모두 main 브랜치, push 완료
- 최종 Opus 4.7 review: 0 Critical + 0 Important + 4 Minor — **Ship-ready, Approved**

### 무변경 제약 (재확인)
- `main_terminal.py` — 0줄
- `run_batch_watch.sh` — 0줄
- `config.json` — 0줄
- `viewer/app/services/papers.py` — 0줄 (v1.1에서 새 helper 모두 mcp_jobs.py 내부에 둠)

### 주요 fix
| Bug | Fix 위치 | 핵심 변경 |
|-----|---------|----------|
| #1 watch timeout 2400s 짧음 | `docker-compose.yml` | `PROCESS_TIMEOUT_SECONDS=7200` env (run_batch_watch.sh 무수정) |
| #2/3/5 reconcile false-positive complete | `mcp_jobs.py` | `_classify_completion` 4-state verdict 도입, `reconcile_job` 양쪽 branch가 partial/missing/skip 명시 분기 |
| #4 cancel_job smart-rename 미정리 | `mcp_jobs.py` | `_cleanup_smart_renamed_paper` outputs-only helper + cancel_job dict response shape `{job_id, status, cleanup}` |
| #6 viewer config.json 부재 | `config.py` + compose | `MCP_REQUIRE_TRANSLATION` env (config.json mount 추가 안 함) |
| zip endpoint stale 200 | `mcp_router.py` | `get_job` → `reconcile_job` 한 줄 |

### 새 helper (모두 mcp_jobs.py 내부)
- `_is_safe_direct_child(base, candidate)` — symlink escape 가드 (RuntimeError 포함)
- `_paper_has_ko_md(paper_dir)` — tri-state (True/False/None)
- `_scan_outputs_dir_only(expected_filename)` / `_scan_archives_dir_only(...)`
- `_find_metadata_match_in_dir(base, expected_filename)` — paper_meta.json read-only
- `_resolve_completed_candidate(expected_filename)` — strict 4-step: outputs metadata → outputs FS → archives metadata → archives FS
- `_paper_dir_for(name, location)`
- `_classify_completion(expected_filename, _precomputed=None)` — verdict 매트릭스

### 사용자 recovery 흐름 (v1.1 정착)
부분 처리된 잡 발견 시:
1. `get_job_status(job_id)` → status=error + 안내 메시지
2. `cancel_job(job_id, delete_file=true)` → outputs/{paper_dir}/ 정리 + newones/PDF 정리
3. `submit_paper(input_type, source, force_reprocess=true)` → 깨끗한 재처리

### Minor (v1.2 backlog, 비차단)
- `_classify_completion` 반환 타입을 `Literal[...]` 로 정밀화 (현재 `str`)
- 두 reconcile branch 의 `translation_missing` 에러 메시지 중복 — 모듈 상수로 DRY
- `cancel_job` 의 newones PDF unlink 실패가 cleanup.warning 에 미반영
- 사전 존재 test isolation 이슈 (`.env` 가 monkeypatch 보다 우선) — v1.1 이전부터 있음, 재현됨

### 운영 환경 검증
- `docker compose exec paperflow-converter sh -lc 'echo $PROCESS_TIMEOUT_SECONDS'` → 7200 ✓
- `docker compose exec paperflow-viewer sh -lc 'echo $MCP_REQUIRE_TRANSLATION'` → true ✓
- `curl -sI -H "Authorization: Bearer $MCP_KEY" http://localhost:8090/mcp/` → 200/405 (정상) ✓
- DeepSeek-V3 retry E2E → **2026-05-25 완료** (아래 § "✅ v1.1 실전 E2E" 참조)

## ✅ v1.1 실전 E2E (2026-05-25) — DeepSeek-V3 retry

arXiv `2412.19437` (DeepSeek-V3 Technical Report, 50p / 72 sections) 를 MCP recovery flow 로 재처리. v1.1 모든 fix 가 실전에서 검증됨.

### Recovery flow (사용자 가이드 확인용)
1. `get_job_status(8bea5129)` → `status=error: paper folder no longer present (archived or deleted externally)` ⇒ **v1.1 reconcile 정상 동작** (v1 의 false-positive complete 를 재분류) ✅
2. `cancel_job(8bea5129, delete_file=true)` → `{job_id, status=error, cleanup:{attempted=false, deleted_path=null, warning=null}}` (폴더 부재로 cleanup 불필요) ✅
3. `submit_paper(url=https://arxiv.org/abs/2412.19437, force_reprocess=true)` → `job_id=afa87423-c843-44e2-8900-ab9889f4a80d`, status=downloading 즉시 반환 ✅

### 처리 결과
| 항목 | 값 |
|---|---|
| 처리 시간 | **60분** (11:56:13 → 12:56:24 UTC), SIGKILL 없음 |
| 최종 status | `complete` (false-positive 아님 — v1.1 reconcile 검증) |
| `_ko.md` | 162,457 bytes / 1,134 lines / 74 headers / 한글 OK |
| `_en.md` | 147,532 bytes |
| zip | HTTP 200, 2.87 MB, 43 files (md_en + md_ko + 38 img + meta + README) |
| `include_pdf=false` | 준수 |
| `files.md_ko` (get_job_result) | `true` |

### v1.1 fix 실전 검증 매트릭스
| Fix | 실전 검증 결과 |
|-----|---|
| **#1** `PROCESS_TIMEOUT_SECONDS=7200` | 60분 처리에도 SIGKILL 없음 — v1 의 2400s 한계 돌파 ✅ |
| **#2/3/5** `_classify_completion` + reconcile 4-state | stale job `8bea5129` 의 폴더 부재를 `status=error` 로 정확히 재분류 ✅ |
| **#4** `cancel_job` dict response + outputs-only cleanup | `{job_id, status, cleanup}` dict 반환, 폴더 부재시 `attempted=false` ✅ |
| **#6** `MCP_REQUIRE_TRANSLATION=true` env | translation 정상 완료 후 complete 진입, `files.md_ko=true` ✅ |
| zip endpoint `get_job → reconcile_job` | 200 + 모든 예상 파일 + README.txt 옵션 명기 ✅ |

### 사이드 작업 (이번 세션, MCP 와 별개)
- **한국어 해설판 작성** (`paper-explainer-korean` 스킬 호출):
  - `outputs/Attention Is All You Need/Attention Is All You Need_ko_explained.md` (67 KB / 816 lines / 56 headers, 1.42× 원문)
  - `outputs/DeepSeek-V3 Technical Report/DeepSeek-V3 Technical Report_ko_explained.md` (165 KB / 2,396 lines / 201 headers, 1.02× 원문)
  - 비유 시스템: 도서관 사서(Attention), 종합병원 전문의 풀(MoE), 도서관 카탈로그 카드(MLA), 양방향 컨베이어(DualPipe), 시계바늘(Positional Encoding) 등
  - 원문의 모든 절·소절·수식·표·이미지·참고문헌 보존, 풀이만 보강
- **HTML 변환** (`md-to-html` 스킬 호출, Quarto):
  - `*_ko_explained.html` 두 편 (2.4 MB / 4.7 MB) — self-contained, 이미지 base64 임베드, cosmo theme, KaTeX 수식
- 파일들은 모두 `outputs/` (gitignored) 에 보존, git 노이즈 없음

### 실측된 MCP 사용 패턴 (사용자가 향후 참고용으로 확인된 사실)
- **submit_paper 입력**: `url` (arXiv·일반 URL, HTML 페이지는 chromium fallback 으로 PDF 변환) 또는 `file` (base64 PDF). HTML 로컬 파일은 직접 지원 없음 — URL 화 또는 PDF 선변환 필요.
- **실측 처리 시간**:
  - Attention Is All You Need (15p) ≈ 27분
  - DeepSeek-V3 (50p / 72 sections) ≈ 60분
  - 대부분 시간은 번역 단계 (config.json 의 `translate_to_korean=true` 일 때).
- **MCP 서버 등록 (Claude Code)**: `claude mcp list` → `paperflow: http://localhost:8090/mcp/ (HTTP) - ✓ Connected`. 같은 세션에서 5개 tool 모두 직접 호출 확인됨 (`list_jobs`, `get_job_status`, `submit_paper`, `cancel_job`, `get_job_result`).

## 🧠 대화에만 있던 핵심 컨텍스트

### 설계 결정
- **per-request `translate`/`web_search` 옵션 제거** (Round 1 critical): `config.json` 은 전역이고 `main_terminal.py` 가 시작 시 한 번 읽음. per-job 옵션은 watch/배치 변경 없이는 불가능 → 무변경 제약과 충돌. 대신 서버 전역 config 따름.
- **`include_pdf`/`include_translation` 은 download 옵션으로만** (submit 옵션에서 제거): zip 구조에만 영향, 파이프라인 무관.
- **`pfmcp-{job_id[:12]}-{slug}.pdf` 파일명**: 같은 초 동시 submit 시 충돌 방지 + 기존 arXiv `web-` guard 와 자동 분리.
- **2단계 publish (cancel race 차단)**: Stage 1 `_write_part_file` 은 sync `def` (asyncio.to_thread 가 받는 callable), Stage 2 `_atomic_publish_part` 는 lock 안에서 status 재확인 후 호출. async def 면 to_thread 가 coroutine object 만 반환하고 실행 안 됨 — Round 4 high 버그.
- **URL submit 비동기 다운로더**: tool call 안에서 동기 다운로드 (35\~60초) 하면 MCP timeout 위험. submit 은 status="downloading" 즉시 반환, `_download_and_publish` 가 `asyncio.to_thread(papers._resolve_url_to_pdf_bytes)` 로 blocking I/O 처리.
- **ASGI wrapper for `/mcp` auth**: FastAPI `Depends` 는 mount 된 sub-app 안 path 에 안 걸림 (공식 한계). `mcp.streamable_http_app()` 을 raw ASGI 함수로 감쌈 (Starlette internals 사후 변경 회피, Round 3 high 해결).
- **`FastMCP(streamable_http_path="/")`**: SDK 기본은 `/mcp` 라 우리가 `app.mount("/mcp", ...)` 하면 최종 URL 이 `/mcp/mcp` 가 됨. root 로 두면 mount path 만 (`/mcp`) 가 endpoint.
- **HTML fallback temp 파일은 `newones/.mcp_tmp/` 하위로**: watch 의 `find -maxdepth 1 -name "*.pdf"` 가 root .pdf 만 잡음. 하위 폴더면 chromium 임시 .pdf 가 미완성 상태에서 picked up 되는 race 방지.
- **`papers.request_cancel_processing` lazy settings import**: 모듈 레벨 import 는 conftest의 `_cfg.settings = Settings()` 교체를 못 봄. 테스트 격리 위해 함수 안 lazy import 로 변경 (mcp_jobs.py 전체 동일 패턴).
- **single-worker 가정**: uvicorn `--workers 1` (Dockerfile 기본값). 다중 worker 시 in-process asyncio.Lock 으로 부족 → MCP 거부해야 (현재 명시만 되어 있고 enforce 는 v1+).

### 발견
- MCP SDK 실제 패턴은 `mcp.server.streamable_http.StreamableHTTPSessionManager` 가 아니라 `FastMCP(...).streamable_http_app()` + Starlette `Mount` + lifespan delegation. 처음 spec 의 import path 가 틀려서 Round 2 에서 codex 가 잡음.
- `main_terminal.py` 는 `process_single_pdf()` 에서 단계별 실패를 잡아 `results[...] = "failed"` 로만 기록하고 계속 진행. 최상위 except 도 `raise` 없이 `write_processing_status(..., "error")` + `return False`. 처음 spec 에서 `raise` 추가하려던 건 watch 종료 코드 영향 줘서 제거.
- `find_processed_paper(original_filename=...)` 1차 매핑이 metadata 단계 실패 시 못 찾음 → reconcile fallback 으로 outputs/archives 하위 폴더 스캔 (`(dir / expected_filename).is_file()`) 추가. Round 2 high.
- `Stage 1 (.part write) + Stage 2 (os.replace)` 를 같은 `to_thread` 에 넣으면 cancel race — Round 4 high. 분리해서 Stage 2 만 coroutine + lock + status 재확인.
- 처리 중 stalled 감지는 `current_file != expected_filename` 조건 필수 — 같은 파일이면 그냥 processing 으로 진행 중인 것. Round 4 fix.

### 배제
- ~~`mcp_errors/{job_id}.json` 사이드카~~ — Round 3 에서 폐기. `JobRecord.error` + `processing_status.json.error` 만 사용.
- ~~`MCP_ALLOWED_ORIGINS` 기본값 permissive~~ — Round 3 medium. `MCP_PUBLIC_BASE_URL` + localhost 자동 derive 로 변경.
- ~~`main_terminal.py` except 블록에 사이드카 1줄 추가~~ — 초기 rev1 아이디어. converter 의 `processing_status.json.error` 가 이미 충분.
- ~~explainer (쉬운 설명판) MCP 노출~~ — v1 제외. Claude skill 로만 동작 중. v2 후보.
- ~~per-job pipeline 옵션 sidecar config~~ — `main_terminal.py` 변경 필요해서 무변경 제약과 충돌. v2 후보.

### 기타
- Codex 리뷰 워크플로우 (5라운드, `===CODEX_FINAL_APPROVAL===` 토큰): 매우 효과적. critical 5개 + high 11개 + medium 다수 발견, 모두 진짜 버그/약점. 향후 다른 spec 작업 시 동일 패턴 권장.
- subagent-driven-development 패턴 (implementer → spec reviewer → quality reviewer → fix → re-review) 도 효과적. fixture isolation 패턴 같은 미묘한 버그가 review 단계에서 잡힘.

## ⚠️ 클리어 전 주의 (2026-05-25 세션 종료 시점)

- **커밋 안 됨**: 이번 세션 **코드 변경 0줄** (MCP 서버는 이미 ship 됨). 새 산출물은 모두 `outputs/` (gitignored) 안:
  - `outputs/Attention Is All You Need/Attention Is All You Need_ko_explained.md` + `.html`
  - `outputs/DeepSeek-V3 Technical Report/DeepSeek-V3 Technical Report_ko_explained.md` + `.html`
  - 영문/한국어 원본 md, paper_meta.json, images, json, pdf 등도 outputs/ 안
  - 미트래킹 2건은 이전부터 존재 (이번 세션 무관): `REPORT_EXPLAINER_BACKFILL_2026-02-24.md`, `scripts/quality_baseline_report.py`
  - `.claude-home/` cache/log 잡음 — 무시
  - **unpushed commits: 0** (HEAD `3039ae2` origin/main 동기화)
- **백그라운드**:
  - **Docker 컨테이너 2개 실행 중** (`Up 19 hours`):
    - `paperflow_viewer` (포트 8090→8000, MCP 활성, `MCP_REQUIRE_TRANSLATION=true`)
    - `paperflow_converter` (`PROCESS_TIMEOUT_SECONDS=7200`)
    - 그대로 두면 됨 — 다음 세션에서 그대로 사용 가능
    - 끄려면: `cd /media/restful3/data/workspace/paperflow && docker compose down`
  - **백그라운드 Bash/Monitor task**: 모두 종료됨 (이번 세션의 Monitor `be2220758` 자연 종료)
- **미완료 todo**: 없음. 이번 세션의 task #1\~#5 모두 completed (현재 task list 비어 있음).

## 📂 관련 파일

### Specs / Plans / Reviews
- `docs/superpowers/specs/2026-05-24-paperflow-mcp-server-design.md` — 최종 spec rev5 (codex 승인)
- `docs/superpowers/plans/2026-05-24-paperflow-mcp-server.md` — 구현 plan (13 task, TDD)
- `docs/reviews/2026-05-24-paperflow-mcp-server-codex{,-2,-3,-4,-5}.md` — 5라운드 codex 리뷰 기록

### 구현 코드 (이번 세션 신규/수정)
- `viewer/app/services/mcp_jobs.py` (488 lines) — JobRecord, submit/reconcile/cancel/cleanup, _download_and_publish 2단계 publish
- `viewer/app/services/mcp_zip.py` (60 lines) — zip stream builder
- `viewer/app/routers/mcp_router.py` (225 lines) — FastMCP 5 tools + ASGI auth wrapper + zip endpoint
- `viewer/app/main.py` (80 lines) — app_lifespan + conditional MCP mount + lifespan cleanup
- `viewer/app/config.py` (127 lines) — MCP_* 4개 settings + mcp_enabled / mcp_allowed_origins_set properties
- `viewer/app/services/papers.py` — `_resolve_url_to_pdf_bytes` helper 추출 (line 207\~350), `request_cancel_processing` lazy settings import (line 1250)
- `viewer/tests/conftest.py`, `viewer/tests/test_{config_mcp,papers_url_resolve,mcp_jobs,mcp_zip,mcp_router}.py` (5 파일, 40 tests)
- `viewer/requirements.txt` — `mcp>=1.27,<2`, `pytest`, `pytest-asyncio` 추가
- `viewer/pytest.ini` — `asyncio_mode = auto`
- `docker-compose.yml` — paperflow-viewer 의 MCP_* 4 env vars 추가

### 무변경 (제약 검증)
- `main_terminal.py` — 0 줄
- `run_batch_watch.sh` — 0 줄
- `config.json` — 0 줄
- viewer 기존 25+ API endpoint — 미변경 (40 테스트 모두 그린)

### 운영 상태
- `.env` (gitignored): `MCP_API_KEY` (token_hex(32), 64자 hex), `MCP_PUBLIC_BASE_URL=http://localhost:8090` 추가
- Docker: `paperflow_viewer` 컨테이너 Up (port 8090→8000), HEAD `8c49494` baked in
- HEAD 위치: 8c49494 (origin/main 대비 +17 commits 가능성 있음 — push 여부는 사용자 결정)
