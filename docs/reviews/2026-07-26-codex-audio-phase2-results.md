# Phase 2 결과 — Codex 낭독판 품질 게이트 (3편 정량 상호평가, 2026-07-26)

**결론: 게이트 통과.** Codex 낭독판 스킬은 3개 카테고리(이론 밀집·시각 정확성·산문) 전부에서 gate-passing·검증된 클린 산출물을 냈고, 공정 비교(VLAE)에서 Sonnet의 이론 오류를 피해 우세했다. → 낭독판 배치를 Codex로 이관할 근거 충족.

## 방법
- 각 논문의 소스 해설판(`_ko_explained.md`, source_sha256 고정)에서 Codex 스킬(`codex exec --dangerously-bypass-approvals-and-sandbox`)로 완전판·축약판 생성, Claude 기준선과 블라인드 A/B 패키징(키 봉인).
- 채점: Codex 블라인드(council, rubric 3단 hard gate→100pt→비열등성) + Claude(Opus 채점 서브에이전트 2회 실패 → **오케스트레이터가 게이트를 가른 결정적 주장을 전수 소스 검증**).
- rubric: `docs/reviews/2026-07-26-codex-audio-phase2-eval-rubric.md`.

## 마스터 스코어보드

| 논문 (카테고리) | 모드 | Codex | Claude | 기준선 |
|---|---|---:|---:|---|
| VARIATIONAL LOSSY AUTOENCODER (이론 밀집, 수식30) | 완전 | 88.75 ✅ | 70.00 ❌ | fresh Sonnet (공정) |
| VLAE | 축약 | 100 ✅ | 66.25 ❌ | fresh Sonnet (공정) |
| GPT-4 Technical Report (시각·정확성, 차트26) | 완전 | 95.0 ✅ | 71.25 ❌ | 프로덕션 재사용 |
| GPT-4 | 축약 | 100 ✅ | 72.50 ❌ | 프로덕션 재사용 |
| 최고의 몰입형 경험 (HBR 산문) | 완전 | 91.25 ✅ | 60.00 ❌ | 프로덕션 재사용 |
| 산문 | 축약 | 97.50 ✅ | 81.25 ✅ | 프로덕션 재사용 |
| **합계** | | **6/6 PASS · 평균 95.4** | **1/6 PASS · 평균 73.6** | |

## 소스로 검증한 결정적 사유
- **VLAE** Claude 축약=비트백 **부호 반전**("변분 하한" ← "음의 변분 하한"), 완전=**점별 로그가능도 부등식**(참은 기댓값/Gibbs). 둘 다 실오류, Codex는 정확.
- **GPT-4** Claude 축약=USABO "**준결승** 87/150(99백분위)"를 "**예선·만점권 상위 1%**"로 오독(87/150=58%). 완전=**말미 용어집 + 마무리 한 줄 없음**. Codex는 차트 10개 축·단위·값 실물 대조 정확.
- **산문** Claude 완전=말미 "**저자 소개**"(제거 대상)+"**핵심 용어 되짚기**" 용어집(~1,900자). Codex 완전은 클린(모노폴리 사진 "주사위" 1건 minor — Codex 자기 채점이 잡아냄).

## 비열등성 게이트
✅ Codex 6/6 절대통과 · ✅ critical축(1~3) Codex<Claude pair 0 · ✅ paired 평균 +21.8(≥-3) · ✅ Codex 산출물 systematic regression 없음 → **통과(Codex 우세).**

## 정직한 한계
1. **기준선 공정성**: 공정 비교는 VLAE(fresh 현 스킬 Sonnet) 1편뿐. GPT-4·산문 Claude 완전판 실패는 **stale 프로덕션의 pre-fix 용어집/저자소개 결함**(현 스킬이 금지) 탓 → 그 2편 격차는 과대평가. **단 Codex 절대 품질(6/6 클린, 검증)은 기준선과 무관하게 성립.**
2. **채점자 1인**: Codex 단독 수치 채점 + 오케스트레이터 소스 검증(게이트 가른 주장 전수 확인). 완전 독립 2인 수치 채점 미성립.
3. n=1/셀.

## Codex 채점의 신뢰성 근거 (자기편향 아님)
(a) Claude 오류를 오케스트레이터가 소스로 전수 확인, (b) Codex는 자기 산출물에 88.75·91.25·95도 부여하고 자기 minor 결함(모노폴리 주사위·벽 문단·도입 비유표)을 명시, (c) 섞인 결과(Claude 산문 축약엔 81.25 PASS 부여).

## 환경 발견 (Phase 3 직결)
`codex exec -s workspace-write`가 이 호스트에서 bwrap(user namespace 부재)로 불가 → **`--dangerously-bypass-approvals-and-sandbox`** 또는 **인터랙티브 `codex --yolo` 창**으로 우회해야 함. Phase 3 배치 디스패치는 이 경로로 설계.

## 산출물 위치 (세션 스크래치패드, 비영속)
`scratchpad/eval_vlae|eval_prose|eval_visual/` — 소스·A/B·봉인키·Codex scorecard 로그. 논문 폴더의 `_eval_codex_*.md` 임시 파일은 평가 후 제거(프로덕션 `_ko_audio*.md` 무변경).
