# 세션 핸드오프 — Papers Library Migration 합의 + 부가 작업
_최종 갱신: 2026-05-26 14:40_

> 이전 핸드오프(v1/v1.1 MCP 서버 작업, 25KB)는 `HANDOFF.md.bak_20260526_143812` 에 백업.
> 본 파일은 **2026-05-25~26 신규 작업** 기준으로 재작성됨.

## 🎯 목표

이번 세션의 세 갈래 작업:

1. **PaperFlow Papers Library Migration Plan 검토 + Codex 합의** — `outputs/` 폴더 기반 모델 → `papers/` 라이브러리 + frontmatter 기반 reading state 모델로 전환하는 계획을 검토·합의하여 구현 진입 가능한 supplement 문서 산출
2. **사이드: 3개 폴더의 `_ko_explained.md` 생성** — paper-explainer skill로 한국어 해설판 생성
3. **사이드: paperflow MCP env 문제 해결** — `PAPERFLOW_MCP_API_KEY` 미상속 진단 + 항구적 수정

## ✅ 완료

### A. Papers Library Migration Plan 합의 (2-round Codex agreement)

- **Round 1**: Claude 14개 비판 → Codex 14개 모두 ACCEPT + 10개 추가 항목 + Q1/Q2/Q3 권고 + 15단계 order
- **Round 2**: Claude 메타-리뷰 (fact-check 통과, 8 ACCEPT + 4 REFINE + 4 EXTEND) → Codex `===CODEX_FINAL_APPROVAL===` 7개 모두 ACCEPT
- 최종 산출: `docs/superpowers/plans/2026-05-25-paperflow-papers-library-migration-supplement.md` — 구현 PR의 source of truth
- 합의 요약: `docs/reviews/2026-05-25-papers-library-migration-final-summary.md`
- 라운드별 리뷰 파일 4개: `docs/reviews/2026-05-25-papers-library-migration-{claude-review,codex,claude-meta-review,codex-2}.md`

### B. 3개 `_ko_explained.md` 생성

| 폴더 | 라인 비율 |
|---|---|
| `outputs/LLM Powered Autonomous Agents/` | 484 → 1052 (2.17×) |
| `outputs/This site can't be reached/` | 14 → 165 (11.79× — 에러 페이지 캡처본) |
| `outputs/종합건강검진 결과보고서Health Examination Report/` | 365 → 935 (2.56×, OCR HTML 표 제외 visible 2.08×) |

### C. paperflow MCP env 항구 수정

- **원인**: tmux 서버(2026-05-13 시작)가 rc 파일 수정(2026-05-25)보다 12일 먼저 시작 → 새 셸이 env 미상속. `tmux show-environment -g`가 비어 있던 것이 결정적 증거.
- **수정**:
  - `tmux setenv -g PAPERFLOW_MCP_API_KEY <key>` — 글로벌 등록
  - `~/.bashrc` line 5-6 export 제거 → NOTE 주석으로 대체 (백업: `~/.bashrc.bak_20260526_134345`)
  - `~/.zshrc` line 2-3 export 제거 → NOTE 주석으로 대체 (백업: `~/.zshrc.bak_20260526_134345`)
  - `~/.profile` line 34는 canonical export로 유지 (변경 없음)
- **검증**: `bash -lc` 새 로그인 셸 env 로드 OK, `curl POST /mcp/ initialize` HTTP 200, `mcp__paperflow__list_jobs` 정상 응답 (paperflow v1.27.1)

## 🔄 진행 중

없음. 모든 작업 완료.

## ⏭️ 다음 단계

1. **신규 6개 문서 git 커밋·푸시** (본 세션에서 진행 중) — supplement, 5 reviews
2. **Papers Library Migration 실제 구현 진입 여부** — supplement의 18단계 중 step 1~3부터 (path config, frontmatter helper, Docker 변경)
3. **🚨 노출된 클라우드 키 3개 로테이트** (사용자 직접):
   - ElevenLabs (앞 `sk_dd07787...`) → <https://elevenlabs.io/app/settings/api-keys>
   - Brave Search (`BSAZxt_mEuR8...`) → <https://api-dashboard.search.brave.com/app/keys>
   - Supermemory (앞 `sm_BGWmZAVF...`) → Supermemory 대시보드
4. **`viewer/app/routers/pages.py` 미커밋 hotfix 커밋** (이전 세션 산출, 이번 세션 무관 — login TemplateResponse 형식 변경)

## 🧠 대화에만 있던 핵심 컨텍스트

### Migration 합의의 핵심 결정 (supplement 본문 참조)

