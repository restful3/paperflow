# PaperFlow MCP Server — Design Spec

**Version**: v1
**Date**: 2026-05-24
**Status**: Draft (pre-implementation)
**Owner**: restful3

---

## 1. Goal

PaperFlow 의 PDF→Markdown(+이미지)→번역 파이프라인을 **MCP (Model Context Protocol) 도구**로 노출한다. 외부 MCP 클라이언트(Claude Code, Claude Desktop 등)가 PDF 파일 또는 웹 페이지 URL을 보내면, 기존 watch-mode 파이프라인이 처리하고, 결과(마크다운 + 이미지 + 옵션으로 번역본)를 zip 으로 다운로드 받을 수 있어야 한다.

**Non-Goals (v1)**

- explainer (쉬운 설명판) 생성 — 현재 Claude skill 로만 동작, Python 모듈화는 v2
- MCP 를 통한 페이퍼 조회/검색 — viewer 가 이미 `/api/papers` 로 노출 중
- 진행률 server-push (SSE notification) — 폴링으로 충분
- 부분 파일 다운로드 (md만/이미지만) — zip 으로 통일

---

## 2. Hard Constraints

1. **기존 PaperFlow 기능 무변경 보장**
   - `main_terminal.py` 정상 경로 미변경 (except 블록 사이드카 1개 추가만 허용)
   - `run_batch_watch.sh`, `config.json`, 공유 볼륨 구조 미변경
   - viewer 의 기존 25개 API 동작 미변경
2. **opt-in 디폴트**: `.env` 에 `MCP_API_KEY` 가 없으면 MCP 라우터 자체가 마운트되지 않음 (외부 노출 0)
3. **GPU 단일 큐 유지**: 기존 converter 컨테이너가 watch 로 직렬 처리 → MCP 도 동일 큐에 합류, 경합 없음

---

## 3. Architecture

```
┌──────────────────┐                    ┌────────────────────────────────────────┐
│  MCP Client      │   HTTP/Streamable  │  paperflow-viewer (FastAPI)            │
│  (Claude Code/   │   /mcp             │                                        │
│   Desktop)       │ ───────────────►   │  ┌──────────────────────────────────┐ │
│                  │   Bearer MCP_API_KEY│ │ /mcp router  (new)               │ │
│                  │                    │  │   - submit_paper                 │ │
│                  │                    │  │   - get_job_status               │ │
│                  │                    │  │   - get_job_result               │ │
│                  │                    │  │   - cancel_job                   │ │
│                  │                    │  │   - list_jobs                    │ │
│                  │                    │  └──────┬──────────────┬────────────┘ │
│                  │                    │         │              │              │
│                  │   GET /api/mcp/    │         ▼              ▼              │
│                  │   jobs/{id}/zip    │  ┌──────────────┐ ┌──────────────┐  │
│                  │ ◄──────────────────│  │ mcp_jobs svc │ │ papers svc   │  │
│                  │   stream zip       │  │ (new file)   │ │ (existing,   │  │
└──────────────────┘                    │  └──────┬───────┘ │  no change)  │  │
                                        │         │         └──────────────┘  │
                                        │  reads/writes                        │
                                        │  ▼                                   │
                                        │  /data/logs/mcp_jobs.json (new)      │
                                        │  /data/logs/processing_status.json   │
                                        │  /data/newones/  (drop here)         │
                                        │  /data/outputs/<paper>/ (read here)  │
                                        └────────────────────────────────────────┘
                                                       ▲
                                                       │ same shared volumes
                                                       │
                                        ┌────────────────────────────────────────┐
                                        │  paperflow-converter (unchanged)       │
                                        │  run_batch_watch.sh                    │
                                        │   - watches newones/                   │
                                        │   - writes processing_status.json      │
                                        │   - produces outputs/<paper>/          │
                                        │   - + writes last_error_<file>.json    │
                                        │     on exception (new sidecar only)    │
                                        └────────────────────────────────────────┘
```

### 3.1 Execution Model

