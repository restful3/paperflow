# Codex 리뷰 — Codex 낭독판 스킬 Phase 1 설계 (2026-07-26)

- **세션**: paperflow (peer-council, `--mode review`)
- **소요**: 390초 (codex 창 대화형 구동)
- **판정**: 조건부 승인
- **대상**: `docs/superpowers/specs/2026-07-26-codex-audio-narration-migration-design.md` Phase 1

## 리뷰 요청 브리프
낭독판 스킬(paper-audio-korean 완전판 + paper-audio-brief-korean 축약판)을 Claude → Codex 포팅하는 Phase 1 설계. Codex 본인의 환경 사실(이미지 판독·스킬 로딩·rtk·배치 실행 모델·TUI/파일쓰기)을 자가 검증 요청.

## Codex 답변 (원문 요지)

### 환경 사실 검증
1. **이미지 판독 — 가능**. `view_image` 로 로컬 JPEG 판독. 예시 경로 `_page_4_Figure_2.jpeg` 가 실제로는 "Table 1" 캡션 조각(481×61)이고 실제 선차트는 `_page_4_Figure_3.jpeg` 임을 식별(x축 `#CoT-SC trials`, y축 `HotpotQA EM`/`Fever Acc`, 포화 추세). → **핵심 그림은 실물 대조가 기본**, 도구 실패 시에만 degrade.
2. **스킬 로딩 — 자동 발견 + name/description 트리거, 본문 지연 로딩**. 절대경로 심링크 동작 확인(para-memory-files). sibling 본문 자동 연쇄 안 됨. 신규 심링크는 **새 세션에서 재발견** 필요. 배치는 `$paper-audio-korean` 명시 호출 권장. `agents/openai.yaml` 권장.
3. **`wc -m` — 정상**(`/usr/bin/wc`, rtk 아님). `wc -m < file`. `LC_ALL=C` 금지 권장(바이트 카운트).
4. **배치 모델 — 순차 + "논문별 새 `codex exec`"**. `spawn_agent` 는 model/agent 선택 인자 없음(terra-worker 고정 불가). 장기 단일 세션은 논문 간 오염.
5. **TUI/파일쓰기 — 크론은 `codex exec` 권장**. `-s workspace-write -a never`(or `approval_policy="never"`), 출력 폴더가 `-C` 밖이면 `--add-dir`. `Actioning…` 등가물 없음 → 프로세스 생존·`--json`·종료코드·sidecar 로 완료 판정. 파일 수정 `apply_patch` 기본, `mv` atomic publish. 재시작 새 세션 기본(`codex resume <UUID>` 명시적일 때만).

### 설계 판단
6. **하드닝 타당, 5개 보강**: (1) 신규 스킬 fresh-session 재발견 (2) sandbox writable root 가 논문 폴더 포함 (3) `.part` 진행 체크포인트(source_sha256·완료섹션·run ID, stale append 금지) (4) `apply_patch` 섹션 쓰기 + publish 전 재검증 (5) `agents/openai.yaml` + 설치 후 discovery 테스트. grep 은 exit code(0건=1, 오류=2) 구분하는 validator 로 고정. "본문 무변경"은 allowlist diff 로 표현.
7. **결정 A**: 조건부 동의(단일 장기 세션 → 논문별 fresh session 순차). **결정 B**: `_ko.md` 날조 금지 강력 동의. **단 Codex 에 `interpretive-panel`(해설판 생성) 존재** → "있으면 실행"하면 해설판=Claude 유지 목표 붕괴 → 배치는 유효 해설판 없으면 **무조건 skip+보고+Claude 큐로**.
8. **구조 — self-contained 유지**(Codex 는 선택 스킬 본문만 로드). 유지보수 중복은 공통 조각/빌드 스크립트 + diff 검증으로.

## 반영 결정 (Claude 종합)
Codex 교정 전부 타당 → 스펙에 반영 완료. 특히 **결정 B(interpretive-panel 무조건 skip)** 는 *해설판=Claude 유지* 목표를 지키는 핵심. 배치 모델은 **논문별 fresh `codex exec`** 로, 검증은 **`scripts/verify_audio.sh` validator** 로, 파리티는 **allowlist diff** 로 확정. `agents/openai.yaml` 은 기존 설치 스킬이 SKILL.md 단독이라 일단 생략(후속 보강 여지).

---

## 2차 리뷰 — 저작 결과 (331초, 판정: 저작 시점엔 미완료 → 수정 후 완료)

Codex 가 실제 명령을 돌려 6개 결함 지적:
1. frontmatter 가 `quick_validate.py` 실패 — 두 description 의 `<basename>` 꺾쇠, 축약판 `core:` 콜론(YAML).
2. `codex exec -a never` 무효(`-a/--ask-for-approval` 는 `codex exec` 에 없음) → `-c 'approval_policy="never"'`.
3. `verify_audio.sh` 라벨 과장("모든 CRITICAL")·`brlef` 오타 mode 통과·`cut -c` 한글 깨짐.
4. `Inherit the paper-explainer batch rules` 교차참조 → self-contained.
5. 완전판 "상위 감독 세션" 잔향 → fresh remediation 세션.
6. 완료 신호에서 liveness(진행)와 completion(완료) 분리.
+ validator 경로 cwd 의존.

**Codex 가 확인해준 긍정**: validator 의 0건=exit1=PASS·brief H2 게이트 정확(실파일 PASS, fixture FAIL). 품질 본체 무손실, 그림 실물대조 강화. Claude 잔재(rtk·Sonnet·Agent·TUI 자동실행) 없음.

## 2차 수정 결과 (Claude, 객관 검증)
- frontmatter: `<basename>`→`*_ko_audio*.md`, 축약판 `core:`→`core —` → **`quick_validate.py` 둘 다 "Skill is valid!"**
- `-a never` 제거(`grep` 0건), `codex exec` 예시는 `-s workspace-write -c 'approval_policy="never"'`.
- `verify_audio.sh`: mode 검증(`brlef`→exit 2), `STATIC CHECKS` 라벨 + 범위 주석, `cut`→`awk substr`(멀티바이트 안전). 실파일 PASS/fixture FAIL/`bash -n` 통과.
- `Inherit …` → `Batch rules (self-contained)`, 완전판 실행모델 fresh remediation 세션.
- 완료 신호/판정: liveness 관찰 vs completion(정상종료+검증+sidecar) 분리.
- validator 경로: `"$(git -C <paper_dir> rev-parse --show-toplevel)"/scripts/verify_audio.sh`.
- **새 Codex 세션 discovery**: `codex exec`(fresh, session 019f9bb4…) → `paper-audio-korean: yes`, `paper-audio-brief-korean: yes`.

→ Codex 완료 조건 6개 전부 충족. 커밋 `43b9c49`.
