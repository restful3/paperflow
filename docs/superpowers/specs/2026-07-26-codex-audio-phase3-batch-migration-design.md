# Phase 3 설계 초안 — 낭독판 배치 Codex 이관 (2026-07-26)

**목표**: 해설판(explainer) 배치는 Claude 창 유지, **낭독판(audio 완전판 + audio_brief 축약판) 배치는 Codex로 이관**. Phase 2 게이트 통과(Codex 6/6, 검증됨) 후 착수. 사용자 지시: "코덱스와 합의해서 끝까지 진행".

## 현행 아키텍처 (요약)
- 크론 `_common/paperflow_batch_drain_tick.sh`(*/3): 배치 창 `paperflow:batch`(인터랙티브 Claude) idle 확인 → `choose_next_type.py`(explainer>audio>brief, 캡·starvation) → 타입별 `dispatch_batch_*.sh --limit 1`.
- `dispatch_common.sh` `dispatch_to_batch_window`: Claude 창에 file-ref 한 줄 paste. pane_cmd `claude|node` 대기, busy-check(`esc to interrupt`·`작성 중`), `/clear` pre-clear.
- audio 디스패처: find→prompt(빌드)→work_id→idempotency(state json)→publish prompt file→paste. **프롬프트가 full+brief를 한 컨텍스트에 체이닝**, Claude 전용 문구("Skill 도구", "Claude Code", "MCP 우선").
- `ctx_watchdog.sh`(*/2): Claude 배치 창 컨텍스트 누적 감시·pre-clear. respawn: `claude --dangerously-skip-permissions`.
- 환경 제약: 이 호스트는 `codex exec -s workspace-write`가 bwrap(user namespace 부재) 불가 → `--dangerously-bypass-approvals-and-sandbox` 필요(Phase 2 검증).

## 제안 설계 — Path 2: codex exec per job (2-lane)

**낭독판 잡은 인터랙티브 창 paste 대신 잡마다 fresh `codex exec --dangerously-bypass-approvals-and-sandbox -C <repo> - < promptfile` 를 detached 백그라운드로 실행.** 근거: Codex는 stateless-per-job 모델(Phase 2 권장·검증), 창 driving(pane 감지·busy-check·/clear·ctx watchdog·respawn) 전부 불필요, fresh 컨텍스트라 논문 간 오염 없음.

**2-lane 분리:**
- **Claude lane** (기존 유지): drain_tick(*/3) + ctx_watchdog(*/2), 창 `paperflow:batch`, respawn claude. `choose_next_type`를 **explainer로 제한**(env `PAPERFLOW_ALLOWED_TYPES=explainer`).
- **Codex lane** (신규): drain_tick 변형(*/3 or */5), 창 없음. `choose_next_type`를 **audio,brief로 제한**. 창 idle-check 대신 **codex-exec 동시성 락**(pidfile/flock: 이미 codex exec 배치가 돌면 이 틱 skip). audio/brief 디스패처의 Codex 변형이 codex exec 실행.
- find/work_id/idempotency/state/publish prompt 기존 기계 재사용. 프롬프트만 **Codex 판**(`$paper-audio-korean`/`$paper-audio-brief-korean` 명시 호출, Claude 문구 제거).

## Codex 합의 질문 (이 문서 = 합의 대상)
1. **Path 2(codex exec per job) vs Path 1(인터랙티브 codex --yolo 창)** — 무인 배치 신뢰성 관점에서 어느 쪽? 나는 Path 2 선호(창 driving 복잡성 제거·fresh 컨텍스트). 반대 근거 있나?
2. **동시성 가드**: */3 틱인데 codex exec 잡은 5\~15분 → 겹침. 어떻게 막나? flock 비블로킹 + "codex exec 실행 중이면 skip"(pidfile) 방식이면 충분한가? 죽은 프로세스 stale lock 회수는?
3. **2-lane 분리 vs 단일 drain_tick 분기** — 어느 구조가 견고한가?
4. **full+brief 체이닝**: Claude는 한 프롬프트에 full→brief 체이닝. Codex도 한 codex exec에 두 스킬 순차? 아니면 audio·brief 별도 exec? (fresh-per-job 원칙과 상충?)
5. **codex exec 무인 신뢰성**: 반복 크론에서 gotcha? 완료/실패 감지(exit code·sidecar), 실패 잡 재시도(idempotency TTL로 충분?), 리소스(동시 1개면 OK?), bwrap bypass 상시 사용 안전성.
6. **프롬프트 Codex화**: `$skill` 호출·검증(scripts/verify_audio.sh)·완료 판정(정상종료+sidecar) 문구 — 빠뜨린 것?