- **비동기 + job_id 폴링** (MCP 클라이언트 timeout 회피)
- **기존 watch 파이프라인 재사용** (코드 중복 없음, GPU 직렬 큐 유지)
- **URL 기반 zip 다운로드** (큰 파일 대응, base64 인라인 회피)

### 3.2 Data Flow

**Submit**
1. `submit_paper(input_type, source, options)`
2. `force_reprocess=false` (기본) → URL 이면 `find_processed_paper(source_url=source)`, 파일이면 `find_processed_paper(original_filename=source)` 조회 → 히트면 즉시 `status="complete"` job 반환 (`cached=true`)
3. URL: `_site_transform_pdf_urls()` + `_download_pdf()` 재사용 → `newones/<filename>` 저장
   File: base64 디코드 → `newones/<filename>` 저장 (200MB 초과 시 거부)
4. `logs/mcp_jobs.json` 에 `JobRecord` 기록 (atomic replace)
5. `{job_id, status, cached, expected_filename}` 반환

**Poll**
1. `get_job_status(job_id)`
2. `mcp_jobs.json` 에서 expected_filename 조회
3. Reconcile:
   - `processing_status.json.current_file == expected_filename` → stage/percent 반영, status=processing
   - 아니면 `find_processed_paper(filename=expected_filename)` 으로 outputs/ 조회 → 있으면 status=complete + paper_dir 저장
   - `logs/last_error_<filename>.json` 존재 → status=error + error 메시지 반영
   - 위 중 어디에도 안 잡히면 status=queued (watch 가 아직 안 집어감)
4. processing 인데 `processing_status.json` mtime > 30분 → status=stalled (사용자 결정 대기)

**Result**
1. `get_job_result(job_id, include_pdf, include_translation)` — status=complete 일 때만
2. paper_meta.json 핵심 필드 + `files` 요약 + dynamic `download_url` 반환
3. download_url 은 `/api/mcp/jobs/{job_id}/zip?include_pdf=...&include_translation=...`

**Download**
1. `GET /api/mcp/jobs/{job_id}/zip?include_pdf=...&include_translation=...`
2. Bearer 인증 (MCP 와 동일 키)
3. zip stream 생성 (Lazy) → `StreamingResponse`
4. zip 구조:
   ```
   {paper-slug}.zip
   ├── README.txt                  # 입력/옵션/처리시각
   ├── paper_meta.json
   ├── {slug}.md                   # 영문 (always)
   ├── {slug}_ko.md                # 한국어 (include_translation=true)
   ├── {slug}.pdf                  # 원본 (include_pdf=true)
   └── images/*.jpeg
   ```

**Cancel**
1. `cancel_job(job_id, delete_file=true)`
2. `paper_svc.request_cancel_processing(filename, delete_file, force=True)` 호출 (이미 존재)
3. job status → cancelled

---

## 4. Components

```
viewer/app/
├── main.py                        # [수정] mcp_router 마운트 1줄
├── config.py                      # [수정] MCP_API_KEY, MCP_JOB_TTL_DAYS 추가
├── routers/
│   ├── api.py                     # [수정] /api/mcp/jobs/{id}/zip 추가
│   ├── pages.py                   # [무변경]
│   └── mcp_router.py              # [신규]
└── services/
    ├── papers.py                  # [무변경 — import 만]
    └── mcp_jobs.py                # [신규]

main_terminal.py                   # [수정] except 블록 사이드카 1곳만
run_batch_watch.sh                 # [무변경]
config.json                        # [무변경]
```

### 4.1 `viewer/app/services/mcp_jobs.py` (~250 lines)

**책임**: Job 인덱스 관리, 파이프라인 트리거, 상태 reconcile, zip 스트림 생성
**외부 의존**: 없음 (LLM/HTTP 호출 안 함, papers.py 기존 함수만 import)

