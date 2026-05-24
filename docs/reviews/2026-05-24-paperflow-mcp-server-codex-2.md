# Codex Round 2 Review: PaperFlow MCP Server v1 Design Spec

검토 대상:
- `docs/superpowers/specs/2026-05-24-paperflow-mcp-server-design.md` (spec rev 2)
- `docs/reviews/2026-05-24-paperflow-mcp-server-codex.md` (Round 1)
- 관련 코드: `viewer/app/services/papers.py`, `viewer/app/routers/api.py`, `viewer/app/config.py`, `viewer/app/main.py`, `main_terminal.py`, `run_batch_watch.sh`

## 1. Round 1 Critical/High 해결 여부

### 해결됨

- ✅ per-request `translate` / `web_search` 옵션 제거는 해결입니다.  
  근거: rev2는 전역 `config.json`만 따른다고 명시합니다(`docs/...design.md:15`, `38`, `697`). 현재 `main_terminal.py`는 매 실행마다 config를 읽고 pipeline을 구성합니다(`main_terminal.py:2851-2863`).

- ✅ `main_terminal.py`에 `raise`를 넣는 계획은 폐기되어 기존 watch 경로 변경 위험이 크게 줄었습니다.  
  근거: rev2는 `main_terminal.py` 0줄 변경을 hard constraint로 둡니다(`docs/...design.md:48`, `194`, `441-445`, `651`). 현재 실패 경로는 `return False`이며 raise하지 않습니다(`main_terminal.py:3135-3140`).

- ✅ expected_filename 충돌 문제는 방향상 해결입니다.  
  근거: `pfmcp-{job_id[:12]}-{slug}.pdf`로 고유 prefix를 둡니다(`docs/...design.md:18`, `116`, `126`, `241-244`). 기존 `web-{slug}-{초단위}.pdf` 충돌 위험(`viewer/app/services/papers.py:238-243`)보다 낫습니다.

- ✅ partial PDF 노출 문제는 해결입니다.  
  근거: `.part` write → fsync → `os.replace`를 명시합니다(`docs/...design.md:19`, `118`, `241-242`, `575-576`). watch는 `newones/*.pdf`만 봅니다(`run_batch_watch.sh:183-208`).

- ✅ FastAPI `Depends`를 mount에 직접 거는 rev1 문제는 큰 방향에서 해결입니다.  
  근거: rev2는 ASGI middleware를 사용합니다(`docs/...design.md:20`, `296-328`, `331`).

- ✅ SDK 버전 범위는 개선되었습니다.  
  근거: `mcp>=1.27,<2`로 고정합니다(`docs/...design.md:22`, `449-450`). 공식 SDK README도 v1.x를 current stable로 문서화합니다.

- ✅ `MCP_PUBLIC_BASE_URL` 필수화, single-tenant 명시, quarantine 정책은 Round 1 지적을 반영했습니다.  
  근거: base URL 필수(`docs/...design.md:23`, `401-424`, `668-672`), single-tenant(`docs/...design.md:42`, `551-565`, `687-691`), corrupt index quarantine(`docs/...design.md:26`, `237-240`, `577`, `614`).

### 잔존 이견

- ⚠️ [심각도: high] MCP endpoint 경로가 공식 SDK mount 패턴과 여전히 어긋날 가능성이 큽니다.  
  인용: rev2는 클라이언트가 `POST/GET /mcp`로 붙는다고 하고(`docs/...design.md:60`, `677-682`), 구현 예시는 `inner = mcp.streamable_http_app(); app.mount("/mcp", inner)`입니다(`docs/...design.md:320-328`). 공식 Python SDK 예시는 `Mount("/echo", echo_mcp.streamable_http_app())`일 때 클라이언트 URL이 `/echo/mcp`가 된다고 설명하며, mount root에 붙이려면 `settings.streamable_http_path = "/"`를 설정하라고 합니다.  
  제안: `FastMCP("paperflow", stateless_http=True, json_response=True, streamable_http_path="/")` 또는 `mcp.settings.streamable_http_path = "/"`를 명시하세요. 아니면 등록 URL을 `http://localhost:8090/mcp/mcp`로 고쳐야 합니다. 이건 구현 전 반드시 닫아야 합니다.

