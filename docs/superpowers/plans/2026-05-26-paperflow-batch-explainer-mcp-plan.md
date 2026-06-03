# PaperFlow Batch Explainer MCP Plan

_작성: 2026-05-26_

## 목표
기존 `paperflow-claude-batch-explainer` 의 **tmux + Claude Code 위임형 배치 실행**을 PaperFlow MCP 서버에 1급 도구로 편입한다.

핵심은 **tmux를 제거하는 것**이 아니라, **tmux orchestration을 MCP 뒤로 숨겨서 외부 클라이언트가 일관된 MCP 인터페이스로 호출**하게 만드는 것이다.

---

## 현재 상태

### 이미 있는 것
- PaperFlow Viewer 쪽 MCP 서버 존재
  - `submit_paper`
  - `get_job_status`
  - `get_job_result`
  - `cancel_job`
  - `list_jobs`
- 배치 해설판 스킬 존재
  - `find_missing_explainers.py`
  - `dispatch_batch_explainer.sh`
  - `ensure_paperflow_tmux.sh`
- 실제 해설 생성은 `paperflow:claude` tmux 세션에서 `ccd` + `paper-explainer` 스킬로 수행

### 현재 문제
- 외부에서 보기에는 MCP 작업과 배치 해설판 작업이 분리되어 있음
- 배치 작업 상태를 `tmux capture-pane` 휴리스틱으로만 추적함
- dry-run / dispatch / progress / cancel 이 MCP 표면에 노출되지 않음
- 사용자는 "paperflow 작업"이라고 느끼지만 내부 구현이 Viewer MCP / tmux skill 두 갈래로 나뉘어 있음

---

## 설계 원칙
1. **tmux는 유지**한다.
   - 이유: Claude `-p` 대체/비용 이슈로 실운영에서 tmux lane 필요
2. **MCP는 orchestration facade**가 된다.
   - 실제 해설 생성 엔진은 계속 Claude Code + tmux
3. **기존 paper processing MCP와 별도 job type** 으로 추가한다.
   - PDF 처리 job index (`mcp_jobs.py`) 와 섞지 않음
4. **dry-run 우선** 원칙 유지
5. **취소/중복 방지/재시도** 를 MCP 레벨에서 명시한다

---

## 권장 구조 (추천)

### A. 새 service 추가
- `viewer/app/services/mcp_explainer_jobs.py`

역할:
- explainer job index 관리
- 후보 탐색 (`*_ko.md` 있으나 `*_ko_explained.md` 없음)
- tmux 세션 준비 / dispatch 실행
- 상태 추적
- cancel / stale 처리

### B. 새 MCP tools 추가
기존 `mcp_router.py` 에 아래 tool 추가:

1. `list_missing_explainers(limit=20)`
   - read-only
   - 현재 누락 대상 목록 반환

2. `submit_explainer_batch(limit=0, force=False, dry_run=False)`
   - dry_run=true 이면 프롬프트/대상만 반환
   - 실제 실행이면 tmux dispatch 후 job_id 반환

3. `get_explainer_batch_status(job_id)`
   - queued / dispatched / running / complete / error / stalled
   - 대상 수, 완료 수, 실패 수, pane target, 최근 로그 일부 반환

4. `cancel_explainer_batch(job_id)`
   - 최소 v1은 soft cancel
   - 상태를 `cancel_requested` 또는 `cancelled` 로 전환
   - 실제 Claude 작업 강제중단은 v2로 미뤄도 됨

5. `list_explainer_batches(limit=20, status=None)`
   - 최근 배치 작업 확인

### C. 새 index 파일
- `logs/mcp_explainer_jobs.json`

job record 예시:
- `job_id`
- `status`
- `targets`
- `target_count`
- `completed_count`
- `failed_count`
- `tmux_session`
- `tmux_window`
- `submitted_at`
- `completed_at`
- `last_heartbeat_at`
- `error`
- `prompt_path` 또는 prompt digest

---

## 상태 모델 (추천)
- `queued`
- `dispatched`
- `running`
- `complete`
- `partial`
- `error`
- `cancel_requested`
- `cancelled`
- `stalled`

