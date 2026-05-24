# Codex Review: PaperFlow MCP Server v1 Design Spec

검토 대상:
- `/media/restful3/data/workspace/paperflow/docs/superpowers/specs/2026-05-24-paperflow-mcp-server-design.md`
- 관련 기존 코드: `viewer/app/services/papers.py`, `viewer/app/routers/api.py`, `viewer/app/config.py`, `viewer/app/main.py`, `main_terminal.py`, `run_batch_watch.sh`, `viewer/Dockerfile`, `docker-compose.yml`, `CLAUDE.md`

## 1. 기존 기능 무변경 제약 검증

[심각도: critical] 스펙의 `main_terminal.py` 실패 사이드카 설계가 현재 코드의 실패 모델과 맞지 않습니다.  
인용: 스펙 4.5는 `process_single_pdf()` 최상위 `except`에 `last_error_<file>.json`을 쓰고 `raise`한다고 합니다(`docs/.../2026-05-24-paperflow-mcp-server-design.md:262-279`). 그러나 현재 `process_single_pdf()`는 단계별 실패를 대부분 내부에서 잡아 `results["..."] = "failed"`로만 기록하고 계속 진행합니다(`main_terminal.py:2927-2929`, `3013-3015`, `3087-3089`). 최상위 `except`도 `write_processing_status(..., "error")` 후 `return False`입니다(`main_terminal.py:3135-3140`). 즉 실제 주요 실패는 사이드카가 생성되지 않고, 스펙처럼 `raise`를 넣으면 기존 watch의 종료 코드/재시도 동작이 바뀔 수 있습니다. 더구나 `main()`은 실패 카운트를 출력한 뒤 명시적 실패 코드를 반환하지 않습니다(`main_terminal.py:3287-3303`), `run_batch_watch.sh`는 프로세스 exit code로 성공/실패를 판단합니다(`run_batch_watch.sh:252-266`).  
제안: v1에서 `main_terminal.py` 정상/실패 경로 무변경을 지키려면 `raise` 추가는 금지하고, `process_single_pdf()` 반환 직전에 `success_count == 0`일 때 사이드카를 best-effort로 쓰는 식으로 명시하세요. 또는 `processing_status.json.error`를 MCP reconcile의 1차 에러 소스로 사용하고 사이드카는 보조로만 다루세요.

[심각도: high] 스펙의 사이드카 snippet은 현재 `main_terminal.py`에서 그대로 동작하지 않습니다.  
인용: 스펙 4.5는 `settings.logs_dir`를 사용합니다(`docs/...design.md:265-268`). `main_terminal.py`는 viewer 앱의 Pydantic `settings`를 import하지 않고, 기존 status writer도 문자열 경로 `logs/processing_status.json`을 사용합니다(`main_terminal.py:254-259`).  
제안: 컨버터 쪽 코드는 viewer 패키지 설정을 import하지 말고 `Path("logs") / ...`를 사용하세요. viewer `settings`를 컨버터에 끌어오면 작업 디렉터리, env 파일, import path 차이로 기존 batch 경로에 영향을 줄 수 있습니다.

[심각도: critical] MCP submit 옵션(`translate`, `web_search`)은 현재 파이프라인에 전달될 경로가 없습니다.  
인용: 스펙 4.1/5.1은 `JobOptions.translate`, `web_search`를 정의합니다(`docs/...design.md:153-158`, `299-303`). 하지만 컨버터는 매 실행마다 전역 `config.json`에서 pipeline을 읽습니다(`main_terminal.py:2851-2863`). `run_batch_watch.sh`는 `PAPERFLOW_TARGET_PDF`만 넘깁니다(`run_batch_watch.sh:207-209`). Hard Constraints는 `run_batch_watch.sh`, `config.json`, 정상 경로 변경 금지를 요구합니다(`docs/...design.md:23-30`).  
제안: v1에서는 `translate`/`web_search`를 submit 옵션에서 제거하거나 "현재 서버 전역 config를 따름"으로 명시하세요. per-job 옵션을 지원하려면 sidecar config를 추가하고 `main_terminal.py`가 읽도록 해야 하므로 v1의 무변경 제약과 충돌합니다.

