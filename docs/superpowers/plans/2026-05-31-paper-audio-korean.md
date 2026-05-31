# paper-audio-korean 구현 계획

> **⚠️ 설계 변경 (2026-05-31, B-full):** 이 스펙은 처음 `audio/` 하위 디렉터리 방식(백엔드 변경 0)으로 작성되었으나, 사용자 결정으로 **폴더 직하위 `<basename>_ko_audio.md` + viewer/MCP 1급 포맷 통합**으로 전환되었다. 따라서 본문 중 "`audio/` 하위 디렉터리에 두어 회피", "백엔드 변경 없음" 류 서술은 이 전환으로 **대체**되었다 — 실제 출력 위치는 논문 폴더 직하위이고, viewer/backend가 `_ko_audio.md`를 인식하도록 수정되었다. 최종 동작은 `.claude/skills/paper-audio-korean/SKILL.md` 와 `CLAUDE.md` 를 따른다.


> **For agentic workers:** 이 계획은 단일 `SKILL.md`(LLM 지시 문서) 작성 + 문서 갱신 + 스모크 테스트로 구성된다. 산출물이 실행 가능한 코드가 아니라 프롬프트 문서이므로, 단위 테스트(TDD) 대신 **실제 논문 1편 변환 스모크 테스트**로 검증한다. 체크박스(`- [ ]`)로 추적.

**Goal:** 해설판(`_ko_explained.md`)을 아이폰 음성으로 들어 이해되는 한국어 낭독판(`<basename>_ko_audio.md`)으로 변환하는 프로젝트 로컬 스킬을 만든다.

**Architecture:** paper-explainer 패턴(섹션별·section-safe)을 재사용하는 LLM 주도 SKILL.md 하나. 별도 스크립트·뷰어 변경 없음. 출력은 `audio/` 하위 디렉터리(파일감지 충돌 회피) + sidecar 완료 메타.

**Tech Stack:** Markdown SKILL.md (frontmatter), Claude Code Skill 메커니즘. 검증은 grep + 수동 표본 확인.

**Spec:** `docs/superpowers/specs/2026-05-31-paper-audio-korean-design.md` (v3, Codex GO)

---

## File Structure

- Create: `.claude/skills/paper-audio-korean/SKILL.md` — 스킬 본체 (단일 파일)
- Modify: `README.md` — "Claude Code Skills" 표에 행 추가
- Modify: `CLAUDE.md` — Output Structure / 파일 네이밍에 `*_ko_audio.md` 정책 추가
- Smoke test target (생성물, 커밋 안 함): `outputs/<paper>/<basename>_ko_audio.md` + `.meta.json`

---

### Task 1: 스킬 디렉터리 + SKILL.md frontmatter/골격 작성

**Files:**
- Create: `.claude/skills/paper-audio-korean/SKILL.md`

- [ ] **Step 1: frontmatter + 목적/실행모드 헤더 작성**

frontmatter는 폴더명과 일치(`name: paper-audio-korean`). description은 트리거 표현 포함:

```markdown
---
name: paper-audio-korean
description: Convert a Korean paper explainer (_ko_explained.md) into a listen-optimized Korean narration (<basename>_ko_audio.md) using audio-description principles — formulas/tables/figures/code become meaningful spoken sentences, not placeholders. Use when user asks "듣기용으로 만들어줘", "낭독판", "audio 버전", "TTS용 변환", or wants an iPhone-listenable version of a paper.
---
```

- [ ] **Step 2: "When to Use" + 핵심 철학(오디오 디스크립션, placeholder 금지, 완전 낭독판) 서술**

스펙 §1을 근거로: 요약 아님, 시각 요소를 "어떤 수식/무엇을 보여주는 그림"으로, 항상 해설판 기반.

- [ ] **Step 3: 커밋**

```bash
git add .claude/skills/paper-audio-korean/SKILL.md
git commit -m "feat(skill): scaffold paper-audio-korean (frontmatter + philosophy)"
```

---

### Task 2: 입력 소스 해석 & 생성 수명주기 섹션 작성

**Files:**
- Modify: `.claude/skills/paper-audio-korean/SKILL.md`

- [ ] **Step 1: 출력 위치 규칙 작성** (스펙 §5)

`<paper_dir>/<basename>_ko_audio.md`, 작성중 `.part`, sidecar `_ko_audio.meta.json`. `audio/` 하위에 두는 이유(viewer/MCP 비재귀 스캔 회피) 명시.

- [ ] **Step 2: 2단계 수명주기 + legacy completion validation 작성** (스펙 §5)

Phase 1(해설판 확보, marker 아닌 legacy validation: 존재+비어있지않음+제목/본문정상+heading coverage+주요섹션) / Phase 2(변환→`.part`→검증→atomic rename + sidecar). 실패 시 최종본 미생성.

- [ ] **Step 3: skip/재생성 조건 + sidecar 스키마 작성** (스펙 §5)

sidecar `{status, source_path, source_mtime, source_size, source_sha256}`. skip = 최종본 존재 + sidecar.status=="complete" + source 일치.

- [ ] **Step 4: Batch 모드 규칙 작성** (스펙 §5)

paper-explainer batch 규칙 계승 + audio exclusion(`_backup_`/`.bak`/`_mdlint_report.json`/`*_ko_audio.md`/`*.part`) + stale 재생성 + 고아 폴더 리포트.

- [ ] **Step 5: 커밋**

```bash
git add .claude/skills/paper-audio-korean/SKILL.md
git commit -m "feat(skill): source resolution, lifecycle, batch rules"
```

---

### Task 3: 변환 규칙(오디오 디스크립션) 섹션 작성

**Files:**
- Modify: `.claude/skills/paper-audio-korean/SKILL.md`

