# Final Summary — Viewer Security Hardening Plan Agreement

**날짜**: 2026-05-24
**결과**: ✅ 4라운드 합의 완료 (`===CODEX_FINAL_APPROVAL===` Round 4)

## 결과물

- **합의된 계획서**: `docs/superpowers/plans/2026-05-24-viewer-security-hardening.md`
- **리뷰 사이클** (코덱스 ↔ Claude):
  - Round 1: `docs/reviews/2026-05-24-viewer-security-hardening-codex.md`
  - Round 1 메타리뷰: `docs/reviews/2026-05-24-viewer-security-hardening-claude-meta-review.md`
  - Round 2: `docs/reviews/2026-05-24-viewer-security-hardening-codex-2.md`
  - Round 2 메타리뷰: `docs/reviews/2026-05-24-viewer-security-hardening-claude-meta-review-round2.md`
  - Round 3: `docs/reviews/2026-05-24-viewer-security-hardening-codex-3.md`
  - Round 3 메타리뷰: `docs/reviews/2026-05-24-viewer-security-hardening-claude-meta-review-round3.md`
  - Round 4: `===CODEX_FINAL_APPROVAL===` (response file unused — 승인 신호만)

## 합의 내용 (구현 시 적용할 변경)

### Task 1 — JWT 시크릿 검증 강화
- `config.py`: substring 차단 6개(`change-me`, `changeme`, `replace-with`, `placeholder`, `your-secret`, `paperflow-secret`) + 길이 하한 32자
- `main.py`: `create_app()`에서 `settings.validate_runtime()` 호출
- 실제 `.env`의 약한 시크릿 회전 명시

### Task 2 — 쿠키 `secure` 플래그 토글
- `auth.py`: `secure=settings.COOKIE_SECURE`
- 신규 환경 변수 `COOKIE_SECURE` (기본 false, HTTPS 운영 시 true)
- `SameSite=Lax` 유지 이유(cross-site embedding 미지원) 명시
- 검증에 `--force-recreate` + `docker compose exec env` 확인

### Task 3 — Path traversal 방어 (호출자 일관 적용)
- `papers.py`: `safe_paper_dir`, `_is_safe_paper_name`, `_is_within`, `_safe_child_dir` 4개 헬퍼 도입
- `_resolve_paper_dir = safe_paper_dir` alias로 기존 호출자 자동 보호
- 명시 적용:
  - `get_paper_info`, `archive_paper`, `restore_paper`, `enrich_paper_metadata`, `viewer_page`의 `touch_last_read` 순서
  - `list_papers`, `_get_existing_papers_summary` (symlink 일관 차단)
  - `POST /chat` 라우트 초입 가드
- 8개 케이스 manual 검증 (정상 / 트래버설 / symlink escape / listing 노출 / archive·restore·markdown·assets·chat-DELETE·chat-POST)

### Task 4 — `/api/upload` 파일명 traversal 차단
- `papers.py`: `_safe_filename` 헬퍼 (빈 값/NUL/`/`/`\`/`.`/`..` 단일 component/`Path(filename).name` round-trip)
- `save_upload`: defense-in-depth `_is_within` 추가
- `api.py`: upload 라우트에서 sanitized name 사용

### Task 5 — 문서화
- `CLAUDE.md`: `JWT_SECRET_KEY` 필수성, `COOKIE_SECURE` 신규 항목

## Out of scope (follow-up High 후보)

이번 plan 외 별도로 다룰 보안 항목 (코덱스도 별도 plan 동의):
- 약한 `LOGIN_PASSWORD` startup guard
- Markdown / assistant response XSS (`marked.parse` + `x-html` + sanitizer 부재)
- `/api/import-url` SSRF / headless Chromium
- 컨테이너 non-root 실행 (defense-in-depth)
- pytest 인프라 / 단위 테스트

## 부수 결과물 — Codex Peer Reviewer 스킬 보강

이번 합의 루프 중 발견된 운영 결함들을 `/home/restful3/.claude/skills/codex-peer-reviewer/`에 반영:

1. **Step 4 sustained-Working 검증** — 단발 `Working` flash가 plan-mode dialog로 떨어지는 케이스를 catch. `Create a plan?` 텍스트 명시적 grep + 3회 sustained check.
2. **`paste-buffer -p` (bracketed paste) 강제** — 멀티라인 paste에 `-p`가 없으면 Codex CLI가 Enter를 newline으로 흡수해 input이 stuck됨. Step 3 + Anti-pattern에 명시.
3. **poll_codex.sh mid-flight 자가 복구** — `dismiss_plan_mode_if_present()` 헬퍼로 START_WAIT/main loop에서 plan-mode 다이얼로그 자동 dismiss.
4. **Recovery: stuck-input 절차** — Ctrl+C가 codex 프로세스를 죽인다는 함정 + 안전한 복구 방법(짧은 메시지 flush → window 재생성).

## 다음 단계

`docs/superpowers/plans/2026-05-24-viewer-security-hardening.md`를 별도 세션에서 `superpowers:executing-plans` 또는 `superpowers:subagent-driven-development`로 구현.