```python
class JobOptions(BaseModel):
    translate: bool = True
    web_search: bool = False
    include_pdf: bool = False
    force_reprocess: bool = False

class JobRecord(BaseModel):
    job_id: str                     # uuid4
    input_type: Literal["url", "file"]
    source: str                     # url 또는 원본 파일명
    expected_filename: str          # newones/ 에 떨어진 파일명
    options: JobOptions
    status: Literal["queued", "processing", "complete", "error", "cancelled", "stalled"]
    stage: str | None
    percent: int                    # 0-100
    paper_dir: str | None           # outputs/<name>
    error: str | None
    submitted_at: str
    completed_at: str | None

# Public:
def submit_job(input_type, source, options, *, pdf_bytes=None) -> JobRecord
def get_job(job_id) -> JobRecord | None
def reconcile_job(job_id) -> JobRecord
def list_jobs(limit=50, status=None) -> list[JobRecord]
def cleanup_expired_jobs() -> int
def build_zip_stream(job_id, *, include_pdf, include_translation) -> Iterator[bytes]

# Private:
def _atomic_write_index(jobs: dict[str, dict]) -> None
def _load_index() -> dict[str, dict]
def _resolve_url_to_pdf(url) -> tuple[bytes, str]
```

**동시성**: viewer 단일 프로세스 가정 (uvicorn `--workers 1` — 현재 PaperFlow 기본 구성) → in-process `asyncio.Lock` 충분. 다중 worker 도입 시 분산 락 필요 (v2 out-of-scope).
**영속성**: `logs/mcp_jobs.json` atomic replace. viewer 재시작 후에도 진행 중 job 복구 가능.

### 4.2 `viewer/app/routers/mcp_router.py` (~150 lines)

**책임**: MCP 프로토콜 핸들링, 인증, mcp_jobs 호출

```python
from mcp.server import Server
from mcp.server.streamable_http import StreamableHTTPSessionManager

mcp_server = Server("paperflow")

@mcp_server.list_tools()
async def _list_tools() -> list[Tool]: ...

@mcp_server.call_tool()
async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "submit_paper": ...
    elif name == "get_job_status": ...
    elif name == "get_job_result": ...
    elif name == "cancel_job": ...
    elif name == "list_jobs": ...
    else:
        raise ValueError(f"Unknown tool: {name}")

# FastAPI mount (only when MCP_API_KEY is set):
router = APIRouter(prefix="/mcp")
session_manager = StreamableHTTPSessionManager(mcp_server)
router.mount("", session_manager.handle_request,
             dependencies=[Depends(verify_mcp_key)])
```

**Transport**: Streamable HTTP (SSE deprecated by MCP spec)
**Library**: 공식 `mcp[server]>=1.0`

### 4.3 `viewer/app/routers/api.py` (+~40 lines)

```python
@router.get("/mcp/jobs/{job_id}/zip")
async def download_mcp_job_zip(
    job_id: str,
    include_pdf: bool = False,
    include_translation: bool = True,
    _: str = Depends(verify_mcp_key),
):
    job = mcp_jobs.get_job(job_id)
    if not job or job.status != "complete":
        raise HTTPException(status_code=404, detail="Job not complete or not found")
    stream = mcp_jobs.build_zip_stream(
        job_id, include_pdf=include_pdf, include_translation=include_translation
    )
    slug = _slugify_name(job.paper_dir or job.job_id)
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
    )
```

### 4.4 `viewer/app/config.py` (+5 lines)

```python
MCP_API_KEY: str = ""              # empty → MCP disabled entirely
MCP_JOB_TTL_DAYS: int = 7
MCP_PUBLIC_BASE_URL: str = ""      # ex: http://localhost:8090. empty → request 기반 자동 추론

@property
def mcp_enabled(self) -> bool:
    return bool(self.MCP_API_KEY and len(self.MCP_API_KEY) >= 32)
```

`MCP_PUBLIC_BASE_URL` 이 빈 값이면 `download_url` 은 FastAPI request 의 `request.url_for()` 결과 사용 (Docker port forwarding 등 자동 대응). 명시 설정 시 그것을 신뢰.

### 4.5 `main_terminal.py` (+~10 lines, 한 곳만)

