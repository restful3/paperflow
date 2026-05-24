# Codex Round 3 Review: Viewer Security Hardening Plan

검토 대상:
- `docs/superpowers/plans/2026-05-24-viewer-security-hardening.md`
- `docs/reviews/2026-05-24-viewer-security-hardening-codex-2.md`
- `docs/reviews/2026-05-24-viewer-security-hardening-claude-meta-review-round2.md`

## 결론

최종 승인 보류입니다.

Round 2에서 blocking으로 남겼던 2건이 현재 계획서에 아직 반영되지 않았습니다. `safe_paper_dir` 표기 통일, `POST /chat` guard, 추가 curl 검증들은 들어가 있지만, `iterdir()` 기반 symlink escape 필터와 Task 4 설명 정정은 확인되지 않았습니다.

## Blocking Items

### 1. `list_papers()`와 `_get_existing_papers_summary()`의 symlink escape 필터가 아직 계획에 없습니다

현재 계획의 Task 3은 `safe_paper_dir(name)`만 추가합니다. 그러나 `/api/papers?tab=unread` 목록 경로와 duplicate summary 경로는 사용자 입력 name이 아니라 `base.iterdir()` 결과를 직접 처리합니다.

기존 코드 기준:
- `viewer/app/services/papers.py:577-581` `list_papers()`는 `item.is_dir()`만 확인 후 `_paper_info(item, location)` 호출
- `viewer/app/services/papers.py:960-963` `_get_existing_papers_summary()`도 `paper_dir.is_dir()`만 확인

이번 plan은 symlink escape를 위협 모델에 포함했으므로, 이 두 경로도 `_is_within(base, item)`로 필터링해야 합니다.

계획에 추가할 최소 snippet:

```python
def _safe_child_dir(base: Path, item: Path) -> bool:
    """Accept only non-hidden directories that resolve under their base."""
    if item.name.startswith("."):
        return False
    if not item.is_dir():
        return False
    return _is_within(base, item)
```

`list_papers()` 적용:

```python
for item in sorted(base.iterdir(), key=lambda p: p.name):
    if _safe_child_dir(base, item):
        info = _paper_info(item, location)
        info["last_read_at"] = last_read.get(item.name)
        papers.append(info)
```

`_get_existing_papers_summary()` 적용:

```python
for paper_dir in base.iterdir():
    if not _safe_child_dir(base, paper_dir):
        continue
    meta = _load_paper_metadata(paper_dir)
    ...
```

검증에도 listing check를 추가하세요:

```bash
ln -sfn /etc outputs/pf-symlink-escape
curl -s -b "paperflow_token=$TOKEN" "http://localhost:8090/api/papers?tab=unread" \
  | grep -q "pf-symlink-escape" && echo "FAIL: listed symlink escape" || echo "OK: symlink not listed"
rm -f outputs/pf-symlink-escape
```

### 2. Task 4 설명의 `..` 표현이 아직 `_safe_filename()` 동작과 불일치합니다

현재 계획은 Task 4 Why에서 "`filename`에 `/`, `\`, `..`, 절대경로 성분"이라고 설명합니다. 하지만 snippet은 `filename in {".", ".."}`만 거부하고 `paper..v1.pdf` 같은 substring은 허용합니다.

코드는 POSIX traversal 방어 기준으로 타당합니다. 설명을 아래처럼 고치면 됩니다.

```text
filename에 `/`, `\`, NUL, 빈 값, `.`/`..` 단일 component, 절대경로 성분이 들어가면 ...
```

## 최종 판단

위 2건 반영 후 최종 승인 가능합니다. 현재 상태에서는 `===CODEX_FINAL_APPROVAL===`를 줄 수 없습니다.
