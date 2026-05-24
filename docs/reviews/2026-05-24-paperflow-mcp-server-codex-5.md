===CODEX_FINAL_APPROVAL===

# Codex Round 5 Review: PaperFlow MCP Server v1 Design Spec

검토 대상:
- `docs/superpowers/specs/2026-05-24-paperflow-mcp-server-design.md` (spec rev 5)
- `docs/reviews/2026-05-24-paperflow-mcp-server-codex-4.md`

## 1. Round 4 잔존 3개 확인

### 해결됨

- ✅ `_write_part_then_publish` async/to_thread 모순은 해결됨.  
  근거: rev5는 `_write_part_file`을 sync `def`로 분리하고, 이 함수만 `asyncio.to_thread`에서 호출한다고 명시합니다(`docs/...design.md:18`, `151-153`, `292-297`). `_atomic_publish_part`도 별도 sync helper로 분리됐습니다(`docs/...design.md:298-300`).

- ✅ cancel 중 publish race는 해결됨.  
  근거: publish가 Stage 1 `.part` write/fsync와 Stage 2 `os.replace`로 분리됐고, Stage 2는 `_index_lock` 안에서 `JobRecord.status == "downloading"`을 재확인한 뒤에만 publish합니다(`docs/...design.md:151-156`). cancelled 상태면 publish하지 않고 `.part`를 cleanup한다고 명시되어 있어, cancelled job의 `.pdf`가 watch queue에 노출되는 race가 닫혔습니다.

- ✅ `.mcp_tmp/` stale cleanup 정책은 해결됨.  
  근거: `_cleanup_stale_mcp_tmp(max_age_seconds=3600)`가 추가됐고, `cleanup_expired_jobs()` startup path에서 호출한다고 명시합니다(`docs/...design.md:20`, `301-303`, `745-751`). 1시간 기준은 Chromium fallback 60초 timeout보다 충분히 길어 정상 진행 중 파일을 지울 가능성이 낮습니다.

### 잔존 이견

- 없음.

## 2. rev5 신규 문제 검토

### 해결됨

- ✅ Stage 2 lock + status 재확인 + `os.replace`는 v1 single-worker 전제에서 race-free로 볼 수 있습니다.  
  cancel이 Stage 1 중 들어오면 status가 `cancelled`/`error`로 바뀌고, Stage 2에서 publish가 차단됩니다. cancel이 Stage 2 status check 이후 들어오면 이미 queue publish가 완료된 상태이므로 queued/processing cancel path로 넘어가는 것이 올바른 의미입니다.

- ✅ File submit에서 Stage 1/2 분리는 과하지 않습니다.  
  File submit은 background race가 없지만 200MB write/fsync는 blocking I/O입니다. `_write_part_file` 재사용 + `_atomic_publish_part` 호출은 단순하고 일관된 구현입니다.

- ✅ `_cleanup_stale_mcp_tmp(max_age_seconds=3600)`의 1시간 임계는 합리적입니다.  
  HTML fallback은 Chromium timeout 60초로 설계되어 있고, 정상 cleanup은 `finally`에서 수행됩니다. crash/kill 잔존 파일만 startup cleanup 대상이 됩니다.

### 신규 발견

- 없음.

## 3. 공식 SDK 패턴 정합성

### 해결됨

- ✅ `FastMCP(..., stateless_http=True, json_response=True, streamable_http_path="/")` + `mcp.streamable_http_app()` + ASGI mount 조합은 공식 Python SDK 패턴과 일치합니다. 공식 SDK 문서도 stateless/json response production 설정, `session_manager.run()` lifespan delegation, mount root endpoint를 위한 `streamable_http_path="/"` 설정을 안내합니다.

- ✅ raw ASGI wrapper로 Bearer + Origin을 처리하는 방식은 FastAPI `Depends`가 mounted sub-app에 적용되지 않는 문제를 회피합니다. `/api/mcp/jobs/{id}/zip`은 FastAPI route이므로 `Depends(verify_mcp_key)`를 쓰는 현재 분리도 타당합니다.

- ✅ `asyncio.to_thread`는 FastMCP lifespan과 충돌하지 않습니다. blocking URL resolve/write는 executor에서 돌고, job state transition은 event loop에서 lock으로 관리됩니다.

### 잔존 이견

- 없음.

## 4. v1 Ship 보류 사유 여부

### 해결됨

- Round 4의 high 2건과 medium 1건은 모두 닫혔습니다.
- 이전 라운드의 SDK mount/auth, origin guard, partial file exposure, URL submit timeout, metadata-skip reconcile, Docker dependency quote, cleanup task lifecycle 문제도 현재 spec에 반영되어 있습니다.

### 잔존 이견

- 없음.

### 신규 발견

- 없음.

## Ship 결정

**v1 ship 권고.** rev5는 구현 가능한 상태이며, 남은 항목은 구현/E2E 검증 단계에서 확인할 수 있는 정상 범위입니다.

## 참고 소스

- MCP Python SDK README: https://github.com/modelcontextprotocol/python-sdk