### 상태 판정 기준
- `queued`: job 생성됐지만 tmux 전송 전
- `dispatched`: tmux pane 으로 paste+enter 완료
- `running`: pane 상 최근 출력에 실제 작업 시작 흔적 존재
- `complete`: 모든 target 에 대해 `*_ko_explained.md` 생성 확인
- `partial`: 일부만 생성됨
- `stalled`: 일정 시간 동안 pane/파일 변화 없음
- `error`: dispatch 실패 또는 tmux/Claude 미기동/프롬프트 생성 실패

---

## 구현 방식 세부안

### 1) finder 로직 재사용
현재 skill 의 `find_missing_explainers.py` 를 두 방식 중 하나로 연결:

#### 옵션 1. subprocess 재사용 (빠른 v1)
- `python3 .../find_missing_explainers.py --json`
- 장점: 기존 검증된 로직 재사용, 구현 빠름
- 단점: Viewer 서비스가 workspace skill script 경로에 의존

#### 옵션 2. Python 모듈화 (권장 장기)
- finder 핵심 로직을 repo 내부 service/helper 로 편입
- skill script 는 그 helper 를 thin wrapper 로 호출
- 장점: Viewer/MCP 와 skill 이 같은 로직 공유
- 단점: 첫 작업량 증가

**추천**: v1은 옵션 1, 안정화 후 옵션 2로 리팩터.

### 2) dispatch 로직
현재 `dispatch_batch_explainer.sh` 를 통째로 subprocess 호출하는 방식이 가장 현실적이다.

- dry-run: stdout/stderr/exit code 캡처
- real run: stdout 에서 resolved target / dispatched 여부 추출

이유:
- 현재 self-paste 방지
- busy pane 감지
- bracketed paste
- ccd 준비 대기

같은 까다로운 tmux 규칙이 이미 shell script 에 들어있다.

### 3) progress 추적
v1에서는 아래 2축을 함께 본다.

- **파일 시스템 truth**: target 별 `*_ko_explained.md` 생성 여부
- **tmux signal**: pane 최근 출력, last activity time

즉 진행률은:
- `completed_count = explained 파일이 실제 생긴 개수`
- pane 출력은 보조 신호

이게 휴리스틱 의존을 줄이는 핵심이다.

---

## v1 / v2 분리

### v1 (추천: 이번 작업 범위)
- read-only 누락 탐색 MCP tool
- batch submit MCP tool
- status/list MCP tool
- JSON index 저장
- 파일 생성 기반 progress 계산
- cancel 은 soft cancel 또는 not-yet-supported 명시

### v2
- target 단위 세부 상태
- Claude 작업 중단 (`tmux send-keys C-c`) 지원
- job resume / append targets
- prompt template versioning
- Codex review lane 추가

---

## 리스크
1. **tmux pane text 휴리스틱은 불안정**
   - 대응: 완료 판정은 반드시 파일 존재 기반
2. **Claude가 프롬프트를 이해했지만 다른 순서로 실행 가능**
   - 대응: status 는 target 결과 기반으로 계산
3. **동시에 여러 batch submit 시 충돌 가능**
   - 대응: 같은 tmux target 기준 active explainer batch 1개 제한
4. **강제 cancel 은 안전하지 않을 수 있음**
   - 대응: v1은 soft cancel 우선

---

## 추천 구현 순서
1. `mcp_explainer_jobs.py` 생성
2. finder subprocess 래퍼 추가
3. dispatch subprocess 래퍼 추가
4. explainer job index CRUD 추가
5. `list_missing_explainers` / `submit_explainer_batch` MCP tool 추가
6. `get_explainer_batch_status` / `list_explainer_batches` 추가
7. 최소 테스트 추가

---

## 내가 보는 최종 방향
정답은 **"tmux 제거"가 아니라 "tmux를 MCP 뒤로 격리"** 야.

PaperFlow 사용자는 결국:
- 논문 처리도 MCP
- 누락 해설판 배치도 MCP

처럼 보이게 하고,
실제 내부 실행은 계속 **tmux + Claude Code** 로 유지하는 게 지금 운영 제약과 가장 잘 맞는다.

---

## 바로 다음 액션 제안
- **A안 (추천)**: v1 구현 바로 시작
  - `list_missing_explainers`
  - `submit_explainer_batch`
  - `get_explainer_batch_status`
- **B안**: 먼저 spec 문서까지 더 엄격하게 씀
  - codex 리뷰 전제로 세부 상태 전이/에러 코드까지 명세