- ⚠️ [심각도: high] zip endpoint 인증 설명이 서로 충돌합니다.  
  인용: Download flow는 `/api/mcp/jobs/{job_id}/zip`도 "ASGI middleware가 Bearer 검증"한다고 합니다(`docs/...design.md:151-153`). 하지만 나중에는 ASGI middleware는 `/mcp` mount에만 적용되고 zip은 자체 Depends/검증자라고 정정합니다(`docs/...design.md:397`). snippet도 `Depends`가 아니라 `request: Request = None` 뒤 `_verify_bearer(request, ...)` 수동 호출입니다(`docs/...design.md:373-382`).  
  제안: zip endpoint는 `@mcp_zip_router.get(..., dependencies=[Depends(verify_mcp_key)])` 또는 `request: Request` + 명시 검증 중 하나로 단일화하세요. "ASGI middleware가 이미 처리" 주석은 삭제해야 합니다.

- ⚠️ [심각도: high] `safe_paper_dir` 호출 signature가 실제 코드와 다릅니다.  
  인용: rev2 snippet은 `paper_svc.safe_paper_dir(paper_info["name"], paper_info["location"])`를 호출합니다(`docs/...design.md:390`). 현재 함수는 `safe_paper_dir(name: str) -> Path | None` 단일 인자입니다(`viewer/app/services/papers.py:735-751`).  
  제안: snippet을 `paper_svc.safe_paper_dir(paper_info["name"])`로 고치세요. location 강제가 필요하면 새 helper를 별도로 설계해야 합니다.

- ⚠️ [심각도: high] `find_processed_paper(original_filename=expected_filename)`만으로 complete 매핑하는 것은 metadata 단계에 강하게 의존합니다.  
  인용: rev2 reverse lookup과 reconcile은 `find_processed_paper(original_filename=expected_filename)`를 핵심으로 둡니다(`docs/...design.md:123`, `137`, `386`). 현재 `original_filename`은 `extract_paper_metadata()` 안에서만 `paper_meta.json`에 기록됩니다(`main_terminal.py:1103-1130`). metadata 단계가 disabled/skipped/failure여도 markdown 변환만 성공하면 전체 처리는 success로 끝날 수 있습니다(`main_terminal.py:2975-3017`, `3127-3133`). `main()`은 마지막에 idle status를 덮어씁니다(`main_terminal.py:3302-3303`).  
  제안: reconcile에 fallback을 추가하세요. 예: outputs/archives 하위 폴더 중 `(paper_dir / expected_filename).is_file()`인 폴더를 찾기. 기존 cancel cleanup도 같은 식으로 output 폴더를 찾습니다(`viewer/app/services/papers.py:1310-1314`). 이 fallback 없이는 config/LLM 상태에 따라 정상 산출물이 있어도 MCP job이 error가 될 수 있습니다.

- ⚠️ [심각도: medium] Origin 검증은 추가됐지만 기본값이 permissive라 MCP spec의 MUST 요구와 긴장이 남습니다.  
  인용: `MCP_ALLOWED_ORIGINS` empty면 `{"*"}`입니다(`docs/...design.md:417-421`, `668-672`, `687-691`). MCP Streamable HTTP spec은 DNS rebinding 방어를 위해 모든 incoming connection의 Origin 검증을 MUST로 둡니다.  
  제안: MCP enabled 상태에서는 기본 allowed origin을 `MCP_PUBLIC_BASE_URL`의 origin과 localhost 계열로 제한하세요. 외부 노출 시 "명시 권장"이 아니라 "명시 필요"가 더 맞습니다.

## 2. rev2가 만든 새 문제

### 신규 발견

- [심각도: high] Dockerfile 의존성 설치 예시가 shell redirection으로 깨질 수 있습니다.  
  인용: `RUN pip install --no-cache-dir mcp>=1.27,<2`(`docs/...design.md:447-450`). Dockerfile shell form에서 `>`/`<`는 redirection으로 해석될 수 있습니다.  
  제안: `RUN pip install --no-cache-dir 'mcp>=1.27,<2'`로 quote 하거나 `viewer/requirements.txt`에 추가하세요. 기존 Dockerfile은 이미 requirements를 설치합니다(`viewer/Dockerfile:12-13`).

- [심각도: high] URL submit은 여전히 MCP tool call 자체가 오래 걸릴 수 있습니다.  
  인용: rev2 submit은 job 생성 후 URL→PDF 다운로드를 수행하고, 다운로드가 끝난 뒤에야 `queued`를 반환합니다(`docs/...design.md:112-121`). 기존 URL flow는 direct candidates 각각 35초, headless fallback 60초까지 갈 수 있습니다(`viewer/app/services/papers.py:251-350`).  
  제안: "비동기 + job_id 폴링"의 timeout 회피 목표를 URL 다운로드 단계에도 적용하려면 job을 먼저 `downloading`/`queued`로 저장하고 background task가 PDF를 publish해야 합니다. v1에서 background downloader를 피하려면 URL submit이 최악 수십 초 걸릴 수 있음을 명시하고 E2E timeout 기준을 둬야 합니다.

