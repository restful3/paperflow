# Viewer Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PaperFlow viewer의 High-severity 보안 문제를 surgical하게 수정한다 — (1) JWT 시크릿 placeholder 통과 차단, (2) 인증 쿠키 `secure` 플래그 토글, (3) 인증 후 디렉터리 트래버설(`_resolve_paper_dir` + 우회 호출자 5곳), (4) `/api/upload` 파일명 traversal.

**Architecture:** 변경은 `viewer/app/{config.py,auth.py,main.py,services/papers.py,services/web_search.py,routers/pages.py,routers/api.py}` 7개 파일에 국한. 새 환경 변수 1개(`COOKIE_SECURE`), 시작 시 검증 1건(시크릿 placeholder 차단), 신규 헬퍼 2개(`safe_paper_dir`, `_safe_filename`). 외부 API 시그니처는 그대로.

**Tech Stack:** FastAPI 0.115+, python-jose JWT, pydantic-settings, pathlib. viewer/에 `pytest` 인프라 부재 — 본 계획은 **단위 테스트를 추가하지 않고** 컨테이너에 대한 curl 검증과 코드 리뷰로 verification한다. (테스트 인프라 도입은 별도 plan.)

---

## File Structure

| 파일 | 변경 종류 | 책임 |
|---|---|---|
| `viewer/app/config.py` | Modify | `JWT_SECRET_KEY` substring+길이 검증, `COOKIE_SECURE` 신규, startup `validate_runtime()` |
| `viewer/app/main.py` | Modify | `create_app()`에서 `settings.validate_runtime()` 호출 |
| `viewer/app/auth.py` | Modify | `set_auth_cookie`가 `settings.COOKIE_SECURE` 반영 |
| `viewer/app/services/papers.py` | Modify | `safe_paper_dir`, `_safe_filename` 신설. `get_paper_info`/`archive_paper`/`restore_paper`/`save_upload` 호출자 일관 적용 |
| `viewer/app/services/web_search.py` | Modify | `enrich_paper_metadata`가 `safe_paper_dir` 사용 |
| `viewer/app/routers/pages.py` | Modify | `viewer_page`에서 `touch_last_read`를 안전 검증 후로 이동 |
| `viewer/app/routers/api.py` | Modify | `/api/upload`에서 `_safe_filename` 적용 |
| `.env.example` | Modify | `COOKIE_SECURE` 추가, `JWT_SECRET_KEY=` 빈 placeholder + 생성 명령 주석 |
| `CLAUDE.md` | Modify | 보안 환경 변수 항목 갱신 |

각 파일은 단일 책임 유지. `papers.py`가 path-safety helper의 single source of truth, 다른 모듈은 import해서 재사용한다.

---

## Task 1: JWT secret 검증 강화 + 시작 시 거부

**Why:** 현재 `.env`에는 `JWT_SECRET_KEY=paperflow-secret-change-me-in-production` 형태의 약한 시크릿이 들어 있다. 단순 exact-match 차단으로는 이런 변형이 통과한다. lower-case 후 known placeholder substring을 검사하고 길이 하한(32자)을 두면, 운영자가 실수로 약한 값을 두고 띄울 경우 startup에서 즉시 실패한다.

**Files:**
- Modify: `viewer/app/config.py`
- Modify: `viewer/app/main.py`

- [ ] **Step 1: `config.py` 전체 교체**

```python
from pydantic_settings import BaseSettings
from pathlib import Path


_JWT_PLACEHOLDER_SUBSTRINGS = (
    "change-me",
    "changeme",
    "replace-with",
    "placeholder",
    "your-secret",
    "paperflow-secret",
)
_JWT_MIN_LENGTH = 32


class Settings(BaseSettings):
    BASE_DIR: str = "."

    LOGIN_ID: str = "admin"
    LOGIN_PASSWORD: str = "admin"

    # JWT — JWT_SECRET_KEY MUST be set via env; placeholders / short values are rejected at startup
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 30

    # Cookie security — set to true when serving over HTTPS
    COOKIE_SECURE: bool = False

    BRAVE_SEARCH_API_KEY: str = ""

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def validate_runtime(self) -> None:
        """Fail fast on missing/weak JWT secret. Called from create_app()."""
        secret = self.JWT_SECRET_KEY.strip()
        if not secret:
            raise RuntimeError(
                "JWT_SECRET_KEY is empty. Set a strong random value via the env var "
                "(e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`)."
            )
        if len(secret) < _JWT_MIN_LENGTH:
            raise RuntimeError(
                f"JWT_SECRET_KEY is too short ({len(secret)} chars). "
                f"Minimum length is {_JWT_MIN_LENGTH}."
            )
        normalized = secret.lower()
        for needle in _JWT_PLACEHOLDER_SUBSTRINGS:
            if needle in normalized:
                raise RuntimeError(
                    f"JWT_SECRET_KEY looks like a placeholder (contains '{needle}'). "
                    "Rotate to a strong random value."
                )

    @property
    def outputs_dir(self) -> Path:
        return Path(self.BASE_DIR) / "outputs"

    @property
    def archives_dir(self) -> Path:
        return Path(self.BASE_DIR) / "archives"

    @property
    def newones_dir(self) -> Path:
        return Path(self.BASE_DIR) / "newones"

    @property
    def newones_meta_dir(self) -> Path:
        return self.newones_dir / ".meta"

    @property
    def logs_dir(self) -> Path:
        return Path(self.BASE_DIR) / "logs"