```python
# process_single_pdf() 의 최상위 except 블록 내부:
try:
    err_path = settings.logs_dir / f"last_error_{pdf_path.name}.json"
    err_path.write_text(json.dumps({
        "filename": pdf_path.name,
        "error": str(e),
        "traceback": traceback.format_exc()[:4000],
        "occurred_at": datetime.now().isoformat(),
    }))
except Exception:
    pass    # 사이드카 실패는 무시
raise   # 기존 예외 전파 유지
```

기존 정상 경로 영향 0. 사이드카는 watch 의 정규 로그와 별개 — 실패해도 batch 실행 자체에 영향 없음.

---

## 5. MCP Tool Surface

### 5.1 `submit_paper`

```json
{
  "name": "submit_paper",
  "description": "PDF 파일 또는 웹 URL을 PaperFlow 파이프라인에 투입. 비동기 — job_id 반환.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "input_type": {"type": "string", "enum": ["url", "file"]},
      "source": {"type": "string"},
      "file_base64": {"type": "string", "description": "input_type=file 일 때 PDF base64. 최대 200MB."},
      "options": {
        "type": "object",
        "properties": {
          "translate": {"type": "boolean", "default": true},
          "web_search": {"type": "boolean", "default": false},
          "include_pdf": {"type": "boolean", "default": false},
          "force_reprocess": {"type": "boolean", "default": false}
        }
      }
    },
    "required": ["input_type", "source"]
  }
}
```

**Return** (TextContent JSON):
```json
{"job_id": "uuid", "status": "queued|complete", "cached": false, "expected_filename": "..."}
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
  "completed_at": null
}
```

Percent: stage 별 가중치 근사 (PDF→MD 50%, metadata 5%, web_search 5%, translate 35%, verify 5%).

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
  "paper_meta": {
    "title": "...",
    "authors": ["..."],
    "abstract": "...",
    "venue": "NeurIPS 2017",
    "year": 2017,
    "doi": "...",
    "categories": ["..."]
  },
  "files": {"md_en": true, "md_ko": true, "pdf": true, "images_count": 12},
  "download_url": "{MCP_PUBLIC_BASE_URL}/api/mcp/jobs/{job_id}/zip?include_pdf=false&include_translation=true"
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

내부: `paper_svc.request_cancel_processing(filename, delete_file, force=True)`. 멱등.

### 5.5 `list_jobs`

```json
{"name": "list_jobs",
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

| 카테고리 | 발생 위치 | 처리 |
|---------|---------|------|
| 입력 검증 실패 (잘못된 URL, base64 디코드 실패, file > 200MB) | submit_paper | `ValueError` → MCP `isError: true`, job 생성 안 함 |
| URL→PDF 변환 실패 | submit | 기존 `import_pdf_from_url` 반환값 그대로 전달, job 생성 안 함 |
| 컨버터 비정상 종료 (OOM 등) | converter | `logs/last_error_<filename>.json` 기록 → MCP poll 시 발견 → error |
| 번역 실패 (LLM 5xx, max_retries 초과) | converter | 위와 동일 경로 |
| converter 컨테이너 죽음 | infra | mtime > 30분 → `status="stalled"` (사용자 결정 대기) |
| viewer 재시작 중 job 손실 | viewer | `mcp_jobs.json` 영속화 → 부팅 시 reconcile |
| job_id 미존재 | 모든 get/cancel | MCP `isError: true`, "job not found" |
| download_url 호출 시 paper 폴더 삭제됨 | zip 스트림 | 404 + 명확 메시지, job → error 업데이트 |
| 동일 URL 동시 submit | submit | 둘 다 진입 — 의도적 허용 (분산 락 오버엔지니어링) |

### 6.1 stalled 감지

```python
# get_job_status 내부:
if job.status == "processing":
    status_mtime = processing_status_path.stat().st_mtime
    if now - status_mtime > 30 * 60:
        return job.with_status("stalled")
