# Codex 낭독판 배치 이관 설계 (2026-07-26)

**목표**: 해설판(explainer) 배치는 Claude로 유지하고, **낭독판 배치(audio 완전판 + audio_brief 축약판)를 Codex로 이관**한다. 최종 게이트는 "Codex 산출물이 Claude와 동일 품질로 판단될 때 크론 배치 잡을 Codex용으로 전환".

## 배경 — 현행 배치 아키텍처

배치 시스템은 `~/.openclaw/workspace/` 에 있고 크론으로 구동된다.

- **콘텐츠 스킬**(품질 규칙 본체): `paperflow/.claude/skills/paper-audio-korean`, `.../paper-audio-brief-korean`
- **배치 래퍼 스킬**(디스패치): `~/.openclaw/workspace/skills/paperflow-claude-batch-{explainer,audio,audio-brief}`
- **공용 헬퍼**: `~/.openclaw/workspace/skills/_common/`
  - `paperflow_batch_drain_tick.sh` (크론 \*/3분): `choose_next_type.py` 로 다음 타입 선택 → `dispatch_batch_{explainer,audio,audio_brief}.sh` 호출
  - `dispatch_common.sh`: tmux 준비·self-paste·`dispatch_to_batch_window`
  - `publish_prompt_file.py`: file-ref 프롬프트 퍼블리셔
- **타깃**: 3종 잡 모두 하나의 **Claude 배치 창** `paperflow:batch` 로 paste. pane 이 shell 이면 `claude --dangerously-skip-permissions` 자동 재주입. explainer 전용 `ctx_watchdog.sh` (\*/2분).

## 단계 계획

### Phase 1 — Codex 낭독판 콘텐츠 스킬 제작 (본 문서 범위)

- `paper-audio-korean`, `paper-audio-brief-korean` 을 리포 `.codex/skills/<name>/SKILL.md` 에 저작하고 `~/.codex/skills/<name>` 로 **절대경로 심링크**(para-memory-files 패턴, git 추적).
- **포팅 원칙**: 품질을 만드는 본문(변환 규칙표 1\~10·변환 예시·숫자/참조번호 표·제거 대상·Verification grep·분량 게이트)은 **한 글자도 손대지 않고 이식**. Claude 판이 두 파일을 각각 self-contained 로 중복 유지하는 선택을 미러링(교차참조 없음).
- **플랫폼 교체 4곳** (Codex 리뷰 2026-07-26 반영):
  1. `rtk proxy wc -m` → 일반 `wc -m < "$file"` (Codex 는 `/usr/bin/wc`, rtk 훅 없음). **`LC_ALL=C` 금지 한 줄** 추가(바이트 카운트 방지; locale 은 `C.UTF-8`).
  2. TUI 신뢰성 문구(`Actioning…`·"allow all") → Codex 는 `Actioning…` 등가 상태 문자열이 **없다**. 완료/중단 판정은 상태 문자열이 아니라 **프로세스 생존·`--json` JSONL 이벤트·종료 코드·최종 sidecar** 기준. 파일 수정은 **`apply_patch` 기본**, 검증 후 `mv` atomic publish(셸 redirection 덮어쓰기 위험 감소).
  3. "paper-explainer 스킬 실행"(Skill 도구) → **결정 B(교정): 배치에서는 유효 `_ko_explained.md` 없으면 무조건 skip+보고**. Codex 엔 해설판을 만드는 `interpretive-panel` 스킬이 실제 존재하므로 "있으면 실행"하면 *해설판=Claude 유지* 목표가 깨진다. 해설판 부재 폴더는 skip 하고 Claude explainer 큐로 되돌린다. `_ko.md` 로 날조 금지. (대화형 단건에서 사용자가 명시적으로 해설 생성까지 요청한 경우에만 `interpretive-panel` 허용.)
  4. Sonnet 워커 위임(배치 기본값) → **결정 A(교정): 논문별 fresh `codex exec` 순차 실행**(셸 오케스트레이터가 논문 하나씩). 한 대화에 여러 긴 논문을 누적하면 compaction·논문 간 오염 발생. 논문 내부만 `.part` 섹션 기록. `spawn_agent` 위임은 model/agent 선택 인자가 없어 워커 타입 고정 불가 → 기본 아님, 대규모 병렬의 선택 사항으로만(임시파일 분리 + 부모 직렬 publish).