- **Q1 (frontmatter primary)**: 단일 primary note (`*_ko.md` 우선, 없으면 `*.md`). 나머지는 `type: paper-variant` + `paperflow_primary`/`paperflow_variant` 키. Dataview `FROM "papers" WHERE type="paper"`가 한 논문을 1회만 카운트하도록.
- **Q2 (location 스키마)**: `Literal["papers", "outputs", "archives"]` + 응답에 `library_status: "active"|"archived"` 병기. UI는 `location === 'outputs'` 검사를 `library_status === 'active'`로 점진 마이그레이션.
- **Q3 (frontmatter 흡수 범위)**: 혼합 모델 — `rating`/`read_at` → frontmatter, `reading_progress`/`last_read_at` → JSON. **단 JSON 위치는 `<BASE_DIR>/.paperflow/state/`** 로 vault(`papers/`) 밖. Obsidian noise 방지.
- **paper_meta.json ↔ frontmatter**: one-time projection only. 양방향 sync는 race condition 비용 때문에 거부. re-process 시 사용자 편집 키(`rating`, `read_at`, `reading_status`, `library_status`, `aliases`)는 보존.
- **Migration workflow**: dry-run (services up, **read-only 보장**) → 사용자 confirm → maintenance lock → real run → post-check → fallback ≥1 release. duplicate folder/original_filename hard-fail.
- **PAPER_LIBRARY_DIR env var**: 기본값 `papers`, deployment마다 vault 위치 변경 가능.
- **`paperflow_id` 기반 stable route는 본 plan OUT OF SCOPE** — 별도 plan 필요.
- **encoding/BOM/CRLF 처리는 frontmatter helper의 MUST 요구사항**.

### Codex 합의 운영 노트

- Codex CLI는 `===CODEX_FINAL_APPROVAL===` 정확 토큰만 종료 신호로 인식 (자연어 "동의합니다" 불가)
- Codex window: `paperflow:codex` (tmux 세션 `paperflow` 내)
- Codex가 응답 파일을 직접 저장하도록 매 요청에 `<RESPONSE_PATH>`를 명시
- Round 2에서 Codex가 즉시 1초 미만에 final approval — 백그라운드 폴링이 시작 전에 종료된 것처럼 보였으나 정상 동작

### MCP env 진단 노트

- `tmux show-environment -g` (글로벌)과 `tmux show-environment` (세션) 모두 비어 있던 것이 핵심 증거
- `bash -lc` (login shell)로 검증해야 `.profile` 실행되어 env 확인 가능
- tmux 9개 세션 (connect, health, md, mosh, office, paperflow, qsc, tori, wiki) 모두 동일 tmux 서버 위에 있음 → 글로벌 setenv 1회로 9개 모두 새 spawn 정상 상속

### _ko_explained.md 처리 노트

- **This site can't be reached**: 학술 자료 아님. Chrome `ERR_CONNECTION_REFUSED` 페이지가 PDF로 캡처되어 PaperFlow에 들어온 산출물. MCP가 `http://127.0.0.1:8765`의 PDF를 가져오려다 실패한 부산물. 1.5× 비율 적용 불가 (원본 3줄). 운영자 관점 진단 가이드로 확장.
- **종합건강검진 결과보고서**: 환자 송태영, 차병원 검진센터 2026-04-30. 단기추적 2개(지방간/HbA1c 6.3%) + 경과관찰 7개(비만·위염·GGO·담낭용종·전립선석회·뇨당·A형간염 백신). 대사증후군은 없음(허리둘레 97.2cm 하나만 기준 초과). InBody 권장 체중 -14.9kg.
- **LLM Powered Autonomous Agents**: Lilian Weng 2023-06 블로그. AutoGPT/GPT-Engineer 시스템 메시지 OCR 깨짐은 원문 보존, 형식만 명료화.

## ⚠️ 클리어 전 주의

### 미커밋 (커밋·푸시 진행 중)

이번 세션에서 커밋할 항목:

```
?? docs/superpowers/plans/2026-05-25-paperflow-papers-library-migration.md           # 이전 세션 codex 산출 (untracked)
?? docs/superpowers/plans/2026-05-25-paperflow-papers-library-migration-supplement.md # 이번 세션 합의 최종본
?? docs/reviews/2026-05-25-papers-library-migration-claude-review.md
?? docs/reviews/2026-05-25-papers-library-migration-codex.md
?? docs/reviews/2026-05-25-papers-library-migration-claude-meta-review.md
?? docs/reviews/2026-05-25-papers-library-migration-codex-2.md
?? docs/reviews/2026-05-25-papers-library-migration-final-summary.md
M  HANDOFF.md                                                                         # 본 파일
```