- [심각도: medium] cleanup background task가 lifespan 종료 시 취소되지 않습니다.  
  인용: `asyncio.create_task(_periodic_mcp_cleanup())`만 있고 task handle cancel/await가 없습니다(`docs/...design.md:340-346`).  
  제안: lifespan에서 task handle을 보관하고 `finally: task.cancel(); await suppress(CancelledError)` 패턴을 명시하세요. reload/test 환경에서 task 누수가 납니다.

- [심각도: medium] `mcp_errors/{job_id}.json` 설계가 남아 있지만 writer가 없습니다.  
  인용: architecture와 reconcile은 `logs/mcp_errors/{job_id}.json`을 검사합니다(`docs/...design.md:85`, `136`, `591-595`, `615-617`). 반면 4.8은 추가 sidecar 불필요, `processing_status.json.error`를 1차 소스로 신뢰한다고 합니다(`docs/...design.md:441-445`).  
  제안: converter 변경 0줄을 유지하려면 `mcp_errors`를 submit/write/zip 계층의 MCP 자체 오류용으로 한정한다고 문서화하거나, 아예 제거하고 JobRecord.error만 쓰세요.

- [심각도: medium] `_resolve_url_to_pdf_bytes()` 추출은 기존 `import_url_as_paper()`와 1:1이 아닙니다.  
  인용: helper는 bytes를 반환한다고 되어 있습니다(`docs/...design.md:430-436`). 하지만 기존 흐름의 headless fallback은 Chromium이 파일 경로로 PDF를 쓰고, quality gate는 그 파일을 `PyPDF2`로 읽습니다(`viewer/app/services/papers.py:316-390`).  
  제안: helper 내부 temp file 전략을 명시하세요. 예: `tempfile.NamedTemporaryFile(dir=settings.newones_dir, suffix=".pdf")`로 기존 file-based quality gate를 수행한 뒤 bytes를 읽고 temp를 삭제. 그렇지 않으면 기존 behavior 동일이라는 주장이 약합니다.

## 3. 여전히 약한 부분

### 잔존 이견

- [심각도: high] Open Question 1은 ship 차단입니다.  
  인용: spec이 핵심 mount/auth 경로로 `user_middleware.insert` 후 `build_middleware_stack()` 재호출을 쓰고(`docs/...design.md:320-328`), Open Question에서 이 안정성을 POC 필요라고 인정합니다(`docs/...design.md:710`).  
  판단: 이건 구현 세부가 아니라 MCP endpoint의 인증/동작 자체입니다. v1 spec sign-off 전에 안전한 ASGI wrapper 방식으로 확정하는 편이 맞습니다.

- [심각도: low] Open Question 2는 거의 해결된 것으로 봅니다.  
  인용: 기존 guard는 arXiv abs URL + `original_filename.startswith("web-")`일 때만 적용됩니다(`viewer/app/services/papers.py:631-670`). rev2 expected filename은 `pfmcp-`입니다(`docs/...design.md:116`, `126`).  
  판단: `pfmcp-`와 직접 충돌은 없습니다. 다만 기존 viewer URL import의 `web-` cache를 얼마나 배제할지는 product decision입니다.

- [심각도: medium] Open Question 3은 ship 차단은 아니지만 E2E 필수입니다.  
  인용: converter output folder는 input filename stem에서 시작합니다(`main_terminal.py:2845-2876`) 후 metadata title로 rename될 수 있습니다(`main_terminal.py:2991-3007`). `pfmcp-` filename은 처리 자체에는 큰 문제 없어 보입니다.  
  제안: E2E에서 `pfmcp-...pdf`가 `paper_meta.original_filename`에 보존되고, final folder 안에 원본 PDF가 이동되는지 확인하세요.

## 4. 공식 SDK 패턴 정합성

### 해결됨

- ✅ `FastMCP(..., stateless_http=True, json_response=True)` 선택은 공식 SDK 권장 방향과 맞습니다.  
  근거: 공식 Python SDK README는 Streamable HTTP production 배포에 `stateless_http=True`와 `json_response=True`를 권장하고, Starlette `Mount(..., app=mcp.streamable_http_app())` + `mcp.session_manager.run()` lifespan 패턴을 예시합니다.