- **Codex 하드닝**(정적 보강, 리뷰 반영):
  - **Vision = 1급 기본**: Codex 는 `view_image` 로 로컬 그림을 판독한다(실측 확인). **포함하는 핵심 그림은 실물 파일을 여는 것이 기본**, 순서 `실물 열기 시도 → (도구 실패 시) 캡션+본문의 공통 확정사항만 서술 → 미확인 플래그`. 날조 절대금지.
  - **알려진 워커 오류 3종 선제 금지**: 차트 축 단위 오독(€bn→"억" 10배 축소)·동아시아 인명 로마자 한글 음차 추정·소스 풀쿼트 중복 이월.
  - **검증 = grep validator 스크립트**: GNU grep 은 0건=exit 1, 오류=exit 2 → `set -e`에서 0건이 실패로 중단될 수 있다. "명령 실행함"으론 부족 → `scripts/verify_audio.sh`(또는 python)로 **명령·매치 수·exit code 를 구분**해 고정하고 결과를 보고에 첨부.
  - **`.part` 진행 체크포인트**: 완료 섹션 목록 + `source_sha256` + run/session ID 를 `.part` 옆에 기록. **소스가 바뀐 stale `.part` 에 맹목 append 금지**(compaction/재시작 대비).
  - **파리티 검증 = allowlist diff**: "본문 한 글자도 변경 없음" 대신, Claude 원본 대비 diff 에서 **플랫폼 교체/하드닝 블록만 차이나는지** 확인.

### Phase 2 — 품질 검토·Claude 동일화 (경험적, Phase 3 게이트)

- 대표 논문 1\~2편을 Codex 스킬로 낭독판 생성 → 기존 Claude 산출물과 **블라인드 A/B 대조**(사용자의 기존 스킬 A/B 방법론 계승, 심사엔 이미지 제공).
- 격차 부분을 Codex 스킬에 반영해 재실행, "동일 판단" 될 때까지 반복.

### Phase 3 — 배치 크론 audio+brief 를 Codex 로 라우팅 (고위험·별도 설계)

- 디스패치 라우팅을 타입별로 분기: explainer→Claude 창(현행 유지), audio+brief→Codex.
- **크론은 TUI paste 보다 `codex exec` 권장**(Codex 리뷰): 별도 tmux/cron Codex 는 대화형 권한을 자동 상속하지 않는다. 예: `codex exec -C /media/restful3/data/workspace/paperflow -m gpt-5.6-sol -s workspace-write -c 'approval_policy="never"' -o <report> - < <prompt-file>`. sandbox writable root(`-C`, 필요 시 `--add-dir`)가 **논문 폴더를 포함**해야 함. 재시작은 기본 새 세션(`codex resume <UUID>` 는 명시적일 때만, `--last` 의존 금지). 배치 프롬프트는 `$paper-audio-korean`/`$paper-audio-brief-korean` 을 **명시 호출**.
- 개조 후보: `drain_tick`/`choose_next_type`/`dispatch_common`/`ctx_watchdog`/respawn.
- **프로덕션 배치 인프라 변경** → 자체 설계 + peer-council 선협의 + 사용자 승인 게이트. Phase 2 통과 후 착수.

## 검증 (Phase 1)

1. 두 SKILL.md frontmatter(name+description)/구조 정합성 — 각각 self-contained(sibling 참조 없음, Codex 리뷰로 확정)
2. 심링크가 리포 파일로 resolve (절대경로)
3. **새 Codex 세션**에서 스킬 discover (hot reload 없음 — fresh-session 테스트 필수)
4. `scripts/verify_audio.sh` validator 가 Codex 셸에서 실동작(grep exit code 구분)
5. allowlist diff: Claude 원본 대비 차이가 플랫폼/하드닝 블록에 한정

`agents/openai.yaml`(display_name/short_description/default_prompt)은 Codex 권장이나, 현재 설치된 Codex 스킬들이 SKILL.md 단독이므로 **기존 패턴을 따라 생략**(필요 시 후속 보강).

## 비고

- **Codex 리뷰 기록**: `docs/reviews/2026-07-26-codex-audio-skill-phase1-review.md` (Phase 1 설계 조건부 승인 + 환경 사실 교정).
- 작업 시작 시 DSBA 폴링 크론(crontab line 43)을 일시중지(백업: scratchpad). 전체 완료 후 원복.
- Phase 1 리포 변경은 `paperflow` 리포 브랜치 `codex-audio-narration-skills`. Phase 3 는 `~/.openclaw/workspace/` (별도 위치).