settings = Settings()
```

- [ ] **Step 2: `main.py`에서 `create_app()` 초입에 `settings.validate_runtime()` 호출**

먼저 현재 내용 확인:

```bash
cat viewer/app/main.py
```

수정 — `create_app()` 함수 body 첫 줄로 `settings.validate_runtime()` 추가. 다른 줄/순서는 유지. 예 (구조 보고 적용):

```python
from fastapi import FastAPI
from .config import settings
from .routers import pages, api

def create_app() -> FastAPI:
    settings.validate_runtime()  # ← 추가
    app = FastAPI(title="PaperFlow Viewer")
    app.include_router(pages.router)
    app.include_router(api.router)
    return app

app = create_app()
```

- [ ] **Step 3: 검증 — 현재 `.env`의 약한 값이 거부되는지 + 강한 값은 통과하는지**

```bash
cd /media/restful3/data/workspace/paperflow

# A) 현재 .env에 들어 있는 약한 값 패턴 → 시작 실패
JWT_SECRET_KEY="paperflow-secret-change-me-in-production" \
  python -c "from viewer.app.main import create_app; create_app()" 2>&1 | tail -3
# Expected: RuntimeError ... placeholder (contains 'paperflow-secret') ...

# B) 빈 값 → 시작 실패
JWT_SECRET_KEY="" python -c "from viewer.app.main import create_app; create_app()" 2>&1 | tail -3
# Expected: RuntimeError ... JWT_SECRET_KEY is empty ...

# C) 너무 짧은 값 → 시작 실패
JWT_SECRET_KEY="short" python -c "from viewer.app.main import create_app; create_app()" 2>&1 | tail -3
# Expected: RuntimeError ... too short ...

# D) 강한 랜덤 값 → 정상 통과
JWT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  python -c "from viewer.app.main import create_app; create_app(); print('OK')"
# Expected: OK
```

- [ ] **Step 4: 실제 `.env`의 시크릿을 강한 랜덤 값으로 회전**

```bash
NEW_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')
# 기존 라인 제거 후 새 값 추가
sed -i '/^JWT_SECRET_KEY=/d' .env
echo "JWT_SECRET_KEY=$NEW_SECRET" >> .env
grep ^JWT_SECRET_KEY .env | cut -d= -f1
# Expected: JWT_SECRET_KEY (값 출력 안 함)
```

⚠️ 이 단계 후 기존 발급 토큰은 즉시 무효화된다 — 운영자/사용자는 재로그인 필요.

- [ ] **Step 5: 컨테이너 재기동 후 startup 성공 + 로그인 동작 확인**

```bash
docker compose up -d --force-recreate paperflow-viewer
sleep 3
docker compose logs paperflow-viewer | tail -20
# Expected: Uvicorn running ... (RuntimeError 없음)

# 로그인 정상 동작 확인
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8090/api/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$(grep ^LOGIN_ID= .env | cut -d= -f2)\",\"password\":\"$(grep ^LOGIN_PASSWORD= .env | cut -d= -f2)\"}"
# Expected: 200
```

- [ ] **Step 6: Commit**

```bash
git add viewer/app/config.py viewer/app/main.py
git commit -m "security(viewer): require strong JWT_SECRET_KEY at startup"
```

`.env`는 `.gitignore`에 포함되어 commit 대상 아님.

---

## Task 2: 쿠키 `secure` 플래그를 설정 가능하게 노출

**Why:** `auth.py:27`의 쿠키는 `httponly+samesite=lax`만 갖고 `secure` 플래그가 없다. HTTPS 운영자가 명시적으로 켤 수 있어야 하고, 로컬 HTTP 환경(8090 직접 노출)에서는 false 유지가 필요하다.

`SameSite=Lax` 유지 이유: 본 viewer는 cross-site embedding(iframe/cross-site POST)을 지원하지 않는다. Lax 유지가 보수적이고 CSRF 방어에 유리. cross-site 임베딩이 필요해지면 별도 plan으로 `SameSite=None; Secure` + CSRF 토큰 도입.

**Files:**
- Modify: `viewer/app/auth.py`
- Modify: `.env.example`

- [ ] **Step 1: `auth.py` 전체 교체**

```python
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from fastapi import Response

