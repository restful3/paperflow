# 세션 핸드오프 — paper-audio-korean 듣기 낭독판 스킬 + 뷰어 통합
_최종 갱신: 2026-05-31 13:10 KST_

## 🎯 목표
해설판(`_ko_explained.md`)을 아이폰 음성으로 들었을 때 이해되는 한국어 낭독판(`<basename>_ko_audio.md`)으로 변환하는 `paper-audio-korean` 스킬을 만들고, 뷰어에서 "듣기" 토글로 보이게 한다 (시각장애인용 오디오 디스크립션 원칙: 수식·표·그림·코드를 placeholder 아닌 자연어로).

## ✅ 완료
- **paper-audio-korean 스킬** 작성: `.claude/skills/paper-audio-korean/SKILL.md` (코덱스 3라운드 리뷰 REFINE→REFINE→GO 반영)
- **뷰어 1급 포맷 통합** (commit `a402fbd`): 백엔드(papers.py `md_ko_audio` 감지 + `get_md_ko_audio_path` + en경로/save/RAG 제외 + mcp_zip 게이팅 + api 엔드포인트 + pages 템플릿 변수) + 프론트(viewer.html "듣기" 토글 2곳, KO전용, Easy와 상호배타) + **TDD 테스트 `tests/test_papers_audio.py` 5개**. **전체 161 passed (회귀 0)**.
- **LongLM 전체 낭독판 생성**(스모크): `outputs/LLM Maybe LongLM SelfExtend.../...­_ko_audio.md` (589줄/90KB) + `_ko_audio.meta.json` sidecar. CRITICAL grep 위반 0건. 서브에이전트 5개 병렬 변환 후 메인이 조립.
- **라이브 검증**: viewer 재빌드·재시작 완료, `/api/papers/{name}/md-ko-audio` → HTTP 200 90738 bytes, 뷰어 페이지 `hasMdKoAudio: true` + 듣기 토글 렌더 확인.
- **문서 정합화** (commit `6986394`): README/CLAUDE.md를 B-full로 정정, 스펙·계획·코덱스 리뷰 트레일 3개 추가.

## 🔄 진행 중
없음. (audio 기능 작업은 코드·문서·스모크·검증까지 일단락)

## ⏭️ 다음 단계
1. (선택) 다른 논문에도 `paper-audio-korean` 적용 — batch 모드로 `_ko_audio.md` 없는 해설판부터.
2. (선택) 큰 장(예: 4장)은 서브에이전트 출력 한계 근처 — 더 큰 논문은 더 잘게 분할 변환.

(완료: paper-explainer batch 필터 + 이름 수정 커밋 `879d7a6`.)

## 🧠 대화에만 있던 핵심 컨텍스트
- **결정 (B-full)**: 출력 위치를 처음엔 `audio/` 하위 디렉터리(백엔드 변경 0)로 설계했으나, 사용자가 "해설판처럼 파일명으로 구분 + 뷰어에서 보이게"를 택해 **폴더 직하위 `_ko_audio.md` + viewer/MCP 1급 포맷 통합**으로 전환. 스펙/계획 상단에 전환 주석 있음.
- **발견 (파일 감지 충돌)**: 새 suffix `_ko_audio.md`는 `papers.py`의 `elif` 사슬에서 `_ko.md`/`_explained.md`에 안 걸려 마지막 `.md` catch-all로 떨어져 **영어 원문(`md_en`)으로 오분류** → `get_md_en_path`/`save_markdown(en)`이 덮어쓸 위험. 코덱스 R1 High #1, 실제 코드로 검증됨. 해결: 전용 `md_ko_audio` 분기 + 5개 호출처 제외.
- **발견 (paper-explainer marker 없음)**: paper-explainer는 completion marker를 안 쓰고 기존 해설판에도 없음 → 해설판 완료 판정은 marker가 아니라 **legacy validation**(존재+비어있지않음+제목+heading coverage)으로. marker/sidecar는 audio 산출물에만.
- **결정 (서브에이전트 하이브리드)**: 긴 변환은 서브에이전트가 **텍스트만 반환**(파일 안 씀 — 프로젝트 교훈: 백그라운드 서브에이전트 파일쓰기 불가 + 32K 출력한계), 메인이 조립·검증·rename. 일관성은 **공유 낭독 사전**(LLM→엘엘엠, RoPE→로프, SelfExtend→셀프익스텐드 등)으로 통일.
- **결정 (TTS 노이즈 방지)**: 최종 `.md`엔 YAML·HTML comment 메타 금지(일부 뷰어가 낭독). 완료 메타는 sidecar `_ko_audio.meta.json`(status + source mtime/size/sha256).
- **테스트 산출물 주의**: LongLM `_ko_audio.md`/`.meta.json`은 `outputs/`(gitignored)에 있어 디스크엔 남지만 git엔 없음. /clear로 사라지지 않음.
- **공개 URL**: 뷰어 공개 도메인 `https://paper.restful3.store` (메모리에 저장됨). 듣기판: `https://paper.restful3.store/viewer/LLM%20Maybe%20LongLM%20SelfExtend%20LLM%20Context%20Window%20Without%20Tuning` → "듣기" 토글.

## ⚠️ 클리어 전 주의
- **커밋 안 됨**: `M HANDOFF.md`(이 파일, 상태 파일이라 미커밋 정상). 이번 세션 코드·스킬·문서는 전부 커밋됨(`a402fbd`/`6986394`/`879d7a6`). `?? HANDOFF.md.bak_20260526_143812`, `?? docs/superpowers/plans/2026-05-26-...-mcp-plan.md`(이전 세션 잔여, 무관).
- **백그라운드**: codex polling tasks(`b3jzqhorm`/`bc9277l5o`/`bnxxq3e4z`) 모두 completed. tmux `paperflow:codex` 윈도우 idle 상태로 살아있음(스펙 리뷰 3라운드 사용). Docker `paperflow_viewer`(audio 기능 반영된 새 이미지로 재시작, Up ~37분)·`paperflow_converter` 실행 중.
- **미완료 todo**: 없음 (이번 세션 Task #1-7 모두 completed).

## 📂 관련 파일
- `.claude/skills/paper-audio-korean/SKILL.md` — 스킬 본체 (커밋됨 `a402fbd`)
- `viewer/app/services/papers.py` — `md_ko_audio` 감지 + `get_md_ko_audio_path` + 제외 (커밋됨)
- `viewer/app/services/chat.py`, `mcp_zip.py`, `routers/api.py`, `routers/pages.py` — audio 통합 (커밋됨)
- `viewer/app/templates/viewer.html` — "듣기" 토글 + audioMode 상태/로드 (커밋됨)
- `viewer/tests/test_papers_audio.py` — 5 테스트 (커밋됨). settings stale binding은 `_rebind_settings` 픽스처로 해결.
- `README.md` / `CLAUDE.md` — paper-audio-korean + `_ko_audio.md` 정책 (커밋됨 `6986394`)
- `docs/superpowers/specs|plans/2026-05-31-paper-audio-korean-*` — 스펙·계획 (B-full 전환 주석, 커밋됨)
- `docs/reviews/2026-05-31-paper-audio-korean-spec-codex{,-2,-3}.md` — 코덱스 리뷰 트레일 (커밋됨)
- `.claude/skills/paper-explainer/SKILL.md` — batch 필터 + 이름 수정 (커밋됨 `879d7a6`)
- `outputs/LLM Maybe LongLM.../..._ko_audio.md` + `.meta.json` — 스모크 산출물 (gitignored, 디스크 only)