[심각도: medium] MCP opt-in 마운트는 방향은 맞지만, 구현 위치가 모호하면 비활성 상태에서도 import 영향이 생길 수 있습니다.  
인용: 스펙 2는 `MCP_API_KEY`가 없으면 라우터가 마운트되지 않는다고 합니다(`docs/...design.md:29`). 현재 `create_app()`는 `api`와 `pages`를 top-level import합니다(`viewer/app/main.py:6-16`). 스펙은 `api.py`에 zip endpoint를 추가하고 `mcp_jobs`를 사용합니다(`docs/...design.md:224-246`).  
제안: `mcp_router`와 MCP SDK import는 반드시 `if settings.mcp_enabled:` 블록 안에서 지연 import하세요. `/api/mcp/jobs/{id}/zip`도 `MCP_API_KEY`가 비어 있으면 등록하지 않는 별도 router로 분리하는 편이 "외부 노출 0" 약속과 더 일치합니다.

[심각도: low] `logs/mcp_jobs.json` 자체는 기존 logs 패턴과 큰 충돌은 없어 보입니다.  
인용: 기존 latest-log는 `logs/paperflow_*.log`만 읽습니다(`viewer/app/services/papers.py:918` 부근), watch는 `processing_status.json`, `cancel_requests.json`, `processing_runtime.json`, `fail_counts.json`을 사용합니다(`run_batch_watch.sh:6-9`, `76-105`).  
제안: 파일명 충돌은 낮지만, `logs/`가 없는 새 설치에서도 `mcp_jobs.json` 생성 전에 `mkdir(parents=True)`를 명시하세요.

## 2. 경쟁/동시성 이슈

[심각도: medium] "viewer single worker" 가정은 현재 Docker 기본값과는 일치합니다.  
인용: `viewer/Dockerfile`은 `uvicorn app.main:app --host 0.0.0.0 --port 8000`만 실행하고 `--workers`를 지정하지 않습니다(`viewer/Dockerfile:19`).  
제안: 이 가정은 스펙에 "Dockerfile 기준"으로 박아두고, `--workers > 1`이면 startup에서 MCP를 거부하거나 파일 락(`fcntl.flock`)을 사용하도록 명시하세요.

[심각도: high] `asyncio.Lock`만으로는 `mcp_jobs.json` 일관성을 보장한다고 보기 어렵습니다.  
인용: 스펙 4.1은 public API를 동기 함수로 정의하면서 in-process `asyncio.Lock`이 충분하다고 합니다(`docs/...design.md:174-189`). 기존 `cancel_requests.json`도 read-modify-write는 tmp+`os.replace`를 쓰지만 프로세스 간 락은 없습니다(`viewer/app/services/papers.py:1321-1345`, `run_batch_watch.sh:58-72`).  
제안: `mcp_jobs` API를 전부 async로 만들고 하나의 `asyncio.Lock` 아래에서 `_load_index`→수정→`_atomic_write_index`를 수행한다는 불변식을 명시하세요. 다중 프로세스 가능성을 조금이라도 열어둘 거면 `fcntl.flock` 또는 SQLite를 v1로 올리는 편이 낫습니다. tmp 파일명도 요청별 unique tmp를 쓰세요.

[심각도: critical] 동일 URL 동시 submit은 "둘 다 진입"하지 않고 같은 파일명/같은 expected_filename으로 충돌할 수 있습니다.  
인용: 스펙 6은 동일 URL 동시 submit을 의도적으로 허용한다고 합니다(`docs/...design.md:420`). 기존 URL import 파일명은 `web-{slug}-{YYYYMMDD-HHMMSS}.pdf`로 초 단위입니다(`viewer/app/services/papers.py:238-243`). 같은 초에 같은 host/title이면 같은 `pdf_path`에 쓰며, 스펙의 MCP file submit도 원본 filename을 expected_filename으로 쓰는 흐름입니다(`docs/...design.md:86-89`, `163-165`).  
제안: MCP job은 항상 `pfmcp-{job_id[:12]}-{safe_slug}.pdf` 같은 job_id 기반 파일명을 생성하세요. 원본 파일명/URL은 metadata에만 보존하고, `last_error`, cancel, reconcile도 이 고유 expected_filename을 기준으로 해야 합니다.