별도 처리 보류 (이번 세션 무관, 사용자 결정 필요):

```
M  viewer/app/routers/pages.py       # 이전 세션 login hotfix
?? HANDOFF.md.bak_20260526_143812    # 이전 v1.1 핸드오프 백업 (.gitignore 후보)
```

`.claude-home/.npm/*` 변경분 다수는 캐시 노이즈로 무시. `outputs/`는 .gitignore 이므로 신규 3개 `_ko_explained.md`는 git에 잡히지 않음(정상).

### 백그라운드

없음. 이번 세션의 codex 폴링 작업 2건(`bbmyu0nfe`, `btbpp6brf`)은 모두 completed.

### 미완료 todo

없음. 이번 세션의 8개 TaskCreate 모두 completed.

### 셸 환경

- `~/.profile` 가 `PAPERFLOW_MCP_API_KEY` 의 canonical export 위치
- `tmux setenv -g` 로 글로벌 등록되어 새 spawn 정상 상속
- 현재 cdd로 띄운 codex 셸은 이전 env 그대로 — 사용자가 `exec $SHELL` 또는 `source ~/.profile` 후 codex 재실행 필요

### 🚨 키 노출 (이전 진단 출력에 평문 출현)

- `ELEVENLABS_API_KEY` (sk_dd07787...)
- `BRAVE_SEARCH_API_KEY` (BSAZxt_mEuR8...)
- `SUPERMEMORY_API_KEY` (sm_BGWmZAVF...)
- `PAPERFLOW_MCP_API_KEY` (ef983bc98...) — 로컬 전용 (`localhost:8090`), 위험 낮음

→ 이 대화 로그에 남았으므로 위 3개는 각 서비스에서 재발급 권장.

## 📂 관련 파일

### 이번 세션 신규 작성

- `docs/superpowers/plans/2026-05-25-paperflow-papers-library-migration-supplement.md` — Q1/Q2/Q3 결정 + frontmatter 스키마 + state dir 정책 + paper_meta projection + Docker 변경 표면 + 18단계 implementation order. **구현 PR의 source of truth.**
- `docs/reviews/2026-05-25-papers-library-migration-claude-review.md` — Claude 14개 비판 항목
- `docs/reviews/2026-05-25-papers-library-migration-codex.md` — Codex Round 1 응답 (14 ACCEPT + 10 추가 + Q권고 + 15단계)
- `docs/reviews/2026-05-25-papers-library-migration-claude-meta-review.md` — fact-check + 8 ACCEPT + 4 REFINE + 4 EXTEND
- `docs/reviews/2026-05-25-papers-library-migration-codex-2.md` — `===CODEX_FINAL_APPROVAL===` + 7 ACCEPT 요약
- `docs/reviews/2026-05-25-papers-library-migration-final-summary.md` — 라운드·산출·LOC 추정(~2,120 LOC) 요약
- `outputs/LLM Powered Autonomous Agents/LLM Powered Autonomous Agents_ko_explained.md`
- `outputs/This site can't be reached/This site can't be reached_ko_explained.md`
- `outputs/종합건강검진 결과보고서Health Examination Report/종합건강검진 결과보고서Health Examination Report_ko_explained.md`

### 이번 세션 수정 (홈 디렉터리)

- `~/.bashrc` — line 5-6 export 제거 → NOTE 주석. 백업: `~/.bashrc.bak_20260526_134345`
- `~/.zshrc` — line 2-3 export 제거 → NOTE 주석. 백업: `~/.zshrc.bak_20260526_134345`
- `~/.profile` — 변경 없음 (canonical export 위치)
- tmux 글로벌 env — `PAPERFLOW_MCP_API_KEY` 등록 (재부팅 시 사라짐, .profile이 다시 채움)

### 이전 세션 산출물 (참고만, 이번 세션 무관)

- `viewer/app/routers/pages.py` — TemplateResponse `request=..., name=..., context=...` 키워드 형식으로 변경 (Starlette deprecation hotfix)
- `HANDOFF.md.bak_20260526_143812` — 이전 v1/v1.1 MCP 서버 작업 핸드오프 25KB. v1.1 ship 완료 상태였음.

### Codex 환경

- tmux 세션 `paperflow` 내 윈도우 `codex`
- Codex CLI v0.133.0, model gpt-5.5 high
- `~/.codex/config.toml` 의 `[mcp_servers.paperflow]` 가 `bearer_token_env_var = "PAPERFLOW_MCP_API_KEY"` 로 paperflow MCP를 등록
