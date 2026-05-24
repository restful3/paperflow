# Codex Review: Viewer Security Hardening Plan

검토 대상: `docs/superpowers/plans/2026-05-24-viewer-security-hardening.md`

관련 코드 기준:
- `viewer/app/config.py`
- `viewer/app/auth.py`
- `viewer/app/main.py`
- `viewer/app/services/papers.py`
- `viewer/app/services/web_search.py`
- `viewer/app/services/chat.py`
- `viewer/app/routers/pages.py`
- `viewer/app/routers/api.py`
- `.env.example`
- `CLAUDE.md`

## 결론

계획의 핵심 방향은 맞습니다. JWT 기본값 제거/placeholder 거부, `COOKIE_SECURE` 노출, paper name 단일 컴포넌트 제한 + `resolve().relative_to(base)` 조합, upload filename 단일 컴포넌트 제한은 각각 의도한 위협을 실질적으로 줄입니다.

다만 이 계획을 그대로 구현하기 전에 아래 4가지는 보완하는 것이 좋습니다.

1. 같은 High 후보로 `LOGIN_PASSWORD` 기본값/약한 값 startup guard를 같이 넣을지 결정해야 합니다. 8090 직접 노출 전제에서는 JWT placeholder만 막고 `admin/admin` 또는 `changeme`를 허용하는 것은 같은 급의 운영 실수입니다.
2. Markdown/assistant 응답 렌더링 XSS는 이 3~4개 이슈와 별개의 High 후보입니다. `x-html` + `marked.parse()` + allow-listed raw HTML이 sanitization 없이 동작합니다.
3. 수동 검증은 `..` traversal만 증명합니다. 이 계획의 핵심인 symlink escape 차단, archive/restore, markdown save, asset, chat POST/DELETE 경로를 추가로 검증해야 합니다.
4. 계획 문서 내부에서 `_safe_paper_dir`라고 부르지만 실제 snippet은 `safe_paper_dir`입니다. 구현자가 헷갈리지 않도록 용어를 통일해야 합니다.

## Findings

### High: 약한 `LOGIN_PASSWORD`를 scope-out하면 8090 직접 노출 운영에서 같은 급의 인증 우회 리스크가 남습니다

위치:
- Plan `Out of scope`, line 705
- Existing `viewer/app/config.py`, `LOGIN_ID=admin`, `LOGIN_PASSWORD=admin`
- Existing `.env.example`, `LOGIN_PASSWORD=changeme`

JWT secret guard는 "로그인 이후 토큰 위조"를 막지만, 8090이 직접 노출된 환경에서 기본/placeholder 로그인 비밀번호는 그보다 더 직접적인 인증 우회입니다. 특히 현재 `Settings` 기본값이 `admin/admin`이고 `.env.example`도 `changeme`라서 `.env` 누락 또는 예시값 복붙 시 운영자가 취약한 상태로 띄울 수 있습니다.

계획에는 "follow-up High"라고 적혀 있어 판단 자체는 정확하지만, 사용자가 말한 "3대 High" 범위라면 이 항목은 같은 우선순위로 포함하는 편이 더 일관됩니다. surgical하게 유지하려면 JWT와 같은 패턴으로 `LOGIN_PASSWORD`도 empty/short/placeholder/default guard만 추가하고, 해싱은 별도 plan으로 남기는 절충이 좋습니다.

권장 보완:

```python
_PASSWORD_PLACEHOLDER_SUBSTRINGS = (
    "admin",
    "changeme",
    "change-me",
    "password",
    "placeholder",
)
_PASSWORD_MIN_LENGTH = 12
```

단, 로컬 단일 사용자 환경에서 일부러 `admin`을 쓰는 워크플로가 있다면 breaking change입니다. 그 경우 최소한 `.env.example`과 `CLAUDE.md`에는 "직접 노출 금지"가 아니라 "startup에서 거부" 수준으로 명확히 바꾸는 것이 맞습니다.

### High: Markdown/assistant message XSS가 같은 viewer 보안 우선순위 후보입니다

