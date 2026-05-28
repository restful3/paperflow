# `/viewer/by-id` 설계 — Claude 메타 리뷰 (Codex round-1 REFINE 대응)

각 지적을 실제 파일로 검증한 뒤 ACCEPT / DEFER 분류. 모두 spec 에 반영됨.

## ACCEPT (검증 후 spec 반영)

### Codex #1 — `%2F` 설명 부정확 → 정정
- **검증**: `papers.py:800` `_is_safe_paper_name` 이 `/` 거부. catch-all `/viewer/{paper_name:path}` 가 `by-id/a/b.pdf` 흡수 → `safe_paper_dir` None → 인증 시 302 `/papers`, 비인증 302 `/login`. **404 아님** 확정.
- **반영**: spec 4.2 의 "라우터 404" 삭제, catch-all fallback 동작으로 정정. 테스트 T5d(encoded slash, 기대값 302 `/papers`) + T5c(`%2e%2e` 핸들러 도달 → None → `/papers`) 추가.

### Codex #2 — 라우트 등록 순서 주장 맞음 → regression 테스트 추가
- **반영**: T8 추가 — `/viewer/by-id/{valid}` 가 by-id 핸들러를 타고 catch-all 에 흡수되지 않음(순서 역전 시 실패).

### Codex #3a — full `pfmcp-...pdf` contract 검증 → 채택
- **검증**: `_build_expected_filename`(mcp_jobs.py:99) 이 항상 `pfmcp-{short}-{slug}.pdf` 생성(고정). MCP job 의 PDF 는 expected_filename 이름으로 newones/ 배치(156행), `main_terminal.py:1293` 이 original_filename 을 그 basename 으로 기록 → metadata-match 와 filesystem-scan **둘 다** pfmcp 파일명으로 동작. 따라서 tightening 이 정상 해석을 깨지 않음.
- **반영**: 정규식 `^[A-Za-z0-9._-]{1,128}$` → `^pfmcp-[A-Za-z0-9._-]{1,120}\.pdf$`. `\x00` guard 추가. T5b(contract 위반 안전 파일명 `paper_meta.json`/`foo.pdf`/`.hidden` 거부) 추가.

### Codex #4 — 모든 redirect 에 `no-store` → 채택
- **반영**: `_by_id_redirect` 헬퍼로 성공/`/papers`/`/login` 전부 `no-store`. T1/T3/T4 가 헤더 검증.

### Codex #5 — 테스트 케이스 추가 → 채택
- **반영**: T5a(regex boundary: 120 초과·`%`·공백·unicode·NUL), T5b, T5c, T5d, T8(route order), T10(**기존 T20/T22 갱신**), T11(기존 `/viewer/{name}` regression). symlink 테스트는 #3b DEFER 라 제외.
- **검증**: 기존 T20(`test_mcp_router.py:179`)·T22(232행) 가 paper_name 기반 viewer_url 을 assert → viewer_url 교체로 깨짐 확인. T10 으로 expected_filename-based 재작성.

### Codex #6 — 계약 변경 breaking 명시 + 소비자 점검 → 채택
- **검증**: QuantSquad `paperflow-source-intake/SKILL.md:124` 가 viewer_url 을 보고서 표에 마크다운 링크로 embed 만 함. paper_name 파싱 없음(`.split("/viewer/")` 등 부재) → **계약 변경에 영향 없음**. (working-tree only, 본 PR 수정 안 함.)
- **반영**: spec 4.3 에 breaking change 영향 4종 + "opaque URL, paper_name 파싱 금지, redirect-follow 필요" 명시. docstring/README 갱신 항목에 포함.

### Codex #7 — `expected_filename` 존재 가정 맞음 → 보강 노트
- **반영**: spec 4.3 에 "required field, 누락 record 는 model_validate 단계 실패" 노트. spec 6 에 "source PDF·original_filename 둘 다 없는 과거 산출물은 by-id 해석 불가(수용)" 명시.

## DEFER (범위 밖, 별도 follow-up)

### Codex #3b — child file symlink hardening
- **사유**: (1) 본 라우트는 단일 테넌트 self-hosted viewer 대상 → "untrusted local filesystem writes" 는 threat model 밖. (2) `_scan_*_dir_only` 는 reconcile 경로와 공유 → 수정 시 blast radius 가 본 PR(수술적 변경) 범위 초과. Codex 도 "low priority hardening, 핵심 보안 결함 아님" 으로 평가.
- **반영**: spec 4.2·7 에 후속 항목으로 명시.

## 잔존 이견
없음. Codex round-1 의 필수 2건(#1, #2) + 권고 전부 ACCEPT, #3b 만 근거와 함께 DEFER.