from .config import settings

COOKIE_NAME = "paperflow_token"


def create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str) -> str | None:
    """Return username if token is valid, else None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.JWT_EXPIRE_DAYS * 86400,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")
```

핵심 변경: `secure=settings.COOKIE_SECURE` 한 줄 추가.

- [ ] **Step 2: `.env.example` 갱신 — placeholder 줄을 빈 값 + 주석으로 변경, `COOKIE_SECURE` 추가**

`.env.example`에서 다음 줄:

```
LOGIN_ID=admin
LOGIN_PASSWORD=changeme
JWT_SECRET_KEY=replace-with-random-secret-string
```

를 다음으로 교체:

```
LOGIN_ID=admin
LOGIN_PASSWORD=changeme

# JWT signing secret (REQUIRED — startup fails if empty/short/placeholder).
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET_KEY=

# ─── 쿠키 보안 (HTTPS 운영 시 true) ───────────────────────────────────────
# 로컬 HTTP(예: 8090 직접 노출)에서는 false 유지. HTTPS 리버스 프록시 뒤라면 true 권장.
COOKIE_SECURE=false
```

- [ ] **Step 3: `Set-Cookie`의 `Secure` 플래그 토글 검증 — 컨테이너 재생성 강제**

A) `COOKIE_SECURE=false` (기본):

```bash
# .env에 COOKIE_SECURE 없거나 false인 상태
docker compose up -d --force-recreate paperflow-viewer
sleep 3
docker compose exec paperflow-viewer env | grep COOKIE_SECURE || echo "(unset → false default)"

curl -i -X POST http://localhost:8090/api/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$(grep ^LOGIN_ID= .env | cut -d= -f2)\",\"password\":\"$(grep ^LOGIN_PASSWORD= .env | cut -d= -f2)\"}" \
  | grep -i set-cookie
# Expected: Set-Cookie: paperflow_token=...; HttpOnly; Path=/; SameSite=lax  (Secure 없음)
```

B) `COOKIE_SECURE=true`:

```bash
sed -i '/^COOKIE_SECURE=/d' .env && echo "COOKIE_SECURE=true" >> .env
docker compose up -d --force-recreate paperflow-viewer
sleep 3
docker compose exec paperflow-viewer env | grep COOKIE_SECURE
# Expected: COOKIE_SECURE=true

curl -i -X POST http://localhost:8090/api/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$(grep ^LOGIN_ID= .env | cut -d= -f2)\",\"password\":\"$(grep ^LOGIN_PASSWORD= .env | cut -d= -f2)\"}" \
  | grep -i set-cookie
# Expected: Set-Cookie: ...; HttpOnly; Path=/; SameSite=lax; Secure
```

검증 후 로컬 HTTP 운영을 위해 false로 원복:

```bash
sed -i '/^COOKIE_SECURE=/d' .env
echo "COOKIE_SECURE=false" >> .env
docker compose up -d --force-recreate paperflow-viewer
```

- [ ] **Step 4: Commit**

```bash
git add viewer/app/auth.py .env.example
git commit -m "security(viewer): expose COOKIE_SECURE flag for HTTPS deployments"
```

---

## Task 3: Path-safety helper 도입 + 우회 호출자 일괄 적용

**Why:** `_resolve_paper_dir`만 강화해도 `get_paper_info`, `viewer_page`(via `touch_last_read`), `enrich_paper_metadata`, `archive_paper`, `restore_paper`가 모두 `base / name` raw join을 직접 쓰므로 트래버설이 그대로 가능하다 (`papers.py:587, 853, 865`, `web_search.py:183`, `pages.py:43-44`). 단일 path-safety helper를 `papers.py`에 두고 모든 호출자가 동일 helper를 거치도록 한다.

**Files:**
- Modify: `viewer/app/services/papers.py` (helper 정의 + 호출자 5곳)
- Modify: `viewer/app/services/web_search.py` (호출자 1곳)
- Modify: `viewer/app/routers/pages.py` (`touch_last_read` 순서)
- Modify: `viewer/app/routers/api.py` (`POST /chat` 라우트 초입 가드 추가)

- [ ] **Step 1: `papers.py`의 `_resolve_paper_dir`를 `safe_paper_dir` 중심 구조로 교체**

`papers.py:701-706` (현재 `_resolve_paper_dir`) 위치를 다음으로 교체:

```python
def _is_within(base: Path, candidate: Path) -> bool:
    """True only if `candidate` resolves under `base`."""
    try:
        base_resolved = base.resolve()
        cand_resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return False
    try:
        cand_resolved.relative_to(base_resolved)
        return True
    except ValueError:
        return False


def _is_safe_paper_name(name: str) -> bool:
    """Paper names are single directory components produced by the batch pipeline."""
    if not name or "\x00" in name:
        return False
    if "/" in name or "\\" in name:
        return False
    if name in {".", ".."}:
        return False
    return True


def safe_paper_dir(name: str) -> Path | None:
    """Resolve a paper directory under outputs/ or archives/, rejecting traversal.

    Public helper — re-used by web_search and any other module that needs to
    map a user-supplied paper name to a filesystem directory.
    Returns None for unsafe names, unknown papers, or symlink escapes.
    """
    if not _is_safe_paper_name(name):
        return None
    for base in [settings.outputs_dir, settings.archives_dir]:
        d = base / name
        if not d.is_dir():
            continue
        if not _is_within(base, d):
            return None
        return d
    return None


def _safe_child_dir(base: Path, item: Path) -> bool:
    """Accept only non-hidden directories that resolve under their base.

    Used by listing code paths (`list_papers`, `_get_existing_papers_summary`)
    that take entries from `base.iterdir()` rather than user-supplied names.
    Even though the source isn't user input, a symlink under `outputs/` or
    `archives/` can still escape — keep the symlink-escape threat model
    consistent across all paths.
    """
    if item.name.startswith("."):
        return False
    if not item.is_dir():
        return False
    return _is_within(base, item)


# Backward-compatible alias — keep _resolve_paper_dir for any in-tree callers.
_resolve_paper_dir = safe_paper_dir
```

핵심 의도:
- `_is_within` + `_is_safe_paper_name` 분리 → 각각 테스트/디버그 용이
- `safe_paper_dir`은 public(언더스코어 없음) — 다른 모듈에서 import해 쓰도록 의도
- `_resolve_paper_dir`는 alias로 유지 → 기존 호출자(`delete_paper`, `get_pdf_path`, `get_md_*_path`)는 그대로 동작

- [ ] **Step 2: `get_paper_info`를 `safe_paper_dir` 사용으로 변경**

`papers.py:585-593`을 다음으로 교체:

```python
def get_paper_info(name: str) -> dict | None:
    """Find paper in outputs or archives and return info."""
    paper_dir = safe_paper_dir(name)
    if not paper_dir:
        return None
    # Determine location by parent directory identity (resolved)
    try:
        if paper_dir.parent.resolve() == settings.archives_dir.resolve():
            loc = "archives"
        else:
            loc = "outputs"
    except (OSError, RuntimeError):
        loc = "outputs"
    info = _paper_info(paper_dir, loc)
    info["last_read_at"] = get_all_last_read().get(name)
    return info
```

- [ ] **Step 3: `archive_paper`/`restore_paper`를 safe 처리**

`papers.py:852-873`을 다음으로 교체:

```python
def archive_paper(name: str) -> tuple[bool, str]:
    if not _is_safe_paper_name(name):
        return False, f"Invalid paper name."
    src = settings.outputs_dir / name
    if not src.is_dir() or not _is_within(settings.outputs_dir, src):
        return False, f"Paper '{name}' not found in outputs."
    dest = settings.archives_dir / name
    if dest.exists():
        return False, f"'{name}' already exists in archives."
    settings.archives_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True, f"'{name}' archived."


def restore_paper(name: str) -> tuple[bool, str]:
    if not _is_safe_paper_name(name):
        return False, f"Invalid paper name."
    src = settings.archives_dir / name
    if not src.is_dir() or not _is_within(settings.archives_dir, src):
        return False, f"Paper '{name}' not found in archives."
    dest = settings.outputs_dir / name
    if dest.exists():
        return False, f"'{name}' already exists in outputs."
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True, f"'{name}' restored."
```

핵심: source는 outputs/archives 한 곳에 한정되므로 `safe_paper_dir`(둘 다 시도)이 아니라 `_is_safe_paper_name` + `_is_within`을 직접 호출. 의미가 더 명확.

- [ ] **Step 4: `web_search.py`의 `enrich_paper_metadata`도 helper 사용**

`web_search.py:181-190` 의 raw join 블록을 다음으로 교체:

```python
    # Locate paper directory (safe against traversal)
    from .papers import safe_paper_dir
    paper_dir = safe_paper_dir(paper_name)
    if not paper_dir:
        return {"success": False, "error": "Paper not found", "enriched_fields": []}
```

기존의 `paper_dir = None / for base in ... / break` 루프 6줄을 위 3줄로 대체. import는 함수 내부에 두어 순환 import 회피.

- [ ] **Step 5: `pages.py`의 `viewer_page`에서 `touch_last_read`를 정보 확인 후로 이동**

`pages.py:36-43`의 viewer_page 함수 진입부를 다음으로 교체:

```python
@router.get("/viewer/{paper_name:path}", response_class=HTMLResponse)
async def viewer_page(paper_name: str, request: Request, user: str | None = Depends(get_current_user_page)):
    if not user:
        return RedirectResponse("/login", status_code=302)

    name = unquote(paper_name)
    info = paper_svc.get_paper_info(name)
    if not info:
        return RedirectResponse("/papers", status_code=302)
    # Mark as recently read only after the paper resolves safely
    paper_svc.touch_last_read(name)
```

(이후의 `has_pdf`/`has_md_*` 분기는 그대로 유지. 단, `info`가 항상 truthy임이 보장되므로 `if info else False` 가드는 안전성상 그대로 두어도 무방.)

- [ ] **Step 6: `list_papers`와 `_get_existing_papers_summary`에 symlink 가드 적용**

두 함수 모두 `base.iterdir()` 결과를 `item.is_dir()` 만으로 분기한다. `outputs/`나 `archives/` 안에 base 밖을 가리키는 symlink가 생기면 listing/duplicate-summary에 노출된다. `iterdir()` 출처는 사용자 입력이 아니지만 symlink escape를 위협 모델에 넣은 이상 일관성 있게 막는다.

`papers.py:577-581`의 `list_papers` 루프를 다음으로 교체:

```python
for item in sorted(base.iterdir(), key=lambda p: p.name):
    if not _safe_child_dir(base, item):
        continue
    info = _paper_info(item, location)
    info["last_read_at"] = last_read.get(item.name)
    papers.append(info)
```

`papers.py:960-963`의 `_get_existing_papers_summary` 루프를 다음으로 교체:

```python
for paper_dir in base.iterdir():
    if not _safe_child_dir(base, paper_dir):
        continue
    meta = _load_paper_metadata(paper_dir)
    if meta and meta.get("title"):
        papers.append({
            "title": meta["title"],
            "authors": meta.get("authors", []),
            "location": location,
            "folder": paper_dir.name,
        })
```

- [ ] **Step 7: `api.py`의 `POST /chat` 라우트 초입에 가드 추가**

`POST /api/papers/{name}/chat`는 `EventSourceResponse`를 먼저 반환하고 generator 내부에서 `chat_svc.load_chat_history(name)`의 `ValueError`를 SSE error 이벤트로 처리한다. 즉 traversal name에 대해 HTTP는 200, SSE error 한 줄만 나옴 — manual verification에서 일관성이 깨지고, 다른 라우트와 정책이 어긋난다. route 초입에서 `safe_paper_dir`로 확인하고 없으면 즉시 404.

`api.py:121-153`의 `chat_with_paper` 함수 초입(`name = unquote(name)` 다음 줄)에 추가:

```python
@router.post("/papers/{name:path}/chat")
async def chat_with_paper(
    name: str,
    request: ChatRequest,
    _user: str = Depends(get_current_user_api)
):
    name = unquote(name)
    # Reject unsafe / unknown paper names early — keeps HTTP semantics consistent with other routes
    if not paper_svc.safe_paper_dir(name):
        raise HTTPException(status_code=404, detail="Paper not found")

    async def event_generator():
        ...
```

다른 본문은 변경하지 않는다.

- [ ] **Step 8: 컨테이너 재기동 + 호출자 그물망 전체에서 traversal 거부 확인**

```bash
docker compose up -d --force-recreate paperflow-viewer
sleep 3

TOKEN=$(curl -s -c - -X POST http://localhost:8090/api/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$(grep ^LOGIN_ID= .env | cut -d= -f2)\",\"password\":\"$(grep ^LOGIN_PASSWORD= .env | cut -d= -f2)\"}" \
  | grep paperflow_token | awk '{print $7}')
test -n "$TOKEN" || { echo "FAIL: login token not captured"; exit 1; }

# A) 정상 케이스 — 실제 paper directory가 있어야 함
EXISTING=$(find outputs -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | head -1)
test -n "$EXISTING" || { echo "SKIP: outputs에 paper directory 없음 — 먼저 PDF 하나를 처리해두세요"; exit 1; }
EXISTING_ENC=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$EXISTING")
curl -s -o /dev/null -w "info=%{http_code}\n" -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/$EXISTING_ENC/info"
# Expected: info=200

# B) `..` traversal — GET 라우트
for ep in \
  "api/papers/..%2F..%2Fetc/info" \
  "viewer/..%2F..%2Fetc" \
  "api/papers/..%2F..%2Fetc/pdf" \
  "api/papers/..%2F..%2Fetc/md-ko" \
  "api/papers/..%2F..%2Fetc/md-en" \
  "api/papers/..%2F..%2Fetc/chat/history"
do
  echo -n "GET $ep -> "
  curl -s -o /dev/null -w "%{http_code}\n" -b "paperflow_token=$TOKEN" \
    "http://localhost:8090/$ep"
done
# Expected: info/pdf/md-ko/md-en/chat/history → 404, viewer → 302 (papers redirect)

# C) Symlink escape — outputs 안의 단일 component이지만 실제 대상이 base 밖
ln -sfn /etc outputs/pf-symlink-escape
curl -s -o /dev/null -w "symlink-info=%{http_code}\n" -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/pf-symlink-escape/info"
curl -s -o /dev/null -w "symlink-pdf=%{http_code}\n" -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/pf-symlink-escape/pdf"
# C2) 같은 symlink가 listing에도 노출되면 안 됨
curl -s -b "paperflow_token=$TOKEN" "http://localhost:8090/api/papers?tab=unread" \
  | grep -q "pf-symlink-escape" && echo "FAIL: listed symlink escape" || echo "OK: symlink not listed"
rm -f outputs/pf-symlink-escape
# Expected: symlink-info=404, symlink-pdf=404, listing=OK — `_is_within`이 symlink follow 후 base 외부 거부

# D) archive / restore traversal — POST
echo -n "archive -> "
curl -s -o /dev/null -w "%{http_code}\n" -X POST -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/..%2F..%2Fetc/archive"
echo -n "restore -> "
curl -s -o /dev/null -w "%{http_code}\n" -X POST -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/..%2F..%2Fetc/restore"
echo -n "enrich -> "
curl -s -o /dev/null -w "%{http_code}\n" -X POST -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/..%2F..%2Fetc/enrich"
# Expected: archive/restore → 400, enrich → 404

# E) markdown PUT traversal
echo -n "markdown-PUT -> "
curl -s -o /dev/null -w "%{http_code}\n" -X PUT -b "paperflow_token=$TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"content":"test"}' \
  "http://localhost:8090/api/papers/..%2F..%2Fetc/markdown/en"
# Expected: 400 (save_markdown returns False → HTTPException 400)

# F) asset traversal under a valid paper
echo -n "asset-traversal -> "
curl -s -o /dev/null -w "%{http_code}\n" -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/$EXISTING_ENC/assets/..%2F..%2F..%2Fetc%2Fpasswd"
# Expected: 404

# G) chat history DELETE traversal
echo -n "chat-DELETE -> "
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/papers/..%2F..%2Fetc/chat/history"
# Expected: 404 (clear_chat_history False → 404)

# H) POST /chat traversal (route-entry guard)
echo -n "chat-POST -> "
curl -s -o /dev/null -w "%{http_code}\n" -X POST -b "paperflow_token=$TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"hi","paper_name":"..%2F..%2Fetc"}' \
  "http://localhost:8090/api/papers/..%2F..%2Fetc/chat"
# Expected: 404 (route-entry safe_paper_dir guard)
```

- [ ] **Step 9: Commit**

```bash
git add viewer/app/services/papers.py viewer/app/services/web_search.py viewer/app/routers/pages.py viewer/app/routers/api.py
git commit -m "security(viewer): block path traversal in paper-name resolver and all callers"
```

---

## Task 4: `/api/upload` 파일명 traversal 차단

**Why:** `api.py:537`의 `/api/upload`는 인증 후 `file.filename`의 확장자만 검사하고 `papers.py:934 save_upload`가 `newones_dir / filename`을 raw로 `write_bytes`한다. `filename`이 빈 값/NUL이거나 `/`, `\`을 포함하거나 `.`/`..` 단일 component이거나 `Path(filename).name != filename`(절대경로·다중 component)이면 newones 밖으로 파일 쓰기 가능. 컨테이너가 root로 실행되므로 영향 큼. `_safe_filename` 헬퍼로 차단. (참고: `paper..v1.pdf` 같은 substring `..`은 traversal이 아니므로 허용한다.)

**Files:**
- Modify: `viewer/app/services/papers.py` (`_safe_filename` 신설 + `save_upload` 적용)
- Modify: `viewer/app/routers/api.py` (upload 라우트에서 sanitized name 사용)

- [ ] **Step 1: `papers.py`에 `_safe_filename` 추가 + `save_upload` 수정**

`save_upload` 함수 바로 위에 helper 추가하고, 함수 본문 수정:

```python
def _safe_filename(filename: str) -> str | None:
    """Accept only a single filename component. Reject traversal / absolute paths."""
    if not filename or "\x00" in filename:
        return None
    if "/" in filename or "\\" in filename:
        return None
    if filename in {".", ".."}:
        return None
    # Path() with a single component leaves it intact; verify .name round-trip
    candidate = Path(filename).name
    if candidate != filename:
        return None
    return candidate


def save_upload(filename: str, data: bytes) -> tuple[bool, str]:
    safe = _safe_filename(filename)
    if not safe:
        return False, "Invalid filename."
    settings.newones_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.newones_dir / safe
    # Defense-in-depth: ensure dest stays under newones_dir
    if not _is_within(settings.newones_dir, dest):
        return False, "Invalid filename."
    if dest.exists():
        return False, f"'{safe}' already exists in upload queue."
    dest.write_bytes(data)
    return True, f"'{safe}' uploaded."
```

- [ ] **Step 2: `api.py:535-550`의 upload 라우트가 sanitized name을 사용하도록 수정**

`api.py:535-550` 블록을 다음으로 교체:

```python
@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...), _user: str = Depends(get_current_user_api)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    safe = paper_svc._safe_filename(file.filename)
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid filename")
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:  # 200 MB
        raise HTTPException(status_code=400, detail="File too large (max 200 MB)")
    ok, msg = paper_svc.save_upload(safe, data)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    pdf_path = settings.newones_dir / safe
    similar_papers = await paper_svc.check_duplicate_paper(pdf_path)

    return {"ok": True, "message": msg, "similar_papers": similar_papers}
```

(`_safe_filename`은 private prefix이지만 같은 패키지에서 import가 자연스럽다. 노출이 신경 쓰이면 Step 1에서 `safe_filename`으로 rename 후 두 곳 모두 갱신 — 어느 쪽이든 OK. 이번 plan은 일관성을 위해 `_safe_filename` 그대로 사용.)

- [ ] **Step 3: traversal multipart 시도가 400으로 거부되는지 검증**

```bash
docker compose up -d --force-recreate paperflow-viewer
sleep 3

TOKEN=$(curl -s -c - -X POST http://localhost:8090/api/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$(grep ^LOGIN_ID= .env | cut -d= -f2)\",\"password\":\"$(grep ^LOGIN_PASSWORD= .env | cut -d= -f2)\"}" \
  | grep paperflow_token | awk '{print $7}')

# 작은 더미 PDF (실제 PDF 헤더만 있어도 OK — 400/400 응답을 보는 게 목적)
echo "%PDF-1.4" > /tmp/sample.pdf

# A) traversal filename → 400
curl -s -o /dev/null -w "%{http_code}\n" -b "paperflow_token=$TOKEN" \
  -F 'file=@/tmp/sample.pdf;filename=../../tmp/paperflow-upload-traversal.pdf' \
  "http://localhost:8090/api/upload"
# Expected: 400

# 실제로 외부에 파일이 안 떨어졌는지 확인
test ! -f /tmp/paperflow-upload-traversal.pdf && echo "OK no escape file" || echo "FAIL: escape file exists"

# B) 절대경로 filename → 400
curl -s -o /dev/null -w "%{http_code}\n" -b "paperflow_token=$TOKEN" \
  -F 'file=@/tmp/sample.pdf;filename=/etc/paperflow-x.pdf' \
  "http://localhost:8090/api/upload"
# Expected: 400

# C) 정상 filename → 200
curl -s -o /dev/null -w "%{http_code}\n" -b "paperflow_token=$TOKEN" \
  -F 'file=@/tmp/sample.pdf;filename=test-upload.pdf' \
  "http://localhost:8090/api/upload"
# Expected: 200

# 테스트 후 정리
curl -s -X DELETE -b "paperflow_token=$TOKEN" \
  "http://localhost:8090/api/upload/test-upload.pdf"
rm -f /tmp/sample.pdf
```

- [ ] **Step 4: Commit**

```bash
git add viewer/app/services/papers.py viewer/app/routers/api.py
git commit -m "security(viewer): sanitize upload filename to block path traversal"
```

---

## Task 5: 문서 갱신

**Why:** 새 환경 변수와 보안 정책을 다음 세션이 알 수 있도록 CLAUDE.md에 반영.

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: CLAUDE.md의 `.env` 블록 갱신**

찾을 문자열 (Configuration 섹션):
```
LOGIN_ID, LOGIN_PASSWORD          # Viewer auth
JWT_SECRET_KEY                    # JWT signing
```

교체:
```
LOGIN_ID, LOGIN_PASSWORD          # Viewer auth
JWT_SECRET_KEY                    # JWT signing (required, no default — startup rejects empty/short/placeholder substrings)
COOKIE_SECURE                     # true on HTTPS deployments, false for local HTTP (default false)
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note viewer security env vars (JWT_SECRET_KEY, COOKIE_SECURE)"
```

---

## Out of scope (의도적으로 제외)

### Follow-up High 후보 (다음 plan으로 분리)

- **`LOGIN_PASSWORD` 약한 값 startup guard / 해싱** — 8090 직접 노출 시 외부 망 노출 시나리오에서는 follow-up High. 본 plan은 JWT/cookie/path traversal 4건에 집중.
- **Markdown / assistant response XSS** — viewer.html의 `marked.parse()` 결과를 sanitizer 없이 `x-html`로 렌더. HTTPOnly 쿠키여도 same-origin fetch 가능 → API 호출로 상태 변경/탈취 가능. follow-up High.
- **`/api/import-url` SSRF / headless Chromium fetch** — 인증 후이긴 하나 약한 password와 결합 시 내부망/host service 접근 가능. follow-up Medium/High.

### Defense-in-depth follow-up

- **컨테이너 non-root 실행** — Dockerfile 변경 필요. 본 plan의 path/upload traversal 영향 반경을 줄이는 보조 수단.

### 의도적 영구 제외

- **pytest 인프라 도입 / 단위 테스트** — viewer/에 테스트 전무. 별도 plan으로 분리.
- **HSTS / CSP / X-Frame-Options** — 리버스 프록시 단에서 처리.
- **Windows 운영 환경의 drive/colon/예약명** — 본 앱은 Linux Docker 전용.
- **`secrets.token_urlsafe` 자동 생성** — 토큰 영속성 깨짐(재시작마다 로그아웃). 명시적 .env 강제가 운영자 의도 명확.

---

## Self-Review

**Spec coverage:**
- High #1 (JWT 시크릿 약한 값) → Task 1 ✓ (substring + 길이 + 실제 .env 회전)
- High #2 (쿠키 secure) → Task 2 ✓ (force-recreate 검증 포함)
- High #3 (path traversal, 호출자 5곳) → Task 3 ✓
- High #4 (upload filename) → Task 4 ✓ (신설)
- 문서화 → Task 5 ✓

**Placeholder scan:** 모든 코드 블록이 완전. "TBD"/"적절히"/"비슷하게" 없음. 모든 curl이 실행 가능.

**Type consistency:**
- `safe_paper_dir(str) → Path | None`, `_is_safe_paper_name(str) → bool`, `_is_within(Path, Path) → bool`, `_safe_filename(str) → str | None` 모두 호출자와 시그니처 일치.
- `_resolve_paper_dir` alias 유지로 `delete_paper`, `get_pdf_path`, `get_md_*_path` 호출자 무변경.

**Surgical-change check:** 변경 라인 수 — config.py +30, main.py +1, auth.py +1, papers.py +60, web_search.py 6→3, pages.py +4, api.py +5, .env.example +5, CLAUDE.md +1. 무관한 리팩터/포맷/주석 정리 없음.

**호출자 그물망 검증:**
| 호출자 | 함수 | 보호 경로 |
|---|---|---|
| `/api/papers/{name}/info` | `get_paper_info` | Task 3 Step 2 |
| `/viewer/{name}` | `viewer_page → get_paper_info` + `touch_last_read` 순서 | Task 3 Step 5 |
| `/api/papers/{name}/enrich` | `enrich_paper_metadata` | Task 3 Step 4 |
| `/api/papers/{name}/archive` | `archive_paper` | Task 3 Step 3 |
| `/api/papers/{name}/restore` | `restore_paper` | Task 3 Step 3 |
| `/api/papers/{name}/pdf,md-ko,md-en,...` | `get_*_path → _resolve_paper_dir` (alias) | Task 3 Step 1 |
| `/api/papers/{name}` DELETE | `delete_paper → _resolve_paper_dir` (alias) | Task 3 Step 1 |
| `/api/papers/{name}/markdown/{type}` PUT | `save_markdown → _resolve_paper_dir` (alias) | Task 3 Step 1 |
| `/api/papers/{name}/assets/{file}` | `get_asset_path → _resolve_paper_dir` (alias) + `_is_within(paper_dir, asset)` | Task 3 Step 1 |
| `/api/papers/{name}/chat/history` GET/DELETE | `load_chat_history` / `clear_chat_history → _resolve_paper_dir` (alias) | Task 3 Step 1 |
| `/api/papers/{name}/chat` POST | route-entry `safe_paper_dir` 가드 | Task 3 Step 7 |
| `/api/papers?tab=...` listing | `list_papers + _safe_child_dir` | Task 3 Step 6 |
| duplicate check listing | `_get_existing_papers_summary + _safe_child_dir` | Task 3 Step 6 |
| `/api/upload` | `save_upload + _safe_filename` | Task 4 |
