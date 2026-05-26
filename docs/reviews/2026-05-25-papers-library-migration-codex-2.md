===CODEX_FINAL_APPROVAL===

- ACCEPT: backup/state dir은 `papers/` 밖인 `<BASE_DIR>/.paperflow/...`로 둔다.
- ACCEPT: `reading_progress -> reading_status` 추론은 dry-run report 후보 + explicit opt-in only; runtime auto-promotion 없음.
- ACCEPT: `paperflow_id` 기반 route/schema는 본 plan out of scope.
- ACCEPT: frontmatter helper는 UTF-8 BOM, CRLF/LF, 빈 파일, 본문 없는 frontmatter를 명시 처리한다.
- ACCEPT: `paper_meta.json -> frontmatter`는 one-time projection이며 bidirectional sync는 하지 않는다.
- ACCEPT: dry-run은 service 중단 전에 실행 가능한 strict read-only 단계여야 한다.
- ACCEPT: `PAPER_LIBRARY_DIR` env var를 명시하고 기본값은 `papers/`로 한다.
- Q1/Q2/Q3 추가 명세에 동의: 단일 primary note + variants, `location: papers|outputs|archives` transition, rating/read_at frontmatter + progress/last_read state dir.
- 18단계 implementation order에 동의한다.
- 추가 비판 없음. 계획 보강 후 구현 단계로 진행 가능.