위치:
- `viewer/app/templates/viewer.html:698`, `x-html="activeMdContent"`
- `viewer/app/templates/viewer.html:765`, `x-html="splitMdContent"`
- `viewer/app/templates/viewer.html:850`, `x-html="editPreviewHtml"`
- `viewer/app/templates/viewer.html:999`, `x-html="renderMarkdown(msg.content)"`
- `viewer/app/templates/viewer.html:1395-1405`, raw HTML allow-list
- `viewer/app/templates/viewer.html:1812`, `marked.parse(safeText)`
- `viewer/app/templates/viewer.html:2937`, `marked.parse(text)`

현재 viewer는 Markdown과 assistant 응답을 `marked.parse()` 후 `x-html`로 삽입합니다. `renderer.html`에서 일부 태그를 allow하지만 attribute-level sanitizer가 없습니다. 예를 들어 raw HTML의 `<img src=x onerror=...>`, `<a href="javascript:...">`, `style`/event handler류 속성, assistant가 반환한 HTML/Markdown이 DOM에 들어갈 수 있습니다. HTTPOnly 쿠키 때문에 토큰 탈취는 어렵더라도, 같은 origin에서 `fetch(..., credentials: 'same-origin')`로 archive/delete/upload/markdown update 같은 상태 변경은 가능합니다.

이 계획의 path traversal/JWT/cookie와 직접 같은 패치에 넣으면 범위가 커질 수 있으므로 별도 plan이어도 됩니다. 하지만 "High가 더 있었는가?"라는 질문에는 "있다"가 제 판단입니다. 최소 보완은 DOMPurify 도입 후 `marked.parse()` 결과와 KaTeX restore 결과를 sanitize하는 것입니다. `trust: true`인 KaTeX 옵션도 함께 재검토해야 합니다.

### Medium: verification이 symlink escape와 주요 호출자를 충분히 증명하지 않습니다

위치:
- Plan Task 3 Step 6, lines 504-540

Task 3의 핵심은 단순 문자열 `../` 차단뿐 아니라 `resolve()`가 symlink를 따라간 뒤 base 밖이면 거부하는 것입니다. 그런데 검증은 `..%2F..%2Fetc`만 확인합니다. 이러면 `_is_safe_paper_name()`만 검증되고, `_is_within(... resolve().relative_to(...))`의 핵심 동작은 증명되지 않습니다.

추가 권장 curl/쉘 검증:

```bash
# symlink escape: outputs 안의 이름은 안전해 보이지만 실제 대상은 밖
ln -sfn /etc outputs/pf-symlink-escape
curl -s -o /dev/null -w "symlink-info=%{http_code}\n" -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/pf-symlink-escape/info"
curl -s -o /dev/null -w "symlink-pdf=%{http_code}\n" -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/pf-symlink-escape/pdf"
rm -f outputs/pf-symlink-escape
# Expected: 404 / 404
```

또한 호출자 표에는 archive/restore/delete/pdf/md/assets/markdown/chat가 포함되어 있지만 실제 curl은 일부만 검증합니다. 최소한 아래를 추가하는 것이 좋습니다.

```bash
# archive / restore traversal
curl -s -o /dev/null -w "archive=%{http_code}\n" -X POST -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/..%2F..%2Fetc/archive"
curl -s -o /dev/null -w "restore=%{http_code}\n" -X POST -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/..%2F..%2Fetc/restore"
# Expected: 400 / 400

# markdown save traversal should not write outside paper dirs
curl -s -o /dev/null -w "markdown=%{http_code}\n" -X PUT -b "paperflow_token=$TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"content":"test"}' \
  "http://localhost:8090/api/papers/..%2F..%2Fetc/markdown/en"
# Expected: 400

# asset traversal under a valid paper
curl -s -o /dev/null -w "asset=%{http_code}\n" -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/$EXISTING_ENC/assets/..%2F..%2F..%2Fetc%2Fpasswd"
# Expected: 404

# chat DELETE traversal
curl -s -o /dev/null -w "chat-delete=%{http_code}\n" -X DELETE -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/..%2F..%2Fetc/chat/history"
# Expected: 404
```

