# Codex Round 3 Review: PaperFlow MCP Server v1 Design Spec

검토 대상:
- `docs/superpowers/specs/2026-05-24-paperflow-mcp-server-design.md` (spec rev 3)
- Round 1/2 리뷰 및 관련 코드

## 1. Round 2 잔존 이견 10개 확인

### 해결됨

- ✅ MCP endpoint mismatch는 해결됨.  
  근거: `FastMCP(..., streamable_http_path="/")`가 명시됐고(`/docs/...design.md`, 4.3), `/mcp` mount root가 최종 endpoint라고 설명합니다. 공식 SDK README도 mount root endpoint를 원하면 `streamable_http_path="/"`를 설정하라고 합니다.  
  참고: MCP Python SDK README lines 1336-1339, 1484-1487, 1518-1524.

- ✅ `safe_paper_dir` signature mismatch는 해결됨.  
  근거: zip snippet이 `paper_svc.safe_paper_dir(job.paper_name)` 단일 인자로 바뀌었습니다. 실제 코드도 `safe_paper_dir(name: str)`입니다(`viewer/app/services/papers.py:735-751`).

- ✅ metadata 의존 reconcile은 해결 방향이 맞음.  
  근거: primary `find_processed_paper(original_filename=expected_filename)` 실패 시 outputs/archives 스캔 fallback이 추가됐습니다. 기존 cancel cleanup도 output folder 내 `filename` 존재 여부를 스캔하는 패턴입니다(`viewer/app/services/papers.py:1310-1314`).

- ✅ `user_middleware.insert + build_middleware_stack()` 불확실성은 해결됨.  
  근거: rev3는 raw ASGI wrapper를 채택하고 Starlette internals 사후 변경을 제거했습니다.

- ✅ Dockerfile dependency quote 문제는 해결됨.  
  근거: `viewer/requirements.txt` 추가를 권장하고, Dockerfile 직접 수정 시 `RUN pip install --no-cache-dir 'mcp>=1.27,<2'`로 quote가 들어갔습니다.

- ✅ cleanup task 누수는 해결됨.  
  근거: lifespan에서 task handle을 보관하고 shutdown 시 cancel/await/suppress하는 패턴이 추가됐습니다.

- ✅ `mcp_errors/{job_id}.json` 모호성은 해결됨.  
  근거: rev3는 mcp error sidecar를 폐기하고 `JobRecord.error` + `processing_status.json.error`로 단일화했습니다.

### 잔존 이견

- ⚠️ [심각도: medium] zip endpoint 인증 설명이 일부 남아 있는 자기모순을 아직 포함합니다.  
  인용: Data Flow의 Download 단계는 여전히 "`ASGI middleware`가 Bearer 검증"이라고 합니다. 하지만 4.5는 `/api/mcp/jobs/{id}/zip`이 FastAPI route이고 `Depends(verify_mcp_key)`가 인증한다고 정확히 정리했습니다.  
  제안: Download 단계 1번을 "`Depends(verify_mcp_key)`가 Bearer 검증"으로 고치세요. 구현 방향은 맞지만 spec 내부 불일치입니다.

- ⚠️ [심각도: medium] Origin 기본값 설명이 아직 문서 하단과 충돌합니다.  
  인용: 4.6은 empty `MCP_ALLOWED_ORIGINS`일 때 `MCP_PUBLIC_BASE_URL` origin + localhost 계열을 derive한다고 합니다. 반면 `.env` 예시와 Security Notes는 아직 "empty = permissive"라고 적습니다.  
  제안: deployment/security 문구를 4.6과 일치시키세요. explicit `*`만 permissive opt-out이라고 써야 합니다.

- ⚠️ [심각도: medium] URL submit timeout 문제는 "tool call은 즉시 반환" 측면에서는 해결됐지만, blocking downloader가 event loop를 막을 수 있습니다.  
  인용: background task가 `_resolve_url_to_pdf_bytes(url)`를 호출한다고만 되어 있고, helper는 `urllib`, `subprocess.run`, PyPDF2 등 동기 I/O를 포함합니다.  
  제안: `_download_and_publish()` 안에서 `await asyncio.to_thread(papers._resolve_url_to_pdf_bytes, url)`를 명시하세요. 그렇지 않으면 `create_task` 후 첫 실행 시 viewer event loop가 35-60초 이상 block될 수 있습니다.