```

`stalled` 는 error 와 달리 재시도 가능 — 사용자가 cancel_job 후 재submit.

### 6.2 멱등성

- `submit_paper(force_reprocess=false)` 는 매 호출마다 새 job_id 반환. 단 status 즉시 complete 로 와서 결과는 동일.
- `cancel_job` 은 이미 complete/cancelled 면 no-op 으로 ok 응답.

---

## 7. Testing

### 7.1 단위 테스트 (`viewer/tests/test_mcp_jobs.py` 신규)

1. JobRecord 직렬화/역직렬화 라운드트립
2. atomic write 동시성 (asyncio.gather 50개 submit)
3. `find_processed_paper` 캐시 히트 → 즉시 complete
4. `force_reprocess=true` → 캐시 무시
5. URL 변환 실패 → 예외, job 생성 안 됨
6. file_base64 200MB 초과 → ValueError
7. stalled 감지 (mtime > 30분, stage=processing)
8. cleanup: 7일 지난 completed 삭제, 진행 중 보존
9. zip 생성: include_pdf/include_translation 조합별 파일 목록
10. download 도중 paper 삭제 → 404

### 7.2 통합 테스트 (`viewer/tests/test_mcp_router.py` 신규)

MCP SDK `mcp.client.streamable_http` 로 테스트 클라이언트:

1. list_tools → 5개 tool 확인
2. submit_paper → get_job_status 시퀀스 (mocked converter)
3. Bearer auth: 키 없음/잘못된 키 → 401, 정확 → 200
4. cancel_job → request_cancel_processing 호출 확인 (mock)
5. get_job_result without complete status → error

### 7.3 수동/E2E

- 실제 arXiv URL submit → 폴링 → zip 다운로드 → 압축 해제 → md/이미지 확인
- 같은 URL 두 번째 submit → cached=true, < 1초 응답 확인
- Claude Code 에서 MCP 서버 등록 후 도구 사용 1회

### 7.4 회귀 방지

- viewer 기존 25개 API 정상 동작 (변경 없음)
- watch 모드 PDF 처리 정상 동작 (`main_terminal.py` 사이드카 추가만)
- `pytest viewer/tests/` 전체 그린

---

## 8. Impact on Existing PaperFlow

| 컴포넌트 | 변경? | 영향 |
|---------|------|-----|
| `main_terminal.py` 정상 경로 | ✗ | 0 |
| `main_terminal.py` except 블록 | △ | 사이드카 1개 추가 — 정상 동작 영향 없음 |
| `run_batch_watch.sh` | ✗ | 0 |
| `config.json` | ✗ | 0 |
| viewer 기존 라우터 | ✗ | 0 (zip endpoint는 신규 path) |
| viewer 기존 서비스 | ✗ | 0 (mcp_jobs.py 가 단방향 import) |
| viewer 템플릿/UI | ✗ | 0 |
| Docker compose | △ | env 추가만 — `MCP_API_KEY` 빈 값이면 MCP 비활성 |
| 공유 볼륨 구조 | ✗ | 0 (logs/mcp_jobs.json 만 신규) |

---

## 9. Deployment

### 9.1 새 의존성

```
mcp>=1.0.0                # 공식 MCP Python SDK
```

`viewer/Dockerfile` 에 한 줄 추가.

### 9.2 .env

```
MCP_API_KEY=<openssl rand -hex 32>
MCP_JOB_TTL_DAYS=7    # 선택, 기본 7
```

### 9.3 빌드 & 등록

```bash
docker compose build paperflow-viewer && docker compose up -d paperflow-viewer

claude mcp add paperflow --transport http \
    --url http://localhost:8090/mcp \
    --header "Authorization: Bearer <MCP_API_KEY>"

# Claude Code 안에서 /mcp 로 paperflow 확인
```

---

## 10. Out-of-Scope (v2 후보)

- explainer (쉬운 설명판) skill 의 Python 모듈화
- SSE 진행률 push (폴링 제거)
- 부분 파일 다운로드 (md만, 이미지만)
- 페이퍼 조회 tool (search_papers, get_paper)
- 다중 viewer worker 시 분산 락 (현재 `--workers 1` 가정)