[심각도: high] `newones/`에 최종 `.pdf` 이름으로 직접 쓰면 watch가 partial file을 집어갈 수 있습니다.  
인용: watch는 5초마다 `find newones -maxdepth 1 -name "*.pdf" -type f`로 즉시 처리합니다(`run_batch_watch.sh:183-208`). 기존 `import_url_as_paper()`도 `pdf_path.write_bytes()`로 직접 씁니다(`viewer/app/services/papers.py:253-255`, `276-289`), 스펙도 `newones/<filename>` 저장만 말합니다(`docs/...design.md:87-89`).  
제안: MCP 경로는 `newones/.incoming/{job_id}.tmp` 또는 `newones/<name>.part`에 완전히 쓴 뒤 `fsync` 후 `os.replace()`로 `.pdf`를 노출하세요. 기존 viewer import는 건드리지 않더라도 MCP 신규 경로에는 이 패턴을 적용해야 합니다.

[심각도: medium] `processing_status.json` mtime 기준 자체는 컨테이너 시간 동기화 문제는 낮지만, status 전환 모델이 불완전합니다.  
인용: 스펙 6.1은 processing 상태에서 mtime > 30분이면 stalled라고 합니다(`docs/...design.md:422-430`). 기존 writer는 tmp+`os.replace`를 사용합니다(`main_terminal.py:254-259`), Docker bind mount라 mtime은 호스트 커널 기준입니다. 그러나 `main()`은 마지막에 항상 idle status를 씁니다(`main_terminal.py:3302-3303`).  
제안: reconcile은 `processing_status.current_file == expected_filename`만 보지 말고, `newones/<expected_filename>` 존재, `failed/<expected_filename>` 존재, 출력 폴더 존재, status.error, log sidecar를 종합해야 합니다. 그렇지 않으면 실패 후 idle 상태에서 job이 영원히 queued로 남을 수 있습니다.

[심각도: high] `logs/last_error_<filename>.json`은 stale error 오인 가능성이 큽니다.  
인용: 스펙 Poll은 해당 파일 존재만으로 error 처리합니다(`docs/...design.md:95-99`, `414-415`). 동시에 스펙은 동일 URL submit을 허용합니다(`docs/...design.md:420`).  
제안: error sidecar에는 `job_id`, `expected_filename`, `occurred_at`, `submitted_at` 이후 여부를 넣고 reconcile에서 `occurred_at >= job.submitted_at`만 채택하세요. 더 좋은 방법은 `last_error_{job_id}.json` 또는 job index 내부 error 필드로 기록하는 것입니다.

## 3. 누락된 에러 케이스/엣지 케이스

[심각도: high] arXiv URL 캐시가 MCP에서 계속 miss 될 가능성이 있습니다.  
인용: 스펙 Submit은 URL cache hit에 `find_processed_paper(source_url=source)`를 사용합니다(`docs/...design.md:86`). 현재 `find_processed_paper()`는 arXiv abs URL일 때 `original_filename`이 `web-`로 시작하면 legacy page-capture로 보고 건너뜁니다(`viewer/app/services/papers.py:631-669`). 기존 URL import의 arXiv 파일명도 `web-arxiv.org-<timestamp>.pdf`입니다(`viewer/app/services/papers.py:238-243`).  
제안: MCP/현재 URL import가 direct PDF transform으로 성공한 경우에는 sidecar 또는 metadata에 `import_method="direct_pdf"`를 기록하고, arXiv guard는 `import_method == "browser_print"` 같은 legacy case에만 적용하세요.

[심각도: high] URL submit 구현 경로가 스펙 안에서 자기모순입니다.  
인용: Data Flow는 `_site_transform_pdf_urls()` + `_download_pdf()`만 재사용한다고 합니다(`docs/...design.md:87`). Error Handling은 존재하지 않는 `import_pdf_from_url` 반환값을 언급합니다(`docs/...design.md:413`). 기존 실제 함수는 `import_url_as_paper()`이며 URL validation, DOI resolve, headless fallback, quality gate, source sidecar를 포함합니다(`viewer/app/services/papers.py:206-390`).  
제안: v1은 `import_url_as_paper()`를 재사용하거나, 그 내부를 "URL 해석/다운로드"와 "queue write"로 안전하게 분리하는 계획을 명시하세요. `_download_pdf()`만 쓰면 현재 viewer URL import의 fallback/quality gate와 다르게 동작합니다.

