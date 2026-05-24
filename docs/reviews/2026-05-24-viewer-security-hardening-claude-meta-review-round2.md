# Meta-Review of Codex Round 2

대상: `docs/reviews/2026-05-24-viewer-security-hardening-codex-2.md`
계획서: `docs/superpowers/plans/2026-05-24-viewer-security-hardening.md`

## 검증 결과

| 코덱스 Round 2 지적 | 실제 상태 | 결론 |
|---|---|---|
| Plan에 `_safe_paper_dir` 표기 잔존 (line 7, 20, 21, 354) | grep 결과 정확히 4곳 잔존; 코드 snippet은 `safe_paper_dir` | ✅ ACCEPT |
| Symlink escape 검증 부재 | `Path.resolve()`가 symlink follow + `_is_within`이 base.resolve() 하위 검사 → 방어는 됨. 그러나 manual verify에서 입증 안 됨 | ✅ ACCEPT (검증만 추가) |
| archive/restore HTTP 기대값 | api.py:97 `HTTPException(status_code=400)` → 400 정상 | ✅ ACCEPT (검증 추가) |
| markdown PUT traversal | `save_markdown`이 `_resolve_paper_dir`(alias) 사용 → 자동 보호. 검증 부재 | ✅ ACCEPT (검증 추가) |
| asset traversal | `get_asset_path`(papers.py:841)가 `_resolve_paper_dir` + `paper_dir in asset.resolve().parents` 이중 가드 → 보호됨. 검증 부재 | ✅ ACCEPT (검증 추가) |
| chat history DELETE traversal | `clear_chat_history`(chat.py:104)가 `_resolve_paper_dir` 사용 → 보호됨 (False 반환 → 404). 검증 부재 | ✅ ACCEPT (검증 추가) |
| `POST /chat` route 초입 가드 없음 | api.py:121-153 — generator 내부 ValueError → SSE error event. HTTP는 200 | ✅ ACCEPT (route 초입 `safe_paper_dir` 가드 추가) |
| outputs 비어있을 때 / 빈 토큰 guard | bash 검증 명령에 `test -n` 가드 없음 | ✅ ACCEPT (간단한 가드 추가) |

## ACCEPT (Plan에 반영)

1. **표기 통일** — Plan line 7, 20, 21, 354의 `_safe_paper_dir`를 `safe_paper_dir`로 교체.
2. **Task 3 Files에 `viewer/app/routers/api.py` 추가** + **새 Step**: `chat_with_paper` 라우트 초입에 `paper_dir = paper_svc.safe_paper_dir(name); if not paper_dir: raise HTTPException(status_code=404)` 가드 추가.
3. **Task 3 Step 6 검증 보강**:
   - `test -n "$TOKEN" || { echo FAIL; exit 1; }` 추가
   - `test -n "$EXISTING" || { echo "outputs 비어있음 — 검증 스킵, 먼저 paper 1개 이상 필요"; exit 1; }` 추가
   - 신규 케이스: symlink escape, archive/restore (POST → 400), markdown PUT (→ 400), asset traversal (→ 404), chat/history DELETE (→ 404), chat POST (→ 404 with route guard)

## DEFER (Out of scope 섹션에 follow-up High로 명시)

코덱스가 "blocking은 아니나 같은 우선순위"로 지적한 항목들 — 계획의 Out of scope 섹션을 follow-up High 후보로 명확히 한다:

- **Markdown XSS** (viewer.html의 `marked.parse()` + `x-html` + sanitizer 부재) — HTTPOnly 쿠키 우회 same-origin fetch 가능 → follow-up High
- **`LOGIN_PASSWORD` 약한 값 startup guard** — 8090 직접 노출 시 follow-up High
- **`/api/import-url` SSRF / headless Chromium** — 약한 password와 결합 시 위험 — follow-up Medium/High
- **컨테이너 non-root 실행** — defense-in-depth follow-up

## REJECT

(없음) — 코덱스 지적 전부 actual code/계획서로 검증되어 ACCEPT.

## 누적 변경 추정

원 계획 → Round 1 보완 → Round 2 보완 누적:
- Task 수: 4 → 5 → 5 (Task 3에 라우트 가드 1 step 추가)
- Plan 라인: ~270 → ~700 → ~770 (검증 케이스 추가)
- 코드 변경 폭: api.py에 chat route 5줄 추가, 그 외 동일

여전히 surgical: 새 모듈 없음, 무관한 리팩터 없음.