구체적으로. 이 설계로 바로 구현할 거라 실전 함정 위주로.

---

## Codex 합의 결과 (2026-07-26)

**Path 2 + 2-lane 승인.** 단 4개 구현 게이트 + P0 10개 제시. 핵심 수정:
1. **detached 금지 → flock 잡은 foreground runner**(크론 틱이 lock 쥐고 codex exec 종료까지 대기, 다음 틱 `flock -n` skip).
2. **full·brief 별도 fresh exec**(체이닝 금지, 스케줄러가 full 성공→brief follow-up).
3. **TTL 아닌 durable 상태머신 + host postflight**(exit 0 ≠ 성공; rc0+output+verify+sidecar+SHA일치 AND).
4. **bypass-sandbox 보완 = 전용 OS 계정/ACL**(외부 논문=신뢰불가 입력; 상시 크론 최대 잔여 위험).
- 정제: `--ephemeral --ignore-user-config`, mode timeout(full 120m/brief 60m; `timeout 150` 재사용 금지), work_id에 source_sha256+skill_rev, per-run 디렉터리, cron PATH에 NVM codex 명시, `LC_ALL=C` 금지, agent-writes-staging→host-finalizer 권장, source-race SHA 재검, finder stale-freshness 미감지 수정.

전문: `council minutes` / task 로그. 회의록성 원문은 세션 스크래치패드.

## 구현 진행 (canary 단계 — 프로덕션 미접촉)

**빌드·검증 완료:**
- `_common/paperflow_batch_choose_next_type.py`: `--allowed-types`(P0 #1)+`--strict`(P0 #7) 추가. **테스트 14/14 통과**(기존 8 하위호환+신규 6). Claude lane=explainer, Codex lane=audio,brief.
- `paperflow-codex-batch-audio/scripts/codex_audio_lane.sh`: foreground+flock runner(게이트 1,2,3 반영: 별도 exec·mode timeout·host postflight[rc/output/verify_audio/sidecar/source-SHA 재검]·durable state[claimed→running→succeeded/failed_retryable/permanent, backoff 5m→2h, 4회 dead-letter]·per-run dir·기존출력 백업+실패복원·env/PATH/locale 고정). **dry-run 전 구간 통과.**
- `paperflow-codex-batch-audio/scripts/build_codex_audio_prompt.py`: 단일 artifact Codex 프롬프트(`$skill` 명시·scope-lock·source-SHA 가드·verify 지시·structured JSON 보고).
- **스모크 테스트**: `--ephemeral --ignore-user-config --dangerously-bypass`에서도 두 스킬 정상 발견(Codex 플래그한 위험 해소).
- **라이브 canary**: brief 1건 실제 runner end-to-end 실행(결과 별도 기록).

**남은 작업 (사람 게이트 / 후속 하드닝):**
- **[사람 게이트] 보안 격리**(Codex 게이트 4): 전용 OS 계정/ACL로 bypass-sandbox 피해범위 축소 — 상시 크론 전 필수. 인프라·정책 결정.
- **[사람 게이트] 프로덕션 컷오버**: 크론에 Codex lane 추가 + Claude lane을 explainer 전용으로 제한 + 구 audio/brief Claude route disable. 되돌리기 어려운 프로덕션 변경.
- 후속 하드닝: host finalizer(agent staging→host publish), find_missing_audio stale-freshness 감지, full finder outputs+archives·video 제외 정합, 실패주입 테스트 스위트(두 틱 동시·abandoned·rc0 output없음·verify fail·source 변경·auth 실패·timeout), 24h canary 지표.

**백업**: 수정 대상 openclaw 스크립트 원본은 세션 스크래치패드 `phase3_backup_*/`. openclaw 리포(shared master)에는 자동 커밋하지 않음 — 사용자 워크플로우로 커밋.
