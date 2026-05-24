# Codex Round 2 Review: Viewer Security Hardening Plan

검토 대상:
- `docs/superpowers/plans/2026-05-24-viewer-security-hardening.md`
- `docs/reviews/2026-05-24-viewer-security-hardening-codex.md`
- `docs/reviews/2026-05-24-viewer-security-hardening-claude-meta-review.md`

## 결론

Round 1의 핵심 지적은 대부분 잘 반영되었습니다. `safe_paper_dir` 명명 통일, symlink escape 검증, `POST /chat` route-entry guard, XSS/LOGIN_PASSWORD/SSRF follow-up 명시는 방향이 맞습니다.

다만 최종 승인 전 아래 2개는 계획서에 반영하는 것이 좋습니다. 첫 번째는 이번 plan이 symlink escape를 명시적으로 방어 범위에 넣었기 때문에 누락으로 봅니다.

## 추가 수정 필요

### 1. `list_papers()`와 `_get_existing_papers_summary()`도 symlink escape를 필터링해야 합니다

관련 코드:
- `viewer/app/services/papers.py:577-581` `list_papers()`가 `base.iterdir()` 결과를 `item.is_dir()`만 보고 `_paper_info(item, location)`에 넘김
- `viewer/app/services/papers.py:960-963` `_get_existing_papers_summary()`도 같은 패턴

사용자 입력 `name` 기반 traversal은 `safe_paper_dir()`로 막히지만, 이번 plan은 `resolve()` 기반 symlink escape 차단까지 목표로 삼고 있습니다. 그렇다면 `outputs/pf-symlink-escape -> /etc` 같은 항목이 있을 때 `/api/papers` 목록과 duplicate summary 경로도 같은 정책으로 걸러야 합니다.

현재 Task 3 Step 7의 symlink 검증은 `/info`와 `/pdf`만 확인합니다. 하지만 `list_papers()`는 `safe_paper_dir()`를 거치지 않으므로 symlink escape 항목을 계속 목록 처리할 수 있습니다. `_paper_info()`가 파일 내용을 직접 반환하지는 않더라도 외부 디렉터리의 mtime/size/metadata 존재 여부를 처리하고, 외부 디렉터리에 `paper_meta.json`이 있으면 metadata 필드가 노출될 수 있습니다.

권장 보완:

```python
def _safe_child_dir(base: Path, item: Path) -> bool:
    if item.name.startswith("."):
        return False
    if not item.is_dir():
        return False
    return _is_within(base, item)
```

`list_papers()`:

```python
for item in sorted(base.iterdir(), key=lambda p: p.name):
    if _safe_child_dir(base, item):
        info = _paper_info(item, location)
        info["last_read_at"] = last_read.get(item.name)
        papers.append(info)
```

`_get_existing_papers_summary()`:

```python
for paper_dir in base.iterdir():
    if not _safe_child_dir(base, paper_dir):
        continue
    meta = _load_paper_metadata(paper_dir)
    ...
```

검증도 추가하세요:

```bash
ln -sfn /etc outputs/pf-symlink-escape
curl -s -b "paperflow_token=$TOKEN" "http://localhost:8090/api/papers?tab=unread" \
  | grep -q "pf-symlink-escape" && echo "FAIL: listed symlink escape" || echo "OK: symlink not listed"
rm -f outputs/pf-symlink-escape
```

`_paper_info()` 내부의 image/metadata 처리는 "검증된 paper_dir에 대해서만 호출된다"는 전제로 두는 것이 더 깔끔합니다.

### 2. Task 4 설명과 `_safe_filename()` 동작에서 `..` 표현을 맞춰야 합니다

관련 위치:
- Plan line 625: "`filename`에 `/`, `\`, `..`, 절대경로 성분"
- Plan lines 636-648: `_safe_filename()`은 `filename in {".", ".."}`만 거부하고 `paper..v1.pdf` 같은 substring은 허용

POSIX traversal 방어 기준으로는 현재 코드가 맞습니다. `/`와 `\`를 막고 단일 filename component만 허용하면 `..` substring 자체는 위험하지 않습니다. 오히려 `paper..v1.pdf`를 금지하면 불필요한 false positive가 생깁니다.

따라서 코드보다 설명을 고치는 쪽을 권장합니다.

수정 예:

```text
filename에 `/`, `\`, NUL, 빈 값, `.`/`..` 단일 component, 절대경로 성분이 들어가면 ...
```