## 2. rev3 신규 문제

### 신규 발견

- [심각도: high] `_resolve_url_to_pdf_bytes()`의 HTML fallback temp file 위치/확장자가 watch와 충돌합니다.  
  인용: rev3는 `tempfile.NamedTemporaryFile(dir=settings.newones_dir, suffix=".pdf", delete=False)`를 제안합니다. 하지만 watch는 `find newones -maxdepth 1 -name "*.pdf" -type f`로 즉시 처리합니다(`run_batch_watch.sh:183-208`). Chromium이 쓰는 임시 `.pdf`를 watch가 집어갈 수 있어, rev3의 `.part` publish 방어를 우회합니다.  
  제안: temp file은 `newones/.mcp_tmp/` 같은 하위 디렉터리 또는 suffix `.part`/`.tmp`로 생성하세요. watch가 `maxdepth 1`이라 하위 디렉터리면 안전합니다. 최종 queue publish만 `newones/{expected_filename}.pdf`로 `os.replace`하세요.

- [심각도: high] background downloader가 동기 I/O를 event loop에서 실행할 가능성이 큽니다.  
  인용: `_download_and_publish()`는 async로 정의됐지만 URL resolve helper는 동기 함수입니다. `urllib.request.urlopen`, `subprocess.run(... timeout=60)`, PDF text extraction은 모두 blocking입니다.  
  제안: download/quality gate 전체를 `asyncio.to_thread`로 감싸세요. file publish와 job status update만 event loop에서 수행하면 됩니다.

- [심각도: medium] active download task lifecycle에서 shutdown과 user cancel의 상태 의미가 섞일 수 있습니다.  
  인용: Error Handling은 viewer 재시작 중 downloading job을 error로 바꾼다고 하고, cancel_job(downloading)은 cancelled로 바꾼다고 합니다. 그런데 lifespan shutdown은 `cancel_all_active_downloads()`를 호출합니다.  
  제안: `cancel_all_active_downloads(reason="shutdown")`는 status를 `error` / "download interrupted, retry submit"로 남기고, user `cancel_job`만 `cancelled`로 남기도록 구분하세요.

- [심각도: low] `_active_download_tasks` dict 동시성은 single event loop 전제에서는 괜찮지만 done cleanup 규칙이 명시되지 않았습니다.  
  제안: task 생성 직후 `task.add_done_callback(lambda _: _active_download_tasks.pop(job_id, None))` 또는 finally cleanup을 명시하세요. dict 조작 자체는 single worker/single loop라 큰 문제는 아닙니다.

- [심각도: low] fallback O(N) scan은 v1 규모에서는 허용 가능합니다.  
  근거: outputs가 수백 개 수준이면 poll당 디렉터리 stat 수백 번은 감당 가능합니다. 다만 polling 주기가 짧은 클라이언트가 많으면 noisy해질 수 있습니다.  
  제안: primary miss 후에만 fallback scan하고, complete 매핑이 한번 성공하면 JobRecord에 `paper_name`을 저장해 반복 scan을 피하는 현재 방향을 유지하세요.

- [심각도: medium] 테스트 섹션에 제거된 error sidecar 테스트가 남아 있습니다.  
  인용: rev3는 `mcp_errors` sidecar를 폐기했는데, 테스트 12/13은 "error sidecar 우선", "stale error sidecar 무시"를 여전히 언급합니다.  
  제안: 해당 테스트를 `JobRecord.error` 및 `processing_status.json.error` 우선순위 테스트로 바꾸세요.

- [심각도: low] ASGI wrapper의 header parsing은 대체로 정확합니다.  
  근거: ASGI headers는 bytes pair이고, latin1 decode + lowercase key 처리는 HTTP header 처리에 적합합니다. duplicate `authorization`/`origin` header를 dict가 덮어쓰는 점은 이 용도에서는 큰 문제는 아닙니다.  
  제안: `scope["type"]` 접근은 `scope.get("type")`로 조금 더 방어적으로 써도 됩니다.

