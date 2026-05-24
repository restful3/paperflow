# PaperFlow MCP Server — Design Spec (v2, post-codex review)

**Version**: v1 (spec rev 2)
**Date**: 2026-05-24
**Status**: Draft (pre-implementation, awaiting user sign-off)
**Owner**: restful3
**Prior review**: `docs/reviews/2026-05-24-paperflow-mcp-server-codex.md`

---

## Change Log (vs spec rev 1)

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
                                        │  /data/logs/mcp_errors/{job}.json    │
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

**Submit (URL)**
1. `submit_paper(input_type="url", source=url, options={force_reprocess?})`
2. URL 검증 (scheme/host basic check)
3. `force_reprocess=false` (기본): `find_processed_paper(source_url=url)` 조회. 히트면 즉시 `status="complete"` job 반환 (`cached=true`). 단 히트한 paper 의 `paper_meta.json.original_filename` 이 `web-` 로 시작하면 legacy page-capture 일 가능성 → 캐시 미스로 fallthrough (기존 arXiv guard 와 일치하는 보수적 동작)
4. job_id 생성 (uuid4), expected_filename = `pfmcp-{job_id[:12]}-{slugify(host_or_title)[:40]}.pdf`
5. URL → PDF 다운로드: 기존 `papers._site_transform_pdf_urls()` + `papers._download_pdf()` + DOI redirect resolve + HTML fallback 재사용 (현재 `import_url_as_paper()` 가 이미 구현한 흐름. v1 은 이 함수를 새 시그니처로 분리/래핑하지 않고, 작은 helper `_resolve_url_to_pdf_bytes(url) -> (bytes, final_url)` 만 추출해서 재사용)
6. PDF 바이트를 `newones/{expected_filename}.part` 에 write → `fsync` → `os.replace(...part → .pdf)`. `.pdf` 파일이 시야에 나타나는 순간 완전체 보장
7. URL 입력의 경우: 기존 `_write_source_sidecar(filename, url)` 호출 (paper 폴더가 생성된 뒤 `paper_meta.json.paper_url` / `source_url_original` 백필 가능)
8. `logs/mcp_jobs.json` 에 `JobRecord` (import_method 필드 포함) 기록 (asyncio.Lock 하에서 load→modify→atomic replace)
9. `{job_id, status: "queued", cached: false, expected_filename}` 반환

**Reverse-lookup**: paper 폴더가 완성된 뒤 MCP reconciler 는 `find_processed_paper(original_filename=expected_filename)` 으로 job ↔ paper 매핑. expected_filename 의 `pfmcp-{job12}-` prefix 가 fingerprint 역할 — 사용자가 파일 rename 하지 않는 한 안전. (rename 한 경우는 v1 미지원, 사용자 책임.)

**Submit (File)**
- 같은 흐름. PDF base64 디코드 (200MB 초과 거부, magic byte `%PDF-` 검증), expected_filename = `pfmcp-{job_id[:12]}-{slugify(original_filename)[:40]}.pdf`
- 입력 `source` 는 사용자 제공 original_filename (메타 보존용)
- duplicate check: `find_processed_paper(original_filename=source)` 도 시도 — 단 file 입력은 사용자별 의도가 다양해 캐시 적중률 낮음, 그래도 시도는 함

**Poll: reconcile_job(job_id)**

순서대로 검사:

1. `mcp_jobs.json` 에서 JobRecord 로드 → 없으면 None
2. 종료 상태(`complete|error|cancelled`) 이면 그대로 반환
3. `logs/mcp_errors/{job_id}.json` 존재 → `status="error"`, error 메시지 저장, `completed_at` 설정
4. `find_processed_paper(original_filename=expected_filename)` → 결과 있고 `paper_meta.json` 의 mtime > `submitted_at` 면 `status="complete"`, `paper_name` + `location` 저장
5. `processing_status.json` 로드:
   - `current_file == expected_filename` 이고 `stage not in ("idle","complete","error")` → `status="processing"`, stage/percent 반영
   - `current_file == expected_filename` 이고 `stage == "error"` → `status="error"`, error 메시지 반영
   - `processing_status` mtime > 30분이고 stage 무변화 + 위 4 미히트 → `status="stalled"`
6. 위 어디에도 안 잡히면 `newones/{expected_filename}` 존재 → `status="queued"`. 미존재 → `status="error"` (파일이 watch 에 의해 처리됐어야 하는데 outputs 도 없음 — 비정상)

**중요**: 4번이 3번보다 뒤에 있는 이유 — 컨버터가 실패해서 sidecar 를 쓴 직후, 또 다른 watch 사이클이 이전 partial outputs 를 발견하면 거짓 complete 가 될 수 있음. error sidecar 우선.

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
2. 기존 `paper_svc.request_cancel_processing(filename=expected_filename, delete_file, force=True)` 호출
3. `JobRecord.status = "cancelled"`, completed_at 설정

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
    status: Literal["queued", "processing", "complete", "error", "cancelled", "stalled"]
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
async def get_job(job_id) -> JobRecord | None
async def reconcile_job(job_id) -> JobRecord
async def list_jobs(limit=50, status=None) -> list[JobRecord]
async def cancel_job(job_id, delete_file=True) -> JobRecord
async def cleanup_expired_jobs() -> int   # 시작 시 + 매 1시간 background task
async def mark_paper_missing(job_id) -> JobRecord   # download 시 paper 폴더 사라진 경우

