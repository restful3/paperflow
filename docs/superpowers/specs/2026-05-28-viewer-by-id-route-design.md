# PaperFlow `/viewer/by-id/{source_id}` 안정 식별자 라우트 — 설계

_작성: 2026-05-28 KST · 상태: 승인됨 (구현 대기)_

## 1. 배경 / 문제

MCP `get_job_result` 가 반환하는 `viewer_url` 은 현재 `{base}/viewer/{quote(paper_name)}` 형태다. `paper_name` 은 PaperFlow 폴더명으로, **영속 식별자가 아니다**:

- smart folder rename 이 `status==complete` 이전에 일어남 (`main_terminal.py:3174-3208`)
- complete 이후에도 manual archive/restore/delete/rename, 동일 제목 재처리 suffix(`-2`, `-3`), TTL cleanup 으로 이름이 이동할 수 있음

따라서 장기 보고서에 박힌 `viewer_url` 은 폴더명이 바뀌는 순간 깨진다 (CLAUDE.md gotcha #14).

`paperflow_source_id` (= `expected_filename`, 형식 `pfmcp-{job_id[:12]}-{slug[:40]}.pdf`) 는 job 당 durable key 다. 이 값을 받아 현재 폴더로 해석해주는 라우트를 두면, 보고서 링크가 rename 에 영향받지 않는다.

## 2. 목표 / 비목표

**목표**

- `GET /viewer/by-id/{source_id}` 라우트 신설 → source_id 를 현재 폴더로 해석해 기존 viewer 로 302 redirect
- MCP `get_job_result.viewer_url` 을 이 by-id 형태로 교체
- 폴더 rename / archive↔outputs 이동 후에도 동일 source_id 가 올바른 폴더로 해석됨

**비목표 (별도 follow-up)**

- DNS rebinding-proof SSRF (HANDOFF #5)
- 외부 노출 운영 정책 문서화 (HANDOFF #6)
- in-progress(미완료) job 의 by-id 해석 — resolver 는 완료된 폴더만 찾으므로 자동으로 not-found 처리
- `viewer_url` 의 auth-required 성질 자체를 바꾸는 것 (여전히 로그인 필요 — 본 PR 범위 밖)

## 3. 접근법 결정

해석기(resolver) 배치에 대해 3 안을 검토했다:

- **A (채택)**: `mcp_jobs.py` 에 얇은 public wrapper `resolve_paper_by_source_id` 추가, 기존 private `_resolve_completed_candidate` 의 4-step priority 를 재사용. `pages.py` 가 이 public 함수 호출. 최소 diff, round-1/round-2 에서 검증된 resolver 를 건드리지 않음.
- **B (기각)**: resolver + 스캔 헬퍼 3개를 `papers.py` 로 이전. "올바른 집" 이지만 큰 diff, 회귀 위험.
- **C (기각)**: `pages.py` 에 스캔 로직 중복. DRY 위반.

레이어링: `pages` → `mcp_jobs` 서비스 호출은 허용 (mcp_jobs 는 서비스 모듈).

## 4. 상세 설계

### 4.1 새 라우트 — `viewer/app/routers/pages.py`

```python
def _by_id_redirect(target: str) -> RedirectResponse:
    resp = RedirectResponse(target, status_code=302)
    resp.headers["Cache-Control"] = "no-store"
    return resp

@router.get("/viewer/by-id/{source_id}", response_class=HTMLResponse)
async def viewer_by_id(source_id: str, request: Request,
                       user: str | None = Depends(get_current_user_page)):
    if not user:
        return _by_id_redirect("/login")
    resolved = mcp_jobs.resolve_paper_by_source_id(source_id)
    if not resolved:
        return _by_id_redirect("/papers")
    paper_name, _location = resolved
    return _by_id_redirect(f"/viewer/{quote(paper_name, safe='')}")
```

`no-store` 를 성공/`/papers`/`/login` **모든** by-id redirect 에 일관 적용한다 (negative lookup·race 도 캐시되지 않도록).

- **라우트 등록 순서**: `/viewer/by-id/{source_id}` 를 `/viewer/{paper_name:path}` **보다 먼저** 선언해야 한다. `:path` 컨버터는 `by-id/...` 까지 통째로 매칭하므로, 순서가 뒤바뀌면 by-id 가 일반 viewer 로 흡수된다. (실제 폴더명이 정확히 `by-id` 일 가능성은 `pfmcp-` slug 규칙상 사실상 없음.)
- **302 (temporary) + `Cache-Control: no-store`**: rename 추적이 항상 최신 폴더로 가도록, 클라이언트/프록시가 redirect 를 영구 캐시하지 않게.
- **인증**: 기존 viewer 와 동일 — cookie 기반, 비로그인 시 `/login` 리다이렉트.
- **not found**: `/papers` 리다이렉트 (기존 `viewer_page` 의 `info is None` 동작과 일치).
- `pages.py` 는 `from ..services import mcp_jobs` import 추가.

### 4.2 해석기 + 검증 — `viewer/app/services/mcp_jobs.py`

```python
# source_id == paperflow_source_id == expected_filename, 형식이 항상
# pfmcp-{job_id[:12]}-{slug[:40]}.pdf 로 고정 (_build_expected_filename).
# contract 에 맞춰 prefix/suffix 까지 검증 → 임의 안전 파일명(paper_meta.json,
# foo.pdf, .hidden) probing 표면 차단.
_SOURCE_ID_SAFE_RE = re.compile(r"^pfmcp-[A-Za-z0-9._-]{1,120}\.pdf$")

def _is_safe_source_id(source_id: str) -> bool:
    if not source_id or source_id in (".", ".."):
        return False
    if "/" in source_id or "\\" in source_id or "\x00" in source_id:
        return False
    return bool(_SOURCE_ID_SAFE_RE.match(source_id))

def resolve_paper_by_source_id(source_id: str) -> tuple[str, str] | None:
    """Public: map a durable paperflow_source_id (== expected_filename) to
    (paper_name, location). Validates source_id against path traversal +
    the pfmcp-...pdf contract, then reuses the 4-step
    _resolve_completed_candidate priority. Disk-based — works beyond the MCP
    job-index TTL."""
    if not _is_safe_source_id(source_id):
        return None
    return _resolve_completed_candidate(source_id)
```

**보안 — path traversal 방어가 필수인 이유**: `_resolve_completed_candidate` → `_scan_outputs_dir_only` / `_scan_archives_dir_only` 가 `(sub / source_id).is_file()` 로 경로를 조인한다. source_id 가 `../` 나 `%2F`(디코드 시 `/`) 를 포함하면 outputs/archives 밖 파일을 탐지할 수 있다. `_is_safe_source_id` 가 이 입력을 거른다. (metadata match 경로는 문자열 `==` 비교라 그 자체로 안전하지만, scan 경로 때문에 입력 검증이 필요.)

**contract tightening 이 안전한 이유**: MCP job 은 source PDF 를 `expected_filename`(= `pfmcp-...pdf`) 이름으로 newones/ 에 두고 (`mcp_jobs.py:156`), `main_terminal.py:1293` 이 `original_filename` 을 그 PDF basename(= `pfmcp-...pdf`) 으로 기록한다. 따라서 metadata-match (`original_filename == source_id`) 와 filesystem-scan (`(sub / source_id).is_file()`) **둘 다** pfmcp 파일명으로 동작한다 → prefix/suffix 검증이 정상 해석을 깨지 않는다. by-id 라우트는 `viewer_url`(= `rec.expected_filename` 기반) 로만 공급되므로 non-pfmcp source_id 가 들어올 정상 경로가 없다.

**`%2F` 실제 동작 (정정)**: FastAPI `{source_id}` (no `:path`) 는 raw `/` 를 세그먼트로 매칭하지 않는다. uvicorn 이 `%2F` 를 `/` 로 디코드한 뒤 라우팅하므로 `/viewer/by-id/a%2Fb.pdf` 는 by-id 핸들러에 도달하지 **않지만 404 가 아니다** — 현재 앱은 catch-all `/viewer/{paper_name:path}` 가 `by-id/a/b.pdf` 를 통째로 흡수해 `viewer_page(paper_name="by-id/a/b.pdf")` 로 떨어진다. 거기서 `safe_paper_dir` → `_is_safe_paper_name` 이 `/` 를 거부(`papers.py:800`)하므로 인증 요청은 `/papers` 302, 비인증은 `/login` 302 가 된다. by-id 핸들러 자체에 도달하는 traversal 검증은 `%2e%2e` 같은 encoded dot segment 케이스로 테스트한다. 어느 경로든 `_is_safe_source_id` 가 defense-in-depth 로 파일시스템 접근 전에 비정상 입력을 거른다.

**범위 밖 hardening (구현 안 함, 후속)**: `_scan_*_dir_only` 의 `(sub / source_id).is_file()` 는 child file symlink 를 따라간다. remote traversal 은 아니고(폴더는 `_is_safe_direct_child` 가 이미 방어), threat model 에 "untrusted local filesystem writes" 가 포함될 때만 의미가 있다. 본 라우트는 단일 테넌트 self-hosted viewer 대상이라 이 위협은 모델 밖이고, `_scan_*` 함수는 reconcile 경로와 공유되므로 수정 시 blast radius 가 본 PR 범위를 넘는다 → 별도 follow-up 으로 남긴다.

### 4.3 MCP `viewer_url` 교체 — `viewer/app/routers/mcp_router.py`

```python
# 변경 전:
# viewer_url = f"{base}/viewer/{quote(rec.paper_name, safe='')}"
# 변경 후:
viewer_url = f"{base}/viewer/by-id/{quote(rec.expected_filename, safe='')}"
```

- `rec.expected_filename` 은 submit 시 항상 생성되므로 None 위험 없음 (`JobRecord.expected_filename` 은 required field; 누락 record 는 `model_validate` 단계에서 이미 실패).
- `get_job_result` docstring 의 `viewer_url` 설명 갱신: "stable by-id link — 폴더 rename/archive 에 영향받지 않음. **opaque URL — 소비자는 paper_name 을 파싱하면 안 되고, 최종 viewer 도달에는 302 redirect-follow 가 필요하다.** 여전히 AUTH-REQUIRED (비로그인 → /login). base 가 localhost 면 host-local."

**계약 변경 (breaking) 명시**: `viewer_url` 형식이 `/viewer/{paper_name}` → `/viewer/by-id/{source_id}` 로 바뀐다.

- redirect 를 따라가는 소비자(브라우저 클릭, redirect-follow HTTP client): 영향 없음 — 최종 viewer 에 도달.
- `viewer_url.split("/viewer/", 1)[1]` 로 paper_name 을 파싱하던 소비자: **깨진다.** 더 이상 paper_name 이 노출되지 않음 (durable id 인 `paperflow_source_id` 가 별도 필드로 이미 제공됨).
- redirect 를 따르지 않는 소비자: 최종 HTML 대신 302 만 받음.
- 알려진 소비자 점검 결과: **QuantSquad `paperflow-source-intake` SKILL.md 는 `viewer_url` 을 보고서 표에 마크다운 링크로 embed 만 하고 paper_name 을 파싱하지 않음 → 영향 없음** (SKILL.md:124, 100, 161 확인). 단 PaperFlow repo 밖 working-tree 파일이라 본 PR 에서 수정하지 않음.

### 4.4 문서 보강

- **CLAUDE.md gotcha #12** (viewer_url auth): "이제 `/viewer/by-id/{source_id}` 형태 — rename 추적됨. auth-required 성질은 동일" 로 갱신.
- **CLAUDE.md gotcha #14** (paper_name 비영속): "`viewer_url` 이 이제 `paperflow_source_id` 기반 → `/viewer/by-id/{source_id}` → 302 → 현재 폴더. rename 안전" 추가.
- **README** MCP 섹션 contract 표의 `viewer_url` 행 갱신.

## 5. 데이터 흐름

```
보고서 링크 클릭: GET /viewer/by-id/pfmcp-abc123def456-attention-is-all.pdf
  → 비로그인? → 302 /login
  → resolve_paper_by_source_id(source_id)
       _is_safe_source_id?  (no → None → 302 /papers)
       _resolve_completed_candidate:
         1. outputs metadata match (original_filename == source_id)
         2. outputs filesystem scan ((sub / source_id).is_file())
         3. archives metadata match
         4. archives filesystem scan
       → (paper_name, location) | None
  → None? → 302 /papers
  → 302 /viewer/{quote(paper_name)}  +  Cache-Control: no-store
  → 기존 viewer_page 가 렌더 (location-aware get_paper_info)
```

## 6. 테스트 (TDD — 구현 전 작성, 실패 확인 후 구현)

신규 `viewer/tests/test_viewer_by_id.py` (+ `test_mcp_router.py` 에 viewer_url 케이스):

| # | 케이스 | 기대 |
|---|--------|------|
| T1 | 유효 source_id(`pfmcp-...pdf`), 로그인 | 302 → `/viewer/{quoted name}`, `Cache-Control: no-store` |
| T2 | source_id 가 archives 폴더에 해당 (T23/T24 패턴: archives 에 source PDF, outputs 에 다른 이름) | 302 → archives 폴더명 (location-aware) |
| T3 | 비로그인 | 302 → `/login`, `Cache-Control: no-store` |
| T4 | 없는(미해석) source_id | 302 → `/papers`, `Cache-Control: no-store` |
| T5a | 단위: `_is_safe_source_id` / `resolve_paper_by_source_id` 에 비정상 입력 (`../etc`, `..`, `a/b`, `a\b`, 빈 문자열, 길이 120 초과, `%`·공백·unicode·NUL 포함) | 모두 거부(None), 파일시스템 미접근 |
| T5b | 단위/라우트: contract 위반 안전 파일명 (`paper_meta.json`, `foo.pdf`, `.hidden`, prefix·suffix 불일치) | 거부(None) → 라우트는 302 `/papers` |
| T5c | 라우트: encoded dot segment `%2e%2e` 가 핸들러에 도달 | resolver None → 302 `/papers` |
| T5d | 라우트: encoded slash `/viewer/by-id/a%2Fb.pdf` (catch-all fallback) | by-id resolver **미호출**, 인증 시 302 `/papers` (현재 앱 동작; **404 아님**) |
| T6 | rename 시뮬레이션: 폴더명 변경 후에도 동일 source_id → 새 폴더 | 302 → 새 이름 |
| T7 | `resolve_paper_by_source_id` 단위: 4-step priority (outputs metadata → outputs scan → archives metadata → archives scan) |
| T8 | route order regression: `/viewer/by-id/{valid}` 가 반드시 by-id 핸들러를 타고 catch-all 로 흡수되지 않음 (등록 순서 역전 시 실패) |
| T9 | `get_job_result.viewer_url` == `{base}/viewer/by-id/{quote(expected_filename)}` |
| T10 | 기존 T20/T22 갱신: viewer_url 이 더 이상 paper_name 기반이 아님. T22(`test_get_job_result_viewer_url_quotes_spaces_and_korean`) 는 expected_filename-based URL 테스트로 재작성 — 공백/한글 paper_name 은 이제 viewer_url 에 반영되지 않는 것이 정상 |
| T11 | 기존 `/viewer/{paper_name}` 페이지 라우트 regression: 정상 paper_name 이 계속 렌더/기존 redirect 동작 유지 (최소 1개) |

**회귀 방지**: T8(route order) + T10(viewer_url 계약) + T11(기존 viewer 라우트). 기존 viewer/MCP 테스트 전수 재실행.

검증 목표: `cd viewer && pytest` → 기존 139 (T20/T22 갱신 반영) + 신규 케이스 모두 passed, 회귀 0건.

**해석 불가 케이스 (수용)**: source PDF 도 없고 `paper_meta.json.original_filename` 도 없는 과거 산출물은 by-id 로 찾을 수 없다. 새 MCP 결과 링크는 source PDF 또는 metadata 가 보존된다는 전제이므로 수용 가능.

**구현 시 테스트 주의 (Codex round-2 ACCEPT 노트)**:

- **T5d**: `resolve_paper_by_source_id` 가 **미호출**됨을 monkeypatch/mock 으로 직접 검증하고, `follow_redirects=False` 로 최종 status/location 확인.
- **T8**: 유효 `pfmcp-...pdf` 에 대해 by-id resolver 가 **호출됨**을 (mock spy) 확인해야 route 순서 회귀를 확실히 잡음.
- **T10**: 기존 T20/T22 의 paper_name URL round-trip 기대를 **완전히 제거**하고, non-ASCII paper_name 이 viewer_url 에 포함되지 않음을 정상으로 assert.
- **T11**: 로그인 dependency override 나 테스트 cookie 를 명시해 기존 `/viewer/{paper_name}` 의 인증 redirect 케이스와 정상 렌더 케이스가 섞이지 않게 함.

## 7. 영향 파일

- `viewer/app/routers/pages.py` — 새 라우트 + `_by_id_redirect` 헬퍼 + mcp_jobs import (라우트는 `/viewer/{paper_name:path}` **위**에 선언)
- `viewer/app/services/mcp_jobs.py` — `_SOURCE_ID_SAFE_RE` / `_is_safe_source_id` / `resolve_paper_by_source_id`
- `viewer/app/routers/mcp_router.py` — viewer_url 한 줄 + docstring (opaque/redirect-follow 명시)
- `viewer/tests/test_viewer_by_id.py` (신규: T1–T8, T11), `viewer/tests/test_mcp_router.py` (T9 신규 + **T20/T22 기존 케이스 갱신**)
- `CLAUDE.md`, `README.md` — 문서 보강 (#12/#14 + MCP contract 표)

**후속(본 PR 범위 밖)**: child file symlink hardening (`_scan_*_dir_only`), DNS rebinding-proof SSRF, 외부 노출 운영 정책 문서화.