`POST /api/papers/{name}/chat`는 현재 구조상 `EventSourceResponse` generator 내부에서 `ValueError`를 잡으면 HTTP status가 200이고 SSE error event를 보낼 수 있습니다. 파일 탈출은 막히지만 수동 검증에서 HTTP 404를 기대하면 안 됩니다. security behavior를 깔끔하게 증명하려면 `chat_with_paper()`에서 generator를 만들기 전에 `paper_svc.safe_paper_dir(name)`를 확인하고 invalid name은 즉시 `HTTPException(404)`로 끝내는 보완을 고려하세요.

### Medium: 계획 문서의 helper 이름이 불일치합니다

위치:
- Plan line 7: 신규 헬퍼 `_safe_paper_dir`
- Plan line 20: `_safe_paper_dir`
- Plan Task 3 Step 1: 실제 snippet은 `safe_paper_dir`
- Plan line 724: `safe_paper_dir(str) -> Path | None`

구현 snippet은 public helper `safe_paper_dir`를 만들고 `_resolve_paper_dir = safe_paper_dir` alias를 둡니다. 이 방향이 더 좋습니다. 문서 상단의 `_safe_paper_dir` 표현을 `safe_paper_dir`로 통일하세요. 특히 `web_search.py`에서 import할 public helper 이름과 plan 요약이 다르면 agentic worker가 `_safe_paper_dir`라는 별도 함수를 만들 가능성이 있습니다.

### Low: `main.py` Step 2는 import 추가를 명시해야 합니다

위치:
- Plan Task 1 Step 2, lines 126-149
- Existing `viewer/app/main.py`에는 `from .config import settings`가 없음

본문에는 "create_app body 첫 줄로 `settings.validate_runtime()` 추가"라고 되어 있고 예시에는 `from .config import settings`가 있습니다. 실제 구현 지시에는 import 추가가 명시되어야 합니다. 그렇지 않으면 `NameError`가 납니다.

수정 문구:

```python
from .config import settings

def create_app() -> FastAPI:
    settings.validate_runtime()
```

### Low: `safe_paper_dir()`는 unsafe symlink가 outputs에 있으면 archives의 정상 동명 paper를 shadow합니다

위치:
- Plan Task 3 Step 1, lines 393-399

현재 snippet은 outputs에서 `d.is_dir()`가 true인데 `_is_within()`이 false면 즉시 `return None`합니다. 즉 `outputs/<name>`이 base 밖 symlink이고 `archives/<name>`에 정상 paper가 있어도 archives까지 보지 않습니다. 보안상 안전한 실패이고 공격자가 outputs에 symlink를 만들 수 있어야 하므로 영향은 DoS에 가깝습니다.

원하면 다음처럼 `continue`로 바꿔 정상 archives를 찾을 수 있습니다.

```python
if not _is_within(base, d):
    continue
```

다만 "동일 이름의 unsafe entry가 보이면 전체 거부"라는 보수적 정책도 defensible합니다. 계획에 의도를 한 줄 적으면 됩니다.

### Low: upload filename helper를 delete/processing queue 계열과 공유하지 않아 정책이 갈라집니다

위치:
- Plan Task 4
- Existing `viewer/app/services/papers.py:1061`, `delete_uploaded_file`
- Existing `viewer/app/services/papers.py:1141`, `delete_queued_file`
- Existing `viewer/app/services/papers.py:1173`, `request_cancel_processing`

`/api/upload`만 `_safe_filename()`을 쓰고 기존 delete/cancel 경로는 `"/" in filename or "\\" in filename or ".." in filename`를 유지합니다. 보안상 큰 구멍은 아니지만 정책이 갈라지고 `paper..v1.pdf` 같은 합법적 이름을 delete/cancel할 수 없는 부수효과가 남습니다.

수술적 범위를 조금 넓혀도 된다면 `_safe_filename()`을 `safe_filename()` public helper로 만들고 `delete_uploaded_file`, `delete_queued_file`, `request_cancel_processing`에서도 재사용하는 것이 낫습니다.

