# Paperflow 야간 듣기판 배치 크론 — 설계

**작성일**: 2026-06-01
**상태**: 승인됨 (사용자 "응 진행" / "구현하고 테스트 해봐")

## 목적

매일 새벽, Paperflow `outputs/` 에서 해설판(`_ko_explained.md`)은 있으나 듣기 낭독판(`_ko_audio.md`)이 아직 없는 문서를 찾아, 최신순 최대 10개를 tmux `paperflow:claude` Claude Code 세션에 배치로 위임해 `paper-audio-korean` 스킬로 듣기판을 생성한다. 기존 "🌙 Paperflow tmux batch explainer nightly" 크론(해설판)과 대칭 구조.

## 요구사항 (확정)

- **대상**: `outputs/` 만. `*_ko_explained.md` 존재 + 같은 폴더에 `*_ko_audio.md` 없음.
- **정렬·상한**: 소스 `_ko_explained.md` mtime **최신순**, **최대 10개/회**.
- **제외**: 없음(해설판 있으면 논문·개인문서 포함 전부 대상).
- **실행 시각**: `0 5 * * *` (Asia/Seoul) — explainer(3:30) 1.5시간 뒤.
- **의존**: 듣기판 소스는 해설판. 해설판이 아직이면 그 문서는 자연히 다음 회차로 미뤄짐(eventual).

## 아키텍처 (A안: 전용 배치 스킬 미러링)

새 스킬 `~/.openclaw/workspace/skills/paperflow-claude-batch-audio/`:

- `scripts/find_missing_audio.py` — `find_missing_explainers.py` 미러. SOURCE=`_ko_explained.md`, TARGET=`_ko_audio.md`. mtime 최신순 정렬, `--limit` 기본 10. 읽기전용, 빈 결과 exit 0, 크래시만 비정상 종료. `--root`/`PAPERFLOW_OUTPUTS` 지원.
- `scripts/dispatch_batch_audio.sh` — `dispatch_batch_explainer.sh` 미러. 기본 LIMIT=10. finder 호출 → 배치 프롬프트 생성 → `--dry-run` 게이트 → 공유 헬퍼 `paperflow-claude-batch-explainer/scripts/ensure_paperflow_tmux.sh`로 세션 확보 → Claude Code 준비 대기 → busy 가드 → bracketed-paste 디스패치. 프롬프트는 `paper-audio-korean` 스킬 사용을 지시.
- `SKILL.md` — 사용법·탐지규칙·공유 헬퍼 의존성 명시.

OpenClaw 크론: `openclaw cron add` 로 등록(jobs.json 수동 편집 안 함). payload는 explainer 잡 미러(agentTurn → dispatch_batch_audio.sh 실행 → 텔레그램 짧은 보고).

## 안전장치

- finder 읽기전용 / 크론 CLI 등록 / 1회 10개 상한 / `--dry-run` 사전 검증 / busy·self-paste 가드(헬퍼 상속).

## 테스트 계획

1. `find_missing_audio.py --json --relative` → 대상·정렬·10개 상한 확인 (읽기전용).
2. `dispatch_batch_audio.sh --dry-run` → 프롬프트/대상만 출력, tmux 무접촉 확인.
3. `openclaw cron add` 등록 후 `openclaw cron get` 으로 정의 확인.
4. 실제 라이브 1회 실행은 사용자 확인 후(`openclaw cron run`).

## 견고화 (2026-06-01, 추가 결정)

첫 라이브 시도에서, paperflow tmux 세션에 인터랙티브 `claude` 창이 여러 개 떠 있으면 `paperflow:claude` 타깃이 모호해지고(또는 busy 가드에 막혀) 배치가 사람 세션과 충돌함을 확인. 사용자가 "전용 배치 창" 견고화를 승인.

변경:
- 공유 헬퍼 `ensure_paperflow_tmux.sh`: "아무 `claude`/`node` 창이나 재사용"하던 cross-window 로직 **제거**. 이제 **전용 `batch` 윈도우만** 확인/생성/재기동.
- `dispatch_batch_audio.sh` + `dispatch_batch_explainer.sh`: 기본 `WINDOW_NAME=batch` (export). 타깃 = `paperflow:batch`. (explainer 크론도 함께 적용 — 두 크론이 3:30/5:00 다른 시각에 같은 `batch` 창 공유)
- 크론 정의(jobs.json) 수정 불필요 — payload는 스크립트만 호출, 타깃 창은 스크립트가 결정.
- 백업: `*.bak.20260601` (ensure, explainer dispatch).

검증: `paperflow:batch` 자동 생성 + ccd 기동 확인, 실제 디스패치가 batch 창에 안착해 Claude Code가 `paper-audio-korean`으로 10건 작업 시작, 인터랙티브 창(window 1/3) 무손상 확인.
