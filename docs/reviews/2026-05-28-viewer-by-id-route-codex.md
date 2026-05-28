# PaperFlow `/viewer/by-id/{source_id}` 설계 리뷰

판정: **REFINE**

핵심 방향(302 redirect, `viewer_url` by-id 교체, `mcp_jobs.py` public wrapper로 기존 resolver 재사용)은 타당합니다. 다만 spec 4.2의 `%2F` 라우팅 설명이 현재 앱 구조와 다르고, 그에 맞춘 테스트 기대값을 조정해야 합니다. 보안 설계는 path traversal 방어 관점에서는 대체로 충분하지만, contract를 `pfmcp-...pdf`로 더 좁힐지와 symlink 파일 스캔 방어를 명시하면 더 깔끔합니다.

## 주요 지적

### 1. spec 4.2 `%2F` 설명은 현재 라우트 구성 기준으로 부정확함

spec 4.2는 “uvicorn 이 `%2F` 를 `/` 로 디코드한 뒤 라우팅하므로 `%2F` 포함 경로는 보통 라우터 레벨에서 404 처리되어 핸들러에 도달하지 않는다”고 설명합니다.

설치된 FastAPI/Starlette 환경에서 재현한 결과, `/viewer/by-id/{source_id}`를 `/viewer/{paper_name:path}`보다 먼저 등록해도 `/viewer/by-id/a%2Fb.pdf`는 by-id 핸들러에는 도달하지 않지만, 404가 아니라 기존 catch-all route인 `/viewer/{paper_name:path}`에 매칭됩니다. 즉 `viewer_page(paper_name="by-id/a/b.pdf")`로 떨어지는 형태입니다.

현행 `viewer_page`는 `paper_svc.get_paper_info()`를 거치고, `safe_paper_dir()`가 `/`를 포함한 paper name을 거부하므로 인증된 요청은 최종적으로 `/papers` 302가 될 가능성이 높습니다. 비로그인 요청이면 기존 viewer route 인증 로직에 의해 `/login` 302입니다.

수정 권고:

- spec 4.2의 “라우터 레벨 404”를 “by-id 핸들러에는 도달하지 않고, 현재 앱에서는 `/viewer/{paper_name:path}` fallback에 매칭된 뒤 기존 viewer 안전 검사로 `/papers` 또는 `/login` 처리된다”로 바꾸세요.
- 테스트 T5/T7 쪽에 encoded slash 케이스를 추가하고, 기대값을 404가 아니라 현재 앱 동작에 맞춰 `302 /papers` 또는 `302 /login`로 두세요.
- raw `/viewer/by-id/..`는 클라이언트/서버 정규화로 다르게 처리될 수 있습니다. by-id 핸들러 도달을 검증하려면 `%2e%2e` 같은 encoded dot segment를 별도 케이스로 쓰는 편이 더 안정적입니다.

### 2. spec 4.1 라우트 등록 순서 주장은 맞음

spec 4.1의 “`/viewer/by-id/{source_id}`를 `/viewer/{paper_name:path}`보다 먼저 선언해야 한다”는 주장은 맞습니다. Starlette 라우팅은 선언 순서의 영향을 받으며, `{paper_name:path}`는 `by-id/abc.pdf`를 통째로 흡수할 수 있습니다.

검증 결과:

- by-id first: `/viewer/by-id/abc.pdf` → by-id route
- path first: `/viewer/by-id/abc.pdf` → 기존 viewer path route

수정 권고:

- 구현 시 실제 decorator 위치를 기존 `/viewer/{paper_name:path}` 위에 두세요.
- T1 또는 별도 regression test에서 `/viewer/by-id/{valid_source_id}`가 기존 viewer route로 흡수되지 않음을 통합 테스트로 확인하세요.

### 3. spec 4.2 source_id path traversal 방어는 원격 입력 기준으로 충분함

`_is_safe_source_id`의 정규식 `^[A-Za-z0-9._-]{1,128}$`와 `/`, `\\`, `.`, `..` 거부는 `(sub / source_id).is_file()` 경로 조인을 안전한 단일 path component로 제한합니다. NUL byte도 정규식에서 탈락하고, percent-encoded slash는 ASGI 레이어에서 slash로 디코드되면 by-id handler의 단일 segment parameter로 들어오지 않습니다.