또는 정말 substring `..`까지 금지하려면 `_safe_filename()`에 `if ".." in filename: return None`을 넣어야 합니다. 다만 이건 보안상 필수는 아닙니다.

## 질문별 답변

### 1. 누락 호출자

사용자 입력 `name`이 직접 path join되는 주요 라우트는 현재 plan이 대부분 잡았습니다. 다만 symlink escape까지 위협 모델에 넣었으므로 `iterdir()` 기반이라고 전부 제외하는 것에는 동의하지 않습니다. `list_papers()`와 `_get_existing_papers_summary()`는 `_is_within(base, item)` 필터를 넣는 편이 맞습니다.

`_paper_info()` 자체는 public resolver가 아니라 내부 builder이므로 모든 caller가 검증된 `paper_dir`만 넘기도록 만드는 방식에 동의합니다.

### 2. JWT substring 차단 리스트

6개 substring + 32자 하한은 이번 repo의 실제 placeholder 계열을 막기에는 충분합니다. 완전한 entropy 검사는 아니므로 `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` 같은 값은 통과하지만, surgical startup guard로는 현실적인 선입니다.

정상 랜덤 secret에서 `placeholder`, `change-me`, `paperflow-secret` 같은 문자열이 우연히 포함될 확률은 낮아서 false positive 위험도 낮습니다. `secret` 단독 같은 너무 넓은 substring은 추가하지 않는 편이 낫습니다.

### 3. `Path(filename).name != filename` round-trip

POSIX 한정으로 충분합니다. `/`는 path separator이고 이미 차단됩니다. `\`도 POSIX에서는 일반 문자지만 Windows/호환성 혼선을 줄이기 위해 차단하는 것이 맞습니다. NUL은 Python path API에서 문제를 만들 수 있어 차단이 맞습니다. `Path(filename).name` round-trip은 절대경로와 separator 포함 입력에 대한 방어-in-depth 역할을 합니다.

우회라고 볼 만한 입력은 없습니다. 다만 newline/control char, leading dash, trailing space 같은 이름은 traversal은 아니지만 운영 UX 문제가 될 수 있습니다. 보안 hardening 범위에서는 필수 차단 대상이 아닙니다.

### 4. `viewer_page`의 `touch_last_read` 순서 변경

정상 paper 이름이면 `get_paper_info(name)`가 성공한 뒤 동일하게 `touch_last_read(name)`가 호출되므로 회귀 가능성은 낮습니다. traversal/unknown name이 last_read JSON에 기록되지 않는 것은 의도한 개선입니다.

참고로 API progress endpoint는 여전히 `save_progress()`와 `touch_last_read()`를 unsafe/unknown name에도 호출할 수 있습니다. 파일 탈출은 아니고 JSON key pollution 수준이지만, 정책 일관성을 원하면 `/progress`와 `/rating`에도 `safe_paper_dir()` guard를 추가할 수 있습니다.

### 5. `enrich_paper_metadata` 함수 내 import

합리적입니다. `papers.py`와 `web_search.py` 사이 순환 가능성을 피하는 surgical 선택입니다. 더 깔끔한 장기 대안은 path-safety helper를 `services/path_safety.py` 같은 별도 모듈로 분리하는 것이지만, 이번 변경 범위에서는 함수 내부 import가 더 작고 안전합니다.

### 6. `archive_paper`/`restore_paper`의 직접 `_is_safe_paper_name + _is_within` 사용

합리적입니다. 두 함수는 source location이 각각 outputs/archives로 고정되어 있으므로 `safe_paper_dir()`처럼 양쪽을 탐색하면 의미가 흐려집니다. 현재 snippet은 source 위치를 명시적으로 제한하므로 더 읽기 쉽습니다.

추가로 dest는 `name`이 단일 component로 검증되므로 `archives_dir / name`, `outputs_dir / name`이 base 밖으로 나갈 수 없습니다.

### 7. 남은 위험

이번 plan에 포함하지 않았지만 같은 우선순위 후보로 보는 항목은 Round 1과 동일합니다.

- `LOGIN_PASSWORD` default/placeholder/short 허용: follow-up High 명시가 됐으므로 이번 plan에서는 defer 가능
- Markdown/assistant response XSS: follow-up High 명시가 됐으므로 이번 plan에서는 defer 가능
- `/api/import-url` SSRF/headless Chromium fetch: 약한 password와 결합하면 Medium/High, follow-up 명시 적절

## 최종 상태

위 2개 수정, 특히 `iterdir()` 기반 symlink escape 필터를 Task 3에 추가하면 최종 승인 가능합니다.