[심각도: high] 디스크 full/쓰기 실패 시 partial 파일 및 잘못된 job 생성 가능성이 명시되지 않았습니다.  
인용: 스펙 Submit은 PDF 저장 후 `mcp_jobs.json` 기록 순서만 말합니다(`docs/...design.md:87-90`). 기존 `save_upload()`는 `dest.write_bytes(data)` 예외를 잡지 않습니다(`viewer/app/services/papers.py:1016-1025` 이후).  
제안: queue write는 temp 파일에 쓰고 실패 시 temp cleanup 후 job을 생성하지 않아야 합니다. job 생성 이후 파일 노출에 실패했다면 status=error로 저장하고 사용자에게 retry 가능한 메시지를 반환하세요.

[심각도: medium] archive/delete와 cached result의 경합이 덜 정의되어 있습니다.  
인용: 스펙 Result는 `paper_dir` 저장 후 download URL을 반환합니다(`docs/...design.md:102-110`, `160-170`). Error Handling은 download 시 paper 폴더 삭제를 404+job error로 처리한다고만 합니다(`docs/...design.md:419`). 현재 `safe_paper_dir()`는 outputs와 archives 양쪽을 찾습니다(`viewer/app/services/papers.py:735-750`).  
제안: `JobRecord.paper_dir`에는 절대/상대 path 문자열 대신 `paper_name`과 `location` 또는 `paper_name`만 저장하고 download 직전에 `safe_paper_dir(paper_name)`로 재해석하세요. archive 이동은 정상 추적하고, delete만 404/410으로 처리하는 것이 기존 UI와 더 일관됩니다.

[심각도: medium] `mcp_jobs.json` 손상 시 부팅/요청 처리 정책이 없습니다.  
인용: 스펙은 `_load_index()`만 정의하고 손상 JSON 처리를 설명하지 않습니다(`docs/...design.md:182-185`, `416-417`).  
제안: load 실패 시 `mcp_jobs.corrupt.<timestamp>.json`으로 quarantine하고 빈 index로 시작하되, 사용자에게 admin-visible warning을 남기세요. atomic replace에는 `fsync(file)`과 가능하면 `fsync(dir)`까지 명시하면 OOM/power loss 내성이 올라갑니다.

[심각도: medium] cleanup TTL과 폴링 클라이언트의 계약이 없습니다.  
인용: TTL 기본 7일은 config에 있지만 언제 cleanup이 실행되는지, expired job 응답이 무엇인지는 없습니다(`docs/...design.md:179`, `252`, `451-452`, `508-510`).  
제안: `expires_at`을 JobRecord와 status/result 응답에 포함하고, 만료된 job은 임의 404보다 `410 Gone` 성격의 MCP error로 반환하세요. processing/stalled/cancelled 보존 정책도 별도 명시가 필요합니다.

[심각도: medium] `list_jobs`는 single-user assumption을 문서화하지 않으면 정보 노출 도구가 됩니다.  
인용: 스펙 5.5는 인증된 MCP caller에게 모든 `JobRecord`를 반환합니다(`docs/...design.md:391-404`). `JobRecord.source`는 URL 또는 원본 파일명입니다(`docs/...design.md:160-165`).  
제안: v1은 single tenant + single MCP_API_KEY임을 Security/Deployment에 명시하세요. 다중 키를 허용할 계획이 있으면 `owner_key_id`를 저장하고 list/get/cancel/result를 key별로 필터링해야 합니다.

## 4. explainer v1 제외 결정의 타당성

[심각도: low] explainer 생성 자체를 v1에서 제외하는 결정은 합리적입니다.  
인용: 스펙 Non-Goals와 v2 후보는 explainer가 Claude skill이고 Python 모듈화가 v2라고 합니다(`docs/...design.md:14-19`, `527-530`). 기존 API에는 explained 파일 serving endpoint가 이미 있지만 생성 경로는 viewer API가 아닙니다(`viewer/app/routers/api.py`의 `/md-ko-explained`, `/md-en-explained`; `CLAUDE.md` Output Structure 설명).  
제안: v1은 "생성은 하지 않음"으로 유지해도 됩니다. 다만 "이미 존재하는 explained 파일을 zip에 포함할지"는 생성과 별개의 결정입니다.

[심각도: medium] 사용자가 MCP 결과에 explainer를 적용하는 경로가 스펙에 없습니다.  
인용: zip 구조는 explained 파일을 포함하지 않습니다(`docs/...design.md:111-119`), v2 후보에도 "생성 모듈화"만 있습니다(`docs/...design.md:527-530`).  
제안: v1 문서에 "MCP 결과 zip의 `.md`를 paper-explainer skill에 입력해서 별도로 생성" 또는 "viewer UI에서 해당 paper의 Easy mode 생성 플로우 사용" 같은 명시적 path를 추가하세요. zip을 viewer에 다시 import하는 방식은 현재 `/api/upload`가 PDF만 받으므로 자연스러운 경로가 아닙니다.

