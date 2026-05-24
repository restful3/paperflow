# Meta-Review of Codex Round 3

대상: `docs/reviews/2026-05-24-viewer-security-hardening-codex-3.md`

## 검증 결과

| 코덱스 Round 3 지적 | 실제 상태 | 결론 |
|---|---|---|
| `list_papers()` (papers.py:577-581)가 `item.is_dir()`만 확인 | `item.is_dir() and not item.name.startswith(".")` 만. symlink 통과 가능 | ✅ ACCEPT |
| `_get_existing_papers_summary()` (papers.py:960-963)도 동일 패턴 | 확인됨 | ✅ ACCEPT |
| Task 4 Why의 `..` 표현이 실제 `_safe_filename` 동작과 불일치 | 코드는 `filename in {".", ".."}` exact match만 거부. `paper..v1.pdf` 허용. 설명은 "`..` 성분"이라 모호함 | ✅ ACCEPT (텍스트 수정만) |

## ACCEPT (Plan에 반영)

1. **`_safe_child_dir(base, item)` helper 신설** (Task 3 Step 1) — 비숨김/디렉터리/base 하위 3조건. listing 경로의 symlink escape 일관 차단.

2. **Task 3 새 Step 6**: `list_papers`와 `_get_existing_papers_summary`에 `_safe_child_dir` 적용. 기존 Step 6~8을 7~9로 한 칸 밀음.

3. **Task 3 Step 8 검증 C2 추가**: symlink가 listing API에도 노출되지 않는지 grep으로 확인.

4. **Task 4 Why 텍스트 정정**: "filename이 빈 값/NUL이거나 `/`, `\`을 포함하거나 `.`/`..` 단일 component이거나 `Path(filename).name != filename`(절대경로·다중 component)이면..."로 명확화. `paper..v1.pdf` 같은 substring은 traversal이 아님을 명시.

5. **Self-Review 호출자 그물망 표 갱신**: listing(`list_papers`)과 duplicate-check(`_get_existing_papers_summary`) 2행 추가, chat POST의 Step 번호 6→7 갱신.

## REJECT

(없음) — 두 지적 모두 actual code로 검증되어 ACCEPT.

## 누적 변경

- Task 수: 5 (구성 변경 없음, Task 3에 Step 6 신설)
- 코드 변경 폭: papers.py에 `_safe_child_dir` helper 1개 + `list_papers`/`_get_existing_papers_summary` 각각 3~5줄 수정
- 여전히 surgical: 새 모듈/리팩터 없음
