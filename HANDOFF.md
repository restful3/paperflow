# 세션 핸드오프 — PaperFlow MCP 서버 v1
_최종 갱신: 2026-05-24 (Asia/Seoul)_
_업데이트: 2026-05-24 — **E2E 검증 완료** (arXiv 1706.03762 full pipeline + cache hit). v1 ship-ready._
_업데이트: 2026-05-24 — **DeepSeek-V3 E2E 에서 v1 Critical 버그 3개 발견** (translation timeout + self-duplicate skip + reconcile false-positive). 상세는 § "🐛 v1 버그" 참조._

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

## ⚠️ 클리어 전 주의

- **커밋 안 됨**: 코드 변경 0건 (작업 결과물은 모두 main 에 커밋됨, b91bf09 → 8c49494). `.claude-home/` 의 cache/log 잡음만 미커밋 — 무시 가능.
- **백그라운드**:
  - **Docker 컨테이너 2개 실행 중**:
    - `paperflow_viewer` (포트 8090→8000, MCP 활성, "StreamableHTTP session manager started" 로그 확인됨)
    - `paperflow_converter` (3주 전 시작, 기존 watch loop)
    - 그대로 두면 됨 — 다음 세션에서 그대로 사용 가능
  - **tmux 창 `codex`**: 코덱스 인스턴스 5라운드 리뷰 후 idle 상태. `tmux kill-window -t paperflow:codex` 또는 그대로 둬도 OK
  - 백그라운드 Bash task 모두 완료됨 (코덱스 polling 작업들)
- **미완료 todo**: 없음. Plan task 13/13 완료. E2E 검증 완료 (5/5 단계 통과).

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