# Private:
async def _atomic_write_index(jobs: dict[str, dict]) -> None
async def _load_index() -> dict[str, dict]
   # 손상 시 mcp_jobs.corrupt.<ts>.json 으로 quarantine, 빈 index 로 시작 + log WARN
async def _write_part_then_publish(pdf_bytes: bytes, dest: Path) -> None
   # .part write → os.fsync(fileno) → os.replace
def _build_expected_filename(job_id: str, slug_source: str) -> str
   # pfmcp-{job_id[:12]}-{safe_slug[:40]}.pdf
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
import contextlib
from mcp.server.fastmcp import FastMCP, Context
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse, Response

from ..config import settings
from ..services import mcp_jobs

mcp = FastMCP("paperflow",
              stateless_http=True,        # 단순화 (세션 의존 없음)
              json_response=True)

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

# ASGI middleware: Bearer + Origin
class MCPAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str, allowed_origins: set[str]):
        super().__init__(app)
        self.api_key = api_key
        self.allowed_origins = allowed_origins   # set or {"*"} for permissive

    async def dispatch(self, request: StarletteRequest, call_next):
        # Bearer
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != self.api_key:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        # Origin (DNS rebinding 방어, MCP spec MUST)
        origin = request.headers.get("origin")
        if origin and "*" not in self.allowed_origins and origin not in self.allowed_origins:
            return JSONResponse({"error": "origin not allowed"}, status_code=403)
        return await call_next(request)

# Lifespan helper: caller (main.py) 가 호출
@contextlib.asynccontextmanager
async def mcp_lifespan(app):
    async with mcp.session_manager.run():
        yield

# Mount helper: caller 가 호출
def mount_mcp(app, api_key: str, allowed_origins: set[str], path: str = "/mcp"):
    from starlette.middleware import Middleware
    inner = mcp.streamable_http_app()
    # Wrap with auth middleware
    inner.user_middleware.insert(0,
        Middleware(MCPAuthMiddleware, api_key=api_key, allowed_origins=allowed_origins))
    inner.middleware_stack = inner.build_middleware_stack()
    app.mount(path, inner)
```

**왜 ASGI middleware**: FastAPI `Depends` 는 mount 된 sub-app 에 안 걸림 (공식 한계). TokenVerifier 는 OAuth 2.1 + RFC 9728 용으로 단순 정적 API key 에는 과함. ASGI middleware 가 정직한 fit.

**왜 stateless_http**: 우리 도구들은 모두 단발 호출. 세션 상태 불필요. 단순화 + 다중 worker 대비.

### 4.4 `viewer/app/main.py` (+~15 lines)

```python
from .routers import mcp_router

@contextlib.asynccontextmanager
async def app_lifespan(app):
    # Other startup (if any)
    if settings.mcp_enabled:
        async with mcp_router.mcp_lifespan(app):
            asyncio.create_task(_periodic_mcp_cleanup())
            yield
    else:
        yield

def create_app() -> FastAPI:
    app = FastAPI(lifespan=app_lifespan)
    app.include_router(pages.router)
    app.include_router(api.router)

    if settings.mcp_enabled:
        # zip download endpoint (별도 router, MCP 비활성 시 미등록)
        from .routers.mcp_router import mcp_zip_router
        app.include_router(mcp_zip_router)
        mcp_router.mount_mcp(app, settings.MCP_API_KEY,
                              settings.mcp_allowed_origins_set)
    return app
```

**Lazy import**: `from .routers import mcp_router` 는 top-level 이지만 `mcp` 패키지 import 가 `MCP_API_KEY` 미설정 시에도 발생 — opt-in 0 노출 약속을 지키려면 이 import 자체를 `settings.mcp_enabled` 안으로 옮기는 게 더 엄격함. v1 은 일단 top-level import 허용, mount/router 등록만 조건부 (mcp 패키지가 viewer dependency 에 항상 포함되므로 import 실패 위험 없음).

### 4.5 `viewer/app/routers/api.py` 안의 zip endpoint → 별도 router

`api.py` 는 무변경. zip endpoint 는 `mcp_router.py` 안의 `mcp_zip_router` (`APIRouter(prefix="/api/mcp")`) 에 정의:

```python
mcp_zip_router = APIRouter(prefix="/api/mcp")