## 질문별 검토

### 1. 정확성

Task 1 JWT secret:
- 기본값을 `""`로 바꾸고 startup에서 empty/short/placeholder를 거부하는 방향은 맞습니다.
- placeholder substring은 현재 repo 예시값을 막기에는 충분합니다. `change-me`, `changeme`, `replace-with`, `placeholder`, `your-secret`, `paperflow-secret`가 `.env.example`과 기존 기본값 계열을 커버합니다.
- `os.environ` vs pydantic Settings 로딩 타이밍은 큰 문제 없습니다. pydantic-settings는 일반적으로 실제 env var가 dotenv보다 우선합니다. `settings = Settings()`는 import 시 만들어지지만 `create_app()` startup에서 같은 객체를 검증하므로 Uvicorn/FastAPI 앱 경로는 fail-fast 됩니다.
- 단, `python -c "from viewer.app.auth import create_token; ..."`처럼 `create_app()`을 거치지 않는 별도 스크립트는 검증을 타지 않습니다. 운영 앱 기준으로는 acceptable입니다.

Task 2 cookie:
- `secure=settings.COOKIE_SECURE` 추가는 의도한 토글을 정확히 구현합니다.
- `SameSite=Lax` 유지도 "cross-site iframe/POST 미지원" 전제라면 맞습니다. cross-site iframe은 Lax로 쿠키가 안 가므로 지원 대상이 아닙니다. cross-site POST도 일반적으로 쿠키가 안 붙어 CSRF 방어에 유리합니다.
- `COOKIE_SECURE=true` 상태에서 HTTP `localhost:8090` 브라우저 로그인이 깨지는 것은 정상 동작입니다. 검증 절차에 "curl은 Set-Cookie 헤더만 확인하고, 브라우저 HTTP 세션 동작 검증은 false 복구 후 수행"이라고 적는 편이 좋습니다.

Task 3 path traversal:
- `name` 단일 컴포넌트 가드 + `resolve().relative_to(base.resolve())`는 POSIX/Linux Docker에서 우회하기 어렵습니다.
- `resolve()`가 symlink를 따라가는 점은 이 계획에서는 장점입니다. symlink가 base 밖을 가리키면 `relative_to()`가 실패해 차단됩니다.
- 빈 문자열, NUL, `/`, `\\`, `.`, `..` 차단이면 path traversal 목적에는 충분합니다. control char, leading/trailing space, `:` 등은 운영/UX 문제는 될 수 있지만 Linux Docker traversal 우회는 아닙니다.
- double-encoded slash는 `unquote()` 한 번 후 `%2F`라는 리터럴 이름으로 남기 때문에 filesystem separator가 되지 않습니다.

Task 4 upload filename:
- 단일 filename component만 허용하고 `settings.newones_dir / safe` 뒤 `_is_within()`을 한 번 더 확인하는 구조는 upload traversal을 막습니다.
- 확장자만 확인하고 PDF magic/content-type은 검증하지 않습니다. 이는 기존 동작 유지 관점에서는 surgical하지만, "악성/비PDF 업로드"는 별도 hardening 후보입니다.

### 2. 수술적 변경 / 부수효과

대체로 수술적입니다. 외부 API signature는 유지됩니다.

주의할 부수효과:
- 실제 `.env` secret 회전은 기존 세션을 모두 무효화합니다. plan에 이미 적혀 있고 맞습니다.
- `COOKIE_SECURE=true`는 HTTP 직접 접속에서 브라우저 로그인을 사실상 불가능하게 합니다. 로컬 검증 후 반드시 false로 되돌리는 절차가 있어 맞습니다.
- `_is_safe_paper_name()`은 slash가 들어간 이름을 전부 거부합니다. batch pipeline이 단일 디렉터리명만 만들기 때문에 정상입니다.
- `safe_paper_dir()`가 symlink escape를 거부하면 기존에 outputs/archives 안 symlink로 외부 paper 폴더를 연결해 쓰던 비공식 운영 방식은 깨집니다. 보안 변경으로는 타당합니다.

