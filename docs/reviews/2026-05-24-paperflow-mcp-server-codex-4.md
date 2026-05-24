# Codex Round 4 Review: PaperFlow MCP Server v1 Design Spec

검토 대상:
- `docs/superpowers/specs/2026-05-24-paperflow-mcp-server-design.md` (spec rev 4)
- Round 1-3 리뷰 및 관련 코드

## 1. Round 3 잔존 이견 8개 확인

### 해결됨

- ✅ HTML fallback temp file watch 충돌은 해결됨.  
  근거: temp file 위치가 `newones/.mcp_tmp/` 하위로 이동했습니다(`docs/...design.md:18`, `557-577`, `775`). `run_batch_watch.sh`는 `newones` root에서 `-maxdepth 1 -name "*.pdf"`만 처리하므로 하위 폴더의 `.pdf`는 watch 대상이 아닙니다(`run_batch_watch.sh:183-208`).

- ✅ `_resolve_url_to_pdf_bytes()` blocking I/O의 event loop 차단은 해결 방향입니다.  
  근거: URL downloader가 `await asyncio.to_thread(papers._resolve_url_to_pdf_bytes, url)`를 사용한다고 명시합니다(`docs/...design.md:19`, `150-152`, `772`).

- ✅ Download 인증 설명 불일치는 해결됨.  
  근거: Download step 1이 FastAPI `Depends(verify_mcp_key)`로 정리됐고(`docs/...design.md:198-200`), 4.5도 같은 구조입니다(`docs/...design.md:470-507`).

- ✅ Origin 기본값 문구 불일치는 해결됨.  
  근거: config, `.env`, Security Notes 모두 empty 값은 `MCP_PUBLIC_BASE_URL` origin + localhost derive이고 explicit `*`만 permissive라고 설명합니다(`docs/...design.md:511-548`, `875-879`, `889-891`).

- ✅ shutdown cancel과 user cancel의 의미 구분은 해결됨.  
  근거: `cancel_all_active_downloads(reason)`가 추가됐고 shutdown은 error, user는 cancelled로 구분합니다(`docs/...design.md:22`, `288-290`, `435-436`, `731-732`, `774`).

- ✅ obsolete `mcp_errors` sidecar 테스트는 제거됨.  
  근거: 테스트 12/13이 reconcile 우선순위와 metadata-skip fallback으로 대체됐습니다(`docs/...design.md:770-771`).

- ✅ `_active_download_tasks` cleanup 규칙은 추가됨.  
  근거: `task.add_done_callback(lambda _: _active_download_tasks.pop(job_id, None))`가 명시됐습니다(`docs/...design.md:157-162`).

- ✅ ASGI wrapper의 scope 접근 hardening은 반영됨.  
  근거: `scope.get("type")`를 사용합니다(`docs/...design.md:361-365`).

### 잔존 이견

- ⚠️ [심각도: high] `_write_part_then_publish`가 `async def`로 정의되어 있는데 `asyncio.to_thread()`에 넘기는 모순이 남았습니다.  
  인용: Data Flow는 `await asyncio.to_thread(_write_part_then_publish, pdf_bytes, dest)`를 호출합니다(`docs/...design.md:151-152`, `170-175`). 하지만 Components의 private API는 `async def _write_part_then_publish(...)`로 선언되어 있습니다(`docs/...design.md:292-297`). `asyncio.to_thread()`는 동기 callable을 실행하는 API라 async function을 넘기면 coroutine object만 반환하고 write/fsync/replace가 실행되지 않습니다.  
  제안: `_write_part_then_publish`를 `def _write_part_then_publish(...) -> None`로 바꾸세요. 또는 async 함수로 유지하려면 `to_thread` 호출을 제거하고 내부에서 blocking 구간만 별도 sync helper로 넘겨야 합니다.

## 2. rev4가 만든 새 문제

### 신규 발견

- [심각도: high] downloading cancel 중 publish 단계가 이미 `to_thread`에 들어가면 cancelled job이 `.pdf`로 publish될 수 있습니다.  
  인용: background task는 `await asyncio.to_thread(_write_part_then_publish, pdf_bytes, dest)`에서 `.part` write와 `os.replace(.part → .pdf)`를 한 번에 수행합니다(`docs/...design.md:151-155`). Error Handling은 `task.cancel()` 후 `CancelledError` 핸들러가 `.part` cleanup한다고 합니다(`docs/...design.md:731-732`). 하지만 `asyncio.to_thread()` 내부 작업은 task cancellation으로 즉시 중단되지 않습니다. cancel이 publish thread 실행 중 발생하면 thread가 끝까지 `os.replace`를 실행할 수 있고, watch가 cancelled job의 PDF를 처리할 수 있습니다.  
  제안: publish를 두 단계로 나누세요. 예: `await asyncio.to_thread(_write_part_file, pdf_bytes, part_path)`는 `.part` write/fsync만 수행하고, coroutine 복귀 후 job이 아직 downloading인지 lock 아래 확인한 뒤 `os.replace(part_path, dest)`를 짧게 실행합니다. cancel/shutdown은 state를 먼저 cancelled/error로 바꾸고 `.part`를 삭제합니다. 이렇게 하면 cancellation 이후 `.pdf` 노출이 없습니다.