[심각도: low] `include_translation`과 별개로 `include_explained` 옵션을 v2가 아니라 v1에서 읽기 전용으로 넣을 수 있습니다.  
인용: 기존 output structure는 `_ko_explained.md`, `_explained.md`를 optional artifact로 인정합니다(`CLAUDE.md` Output Structure).  
제안: 생성은 하지 않더라도, output 폴더에 이미 explained 파일이 있으면 `include_explained=false` 기본 옵션으로 zip 포함 여부를 제어하는 것은 작고 안전합니다. v1 scope가 빡빡하면 최소한 "항상 제외"를 명시하세요.

## 5. MCP SDK Streamable HTTP + FastAPI 통합 현실성

[심각도: critical] 스펙의 FastAPI mount snippet은 현재 SDK/FastAPI 패턴으로는 그대로 구현하기 어렵거나 깨질 가능성이 높습니다.  
인용: 스펙 4.2는 `from mcp.server.streamable_http import StreamableHTTPSessionManager`, `router.mount("", session_manager.handle_request, dependencies=[Depends(...)])`를 제안합니다(`docs/...design.md:195-218`). 공식 Python SDK README는 v1.x를 current stable로 문서화하고, Streamable HTTP mount 예시는 `FastMCP.streamable_http_app()`를 `Starlette.routing.Mount`로 붙이고 session manager lifespan을 실행합니다(공식 SDK README: https://github.com/modelcontextprotocol/python-sdk, lines 306-308, 1405-1409, 1488-1504). 공식 예제/이슈 코드에서 low-level manager import path는 `mcp.server.streamable_http_manager`입니다. FastAPI의 sub-application 문서도 top-level `app.mount("/subapi", subapi)` 패턴을 설명합니다(https://fastapi.tiangolo.com/advanced/sub-applications/, lines 238-263).  
제안: `APIRouter.mount(..., dependencies=...)` 형태를 버리세요. `create_app()`에서 `application.mount("/mcp", authenticated_mcp_asgi_app)`로 직접 마운트하고, FastAPI lifespan에서 MCP session manager를 실행하는 설계로 바꾸세요. 가능하면 `FastMCP(..., streamable_http_path="/")` + `mcp.streamable_http_app()`를 우선 검토하세요.

[심각도: critical] 인증을 FastAPI `Depends`로 mount에 거는 설계는 안전하지 않습니다.  
인용: 스펙 4.2의 인증은 mount call의 `dependencies=[Depends(verify_mcp_key)]`에 의존합니다(`docs/...design.md:214-218`). Streamable HTTP는 같은 endpoint에서 POST/GET/DELETE를 처리합니다(공식 MCP spec: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports, lines 101-103, 118-125, 137-140, 167-178). Mount된 ASGI app은 하위 app이 직접 요청을 처리하므로 FastAPI path operation dependency 모델과 다릅니다.  
제안: ASGI middleware/wrapper에서 `Authorization: Bearer ...`를 검증하고 실패 시 401을 반환하세요. `/api/mcp/jobs/{id}/zip`도 같은 verifier를 쓰되, mount된 MCP endpoint와 별도로 테스트해야 합니다.

[심각도: high] Streamable HTTP 보안 요구사항 중 Origin 검증이 빠져 있습니다.  
인용: 공식 MCP Streamable HTTP spec은 DNS rebinding 방어를 위해 모든 incoming connection의 `Origin` 검증을 MUST로 둡니다(https://modelcontextprotocol.io/specification/2025-06-18/basic/transports, lines 105-113). 현재 스펙은 Bearer 인증만 언급합니다(`docs/...design.md:107-110`, `193-218`).  
제안: `MCP_ALLOWED_ORIGINS` 또는 localhost-only 정책을 추가하고, 로컬 배포에서는 `Origin` absent/localhost만 허용하는 규칙을 명시하세요. Docker가 `0.0.0.0`에 바인드되어 있다는 점도 같이 고려해야 합니다(`viewer/Dockerfile:19`).

[심각도: medium] `mcp>=1.0.0`은 너무 넓습니다.  
인용: 공식 README는 v1.x를 current stable이라고 하며 최신 release는 v1.27.1로 표시됩니다(https://github.com/modelcontextprotocol/python-sdk, lines 306-308, 2390-2393). 스펙은 `mcp>=1.0.0`만 둡니다(`docs/...design.md:498-504`).  
제안: 최소한 `mcp>=1.27,<2`로 v1 범위를 고정하고, 구현 시 사용한 SDK API (`FastMCP.streamable_http_app`, `streamable_http_path`, auth 방식)에 맞춘 smoke test를 Docker build에 포함하세요.

[심각도: medium] 공식 SDK는 자체 OAuth resource server 인증 경로도 제공합니다. 단순 API key가 불가능한 것은 아니지만, 스펙은 그 선택을 명확히 해야 합니다.  
인용: 공식 SDK README는 `mcp.server.auth`와 `TokenVerifier` 기반 OAuth 2.1 resource server 방식을 설명합니다(https://github.com/modelcontextprotocol/python-sdk, lines 1065-1122).  
제안: v1은 단순 Bearer API key로 충분하다고 명시하되, SDK auth helper를 쓰지 않는 이유와 그에 따른 수동 처리 범위(Authorization, Origin, 401/403, CORS expose header)를 적으세요.

## 추가 발견사항

[심각도: medium] `include_pdf`는 submit option으로 두기보다 result/download option으로만 두는 편이 맞습니다.  
인용: `include_pdf`는 처리 파이프라인에 영향을 주지 않고 zip 구조에만 영향을 줍니다(`docs/...design.md:107-119`, `153-158`, `341-371`).  
제안: `submit_paper.options.include_pdf`는 제거하고 `get_job_result`/download query의 기본값으로만 관리하세요. 저장하고 싶다면 `default_include_pdf`라는 이름으로 의미를 좁히세요.

[심각도: medium] MCP `download_url`의 base URL 자동 추론은 MCP tool call context에서 애매합니다.  
인용: 스펙은 `MCP_PUBLIC_BASE_URL`이 비어 있으면 `request.url_for()`를 쓴다고 합니다(`docs/...design.md:248-260`). 하지만 `get_job_result`는 MCP tool handler 내부이고 FastAPI `Request`가 직접 주입되는 구조가 아닙니다.  
제안: tool handler에서 ASGI request 접근 방식을 SDK context로 검증하거나, v1에서는 `MCP_PUBLIC_BASE_URL`을 필수로 만드는 편이 단순합니다. 최소한 reverse proxy/host header 신뢰 정책을 명시하세요.

[심각도: low] `/api/mcp/jobs/{job_id}/zip` 경로는 기존 `/api/papers/{name:path}` 계열과 충돌하지 않습니다.  
인용: 현재 `api.py`의 greedy paper 라우트는 `/api/papers/...` 아래에만 있습니다(`viewer/app/routers/api.py:41` 이후).  
제안: zip endpoint는 별도 router에 두고 `api.router`에 섞지 않으면 회귀 리스크가 더 낮습니다.

## 전체 평가

방향성은 좋지만, 현재 스펙은 v1 구현 전에 고쳐야 할 구조적 문제가 있습니다. 가장 큰 문제는 "기존 watch 파이프라인 무변경"과 "per-job translate/web_search 옵션", "실패 sidecar 기반 reconcile"이 동시에 성립하지 않는다는 점입니다. 또한 MCP Streamable HTTP mount/auth 코드는 공식 SDK/FastAPI 패턴과 맞지 않아 실제 구현에서 import/runtime failure 또는 인증 우회 리스크가 큽니다. 파일명 고유성, partial file 노출, arXiv cache miss, stale error attach도 v1에서 바로 사용자-visible 장애로 이어질 가능성이 높습니다.

## v1 ship 권고/보류

**보류 권고.** 위 critical/high 항목을 스펙에 반영한 뒤 구현에 들어가는 것이 맞습니다. v1을 작게 유지하려면 per-job pipeline 옵션을 제거하고, 고유 expected_filename + atomic queue publish + robust reconcile + 검증된 MCP ASGI mount/auth만 먼저 ship하는 범위로 줄이세요.

## 참고 소스

- MCP Python SDK README: https://github.com/modelcontextprotocol/python-sdk
- MCP Streamable HTTP specification: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- FastAPI sub-applications documentation: https://fastapi.tiangolo.com/advanced/sub-applications/
