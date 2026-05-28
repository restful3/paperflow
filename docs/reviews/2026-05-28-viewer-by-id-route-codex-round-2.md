===CODEX_FINAL_APPROVAL===

판정: **ACCEPT**. round-1 REFINE의 필수 항목은 충분히 해소됐고, 남은 사항은 구현 시 주의 또는 후속 hardening 수준입니다.

## 확인 결과

### 1. `%2F` 정정 설명

spec 4.2의 수정 설명이 정확합니다. `/viewer/by-id/a%2Fb.pdf`는 `%2F`가 `/`로 디코드된 뒤 by-id 단일 세그먼트 route에는 매칭되지 않고, 현재 앱의 catch-all `/viewer/{paper_name:path}`가 `by-id/a/b.pdf`로 흡수합니다. 이후 기존 `viewer_page` 흐름에서 비인증은 먼저 `/login` 302, 인증 상태에서는 `safe_paper_dir` → `_is_safe_paper_name`의 `/` 거부로 `/papers` 302가 됩니다. “라우터 404”를 제거한 것은 맞습니다.

T5c(`%2e%2e`)와 T5d(encoded slash)를 분리한 것도 적절합니다. raw `..`보다 encoded dot segment로 handler 도달 케이스를 테스트하는 편이 안정적입니다.

### 2. `pfmcp` contract tightening

정상 MCP 해석을 깨지 않는다는 검증은 맞습니다. `submit_job()`이 `expected_filename`을 `_build_expected_filename()`으로 생성하고, source PDF를 그 이름으로 `newones/`에 배치합니다. 변환 경로의 `main_terminal.py:1293`도 `md_path` basename에서 `original_filename`을 복원하므로 MCP 경로에서는 `original_filename == expected_filename == pfmcp-...pdf`가 됩니다.

따라서 metadata match와 filesystem scan 모두 `pfmcp-...pdf` 이름으로 동작한다는 spec 4.2 설명은 타당합니다.

비고: 현재 정규식은 exact `pfmcp-{12hex}-{slug<=40}.pdf`까지 강제하지는 않고 `pfmcp-*.pdf` 계열을 넓게 허용합니다. 하지만 round-1에서 요구한 path traversal 방어와 임의 안전 파일명(`paper_meta.json`, `foo.pdf`, `.hidden`) probing 차단 목적에는 충분합니다. 더 좁히는 것은 선택 사항입니다.

### 3. child file symlink hardening DEFER

DEFER 근거는 합당합니다. `_is_safe_direct_child`가 paper folder symlink escape는 막고 있고, 남은 child file symlink 이슈는 remote path traversal이 아니라 로컬 파일시스템을 쓸 수 있는 행위자 threat model입니다. 단일 테넌트 self-hosted 전제에서는 필수 차단 항목이 아닙니다.

또한 `_scan_*_dir_only`가 reconcile 경로와 공유되므로, 이 PR에서 수술적으로 고치지 않고 별도 follow-up으로 남기는 판단이 적절합니다.

### 4. 테스트 T1-T11

필수 케이스는 충분합니다. round-1에서 요구한 route order, encoded slash fallback, encoded dot segment, regex boundary, contract 위반 파일명, `viewer_url` 계약 갱신, 기존 viewer route regression이 모두 반영됐습니다.

구현 시 주의할 점만 남깁니다.

- T5d는 by-id resolver 미호출을 monkeypatch/mock으로 직접 검증하고, `follow_redirects=False`로 최종 status/location을 확인하는 편이 좋습니다.
- T8은 유효 `pfmcp-...pdf`에 대해 by-id resolver가 호출됐다는 사실을 보게 만들어야 route 순서 회귀를 확실히 잡습니다.
- T10은 기존 T20/T22의 paper_name URL round-trip 기대를 완전히 제거하고, non-ASCII paper_name이 viewer_url에 포함되지 않는 것을 정상으로 assert해야 합니다.
- T11은 로그인 dependency override나 테스트 cookie를 명시해 기존 `/viewer/{paper_name}`의 인증 redirect와 정상 렌더 케이스가 섞이지 않게 하세요.

## 결론

더 이상 설계 단계의 필수 수정 항목은 없습니다. 현재 spec으로 구현 진행해도 됩니다.