- [심각도: medium] `.mcp_tmp/` stale cleanup 정책은 아직 명시가 부족합니다.  
  인용: helper는 정상/예외 시 `tmp_path.unlink(missing_ok=True)`를 수행합니다(`docs/...design.md:571-577`). 하지만 viewer crash, process kill, host reboot 시 `.mcp_tmp` 아래 파일이 남을 수 있습니다.  
  제안: `cleanup_expired_jobs()` startup path에서 `newones/.mcp_tmp/*` 중 mtime이 충분히 오래된 파일을 삭제하도록 명시하세요. watch 충돌은 없으므로 ship blocker는 아니지만 운영 청소 정책은 필요합니다.

- [심각도: low] File submit의 `to_thread` 추가는 과하지 않습니다.  
  판단: 200MB write/fsync는 환경에 따라 수십 ms 이상 걸릴 수 있어 event loop 밖으로 빼는 것이 더 보수적입니다. 단, 위의 `async def`/`to_thread` 모순은 같이 고쳐야 합니다.

### 해결됨

- `to_thread` 도입 자체는 FastMCP lifespan과 충돌하지 않습니다. 작업이 default executor에서 돌고, coroutine은 event loop에서 job state를 관리하면 됩니다.
- `.mcp_tmp/` 위치는 watch `-maxdepth 1`과 충돌하지 않습니다.

## 3. 공식 SDK 패턴 정합성

### 해결됨

- ✅ `FastMCP(..., stateless_http=True, json_response=True, streamable_http_path="/")` + `app.mount("/mcp", wrapped)` 조합은 공식 SDK 패턴과 맞습니다. Round 3의 `/mcp/mcp` 우려는 닫혔습니다.

- ✅ `mcp.session_manager.run()`을 FastAPI lifespan에서 감싸는 구조는 공식 예시와 일치합니다(`docs/...design.md:389-393`, `418-438`).

- ✅ raw ASGI wrapper로 `mcp.streamable_http_app()`을 감싸는 방식은 Starlette middleware stack 사후 변경보다 안전합니다(`docs/...design.md:361-399`).

### 잔존 이견

- SDK 패턴 자체에는 추가 이견 없습니다. 남은 문제는 SDK가 아니라 mcp_jobs의 background publish/cancel 설계입니다.

## 4. v1 Ship 보류 사유 여부

### 해결됨

- Round 3의 temp file 위치, URL resolve blocking, zip 인증 설명, origin 문구, shutdown/user cancel 의미, stale test plan, active task cleanup, ASGI scope hardening은 반영됐습니다.

### 잔존 이견

- [high] `_write_part_then_publish`의 `async def` 선언과 `asyncio.to_thread()` 호출이 충돌합니다.
- [high] cancel/shutdown 중 `to_thread(_write_part_then_publish)`가 이미 publish 중이면 cancelled/error job의 `.pdf`가 queue에 노출될 수 있습니다.
- [medium] `.mcp_tmp/` stale file cleanup 정책이 startup cleanup에 포함되어야 합니다.

### 신규 발견

- `to_thread`는 coroutine cancellation으로 worker thread를 중단하지 않는다는 점 때문에 `.part` write와 `.pdf` publish를 하나의 sync helper에 묶으면 cancel race가 생깁니다.

## 전체 평가

rev4는 Round 3의 대부분을 잘 닫았습니다. MCP/FastAPI/SDK 통합 설계는 이제 안정적인 방향입니다. 다만 queue publish는 PaperFlow watch와 직접 맞닿는 핵심 경계라 더 엄격해야 합니다. 현재 스펙 그대로 구현하면 async helper가 실행되지 않는 구현 버그가 생기거나, cancel/shutdown 시 cancelled job이 `.pdf`로 노출될 수 있습니다. 이 두 항목은 작은 설계 수정으로 해결 가능합니다.

## Ship 결정

**추가 소규모 라운드 필요.** v1 ship 보류 사유는 `_write_part_then_publish`의 async/to_thread 모순과 cancel 중 publish race입니다.