- [ ] **Step 1: 최상위 원칙 + 낭독 사전 작성** (스펙 §6)

placeholder 금지 명시. 변환 시작 시 "용어/약어 낭독 사전" 작성·일관 적용.

- [ ] **Step 2: 8개 변환 규칙 표 작성** (스펙 §6 규칙 1-8)

수식/표(유형별)/그림/코드블록/인용·링크/각주(`<sup>`+`[^1]`)/영어약어(음차)/문어체. 각 규칙에 before→after 예시 1개씩 포함 (예: 수식, 표, 그림). 예시는 스펙 표본(REACT 표, DeepSeek 수식)에서 가져온다.

- [ ] **Step 3: 제거 대상 목록 작성** (스펙 §6)

목차/페이지마커/저자소속/URL/학회푸터/References/감사의글.

- [ ] **Step 4: 커밋**

```bash
git add .claude/skills/paper-audio-korean/SKILL.md
git commit -m "feat(skill): audio-description conversion rules"
```

---

### Task 4: 출력 형식 + 모드/안정성 + 검증 섹션 작성

**Files:**
- Modify: `.claude/skills/paper-audio-korean/SKILL.md`

- [ ] **Step 1: 출력 형식 작성** (스펙 §7)

YAML 헤더 생략(기본값), 제목 `# … — 듣기판`, 소스 섹션 구조 유지, 메타는 sidecar.

- [ ] **Step 2: Auto/Section-safe/TUI/Quality-wait 작성** (스펙 §8)

paper-explainer 운영 정책 계승, `.part` append + atomic rename.

- [ ] **Step 3: 검증 섹션 작성** (스펙 §9)

변환 전 Source Inventory(헤딩/표/그림/수식블록/인라인수식 문단별/코드fence/각주). CRITICAL grep 0건 목록(전체) + 항목별 대응 + 섹션 coverage. Important 체크리스트. 실제 검증 grep 명령 예시 포함:

```bash
grep -nE '\$\$|\$[^$]+\$|^\|.*---|^```|!\[\]\(|\[[0-9]+\]|\[\^|<sup|<span|<br|\]\(#' "<f>_ko_audio.md"
```

- [ ] **Step 4: 커밋**

```bash
git add .claude/skills/paper-audio-korean/SKILL.md
git commit -m "feat(skill): output format, modes, verification"
```

---

### Task 5: 스모크 테스트 — 실제 논문 1편 변환

해설판이 이미 있는 짧은 논문으로 테스트. 후보: `outputs/LLM Maybe LongLM SelfExtend LLM Context Window Without Tuning/`(해설판 존재, 수식·표·그림·영어약어 모두 포함 → 규칙 전반 커버).

- [ ] **Step 1: 스킬 호출하여 변환 수행**

`paper-audio-korean` 스킬로 위 논문의 `_ko_explained.md` → `..._ko_audio.md` 생성.

- [ ] **Step 2: CRITICAL grep 검증 (0건 확인)**

Run:
```bash
cd "/home/restful3/workspace/paperflow/outputs/LLM Maybe LongLM SelfExtend LLM Context Window Without Tuning"
grep -cnE '\$\$|^\|.*---|^```|!\[\]\(|\[[0-9]+\]|\[\^|<sup|<span|<br|\]\(#' "LLM Maybe LongLM SelfExtend LLM Context Window Without Tuning_ko_audio.md"
```
Expected: `0`

- [ ] **Step 3: sidecar + 본문 메타 부재 확인**

Run: `ls audio/*.meta.json && tail -3 *_ko_audio.md`
Expected: meta.json 존재(status=complete), 본문 말미에 HTML comment marker 없음.

- [ ] **Step 4: 표본 확인 — 수식/표/그림이 의미 있는 서술인지**

수식·표·그림 각 1곳을 읽고 placeholder("수식입니다")가 아니라 자연어 묘사인지, 섹션 누락 없는지 육안 확인. 문제 발견 시 SKILL.md 규칙 보강 후 재변환.

- [ ] **Step 5: 스모크 결과 기록 (커밋은 스킬 변경분만, 산출물 제외)**

산출물(`_ko_audio.md`)은 테스트물이므로 커밋하지 않는다. SKILL.md 보강이 있었으면 그것만 커밋.

---

### Task 6: 문서 갱신 (README / CLAUDE.md) — 스펙 §10 Low #1

**Files:**
- Modify: `README.md` (Claude Code Skills 표)
- Modify: `CLAUDE.md` (Output Structure / 파일 네이밍)

- [ ] **Step 1: README 표에 행 추가**

```markdown
| **paper-audio-korean** | 해설판을 아이폰 음성용 한국어 낭독판(`*_ko_audio.md`)으로 변환 | "듣기용으로 만들어줘", "낭독판 만들어줘" |
```

- [ ] **Step 2: CLAUDE.md Output Structure에 audio 산출물 추가**

`<basename>_ko_audio.md` + `_ko_audio.meta.json`이 viewer 스캔에서 제외됨(하위 디렉터리)을 명시.

- [ ] **Step 3: 커밋**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document paper-audio-korean skill + audio output policy"
```

---

## Self-Review

- **Spec coverage:** §1철학→T1, §5소스/수명주기/batch→T2, §6변환규칙→T3, §7출력·§8모드·§9검증→T4, 스모크검증→T5, §10문서→T6. 전 섹션 대응 확인.
- **Placeholder scan:** 각 Task가 어떤 스펙 섹션을 근거로 무엇을 쓸지 명시. 변환규칙·검증 grep은 실제 내용 포함.
- **Type consistency:** 파일 경로(`<basename>_ko_audio.md`, `_ko_audio.meta.json`), sidecar 키(status/source_path/source_mtime/source_size/source_sha256), frontmatter name(`paper-audio-korean`)이 전 Task에서 일관.