### 3. scope-out 판단

합리적인 scope-out:
- pytest 인프라 도입: 이번 계획에서 제외 가능. 다만 path helper만이라도 future follow-up에서 빠르게 단위 테스트화할 가치가 큽니다.
- HSTS/CSP/X-Frame-Options: reverse proxy에서 처리한다는 운영 전제가 명확하면 제외 가능. 단, XSS 이슈를 별도 처리할 때 CSP는 보조 방어로 같이 봐야 합니다.
- `secrets.token_urlsafe` 자동 생성: 제외가 맞습니다. 재시작마다 token invalidation이 아니라 signing key가 바뀌어 모든 세션이 끊기고 운영 의도가 불명확해집니다.
- Windows drive/colon/reserved names: Linux Docker 전용이면 제외 가능.
- 컨테이너 non-root: defense-in-depth로 별도 작업이 맞습니다.

재고 권장:
- `LOGIN_PASSWORD` weak/default guard는 이번 계획에 포함하는 편이 낫습니다. 해싱은 제외해도 되지만 startup guard는 JWT guard와 같은 성격입니다.

### 4. 검증 절차

좋은 점:
- JWT empty/short/placeholder/strong 네 케이스를 분리한 점은 좋습니다.
- Docker force-recreate로 env 반영을 확인하는 점도 좋습니다.
- Cookie `Secure` 플래그를 false/true 양쪽으로 확인하는 점도 좋습니다.
- Upload traversal에서 실제 외부 파일 미생성을 확인하는 점도 좋습니다.

빠진 케이스:
- symlink escape
- archive/restore traversal
- markdown save traversal
- asset filename traversal
- chat POST와 DELETE chat history
- `COOKIE_SECURE=true` 후 HTTP 브라우저 세션이 의도대로 불가하다는 운영 주의
- `main.py` import 누락 방지

검증 안정성 보완:
- `EXISTING=$(find outputs ...)`가 빈 값이면 정상 케이스 curl URL이 잘못됩니다. outputs가 비어 있을 때 skip하거나 archives도 fallback하세요.
- `TOKEN=$(curl -s -c - ... | grep paperflow_token | awk '{print $7}')`는 cookie jar format에 의존합니다. 실패 시 빈 토큰으로도 curl이 실행되므로 `test -n "$TOKEN"`를 넣는 것이 좋습니다.
- `curl -i ... | grep -i set-cookie`는 grep exit code만 보고 지나가기 쉽습니다. 수동이라면 괜찮지만 `grep -i 'Secure'` / `grep -vi 'Secure'`처럼 더 명확히 해도 됩니다.

### 5. 추가 위험

같은 우선순위 High 후보:
- `LOGIN_PASSWORD` default/placeholder/short 허용
- Markdown/assistant response XSS (`marked` + `x-html` + sanitizer 부재)

조건부 High/Medium 후보:
- `/api/import-url` authenticated SSRF/headless Chromium fetch. 단일 admin만 접근한다면 낮아지지만, 약한 로그인 비밀번호와 결합하면 내부망/metadata endpoint 접근, 내부 페이지 PDF화 같은 영향이 커질 수 있습니다.
- 서버가 root로 동작하는 점은 upload/path traversal과 결합될 때 영향도를 키웁니다. 단독으로는 hardening backlog가 맞습니다.

## 추천 수정 요약

계획에 바로 반영할 최소 수정:

1. 상단의 `_safe_paper_dir` 표기를 `safe_paper_dir`로 통일.
2. Task 1 Step 2에 `from .config import settings` 추가를 명시.
3. Task 3 검증에 symlink escape, archive/restore, markdown, asset, chat DELETE를 추가.
4. `POST /chat` invalid paper를 SSE 200 error가 아니라 route 초입 404로 만들지 여부를 결정.
5. `LOGIN_PASSWORD` startup guard를 이번 plan에 포함할지 명시적으로 재결정.
6. XSS hardening을 "same priority follow-up High"로 별도 plan에 명시.

이 보완 후에는 현재 계획을 구현해도 방향상 큰 문제는 없습니다.