@mcp_zip_router.get("/jobs/{job_id}/zip")
async def download_zip(
    job_id: str,
    include_pdf: bool = False,
    include_translation: bool = True,
    request: Request = None,
):
    # ASGI middleware 가 인증 이미 처리 (mcp_zip_router 도 같은 미들웨어 적용)
    # 정확히는 router 단위 Depends 로 한 번 더 검증 (defense in depth)
    _verify_bearer(request, settings.MCP_API_KEY)
    job = await mcp_jobs.get_job(job_id)
    if not job or job.status != "complete":
        raise HTTPException(404, "Job not complete or not found")
    paper_info = paper_svc.find_processed_paper(original_filename=job.expected_filename)
    if not paper_info:
        await mcp_jobs.mark_paper_missing(job_id)
        raise HTTPException(410, "Paper folder no longer exists")
    paper_dir = paper_svc.safe_paper_dir(paper_info["name"], paper_info["location"])
    stream = mcp_zip.build_zip_stream(paper_dir,
        include_pdf=include_pdf, include_translation=include_translation, job_record=job)
    return StreamingResponse(stream, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{paper_info["name"]}.zip"'})
```

**정의 위치 vs 인증**: zip endpoint 는 `app.include_router(mcp_zip_router)` 로 등록되므로 FastAPI path operation. 여기엔 `Depends(verify_mcp_key)` 가 정상 동작. ASGI middleware 는 `/mcp` mount 에만 적용, zip 은 자체 Depends 사용. 두 경로의 인증 코드가 분기되지만 같은 검증자 함수 공유.

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
        if not self.MCP_ALLOWED_ORIGINS:
            return {"*"}    # permissive when not configured
        return {o.strip() for o in self.MCP_ALLOWED_ORIGINS.split(",") if o.strip()}
```

**`MCP_PUBLIC_BASE_URL` 필수화 이유**: tool handler 에서 FastAPI Request 직접 접근 불가 (FastMCP context 와 별개). reverse proxy 뒤 호스트 헤더 신뢰 불가. v1 은 명시 설정 강제.

### 4.7 `viewer/app/services/papers.py` 변경 (작은 refactor)

`import_url_as_paper()` 의 내부에서 "URL → PDF bytes" 부분만 추출:

```python
def _resolve_url_to_pdf_bytes(url: str) -> tuple[bytes, str, str]:
    """URL → (pdf_bytes, final_url, import_method).
    DOI resolve → site transformer → direct download → HTML fallback.
    Raises ValueError on failure with concrete message.
    """
    # 기존 import_url_as_paper() 내부 로직 그대로 복사/분리
```

`import_url_as_paper()` 는 이 helper 를 호출하도록 리팩토링. **기존 호출자 동작 변경 없음** (블랙박스 동일). 단위 테스트 추가.

### 4.8 `main_terminal.py` 변경

**없음**. 0줄. 

기존 `processing_status.json.error` 필드를 MCP reconciler 가 읽음. 추가 사이드카 불필요. (당초 rev1 의 `last_error_<filename>.json` 아이디어는 컨버터 변경 필요해서 폐기. `processing_status.json` 의 error 필드를 1차 소스로 신뢰.)

### 4.9 `viewer/Dockerfile` (+1 line)

```dockerfile
RUN pip install --no-cache-dir mcp>=1.27,<2
```

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
{"job_id": "uuid", "status": "queued|complete", "cached": false, "expected_filename": "pfmcp-..."}
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
  "status": "queued|processing|complete|error|cancelled|stalled",
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
     "status": {"type": "string", "enum": ["queued","processing","complete","error","cancelled","stalled"]}
   }
 }}
```

**Return**: `JobRecord` 배열 (submitted_at desc).

---

## 6. Error Handling

| 카테고리 | 처리 |
|---------|------|
| 입력 검증 실패 (잘못된 URL scheme, base64 fail, file > 200MB, magic byte mismatch) | `ValueError` → MCP `isError: true`, job 생성 안 함 |
| URL → PDF 변환 실패 (모든 방법 시도 후) | `_resolve_url_to_pdf_bytes` raises → job 생성 안 함, 명확한 에러 메시지 |
| `newones/{name}.part` write 실패 (디스크 full) | partial 파일 cleanup (`.part` 삭제 시도) → job 생성 안 함 |
| `.part → .pdf` rename 실패 | 위와 동일 |
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
  - `logs/mcp_errors/{job_id}.json` 도 같이 삭제
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
| 공유 볼륨 | `logs/mcp_jobs.json`, `logs/mcp_errors/` 신규 — 기존 파일 미변경 | 0 |
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

## 12. Open Questions (구현 시 확인)

1. `mcp.streamable_http_app()` 의 ASGI app 에 추가로 user_middleware insert 후 `build_middleware_stack()` 재호출이 SDK 1.27 에서 안정적인지 — Starlette 의 미들웨어 가 lifespan 시작 후 변경 불가일 수 있음. POC 필요. 대안: ASGI wrapper 함수 (`async def wrapped_app(scope, receive, send)`) 로 외부 감싸기 — 더 안전.
2. `find_processed_paper` 의 arXiv `web-` guard 가 v1 의 `pfmcp-` prefix 와 충돌 없는지 코드 한 번 더 읽기 (기대대로면 영향 0)
3. converter 가 `pfmcp-` 파일을 정상 처리하는지 (filename slug 가 metadata 추출에 끼치는 영향) — 보통은 metadata extraction 이 PDF 내용 기반이라 무관, 확인 필요