- [심각도: low] origin default derive는 기본 로컬/명시 base URL에는 충분합니다.  
  단, reverse proxy에서 browser client가 `Origin: https://paperflow.example.com`으로 접근한다면 `MCP_PUBLIC_BASE_URL`도 같은 origin이어야 합니다. 이 요구를 deployment note에 명확히 적으면 충분합니다.

## 3. 공식 SDK 패턴 정합성 최종 확인

### 해결됨

- ✅ `FastMCP(..., stateless_http=True, json_response=True)`는 공식 SDK 권장과 일치합니다.  
  근거: 공식 README는 Streamable HTTP production deployment에 `stateless_http=True`와 `json_response=True`를 권장합니다.  
  참고: MCP Python SDK README lines 1262-1275.

- ✅ `mcp.session_manager.run()`을 FastAPI/Starlette lifespan에 연결하는 패턴은 공식 예시와 일치합니다.  
  참고: MCP Python SDK README lines 1321-1327, 1405-1415.

- ✅ `streamable_http_path="/"` + `app.mount("/mcp", inner)` 조합은 공식 path configuration 예시와 일치합니다.  
  참고: MCP Python SDK README lines 1484-1504, 1518-1534.

- ✅ ASGI wrapper로 `mcp.streamable_http_app()`을 감싸는 방식은 SDK public ASGI app을 그대로 호출하므로 `user_middleware` 사후 변경보다 안전합니다.

### 잔존 이견

- [심각도: medium] wrapper와 SDK 자체 transport security가 중복/충돌하지 않는지는 E2E에서 확인해야 합니다.  
  근거: 공식 spec은 Streamable HTTP에서 Origin 검증을 MUST로 둡니다. SDK v1.x도 transport security 관련 동작이 있을 수 있으므로, wrapper 403과 SDK 403/400이 의도대로 나오는지 통합 테스트가 필요합니다.  
  참고: MCP spec lines 101-125 및 107-113.

## 4. v1 ship 보류 사유 여부

### 해결됨

- Round 2 high 항목 대부분은 설계상 닫혔습니다: endpoint path, wrapper auth, safe_paper_dir signature, reconcile fallback, downloader async return, dependency quote, cleanup task cancellation, mcp error sidecar 제거, origin default derive.

### 잔존 이견

- [high] HTML fallback temp `.pdf`가 `newones/` root에 생성되어 watch에 잡힐 수 있음
- [high] `_resolve_url_to_pdf_bytes()` blocking I/O를 event loop에서 실행할 수 있음
- [medium] zip 인증 설명의 Data Flow/4.5 불일치
- [medium] Origin default 문구의 4.6/Deployment/Security Notes 불일치
- [medium] shutdown cancel과 user cancel의 JobRecord status 구분 미정
- [medium] 제거된 error sidecar 테스트가 남아 있음

### 신규 발견

- watch와 temp PDF 충돌
- background downloader event-loop blocking
- graceful shutdown cancellation semantics 미정
- stale test plan 문구

## 전체 평가

rev3는 구조적으로 거의 구현 가능한 상태까지 왔습니다. SDK mount/auth 방향은 이제 공식 패턴과 맞고, 기존 PaperFlow 무변경 제약도 유지됩니다. 다만 `NamedTemporaryFile(... newones, suffix=".pdf")`는 실제 watch loop와 직접 충돌하는 high 이슈이고, 동기 downloader를 event loop에서 돌릴 가능성도 viewer responsiveness에 영향을 줍니다. 이 두 가지는 작은 스펙 수정으로 닫을 수 있지만, 현재 문서 그대로는 final approval을 주기 어렵습니다.

## Ship 결정

**추가 소규모 라운드 필요.** v1 ship 보류 사유는 temp `.pdf` watch 충돌과 blocking downloader의 event-loop blocking 가능성입니다.

## 참고 소스

- MCP Python SDK README: https://github.com/modelcontextprotocol/python-sdk
- MCP Streamable HTTP specification: https://mcp.mintlify.app/specification/2025-06-18/basic/transports