- ✅ `mcp>=1.27,<2` 범위도 합리적입니다.  
  단, Dockerfile에는 quote가 필요합니다.

### 잔존 이견

- [심각도: high] mount path는 반드시 고쳐야 합니다.  
  인용: rev2는 `/mcp`로 mount하면서 inner app path를 root로 바꾸지 않습니다(`docs/...design.md:320-328`). 공식 SDK 예시는 이 경우 하위 `/mcp`가 붙는 패턴입니다.  
  제안: `streamable_http_path="/"`를 코드에 포함하세요.

- [심각도: high] middleware 주입은 wrapper로 바꾸는 편이 맞습니다.  
  인용: rev2 스스로 POC 필요를 인정합니다(`docs/...design.md:710`).  
  제안: 다음 형태로 확정하세요.
  ```python
  inner = mcp.streamable_http_app()

  async def authenticated_mcp(scope, receive, send):
      if scope["type"] == "http":
          # validate Authorization + Origin using raw headers
          ...
      await inner(scope, receive, send)

  app.mount("/mcp", authenticated_mcp)
  ```
  이 방식은 Starlette app internals(`user_middleware`, `middleware_stack`)를 사후 변경하지 않습니다.

- [심각도: medium] top-level `from .routers import mcp_router`는 opt-in의 "노출 0"과는 별개로 "비활성 시 MCP 코드 영향 0"은 아닙니다.  
  인용: rev2는 이를 알고도 허용한다고 합니다(`docs/...design.md:337-364`).  
  제안: `mcp` dependency를 항상 설치할 계획이면 치명적이지 않습니다. 그래도 가장 엄격한 opt-in을 원하면 `if settings.mcp_enabled:` 내부 lazy import로 바꾸세요.

## 5. 최종 v1 Ship 결정

### 해결됨 목록

- per-request pipeline 옵션 제거
- main_terminal.py 0줄 변경으로 정상/실패 경로 보존
- job_id 기반 expected_filename
- `.part` publish로 partial file 방지
- FastAPI Depends mount 폐기
- SDK 버전 범위 고정
- `MCP_PUBLIC_BASE_URL` 필수화
- single-tenant 명시
- corrupt JSON quarantine
- archive 이동 정상 처리 / delete 410 방향

### 잔존 이견 목록

- [high] MCP mount endpoint가 `/mcp`가 아니라 `/mcp/mcp`가 될 수 있음
- [high] zip endpoint 인증 설계/주석/snippet 불일치
- [high] `safe_paper_dir` 실제 signature와 spec snippet 불일치
- [high] complete reconcile이 `paper_meta.original_filename`에 과의존함
- [high] URL submit이 tool call timeout 회피 목표를 완전히 만족하지 못함
- [high] `user_middleware` 사후 변경은 Open Question 상태라 sign-off 전 확정 필요
- [medium] permissive Origin default
- [medium] cleanup background task cancellation 미정
- [medium] `_resolve_url_to_pdf_bytes()` temp-file/quality-gate 보존 전략 미정
- [medium] `mcp_errors` sidecar 용도 불명확

### 신규 발견 목록

- Dockerfile `mcp>=1.27,<2` unquoted install line
- SDK default streamable path와 `/mcp` mount의 endpoint mismatch
- URL download phase가 synchronous라 job polling 전에 timeout 가능
- current code 기준 metadata 실패/비활성 시 MCP job-output mapping 실패 가능
- `safe_paper_dir(name, location)` snippet TypeError

## 전체 평가

rev2는 Round 1의 큰 설계 결함 대부분을 제대로 수용했습니다. 특히 converter 무변경, 고유 파일명, atomic publish, per-job pipeline 옵션 제거는 방향이 맞습니다. 다만 MCP mount path/auth 구현, output reconcile fallback, URL submit timeout, 몇 가지 snippet 불일치가 남아 있어 "그대로 구현 가능" 상태는 아닙니다. 대부분은 스펙을 작게 고치면 해결되는 항목입니다.

## Ship/Hold 결정

**추가 라운드 필요.** v1 ship 보류 사유는 `/mcp` endpoint mismatch, zip 인증 불일치, `safe_paper_dir` signature mismatch, metadata 의존 reconcile, middleware Open Question 미해결입니다.

## 참고한 공식 문서

- MCP Python SDK README: https://github.com/modelcontextprotocol/python-sdk
- MCP Streamable HTTP specification: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
