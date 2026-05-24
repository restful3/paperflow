# PaperFlow MCP Server — Design Spec (rev3, post-codex Round 2)

**Version**: v1 (spec rev 3)
**Date**: 2026-05-24
**Status**: Draft (pre-implementation, awaiting user sign-off)
**Owner**: restful3
**Prior reviews**:
- `docs/reviews/2026-05-24-paperflow-mcp-server-codex.md` (Round 1)
- `docs/reviews/2026-05-24-paperflow-mcp-server-codex-2.md` (Round 2)

---

## Change Log (rev3 vs rev2 — addresses Round 2 codex review)

| 변경 | 이유 (Round 2 항목) |
|------|---------------------|
| `FastMCP(..., streamable_http_path="/")` 명시 | rev2 에서 미설정 → endpoint 가 `/mcp/mcp` 가 됨 (Round 2 high #1) |
| zip endpoint 인증을 `Depends(verify_mcp_key)` 단일화, "ASGI middleware 가 이미 처리" 주석 삭제 | rev2 자기모순 (Round 2 high #2) |
| `safe_paper_dir(paper_info["name"])` — 단일 인자 (실제 시그니처) | snippet TypeError (Round 2 high #3) |
| reconcile 에 **fallback 추가**: `find_processed_paper` 미스 시 outputs/archives 하위 폴더 중 `(dir / expected_filename).is_file()` 인 폴더 스캔 | metadata 단계 실패/skip 시에도 정상 산출물 인식 (Round 2 high #4) |
| **URL submit 비동기화**: submit 은 즉시 `status="downloading"` 반환, `asyncio.create_task` 가 다운로드 → publish → `status="queued"` 전이. cancel_job 이 downloading 상태도 처리 | URL submit tool call 안 동기 다운로드 35\~60초 timeout 위험 (Round 2 high #5) |
| `user_middleware.insert + build_middleware_stack()` 폐기 → **ASGI wrapper 함수** | Open Question 1 해소, 더 안전 (Round 2 high #6) |
| `RUN pip install --no-cache-dir 'mcp>=1.27,<2'` quote, 또는 `viewer/requirements.txt` 추가 | shell redirection 방지 (Round 2 신규 high #1) |
| lifespan 의 cleanup background task handle 보관 → 종료 시 cancel/await | task 누수 방지 (Round 2 medium #2) |
| `_resolve_url_to_pdf_bytes()` temp file 전략 명시: `tempfile.NamedTemporaryFile(dir=settings.newones_dir, suffix=".pdf")` 로 기존 file-based quality gate 보존 후 bytes 읽고 temp 삭제 | 기존 import_url_as_paper behavior 동일 (Round 2 medium #3) |
| `mcp_errors/{job_id}.json` 사이드카 **폐기**. error 는 `JobRecord.error` (mcp_jobs.json 내부) 만 사용. converter 에러는 `processing_status.json.error` | 용도 불명확 (Round 2 medium #4) |
| `MCP_ALLOWED_ORIGINS` 기본값 변경: `MCP_PUBLIC_BASE_URL` 의 origin + localhost 계열 (`http://localhost`, `http://127.0.0.1`) 자동 포함 | DNS rebinding 방어 MCP MUST (Round 2 medium #1) |
| Open Question 1 (middleware 안정성) 제거 — wrapper 채택으로 해소 | (Round 2 high #6) |

## Change Log (rev2 vs rev1)

| 변경 | 이유 |
|------|------|
| per-request `translate` / `web_search` 옵션 제거 | 현재 `main_terminal.py` 가 매 실행마다 전역 `config.json` 을 읽음. per-job 옵션은 watch/배치 변경 없이는 불가능. v1 "기존 무변경" 제약과 충돌 (codex critical #2) |
| `include_pdf` / `include_translation` 을 submit → download 옵션으로 이동 | 파이프라인에 영향 없고 zip 구조에만 영향. submit 단계에 둘 이유 없음 (codex medium #1) |
| `main_terminal.py` 의 `raise` 추가 → 제거 | 기존 `process_single_pdf()` 는 raise 안 함, `return False` + `write_processing_status(..., "error")`. raise 추가 시 watch 종료 코드 변경 위험. 대신 기존 status JSON 의 error 필드를 1차 소스로, 보조 sidecar 는 `logs/mcp_errors/{job_id}.json` (codex critical #1) |
| 파일명 충돌 → `pfmcp-{job_id12}-{slug}.pdf` | 같은 초 동시 submit 시 덮어쓰기. job_id prefix 로 고유성 보장 + 기존 `web-` arXiv guard 와 자동 분리 (codex critical #3, high #9) |
| `newones/` 직접 쓰기 → `.part` + `os.replace` | watch 5초 폴링이 partial PDF 집어감 (codex high #7) |
| FastAPI `router.mount(..., dependencies=)` → ASGI middleware | path operation dependency 가 mount 된 sub-app 에 안 걸림 (codex critical #4) |
| `mcp.server.streamable_http.StreamableHTTPSessionManager` → `FastMCP(...).streamable_http_app()` + Starlette `Mount` + lifespan | 실제 공식 SDK 패턴 (codex critical #5) |
| `mcp>=1.0` → `mcp>=1.27,<2` | SDK 최신 안정 버전 (codex medium #15) |
| `MCP_PUBLIC_BASE_URL` request 자동 추론 → v1 은 환경변수 필수 | MCP tool handler 컨텍스트에서 FastAPI Request 직접 접근 불가 (codex medium #14) |
| Origin 검증 추가 | MCP Streamable HTTP spec 의 MUST 요구사항 (DNS rebinding 방어, codex high #11) |
| `list_jobs` single-tenant 명시 | 다중 키 없음, 모든 caller 가 모든 job 봄 (codex medium #13) |
| `mcp_jobs.json` 손상 시 quarantine 정책 추가 | 부팅 시 corrupt JSON 처리 (codex medium #17) |

**유지된 결정**: 비동기 + job_id 폴링, 기존 watch 파이프라인 재사용, viewer 컨테이너 내장, MCP_API_KEY 인증, URL 기반 zip lazy 생성, explainer v1 제외.

---

## 1. Goal

PaperFlow 의 PDF→Markdown(+이미지)→번역 파이프라인을 **MCP (Model Context Protocol) 도구**로 노출. 외부 MCP 클라이언트(Claude Code, Claude Desktop 등)가 PDF 파일 또는 웹 URL을 보내면 기존 watch-mode 파이프라인이 처리하고, 결과(마크다운 + 이미지 + 선택적으로 번역본)를 zip 으로 다운로드.

**Non-Goals (v1)**

- per-request 파이프라인 단계 토글 (translate/web_search) — 전역 `config.json` 만 따름
- explainer 생성 (Claude skill 전용, Python 모듈화 v2)
- 페이퍼 조회/검색 (viewer 의 `/api/papers` 이미 존재)
- 진행률 server-push
- 다중 사용자/다중 키

---

## 2. Hard Constraints

1. **기존 PaperFlow 무변경**: `main_terminal.py`, `run_batch_watch.sh`, `config.json`, 공유 볼륨 구조, viewer 기존 25+ 라우터 동작 **모두 미변경**. `main_terminal.py` 코드 변경 0줄을 목표로 함.
2. **Opt-in 디폴트**: `MCP_API_KEY` 빈 값 → MCP ASGI mount + zip endpoint 모두 등록 안 됨 → 외부 노출 0
3. **GPU 단일 큐 유지**: 기존 converter 가 watch 로 직렬 처리. MCP 도 동일 큐에 합류, 경합 없음
4. **viewer single worker 가정**: 현재 `viewer/Dockerfile` 의 uvicorn 호출에 `--workers` 미지정 = 1 worker. 다중 worker 도입 시 startup 에서 MCP 거부 (config validation)

---

## 3. Architecture

```
┌──────────────────┐                    ┌────────────────────────────────────────┐
│  MCP Client      │   Streamable HTTP  │  paperflow-viewer (FastAPI single proc)│
│  (Claude Code/   │   POST/GET /mcp    │                                        │
│   Desktop)       │ ───────────────►   │  ┌──────────────────────────────────┐ │
│                  │   Bearer + Origin  │  │ ASGI middleware: verify_mcp_key  │ │
│                  │   check            │  │   + origin guard                 │ │
│                  │                    │  └──────┬───────────────────────────┘ │
│                  │                    │         │                              │
│                  │                    │  ┌──────▼───────────────────────────┐ │
│                  │                    │  │ mcp.streamable_http_app()        │ │
│                  │                    │  │ FastMCP("paperflow", ...)        │ │
│                  │                    │  │  tools: submit_paper /           │ │
│                  │                    │  │         get_job_status /         │ │
│                  │                    │  │         get_job_result /         │ │
│                  │                    │  │         cancel_job /             │ │
│                  │                    │  │         list_jobs                │ │
│                  │                    │  └──────┬───────────────────────────┘ │
│                  │                    │         │                              │
│                  │   GET /api/mcp/    │         ▼                              │
│                  │   jobs/{id}/zip    │  ┌──────────────┐  ┌──────────────┐  │
│                  │ ◄──────────────────│  │ mcp_jobs svc │  │ papers svc   │  │
│                  │   stream zip       │  │ (new)        │  │ (existing,   │  │
└──────────────────┘                    │  └──────┬───────┘  │  no change)  │  │
                                        │         │          └──────────────┘  │
                                        │  reads/writes                        │
                                        │  ▼                                   │
                                        │  /data/logs/mcp_jobs.json (new)      │
                                        │  /data/logs/processing_status.json   │
                                        │  /data/newones/{<name>.part →        │
                                        │                pfmcp-<j>-<s>.pdf}    │
                                        │  /data/outputs/<paper>/ (read only)  │
                                        └────────────────────────────────────────┘
                                                       ▲
                                                       │ same shared volumes
                                                       │
                                        ┌────────────────────────────────────────┐
                                        │  paperflow-converter (UNCHANGED)       │
                                        │  run_batch_watch.sh                    │
                                        │   - watches newones/*.pdf              │
                                        │   - writes processing_status.json      │
                                        │   - produces outputs/<paper>/          │
                                        │  main_terminal.py — 0 line changes    │
                                        └────────────────────────────────────────┘
```

### 3.1 Execution Model

- **비동기 + job_id 폴링**: MCP 클라이언트 timeout 회피
- **기존 watch 파이프라인 재사용**: 코드 중복 0, GPU 직렬 큐 유지, converter 코드 무변경
- **URL 기반 zip 다운로드**: 큰 파일 대응, lazy 생성

### 3.2 Data Flow

**Submit (URL) — 비동기 다운로더**
1. `submit_paper(input_type="url", source=url, options={force_reprocess?})`
2. URL 검증 (scheme/host basic check, ValueError on fail → job 미생성)
3. `force_reprocess=false` (기본): `find_processed_paper(source_url=url)` 조회. 히트면 즉시 `status="complete"` job 반환 (`cached=true`). 단 히트한 paper 의 `paper_meta.json.original_filename` 이 `web-` 로 시작하면 legacy page-capture 일 가능성 → 캐시 미스로 fallthrough
4. job_id 생성 (uuid4), expected_filename = `pfmcp-{job_id[:12]}-{slugify(host_or_title)[:40]}.pdf`
5. **즉시** `JobRecord` 작성: `status="downloading"`, `import_method=None` (확정 전). `logs/mcp_jobs.json` 에 기록 → 도구 반환
6. **백그라운드 task** (`asyncio.create_task(_download_and_publish(job_id, url, expected_filename))`):
   a. `_resolve_url_to_pdf_bytes(url)` 호출 → `(pdf_bytes, final_url, import_method)`. 실패 시 `JobRecord.status="error"`, error 메시지 저장, task 종료
   b. `newones/{expected_filename}.part` 에 write → `fsync(fileno)` → `os.replace(.part → .pdf)`
   c. `_write_source_sidecar(expected_filename, url)` 호출 (paper 폴더가 컨버터에 의해 생성된 뒤 `paper_meta.json.paper_url` / `source_url_original` 백필 가능)
   d. `JobRecord.status="queued"`, `import_method` 확정. (이제 watch 가 PDF 발견 → 처리 시작)
7. `{job_id, status: "downloading", cached: false, expected_filename}` 반환 (도구 호출은 수 ms 안에 끝남)
8. 다운로드 task handle 은 module-level dict `_active_download_tasks[job_id] = task` 에 보관 (cancel_job 이 접근, lifespan 종료 시 모두 cancel)

**Reverse-lookup**: paper 폴더가 완성된 뒤 MCP reconciler 는 두 단계로 매핑.
   - Primary: `find_processed_paper(original_filename=expected_filename)` (metadata 단계 성공 시 동작)
   - **Fallback**: outputs/ 와 archives/ 의 하위 폴더를 스캔해 `(folder / expected_filename).is_file()` 인 폴더 찾기 — metadata 가 disabled/failed/skipped 여도 PDF 가 출력 폴더로 이동만 되면 매핑 성공. 기존 cancel cleanup 도 동일 패턴 사용 (`papers.py:1310-1314`)

expected_filename 의 `pfmcp-{job12}-` prefix 가 fingerprint 역할 — 사용자가 파일 rename 하지 않는 한 안전. (rename 한 경우는 v1 미지원, 사용자 책임.)

**Submit (File) — 동기 publish**
- File 입력은 다운로드 단계가 없음 (bytes 이미 제공). 동기 처리:
  1. PDF base64 디코드 (200MB 초과 거부, magic byte `%PDF-` 검증)
  2. expected_filename = `pfmcp-{job_id[:12]}-{slugify(original_filename)[:40]}.pdf`
  3. `.part` → fsync → `os.replace` (수 ms)
  4. `JobRecord.status="queued"` 로 바로 시작, `cached=false` 반환
- duplicate check: `find_processed_paper(original_filename=source)` 도 시도 — 단 file 입력은 사용자별 의도가 다양해 캐시 적중률 낮음, 그래도 시도는 함

**Poll: reconcile_job(job_id)**

순서대로 검사:

1. `mcp_jobs.json` 에서 JobRecord 로드 → 없으면 None
2. 종료 상태(`complete|error|cancelled`) 이면 그대로 반환
3. status="downloading" 이면 `_active_download_tasks[job_id]` 가 살아있는지 확인. 없으면(viewer 재시작 등) → `status="error"` ("download interrupted, retry submit")
4. **Complete 매핑 (primary)**: `find_processed_paper(original_filename=expected_filename)` → 결과 있고 `paper_meta.json` mtime > `submitted_at` → `status="complete"`, `paper_name` + `location` 저장
5. **Complete 매핑 (fallback)**: primary 미스 시 outputs/ + archives/ 각 하위 폴더 스캔. `(dir / expected_filename).is_file()` AND `dir.stat().st_mtime > submitted_at` → `status="complete"`, paper_name = dir.name, location 설정. (metadata stage 가 skip/fail 해도 PDF 가 폴더로 이동만 되면 인식)
6. `processing_status.json` 로드:
   - `current_file == expected_filename` 이고 `stage not in ("idle","complete","error")` → `status="processing"`, stage/percent 반영
   - `current_file == expected_filename` 이고 `stage == "error"` → `status="error"`, `processing_status.error` 메시지 반영
   - `processing_status` mtime > 30분이고 stage 무변화 + 위 4,5 미히트 → `status="stalled"`
7. 위 어디에도 안 잡히면 `newones/{expected_filename}` 존재 → `status="queued"`. 미존재 → `status="error"` ("file disappeared from queue with no output" — 비정상 시나리오, 사용자가 viewer UI 에서 직접 삭제 등)

**Result**
1. `get_job_result(job_id, include_pdf=false, include_translation=true)` — status=complete 일 때만
2. paper_meta.json 핵심 필드 + files 요약 + `download_url` 반환
3. download_url: `{MCP_PUBLIC_BASE_URL}/api/mcp/jobs/{job_id}/zip?include_pdf=...&include_translation=...`

**Download** (`/api/mcp/jobs/{job_id}/zip`)
1. ASGI middleware 가 Bearer 검증 (MCP 와 동일 키)
2. job 조회 → status != complete → 404
3. `safe_paper_dir(paper_name)` 로 outputs/ 또는 archives/ 재해석 (paper_dir 경로 직접 저장 안 함)
   - 폴더 미존재 → 410 Gone + job → error 마킹 + 에러 메시지 "paper deleted after completion"
4. zip stream 생성 (Lazy):
   ```
   {slug}.zip
   ├── README.txt                  # 입력/처리시각/옵션
   ├── paper_meta.json
   ├── {slug}.md                   # 영문 (always — 없으면 404)
   ├── {slug}_ko.md                # include_translation=true 이고 존재 시
   ├── {slug}.pdf                  # include_pdf=true 이고 존재 시
   └── images/*.jpeg
   ```

**Cancel**
1. `cancel_job(job_id, delete_file=true)`
2. status="downloading": `_active_download_tasks[job_id].cancel()` + `.part` 파일 cleanup (있으면) → `JobRecord.status="cancelled"`
3. status="queued"/"processing": 기존 `paper_svc.request_cancel_processing(filename=expected_filename, delete_file, force=True)` 호출
4. 종료 상태 (complete/error/cancelled): no-op + ok (멱등)
5. `JobRecord.status = "cancelled"`, completed_at 설정

---

## 4. Components

```
viewer/app/
├── main.py                        # [수정] mcp_router + lifespan delegation
├── config.py                      # [수정] MCP_* 4개 env 추가
├── routers/
│   ├── api.py                     # [무변경]
│   ├── pages.py                   # [무변경]
│   └── mcp_router.py              # [신규] FastMCP 정의 + Mount + middleware
└── services/
    ├── papers.py                  # [수정] _resolve_url_to_pdf_bytes 추출 (기존 함수에서 분리)
    ├── mcp_jobs.py                # [신규] JobRecord, submit/poll/cleanup/zip
    └── mcp_zip.py                 # [신규] zip 스트림 생성 (mcp_jobs 에서 분리)

viewer/Dockerfile                  # [수정] pip install 한 줄
viewer/tests/
├── test_mcp_jobs.py               # [신규]
└── test_mcp_router.py             # [신규]

main_terminal.py                   # [무변경, 0줄]
run_batch_watch.sh                 # [무변경, 0줄]
config.json                        # [무변경, 0줄]

docker-compose.yml                 # [수정] viewer 서비스에 MCP_* env 추가
```

### 4.1 `viewer/app/services/mcp_jobs.py` (~300 lines)

**책임**: Job 인덱스, 파이프라인 트리거, 상태 reconcile, cleanup
**의존**: papers.py (find_processed_paper, request_cancel_processing, safe_paper_dir, _resolve_url_to_pdf_bytes), config.py
**외부 호출 없음** (LLM/HTTP 직접 호출 없음 — 다운로드도 papers 위임)

```python
class JobOptions(BaseModel):
    force_reprocess: bool = False

class JobRecord(BaseModel):
    job_id: str                     # uuid4
    input_type: Literal["url", "file"]
    source: str                     # url 또는 원본 filename
    expected_filename: str          # pfmcp-{job12}-{slug}.pdf
    import_method: Literal["direct_pdf", "html_fallback", "site_transform", "file_upload"] | None
    options: JobOptions
    status: Literal["downloading", "queued", "processing", "complete", "error", "cancelled", "stalled"]
    stage: str | None
    percent: int                    # 0-100
    paper_name: str | None          # outputs/<paper_name> or archives/<paper_name>
    location: Literal["outputs", "archives"] | None
    error: str | None
    submitted_at: str               # ISO
    completed_at: str | None
    expires_at: str                 # submitted_at + MCP_JOB_TTL_DAYS

# Public (all async; module-level asyncio.Lock 보호):
async def submit_job(input_type, source, options, *, pdf_bytes=None) -> JobRecord
   # URL: status="downloading" 즉시 반환 + asyncio.create_task(_download_and_publish(...))
   # File: bytes 검증 + .part publish + status="queued" 동기 반환
async def get_job(job_id) -> JobRecord | None
async def reconcile_job(job_id) -> JobRecord
async def list_jobs(limit=50, status=None) -> list[JobRecord]
async def cancel_job(job_id, delete_file=True) -> JobRecord
   # status="downloading" 이면 _active_download_tasks[job_id].cancel() + partial cleanup
async def cleanup_expired_jobs() -> int   # 시작 시 + 매 1시간 background task
async def mark_paper_missing(job_id) -> JobRecord   # download 시 paper 폴더 사라진 경우
async def cancel_all_active_downloads() -> int   # lifespan shutdown 호출

# Private:
async def _atomic_write_index(jobs: dict[str, dict]) -> None
async def _load_index() -> dict[str, dict]
   # 손상 시 mcp_jobs.corrupt.<ts>.json 으로 quarantine, 빈 index 로 시작 + log WARN
async def _write_part_then_publish(pdf_bytes: bytes, dest: Path) -> None
   # .part write → os.fsync(fileno) → os.replace
def _build_expected_filename(job_id: str, slug_source: str) -> str
   # pfmcp-{job_id[:12]}-{safe_slug[:40]}.pdf
async def _download_and_publish(job_id: str, url: str, expected_filename: str) -> None
   # bg task: resolve url → publish → status transition. except → status="error". CancelledError → cleanup .part
async def _scan_outputs_for_filename(expected_filename: str) -> tuple[Path, str] | None
   # reconcile fallback: outputs/<*>/<expected_filename> or archives/<*>/<expected_filename>
```

**module-level state**:
```python
_active_download_tasks: dict[str, asyncio.Task] = {}   # job_id → task, cleared on done
_index_lock = asyncio.Lock()
```

**동시성**: 단일 module-level `asyncio.Lock`. 모든 public API 가 async. 인덱스 read-modify-write 는 lock 안에서 `_load_index → 수정 → _atomic_write_index` 한 번에. 다중 worker → MCP 거부 (config validation).

**영속성**: `logs/mcp_jobs.json` atomic replace (tmp → fsync → os.replace). viewer 재시작 후 진행 중 job 도 reconcile 로 복구.

### 4.2 `viewer/app/services/mcp_zip.py` (~120 lines)

**책임**: zip 스트림 생성만. 별도 파일로 분리해 단위 테스트 용이.

```python
def build_zip_stream(
    paper_dir: Path,
    *,
    include_pdf: bool,
    include_translation: bool,
    job_record: JobRecord,
) -> Iterator[bytes]:
    """zipfile.ZipFile + io.BytesIO chunk-by-chunk."""
```

### 4.3 `viewer/app/routers/mcp_router.py` (~200 lines)

```python
import contextlib, json
from mcp.server.fastmcp import FastMCP

from ..config import settings
from ..services import mcp_jobs

mcp = FastMCP(
    "paperflow",
    stateless_http=True,            # 단발 도구 호출, 세션 무관
    json_response=True,             # production 권장
    streamable_http_path="/",       # mount root 에 endpoint — 클라이언트는 {base}/mcp 로 접속
)

@mcp.tool()
async def submit_paper(input_type: Literal["url","file"],
                       source: str,
                       file_base64: str | None = None,
                       force_reprocess: bool = False) -> dict:
    options = mcp_jobs.JobOptions(force_reprocess=force_reprocess)
    pdf_bytes = base64.b64decode(file_base64) if file_base64 else None
    job = await mcp_jobs.submit_job(input_type, source, options, pdf_bytes=pdf_bytes)
    return {"job_id": job.job_id, "status": job.status,
            "cached": (job.status == "complete"),
            "expected_filename": job.expected_filename}

# ... 다른 4개 tool 동일 패턴

# ASGI wrapper: Bearer + Origin (Starlette internals 미변경, 가장 안전)
def _make_auth_wrapper(inner_asgi, api_key: str, allowed_origins: set[str]):
    async def authenticated(scope, receive, send):
        if scope["type"] != "http":
            await inner_asgi(scope, receive, send)
            return
        headers = {k.decode("latin1").lower(): v.decode("latin1")
                   for k, v in scope.get("headers", [])}
        # Bearer
        auth = headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != api_key:
            await _send_json(send, 401, {"error": "unauthorized"})
            return
        # Origin (DNS rebinding 방어, MCP MUST)
        origin = headers.get("origin")
        if origin and "*" not in allowed_origins and origin not in allowed_origins:
            await _send_json(send, 403, {"error": "origin not allowed"})
            return
        await inner_asgi(scope, receive, send)
    return authenticated

async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})

# Lifespan helper: caller (main.py) 가 호출 (mcp.session_manager.run() delegation)
@contextlib.asynccontextmanager
async def mcp_lifespan():
    async with mcp.session_manager.run():
        yield

# Mount helper: caller 가 호출
def mount_mcp(app, api_key: str, allowed_origins: set[str], path: str = "/mcp"):
    inner = mcp.streamable_http_app()
    wrapped = _make_auth_wrapper(inner, api_key, allowed_origins)
    app.mount(path, wrapped)
```

**왜 ASGI wrapper (not BaseHTTPMiddleware)**: Round 2 에서 codex 가 지적한 대로 `user_middleware.insert + build_middleware_stack()` 재호출은 Starlette internals 사후 변경이라 lifespan 시작 후 안정성 불확실. raw ASGI 함수로 감싸면 Starlette internals 미변경 → 가장 안전.

**왜 `streamable_http_path="/"`**: SDK 기본은 `/mcp` 이므로 우리가 `app.mount("/mcp", ...)` 하면 최종 URL 이 `/mcp/mcp` 가 됨. root 로 두면 mount path 만 (`/mcp`) 가 최종 endpoint.

**왜 ASGI 인증 + FastAPI Depends 분리**: FastAPI path operation dependency 는 mount 된 sub-app 안 path 에 안 걸림 (공식 한계). 따라서 `/mcp` 는 ASGI wrapper 가 책임, 별도 FastAPI route (`/api/mcp/jobs/{id}/zip`) 는 정상 `Depends(verify_mcp_key)` 사용. 두 경로 모두 동일 `MCP_API_KEY` 검증, 다른 매커니즘.

**왜 stateless_http**: 우리 도구들은 모두 단발 호출. 세션 상태 불필요. 단순화 + multi-worker 대비.

### 4.4 `viewer/app/main.py` (+~15 lines)

```python
import asyncio, contextlib
from contextlib import suppress
from .routers import mcp_router
from .services import mcp_jobs

@contextlib.asynccontextmanager
async def app_lifespan(app):
    cleanup_task: asyncio.Task | None = None
    if settings.mcp_enabled:
        async with mcp_router.mcp_lifespan():
            # startup cleanup (1회)
            await mcp_jobs.cleanup_expired_jobs()
            # periodic cleanup background
            cleanup_task = asyncio.create_task(_periodic_mcp_cleanup())
            try:
                yield
            finally:
                # 1) cancel periodic cleanup
                if cleanup_task is not None:
                    cleanup_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await cleanup_task
                # 2) cancel all active URL download tasks
                await mcp_jobs.cancel_all_active_downloads()
    else:
        yield

async def _periodic_mcp_cleanup():
    while True:
        try:
            await asyncio.sleep(3600)
            await mcp_jobs.cleanup_expired_jobs()
        except asyncio.CancelledError:
            raise
        except Exception:
            # never let exception kill the loop
            pass

def create_app() -> FastAPI:
    app = FastAPI(lifespan=app_lifespan)
    app.include_router(pages.router)
    app.include_router(api.router)

    if settings.mcp_enabled:
        # zip download endpoint (별도 router, MCP 비활성 시 미등록)
        from .routers.mcp_router import mcp_zip_router
        app.include_router(mcp_zip_router)
        # MCP ASGI mount (Bearer + Origin 은 wrapper 가 처리)
        mcp_router.mount_mcp(app, settings.MCP_API_KEY,
                              settings.mcp_allowed_origins_set)
    return app
```

**Lazy import**: `from .routers import mcp_router` 는 top-level 이지만 `mcp` 패키지 import 가 `MCP_API_KEY` 미설정 시에도 발생 — opt-in 0 노출 약속을 지키려면 이 import 자체를 `settings.mcp_enabled` 안으로 옮기는 게 더 엄격함. v1 은 일단 top-level import 허용, mount/router 등록만 조건부 (mcp 패키지가 viewer dependency 에 항상 포함되므로 import 실패 위험 없음).

### 4.5 `viewer/app/routers/api.py` 안의 zip endpoint → 별도 router

`api.py` 는 무변경. zip endpoint 는 `mcp_router.py` 안의 `mcp_zip_router` (`APIRouter(prefix="/api/mcp")`) 에 정의. **인증은 FastAPI `Depends` 로 단일화** (ASGI wrapper 는 `/mcp` mount 에만 적용; zip 은 별도 FastAPI route 라 wrapper 가 안 걸림):

```python
mcp_zip_router = APIRouter(
    prefix="/api/mcp",
    dependencies=[Depends(verify_mcp_key)],   # router 전체 Bearer 검증
)

async def verify_mcp_key(
    authorization: str = Header(default=""),
) -> None:
    if not authorization.startswith("Bearer ") or authorization[7:] != settings.MCP_API_KEY:
        raise HTTPException(401, "unauthorized")

@mcp_zip_router.get("/jobs/{job_id}/zip")
async def download_zip(
    job_id: str,
    include_pdf: bool = False,
    include_translation: bool = True,
):
    job = await mcp_jobs.get_job(job_id)
    if not job or job.status != "complete":
        raise HTTPException(404, "Job not complete or not found")
    # paper 폴더 재해석 — JobRecord 의 paper_name 만 신뢰, location 은 safe_paper_dir 가 결정
    paper_dir = paper_svc.safe_paper_dir(job.paper_name)   # 단일 인자, 실제 시그니처
    if not paper_dir:
        await mcp_jobs.mark_paper_missing(job_id)
        raise HTTPException(410, "Paper folder no longer exists")
    stream = mcp_zip.build_zip_stream(paper_dir,
        include_pdf=include_pdf, include_translation=include_translation, job_record=job)
    return StreamingResponse(stream, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job.paper_name}.zip"'})
```

**인증 분리 명확화**:
- `/mcp` mount: **ASGI wrapper** (`_make_auth_wrapper`) 가 Bearer + Origin 검증
- `/api/mcp/jobs/{id}/zip`: **FastAPI `Depends(verify_mcp_key)`** 가 Bearer 검증
- 두 경로 모두 동일 `settings.MCP_API_KEY` 사용. 동일 검증자 사용 불가 (서로 다른 ASGI 계층 — wrapper 는 raw scope, Depends 는 Request 객체) 라 코드 분기는 의도적.

### 4.6 `viewer/app/config.py` (+~10 lines)

```python
class Settings(BaseSettings):
    # ... 기존 필드 ...
    MCP_API_KEY: str = ""              # empty → MCP disabled
    MCP_JOB_TTL_DAYS: int = 7
    MCP_PUBLIC_BASE_URL: str = ""      # ex: http://localhost:8090 (REQUIRED if MCP enabled)
    MCP_ALLOWED_ORIGINS: str = ""      # comma-separated, empty=permissive (no Origin header is OK; with Origin must match)

    @property
    def mcp_enabled(self) -> bool:
        if not (self.MCP_API_KEY and len(self.MCP_API_KEY) >= 32):
            return False
        if not self.MCP_PUBLIC_BASE_URL:
            raise RuntimeError("MCP_API_KEY set but MCP_PUBLIC_BASE_URL missing")
        return True

    @property
    def mcp_allowed_origins_set(self) -> set[str]:
        """DNS rebinding 방어 (MCP MUST). 기본값: MCP_PUBLIC_BASE_URL origin + localhost 계열.
        env 가 명시되면 그것만 사용 (override). '*' 명시는 explicit opt-out 시에만."""
        if self.MCP_ALLOWED_ORIGINS.strip() == "*":
            return {"*"}
        explicit = {o.strip() for o in self.MCP_ALLOWED_ORIGINS.split(",") if o.strip()}
        if explicit:
            return explicit
        # default: derive from MCP_PUBLIC_BASE_URL + localhost
        defaults: set[str] = set()
        if self.MCP_PUBLIC_BASE_URL:
            from urllib.parse import urlparse
            p = urlparse(self.MCP_PUBLIC_BASE_URL)
            if p.scheme and p.netloc:
                defaults.add(f"{p.scheme}://{p.netloc}")
        defaults.update({
            "http://localhost", "https://localhost",
            "http://127.0.0.1", "https://127.0.0.1",
        })
        # Origin 헤더가 port 포함이면 직접 추가 권장 (env 로 override)
        return defaults
```

**`MCP_PUBLIC_BASE_URL` 필수화 이유**: tool handler 에서 FastAPI Request 직접 접근 불가 (FastMCP context 와 별개). reverse proxy 뒤 호스트 헤더 신뢰 불가. v1 은 명시 설정 강제.

### 4.7 `viewer/app/services/papers.py` 변경 (작은 refactor)

`import_url_as_paper()` 의 내부에서 "URL → PDF bytes" 부분만 추출:

```python
def _resolve_url_to_pdf_bytes(url: str) -> tuple[bytes, str, str]:
    """URL → (pdf_bytes, final_url, import_method).
    DOI resolve → site transformer → direct download → HTML fallback (chromium print-to-pdf).
    Raises ValueError on failure with concrete message.
    """
    # 1) DOI redirect resolve, site transformer 시도 (기존 papers.py 로직 그대로)
    # 2) 직접 PDF download — 성공하면 (bytes, final_url, "site_transform" | "direct_pdf") 반환
    # 3) HTML fallback (headless chromium print-to-pdf) — 임시 파일 필요:
    #    with tempfile.NamedTemporaryFile(dir=settings.newones_dir, suffix=".pdf", delete=False) as tf:
    #        tmp_path = Path(tf.name)
    #    try:
    #        subprocess.run([browser_bin, ..., f"--print-to-pdf={tmp_path}", url], ...)
    #        # 기존 quality gate (PyPDF2 page count + text length 검사) — 기존과 동일하게 file path 받음
    #        if not _passes_quality_gate(tmp_path): raise ValueError("low-quality PDF")
    #        return tmp_path.read_bytes(), final_url, "html_fallback"
    #    finally:
    #        tmp_path.unlink(missing_ok=True)
```

**기존 `import_url_as_paper()` 와의 호환성**:
- 기존 함수는 `newones_dir/<name>.pdf` 에 직접 쓰는 file-path 기반 흐름. MCP 의 `_resolve_url_to_pdf_bytes` 는 bytes 를 반환.
- 두 함수의 핵심 로직 (DOI resolve, transformer, fallback, quality gate) 은 **공통 inner helper** 로 추출해 둘 다 사용. file-vs-bytes 차이는 outer 에서만.
- `import_url_as_paper()` 는 내부에서 `_resolve_url_to_pdf_bytes(url)` 호출 후 `dest.write_bytes(bytes)` — 외부 호출자 동작 변경 없음.
- 단위 테스트로 회귀 방지 (기존 viewer URL import 흐름이 같은 결과 내는지 확인).

### 4.8 `main_terminal.py` 변경

**없음**. 0줄. 

기존 `processing_status.json.error` 필드를 MCP reconciler 가 읽음. 추가 사이드카 불필요. (당초 rev1 의 `last_error_<filename>.json` 아이디어는 컨버터 변경 필요해서 폐기. `processing_status.json` 의 error 필드를 1차 소스로 신뢰.)

### 4.9 `viewer/Dockerfile` 또는 `viewer/requirements.txt`

**Option A** (권장 — 기존 requirements 패턴과 일치):
```
# viewer/requirements.txt 마지막에 추가
mcp>=1.27,<2
```
Dockerfile 무변경 (기존 `pip install -r requirements.txt` 가 처리).

**Option B** (Dockerfile 직접 수정 시):
```dockerfile
RUN pip install --no-cache-dir 'mcp>=1.27,<2'
```
**Quote 필수** — shell form 에서 `<` 는 stdin redirection 으로 해석돼 깨짐.

---

## 5. MCP Tool Surface

### 5.1 `submit_paper`

```json
{
  "name": "submit_paper",
  "description": "PDF 또는 웹 URL을 PaperFlow 파이프라인에 투입. 비동기. 파이프라인 단계 (번역 등) 는 서버 전역 config.json 을 따름 — per-request 토글 미지원.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "input_type": {"type": "string", "enum": ["url", "file"]},
      "source": {"type": "string", "description": "url 또는 원본 파일명"},
      "file_base64": {"type": "string", "description": "input_type=file 일 때 PDF base64 (max 200MB)"},
      "force_reprocess": {"type": "boolean", "default": false}
    },
    "required": ["input_type", "source"]
  }
}
```

**Return**:
```json
{"job_id": "uuid", "status": "downloading|queued|complete", "cached": false, "expected_filename": "pfmcp-..."}
```

### 5.2 `get_job_status`

```json
{"name": "get_job_status",
 "inputSchema": {"type": "object",
                 "properties": {"job_id": {"type": "string"}},
                 "required": ["job_id"]}}
```

**Return**:
```json
{
  "job_id": "...",
  "status": "downloading|queued|processing|complete|error|cancelled|stalled",
  "stage": "converting|extracting_metadata|enriching|translating|verifying|null",
  "percent": 0,
  "error": null,
  "submitted_at": "ISO",
  "completed_at": null,
  "expires_at": "ISO"
}
```

### 5.3 `get_job_result`

```json
{"name": "get_job_result",
 "inputSchema": {
   "type": "object",
   "properties": {
     "job_id": {"type": "string"},
     "include_pdf": {"type": "boolean", "default": false},
     "include_translation": {"type": "boolean", "default": true}
   },
   "required": ["job_id"]
 }}
```

**Return** (status=complete only):
```json
{
  "job_id": "...",
  "paper_name": "Attention Is All You Need",
  "location": "outputs|archives",
  "paper_meta": {
    "title": "...", "authors": ["..."], "abstract": "...",
    "venue": "...", "year": 2017, "doi": "...", "categories": ["..."]
  },
  "files": {"md_en": true, "md_ko": true, "pdf": true, "images_count": 12},
  "download_url": "{MCP_PUBLIC_BASE_URL}/api/mcp/jobs/{job_id}/zip?include_pdf=false&include_translation=true",
  "expires_at": "ISO"
}
```

### 5.4 `cancel_job`

```json
{"name": "cancel_job",
 "inputSchema": {
   "type": "object",
   "properties": {
     "job_id": {"type": "string"},
     "delete_file": {"type": "boolean", "default": true}
   },
   "required": ["job_id"]
 }}
```

내부: `paper_svc.request_cancel_processing(filename=expected_filename, delete_file, force=True)`. 멱등.

### 5.5 `list_jobs`

```json
{"name": "list_jobs",
 "description": "Single-tenant. 인증된 MCP_API_KEY 보유자는 모든 job 을 봄.",
 "inputSchema": {
   "type": "object",
   "properties": {
     "limit": {"type": "integer", "default": 20, "maximum": 100},
     "status": {"type": "string", "enum": ["downloading","queued","processing","complete","error","cancelled","stalled"]}
   }
 }}
```

**Return**: `JobRecord` 배열 (submitted_at desc).

---

## 6. Error Handling

| 카테고리 | 처리 |
|---------|------|
| 입력 검증 실패 (잘못된 URL scheme, base64 fail, file > 200MB, magic byte mismatch) | `ValueError` → MCP `isError: true`, job 생성 안 함 |
| URL → PDF 변환 실패 (배경 task 안 모든 방법 시도 후) | 배경 task except → `JobRecord.status="error"` + 에러 메시지 저장 (도구 호출 자체는 이미 반환됨) |
| `newones/{name}.part` write 실패 (디스크 full) | 배경 task except → status="error" + `.part` cleanup |
| `.part → .pdf` rename 실패 | 위와 동일 |
| viewer 재시작이 downloading 중간에 발생 | 부팅 시 status="downloading" 인 job 발견 → status="error" ("download interrupted, retry submit") + 사용자가 force_reprocess 로 재시도 |
| cancel_job(downloading) | task.cancel() → CancelledError 핸들러가 `.part` cleanup → status="cancelled" |
| `mcp_jobs.json` 손상 부팅 | `_load_index` 가 quarantine (`mcp_jobs.corrupt.<ts>.json`) + 빈 인덱스 시작 + WARN 로그 |
| 컨버터 실패 (`processing_status.json.error` set) | reconcile 시 발견 → `status="error"` |
| 컨버터 stall (mtime > 30분 + stage 무변화) | `status="stalled"` (사용자 결정 대기, 자동 cancel 안 함) |
| viewer 재시작 중 progress 손실 | `mcp_jobs.json` + paper 출력물로 reconcile 복구 |
| job_id 미존재 | MCP `isError: true`, "job not found" |
| 동일 URL 동시 submit | 다른 job_id, 다른 expected_filename → 둘 다 처리 (파일명 충돌 없음 — 의도적 허용, 사용자 책임) |
| download 시 paper 폴더 삭제됨 | `safe_paper_dir` 미발견 → 410 Gone + job → error 마킹 |
| download 시 paper 폴더 archive 로 이동됨 | `safe_paper_dir` 가 archives 도 찾음 → 정상 처리 |
| TTL 만료 job 의 status/result/download 요청 | 410 Gone + 메시지 "job expired" |

---

## 7. Cleanup & TTL

- `cleanup_expired_jobs()`:
  - viewer 시작 시 1회 + 매 1시간 background task
  - `JobRecord.expires_at < now` 이고 status in (complete, error, cancelled) → 인덱스에서 삭제
  - **outputs/<paper>/ 은 절대 건드리지 않음** (viewer 의 기존 페이퍼 라이프사이클)
- processing/stalled 상태는 TTL 무시 (사용자 cancel 또는 reconcile 로 정리)

---

## 8. Testing

### 8.1 단위 테스트 `viewer/tests/test_mcp_jobs.py`

1. JobRecord pydantic 직렬화/역직렬화 라운드트립
2. 동시 submit (asyncio.gather 50개) → 인덱스 손상 없음, 50개 모두 고유 job_id + 고유 expected_filename
3. `find_processed_paper` URL hit (legacy `web-` 제외) → 즉시 complete
4. `force_reprocess=true` → 캐시 무시, newones 진입
5. URL resolve 실패 → 예외, job 미생성
6. file_base64 200MB 초과 → ValueError, job 미생성
7. file_base64 PDF magic byte 미스매치 → ValueError
8. `.part` → `.pdf` os.replace 동작 확인 (watch 가 partial 안 보는지)
9. stalled 감지 (status mtime 모킹)
10. cleanup: 만료 complete 삭제, 진행 중 보존
11. mcp_jobs.json 손상 (잘못된 JSON) → quarantine 후 빈 인덱스
12. reconcile: error sidecar 우선, 그 다음 outputs, 그 다음 processing_status
13. stale error sidecar 무시 (sidecar.occurred_at < job.submitted_at)
14. archive 이동된 paper 의 download → 정상 (`safe_paper_dir` 가 archives 찾음)
15. delete 된 paper 의 download → 410, job error 마킹

### 8.2 통합 테스트 `viewer/tests/test_mcp_router.py`

MCP SDK `mcp.client.streamable_http` 로 in-process 테스트:

1. `list_tools` → 5개 노출
2. Bearer 누락/잘못된 키 → 401
3. Origin 헤더가 `MCP_ALLOWED_ORIGINS` 와 불일치 → 403
4. submit_paper → get_job_status 시퀀스 (mocked converter)
5. cancel_job → request_cancel_processing 호출 (mock)
6. get_job_result without complete → error
7. download zip + include_pdf=true/false 조합

### 8.3 회귀 방지

- viewer 기존 25+ API 정상 (변경 0)
- watch 모드 PDF 처리 정상 (`main_terminal.py` 변경 0)
- `pytest viewer/tests/` 전체 그린
- MCP 비활성 (env 없음) 시: `/mcp` 404, `/api/mcp/jobs/.../zip` 404

### 8.4 E2E

- 실제 arXiv URL submit → 폴링 → zip 다운로드 → 압축 해제 확인
- 같은 URL 두 번째 submit → cached, < 1초
- Claude Code 등록 후 1회 흐름

---

## 9. Impact on Existing PaperFlow

| 컴포넌트 | 변경 | 영향 |
|---------|------|------|
| `main_terminal.py` | **0줄** | 0 |
| `run_batch_watch.sh` | 0줄 | 0 |
| `config.json` | 0줄 | 0 |
| `viewer/app/services/papers.py` | helper 함수 1개 분리 + 기존 함수가 그것 호출 | 외부 동작 동일, 단위 테스트로 회귀 방지 |
| `viewer/app/main.py` | lifespan + mount 조건부 추가 | MCP 비활성 시 동작 동일 |
| `viewer/app/config.py` | 4개 env 추가 | 기본값 빈 문자열, 동작 동일 |
| viewer 기존 라우터/템플릿 | 0줄 | 0 |
| Docker compose | viewer service env 4개 추가 (optional) | 빈 값이면 동작 동일 |
| 공유 볼륨 | `logs/mcp_jobs.json` 신규 (atomic replace 시 `.tmp` 도 같은 폴더). 기존 파일 미변경 | 0 |
| Dockerfile | pip install 1줄 | 이미지 크기 미미한 증가 |

---

## 10. Deployment

### 10.1 .env

```
MCP_API_KEY=<openssl rand -hex 32>            # 32+ char required
MCP_PUBLIC_BASE_URL=http://localhost:8090     # required when MCP enabled
MCP_JOB_TTL_DAYS=7                            # optional, default 7
MCP_ALLOWED_ORIGINS=                          # optional CSV, empty = permissive
```

### 10.2 Build & Register

```bash
docker compose build paperflow-viewer && docker compose up -d paperflow-viewer

claude mcp add paperflow --transport http \
    --url http://localhost:8090/mcp \
    --header "Authorization: Bearer $MCP_API_KEY"

# Claude Code 에서 /mcp 로 paperflow 확인
```

### 10.3 Security Notes

- v1 은 **single-tenant**: MCP_API_KEY 보유자는 모든 job 접근 가능
- `0.0.0.0` 바인드된 viewer 포트 8090 은 호스트 모든 네트워크 인터페이스에 노출 — 신뢰 네트워크 외부 노출 시 reverse proxy + TLS 필수
- Origin 검증은 DNS rebinding 방어용. localhost-only 배포는 `MCP_ALLOWED_ORIGINS=` 빈 값 (permissive) 도 무방, 외부 노출 시 명시 권장

---

## 11. Out-of-Scope (v2 후보)

- per-request 파이프라인 토글 (translate/web_search) — sidecar config 방식으로 `main_terminal.py` 변경 필요
- explainer 생성 모듈화 + `include_explained` 옵션
- 다중 사용자/다중 API key + owner_key_id 필터링
- SSE 진행률 push (폴링 제거)
- 부분 파일 다운로드 (md만, 이미지만)
- 페이퍼 조회 tool (search_papers, get_paper)
- 다중 viewer worker 시 분산 락 (fcntl.flock 또는 SQLite)
- OAuth 2.1 + RFC 9728 TokenVerifier 통합

---

## 12. Open Questions (구현 시 E2E 로 확인)

1. converter 가 `pfmcp-` 파일을 정상 처리하는지 (filename slug 가 metadata 추출에 끼치는 영향) — metadata extraction 은 PDF 내용 기반이라 무관할 가능성 높음, E2E 로 확인. 특히 `paper_meta.json.original_filename` 에 `pfmcp-...pdf` 가 그대로 보존되는지 (reconcile 의 primary lookup 가 의존)
2. `find_processed_paper` 의 arXiv `web-` guard 가 `pfmcp-` 와 충돌 없음을 코드 한 번 더 확인 (Round 2 에서 codex 가 거의 closed 로 평가, 확인만)

(rev2 에서 있던 "ASGI middleware 안정성 POC" 는 ASGI wrapper 채택으로 해소되어 제거)