따라서 원격 사용자가 `../`, encoded slash, backslash 등으로 outputs/archives 밖 파일을 탐색시키는 path traversal 벡터는 이 설계로 막힙니다. 기존 `_is_safe_direct_child(base, sub)`가 스캔 대상 paper folder도 direct child로 제한하고 있어 폴더 symlink escape도 이미 막습니다.

남은 hardening 포인트:

- spec 1과 4.2가 `source_id` 형식을 `pfmcp-{job_id[:12]}-{slug[:40]}.pdf`로 정의하므로, public route 입력도 가능하면 이 contract까지 검증하는 편이 더 좋습니다. 지금 정규식은 `paper_meta.json`, `foo`, `.hidden` 같은 임의의 안전 파일명도 허용합니다. path traversal은 아니지만, authenticated 사용자가 paper folder 내부 파일명 존재 여부를 by-id redirect 여부로 probing할 수 있는 표면을 넓힙니다.
- `_scan_*_dir_only`의 `(sub / source_id).is_file()`은 child file symlink를 따라갑니다. remote traversal은 아니지만, threat model에 “untrusted local filesystem writes”가 포함된다면 `candidate = sub / source_id`에 대해 `candidate.is_file() and not candidate.is_symlink()` 또는 `candidate.resolve().parent == sub.resolve()` 같은 추가 조건을 고려하세요.

권고 수준:

- full `pfmcp-...pdf` pattern 검증: 권장. 단, 과거 테스트/레거시 데이터에 `src.pdf` 같은 expected_filename이 남아 있고 public route까지 지원해야 한다면 migration 범위를 먼저 확인하세요.
- child file symlink 방어: low priority hardening. 현재 설계의 핵심 보안 결함은 아닙니다.

### 4. spec 4.1 302 + `Cache-Control: no-store`는 적절함

rename/archive 추적 목적상 301은 부적절합니다. target folder name이 시간에 따라 바뀌는 것이 이 feature의 핵심이므로 302가 맞고, redirect response에 `Cache-Control: no-store`를 붙이는 판단도 맞습니다.

수정 권고:

- 성공 redirect뿐 아니라 invalid/not-found의 `/papers` redirect에도 `no-store`를 붙이는 것을 고려하세요. 302는 기본적으로 영구 캐시되지는 않지만, negative lookup이나 race 상황까지 보수적으로 다루려면 by-id route가 반환하는 모든 redirect에 동일하게 no-store를 붙이는 편이 일관됩니다.
- `/login` redirect에도 no-store를 붙일지는 기존 인증 UX와 맞추면 됩니다. 필수는 아닙니다.

### 5. spec 6 테스트 커버리지는 방향은 좋지만 몇 가지 케이스가 빠짐

T1-T8은 핵심 happy path, archives, auth, missing, traversal, rename, resolver priority, MCP `viewer_url` 교체를 커버하므로 기본 골격은 충분합니다. 다만 현재 라우팅/계약 리스크를 잡으려면 아래를 추가하는 편이 좋습니다.

추가 권고:

- spec 4.1/6: route order regression. `/viewer/by-id/{valid}`가 반드시 by-id handler를 타는지 확인하세요. path-first 회귀가 나면 테스트가 깨져야 합니다.
- spec 4.2/6: encoded slash fallback. `/viewer/by-id/a%2Fb.pdf`가 by-id resolver를 호출하지 않고 기존 viewer 안전 검사 결과로 처리되는지 확인하세요. 기대값은 현재 앱 기준 404가 아니라 authenticated `302 /papers`입니다.
- spec 4.2/6: encoded dot segment. raw `..` 대신 `%2e%2e`가 by-id handler에 도달했을 때 resolver가 None을 반환하고 `/papers`로 가는지 확인하세요.
- spec 4.2/6: regex boundary. 빈 문자열은 route로 만들기 어렵기 때문에 resolver 단위 테스트로 두고, 128자 초과, `%`, whitespace, unicode, NUL에 해당하는 입력은 unit test로 검증하세요.
- spec 4.2/6: full pattern을 채택한다면 `pfmcp-...pdf`가 아닌 안전 파일명(`paper_meta.json`, `foo.pdf`)이 거부되는 테스트를 추가하세요.
- spec 4.2/6: file symlink hardening을 채택한다면 paper folder 안의 source_id symlink가 외부 파일을 가리킬 때 resolve되지 않아야 한다는 테스트를 추가하세요.
- spec 4.3/6: 기존 `test_get_job_result_viewer_url_quotes_spaces_and_korean`는 이제 paper_name quoting 테스트가 아니라 expected_filename based URL 테스트로 바뀌어야 합니다. non-ASCII paper_name은 `viewer_url`에 더 이상 반영되지 않는 것이 정상입니다.
- spec 6: 기존 `/viewer/{name}` route regression test가 현재 거의 없어 보입니다. `/viewer/{quoted paper_name}`가 계속 렌더 또는 기존 redirect 동작을 유지하는지 최소 1개는 추가하세요.

### 6. spec 4.3 하위호환/계약 변경은 명시를 더 강하게 해야 함

`viewer_url`을 병행 필드 없이 교체하는 결정은 이미 승인된 전제이므로 재논쟁하지 않습니다. 다만 contract change는 실제 breaking change입니다.

영향:

- `viewer_url`을 opaque browser URL로만 쓰는 소비자는 대체로 문제 없습니다. 302를 따라가면 기존 viewer에 도달합니다.
- `viewer_url.split("/viewer/", 1)[1]`처럼 URL에서 `paper_name`을 파싱하던 소비자는 깨집니다.
- HTTP client가 redirect를 따르지 않는 소비자는 최종 viewer HTML 대신 302만 보게 됩니다.
- 기존 테스트 T20/T22의 기대값은 반드시 업데이트되어야 합니다.

수정 권고:

- spec 4.3/4.4에 “`viewer_url`은 opaque URL이며 소비자는 paper_name을 파싱하면 안 된다. 최종 viewer 접근에는 redirect follow가 필요하다”를 명시하세요.
- QuantSquad skill 등 알려진 MCP 소비자가 viewer_url을 파싱하는지 grep 또는 별도 확인 항목을 추가하세요. 설계상 병행 필드를 두지 않더라도 migration note는 필요합니다.
- README/CLAUDE 갱신 외에, MCP docstring에도 “stable by-id link, may redirect”를 명시하세요.

### 7. spec 4.3 `expected_filename` 존재 가정은 현재 코드 기준으로 맞음

`JobRecord.expected_filename`은 required field이고, `submit_job()`에서 `_build_expected_filename()`으로 항상 생성됩니다. `get_job_result()`는 `reconcile_job()` 후 `rec.expected_filename`을 사용하므로 정상 MCP job record라면 None 위험은 없습니다.

주의점:

- 오래된 손상 index나 수동 작성 record가 `expected_filename`을 누락하면 `JobRecord.model_validate()` 단계에서 이미 실패하는 쪽에 가깝습니다. 이 route 설계의 추가 문제는 아닙니다.
- TTL cleanup 이후에도 by-id route가 disk 기반 resolver로 동작한다는 목표는 `_resolve_completed_candidate()` 재사용과 잘 맞습니다. 다만 paper folder에 source PDF도 없고 `paper_meta.json.original_filename`도 없는 과거 산출물은 by-id로 찾을 수 없습니다. 새 MCP 결과 링크에 대해서는 expected source PDF 또는 metadata가 보존된다는 전제라면 수용 가능합니다.

## 결론

**REFINE** 권고입니다.

수정해야 할 필수 항목은 두 가지입니다.

1. spec 4.2의 `%2F` 동작 설명과 테스트 기대값을 현재 catch-all viewer route 기준으로 바로잡기.
2. spec 6에 route order 및 encoded slash fallback regression test를 추가하기.

그 외 full `pfmcp-...pdf` 입력 검증, child file symlink hardening, all-redirect `no-store`, consumer migration note는 강력 권고 또는 보완 권고입니다. 이 보완 후에는 설계 자체는 ACCEPT 가능하다고 봅니다.
