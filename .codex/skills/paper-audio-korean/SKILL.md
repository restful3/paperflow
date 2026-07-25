---
name: paper-audio-korean
description: Convert a Korean paper explainer (_ko_explained.md) into a listen-optimized Korean narration (<basename>_ko_audio.md) using audio-description principles — formulas, tables, figures, and code become meaningful spoken sentences, not placeholders. Use when the user asks "듣기용으로 만들어줘", "낭독판 만들어줘", "audio 버전", "TTS용 변환", or wants an iPhone-listenable version of a paper.
---

# Paper Audio (Korean Explainer → Listen-Optimized Narration)

## When to Use

Use this skill when:
- User wants a version of a paper they can **listen to** on a phone (e.g. iPhone Safari "화면 읽어주기" / Speak Screen).
- User says "듣기용으로 만들어줘", "낭독판 만들어줘", "audio 버전 만들어줘", "TTS용으로 정리해줘".
- A processed paper folder has a Korean explainer (`_ko_explained.md`) and the user wants it turned into clean, ear-friendly Korean.

**This is NOT a summary skill and NOT a translation skill.** The output is a **완전 낭독판 (complete narration)** — every section and idea of the source is preserved, but rewritten so it makes sense when *heard*, not seen.

## Core Philosophy — Audio Description

The guiding principle is **시각장애인용 오디오 디스크립션 (audio description for the visually impaired)**: things you normally *see* (formulas, tables, figures, code) must be turned into **meaningful spoken language**, never into placeholders.

- ❌ FORBIDDEN: "수식이 있습니다", "그림 이 번이 있습니다", "표 일 번이 있습니다" (announcing the element type only)
- ✅ REQUIRED: "이 수식은 어텐션 점수를, 쿼리와 키를 곱한 뒤 차원의 제곱근으로 나눠 구한다는 뜻입니다", "그림 이 번은 샘플 수가 늘수록 정확도가 완만히 오르다 스무 개 부근에서 평평해지는 곡선을 보여줍니다", "표 일 번을 요약하면, ReAct가 두 작업 모두에서 행동전용 방식보다 점수가 높았습니다"

Other principles:
- **완전 낭독판**: never condense. Every section/subsection of the source appears in the output. Removing only happens for §"제거 대상" (listen-worthless) items.
- **항상 해설판 기반**: the source is always the explainer (`_ko_explained.md`). The translation (`_ko.md`) is only the explainer's input, never a direct source. 해설판이 없으면 이 스킬은 낭독판을 만들지 않는다 — Lifecycle 의 Codex 규칙(배치는 skip+보고)을 따른다.

## Codex 환경 (플랫폼 노트)

이 스킬은 Codex(gpt-5.6-sol)에서 구동된다. **품질 규칙(변환 규칙표·변환 예시·숫자 읽기·제거 대상·분량 게이트)은 Claude 판과 동일**하며, 아래 플랫폼 항목만 Codex 에 맞춘다 (2026-07-26 Codex 자가검증 반영).

- **자수 측정**: `wc -m < "$file"` — Codex 는 `/usr/bin/wc` 이고 rtk 훅이 없다. **`LC_ALL=C` 로 실행 금지**(바이트 수가 되어 자수가 틀어진다; locale 은 `C.UTF-8` 유지).
- **그림 판독(vision)**: Codex 는 `view_image` 로 로컬 그림 파일을 판독할 수 있다. **포함하는 핵심 그림은 실물 파일을 여는 것이 기본**이다(캡션·파일명 대응이 틀릴 수 있으므로 — 파일명만 믿지 마라). vision 도구가 실패할 때만 캡션+본문의 **공통 확정사항만** 서술하고 완료 보고에 "미확인 그림"으로 플래그한다. 어느 경우에도 날조 금지(규칙#3·Verification 참조).
- **파일 쓰기**: 섹션 쓰기는 `apply_patch` 로 `.part` 에 기록하고, 전체 완료·검증 후 `mv` 로 최종본에 atomic publish 한다(셸 redirection 통짜 덮어쓰기 지양).
- **완료 신호**: Codex 에는 `Actioning…` 같은 진행 상태 문자열이 없다. 진행/완료 판정은 상태 문자열이 아니라 **프로세스 생존 · `--json` JSONL 이벤트 · 종료 코드 · 최종 sidecar** 로 한다.
- **스킬 발견/호출**: 신규 심링크는 **새 세션에서만** 발견된다(hot reload 없음). 배치는 이 스킬을 `$paper-audio-korean` 으로 명시 호출한다(description 추론에 의존하지 않는다).
- **검증기**: 아래 CRITICAL grep 은 "**0건 = 통과**"라서 GNU grep 이 exit 1 을 낸다(정상 — 실패 아님). 직접 grep 하지 말고 `scripts/verify_audio.sh <basename>_ko_audio.md audio` 로 돌려 명령·매치 수·exit code 판정을 고정하고 결과를 보고에 첨부한다.

## 분량 게이트 (침묵 축약 방지 — 필수)

완전 낭독판의 가장 흔한 실패는 **침묵 축약** — 섹션 헤딩은 모두 남기고 각 섹션의 본문 산문을 압축하는 것이다. 섹션 coverage 체크(헤딩 존재 여부)만으로는 절대 잡히지 않는다. 실측에서 13.5만 자 해설판의 "완전 낭독판"이 1.3만 자(10%)로 붕괴한 사례가 다수 발견됐다.

- **기준 분량(낭독 대상 본문)** = 해설판 자수 − §제거 대상(참고문헌·감사의 글·용어집 표 등) − raw 데이터 부록(원문 보존형 — 규칙 4c에 따라 구조 요약으로만 서술되는 블록). 배너·메타 한 줄은 무시할 수준이므로 빼지 않는다. 자수는 `wc -m`으로 잰다 (`wc -m < "$file"`; §Codex 환경 — `LC_ALL=C` 금지).
- **게이트**: 출력 자수 ≥ 낭독 대상 본문의 **70% (미달 = hard fail)**. 권장 75\~110%. 130% 초과는 경고(공허한 부연 점검).
- **긴 논문 압축 금지**: 해설판이 길면 낭독판도 길어지는 것이 정상이다 — **두 시간짜리 낭독판도 정상 출력**이다. "너무 길다"는 이유로 본문을 요약·병합하지 마라. 축약본이 필요하면 그것은 `paper-audio-brief-korean`의 일이지 이 스킬의 일이 아니다.
- **미달 시**: 소스와 출력의 섹션별 길이를 대조해 어느 섹션이 얇아졌는지 찾고, 그 섹션을 재작성한다. 헤딩이 존재한다 ≠ 본문이 보존됐다.

## Source Resolution & Generation Lifecycle

### Output location

```text
최종 출력:     <paper_dir>/<basename>_ko_audio.md
작성 중 임시:  <paper_dir>/<basename>_ko_audio.md.part      (section-safe append 대상)
완료 메타:     <paper_dir>/<basename>_ko_audio.meta.json    (sidecar — 본문 밖)
```

`<basename>` = the explainer filename without `_ko_explained.md` (e.g. `Foo Paper_ko_explained.md` → `Foo Paper_ko_audio.md`).

**파일은 논문 폴더 직하위에 둔다** (해설판처럼). viewer/MCP는 `_ko_audio.md`를 1급 포맷으로 인식하도록 백엔드가 수정되어 있다: `papers.py`의 감지(`md_ko_audio` 플래그)·`get_md_ko_audio_path`·`get_md_en_path`/`save_markdown` 제외, `chat.py` RAG 제외, `mcp_zip` translation 게이팅, `/api/papers/{name}/md-ko-audio` 엔드포인트, viewer.html "듣기" 토글. 따라서 영어 원문으로 오분류되지 않는다.

### Two-phase lifecycle

```text
Phase 1 — 해설판 확보 (Codex):
  _ko_explained.md 없음 OR legacy completion validation 실패
    → 배치: 이 폴더를 skip 하고 완료 보고에 기록한다.
      해설판 생성은 Claude explainer 배치의 몫이다 (해설판=Claude 유지 목표).
      Codex 의 interpretive-panel(해설판 생성)을 배치에서 호출하지 않는다.
    → 대화형 단건에서 사용자가 "해설판까지 만들어" 라고 명시 요청한 경우에만
      $interpretive-panel 로 해설판을 먼저 생성한 뒤 진행한다.
  legacy completion validation 통과해야만 Phase 2 진입
Phase 2 — 듣기 변환:
  검증된 _ko_explained.md 를 소스로 <basename>_ko_audio.md.part 에 섹션별 작성
  전체 완료 + 검증(아래 Verification) 통과 시:
    → .part 를 <basename>_ko_audio.md 로 atomic rename (mv)
    → <basename>_ko_audio.meta.json sidecar 기록
실패 시:
  최종 _ko_audio.md 를 만들지 않는다. .part 와 실패 사유만 남긴다.
```

**Legacy completion validation (해설판 소스 완료 판정):**
`paper-explainer` does NOT write a completion marker, and existing `_ko_explained.md` files have none. So do **NOT** require a marker on the explainer source. Judge it complete when ALL hold:
- `_ko_explained.md` exists and is non-empty
- has a title / real body content (not a stub)
- heading coverage vs the upstream source is reasonable (no large truncation)
- major sections present (References / 감사의 글 etc. may be absent — that's fine)

If it fails this: 배치는 skip + 보고한다(해설판 생성은 Claude 몫). 대화형에서 사용자가 명시 요청한 경우에만 `$interpretive-panel` 로 먼저 해설판을 만든다.

### Skip / regeneration

```text
<basename>_ko_audio.md (최종본) 존재 AND
  sidecar.status == "complete" AND
  sidecar 의 source 메타가 현재 _ko_explained.md 와 일치(최신)   → skip
그 외(.part만 존재 / sidecar 없음 / 소스가 더 최신·변경) → 재생성
```

- The completion metadata lives in the **sidecar**, never in the `.md` body (a body HTML comment can be read aloud by some viewers — see Output Format).
- Sidecar schema:
  ```json
  {
    "status": "complete",
    "source_path": "<basename>_ko_explained.md",
    "source_mtime": "<ISO8601 or epoch>",
    "source_size": 12345,
    "source_sha256": "<hex>"
  }
  ```
  Judge freshness by `source_mtime` **and** `source_size`/`source_sha256` together (mtime alone is unreliable across copy/restore/sync).
- A lone `.part` is "incomplete" and must NEVER be treated as a finished file to skip. 진행 중 `.part` 옆에는 완료 섹션 목록 + `source_sha256` + run/session ID 를 진행 체크포인트로 남기고, **소스가 바뀐(sha256 불일치) stale `.part` 에 맹목 append 하지 않는다**(Codex compaction/재시작 대비).

### Batch mode (대상 미지정 시)

Inherit the `paper-explainer` batch rules and add audio conditions:
- Scan `outputs/` and `archives/` non-recursively. A directory is an **eligible paper folder** only if: name does NOT start with `.`, it contains a source MD, it is not empty/config/symlink.
- **`paper_meta.json`의 `doc_type` 가 `"video"` 인 폴더는 후보에서 제외** — 동영상(HBR Premium 등)은 낭독판 대상이 아니다(소스는 해설판이며, 동영상엔 해설판을 만들지 않으므로 자연히 낭독판도 없음). 폴백 `*_ko.md` 가 있어도 무조건 건너뛴다.
- Exclusions: `_backup_`, `.bak`, `_mdlint_report.json`, and audio artifacts `*_ko_audio.md`, `*.part`.
- Among folders whose `<basename>_ko_audio.md` is missing (by completion-sidecar standard), pick the **single most recently updated source**. Treat "audio older than source" as a regeneration candidate.
- Sourceless/orphan folders: skip and list them in the completion report. **Never create, rename, or delete folders.**

## Conversion Rules — Audio Description

**Supreme rule: NO placeholders.** Never narrate just the element type ("수식입니다 / 그림입니다 / 표입니다"). Always convey *which* formula, *what* the figure shows, *what* the table says.

**Before converting, build a 낭독 사전 (pronunciation map):** collect model names, benchmarks, method names, and acronyms; decide one Korean spoken form for each, and apply it consistently throughout the whole document. 숫자·참조 번호 읽기 방침(규칙 9 — "그림 이 번" 형식, 단위별 한자어/고유어)도 함께 정해 일관 적용한다.

| # | 요소 | 규칙 |
|---|------|------|
| 1 | **수식** (`$$…$$`, 인라인 `$…$`) | placeholder 금지. **"이 수식은 ~를 ~로 계산한다는 뜻입니다"** 로 자연어 낭독. 해설판의 기존 수식 설명을 우선 활용, 없으면 맥락을 읽어 생성. 변수 기호는 **문자까지 한글 음차 또는 의미어**로 읽는다 ("디는 임베딩 차원", "와이는 관측 데이터") — 본문에 알파벳 단독 표기(y·n·T·r)를 남기지 않는다 (실측: 19개 문단 잔존 사례) |
| 2 | **표** (마크다운 `\|…\|`) — 유형별 | (a) glossary/비유/용어 표 → 문단 또는 목록으로 풀어 낭독. (b) **핵심 실험·성능 표 → 4\~8문장**으로 "최고 성능, 기준선 대비 차이, 예외, 대표 수치"를 반드시 포함해 서술 (1\~3문장 강제 요약 금지). 셀·`\|`·`<br>`·표 안 수식은 자연어로 풀되 핵심 수치는 보존 |
| 3 | **그림/이미지** (`![](…)`) | **이미지 구문은 유지(임베딩)** — 단 alt는 비워 `![](경로)` 형태로 둔다 (alt 텍스트는 raw TTS에서 읽힐 수 있으므로). 그리고 **기존처럼** 그림 바로 앞 본문에 **"그림 N 번은 ~를 보여줍니다"** 자연어 묘사를 함께 둔다 (캡션+본문 맥락 기반, 참조번호는 규칙#9). 이렇게 하면 들을 땐 묘사가 들리고, 보고 싶을 땐 뷰어/HTML에서 그림이 보인다. **묘사는 실물과 일치해야 한다**: Codex 는 포함하는 핵심 그림의 이미지 파일을 `view_image` 로 직접 열어(vision) 확인한 뒤 쓴다(캡션·파일명 대응이 틀릴 수 있으므로 파일명만 믿지 마라) — 시계열 차트를 "방법론 도해"로 서술하는 류의 날조 묘사는 정확성 위반이다 (실측 결함). vision 실패 시에만 캡션+본문의 공통 확정사항만 서술하고 "미확인 그림"으로 플래그. 순수 장식 이미지는 생략 가능 |
| 4 | **코드/프롬프트/알고리즘 블록** (` ``` `) | (a) 짧은 핵심 의사코드 → 단계별 자연어 목록. (b) 긴 prompt/log/code dump → "이 블록은 ~용 프롬프트로, ~순서로 구성됩니다"처럼 목적·구조를 설명하고 재현에 필요한 핵심 문구만 낭독 친화적으로 발췌. (c) raw appendix 성격이면 "듣기판에서는 구조와 핵심만 설명했다"고 명시 |
| 5 | **인용·링크** (`[1]`, `(Author, 2023)`, `[text](#anchor)`) | citation marker 제거. 선행 연구 비교가 의미를 갖는 문장은 "기존 연구들"/"저자들이 비교한 선행 방법"으로 자연어화 |
| 6 | **각주** (`<sup>N</sup>` 및 Markdown footnote `[^1]` / `[^1]: …`) | 각주 표식 제거. **각주 본문이 실험 조건·예외·데이터셋 설명이면 해당 문단에 자연어로 병합**, 순수 서지 정보면 삭제 |
| 7 | **영어 용어/약어** | 첫 등장: **"대규모 언어 모델(LLM, 엘엘엠)"** 음차 병기 → 이후 한국어 용어. 약어는 낭독 사전대로 음차 ("RoPE → 로프", "MoE → 모이"). 고유명사·모델명은 자연스러운 음차. **괄호 안에 영어만 두지 않는다** — 괄호를 쓰면 반드시 한글 음차를 함께 넣고(`(LLM, 엘엘엠)`), 그게 아니면 괄호 없이 음차만 남긴다(`셰어지피티(ShareGPT)` ❌ → `셰어지피티` ✅). 특히 낭독 사전에 없는 고유명사·모델명·지표명(ShareGPT, MemoryOS, GPT-5, F1 등)은 음차로만 적고 `(영어)`를 붙이지 않는다 — raw TTS가 괄호 영어를 그대로 읽어 중복·오독이 생긴다. **"영어로는 프리 익스체인지라고 합니다" 류의 별도 발음 안내 문장도 금지** — 음차 병기는 첫 등장 1회의 괄호 형식으로 끝낸다 (실측: 한 문서 13회 잔존 사례) |
| 8 | **문어체·만연체** | 긴 문장을 분할하고 능동·구어체("~합니다")로. 귀로 한 번에 이해되도록 |
| 9 | **숫자·참조 번호** (오독 위험만) | 모든 숫자가 아니라 **오독 위험만** 한글로. 참조번호 `그림 N`→"그림 이 번"(한자어+`번`, 동음 '그림이' 회피·라벨 ID 보존), 문서구조번호 `2장`→"제이 장"·`3.1절`→"제삼 점 일 절"(`제`+한자어, 동음 '이 장≈this'·'사 장≈사장' 회피), 고유어 분류사 `3개`→"세 개"·`2시간`→"두 시간", 모델명 음차 `GPT-4`→"지피티 포", 소수·범위·퍼센트. **우선순위·단위별 체계·변형(suffix/복수/순서/제-접두사)은 아래 §변환 예시의 "숫자·참조 번호" 표 참조** |
| 10 | **소스 해설판의 연속 패러프레이즈 중복** | 입력 `_ko_explained.md` 에 **[충실 번역 문단] + [같은 내용 재설명 문단]** 쌍이나, 인접 문단이 같은 주장·예시·비유를 다른 말로 반복하는 곳이 있으면 — 두 문단의 **고유 정보만 합쳐 하나의 자연스러운 낭독 문단**으로 만든다. **둘 다 낭독하지 않는다.** 이는 "듣기 무가치" 정리(§제거 대상)에 해당하나 **요약이 아니다** — 핵심 정보·숫자·조건·예외는 그대로 보존하고, 단지 같은 말의 두 번째 반복만 걷어낸다. (귀로 듣는 형식이라 연속 패러프레이즈 중복은 화면보다 훨씬 거슬린다.) |

### 변환 예시

**수식 (규칙 1):**

> 원본:
> ```
> $$\mathbf{o}_{t,i}=\sum_{j=1}^{t}\mathrm{Softmax}_j\left(\frac{\mathbf{q}_{t,i}^{T}\mathbf{k}_{j,i}}{\sqrt{d_h+d_h^R}}\right)\mathbf{v}_{j,i}$$
> ```
> 낭독판:
> "어텐션 출력은 이렇게 구합니다. 각 위치의 쿼리와 그 이전 모든 위치의 키를 곱해 유사도를 잰 뒤, 차원의 제곱근으로 나눠 크기를 안정화하고, 소프트맥스로 가중치를 만든 다음, 그 가중치로 값(밸류)들을 합칩니다. 쉽게 말해 '지금 토큰이 과거 토큰 각각에 얼마나 주목할지'를 정해 섞는 것입니다."

**표 (규칙 2, 핵심 실험표):**

> 원본: HotpotQA(EM)·Fever(Acc) 열에 Standard/CoT/Act/ReAct 행이 있는 성능 표
> 낭독판:
> "표 일 번은 네 방법의 성능을 비교합니다. HotpotQA에서는 ReAct와 사고사슬을 결합한 방식이 가장 높은 삼십오 점 일 점을 기록했고, 표준 프롬프팅은 이십팔 점 칠 점에 그쳤습니다. Fever에서도 결합 방식이 육십사 점 육 점으로 가장 높았습니다. 다만 지도학습 기반 최고 성능인 육십칠 점 오 점, 팔십구 점 오 점에는 아직 못 미칩니다."

**그림 (규칙 3) — 묘사는 그대로, 그림은 임베딩 유지:**

> 원본: `![](_page_4_Figure_2.jpeg)` + "그림 2: 사용된 CoT-SC 샘플 수에 따른 PaLM-540B 결과"
> 낭독판:
> "그림 이 번은 자기일관성 기법에서 샘플 수를 늘릴 때 성능이 어떻게 변하는지 보여줍니다. 샘플이 많아질수록 정확도가 오르지만, 일정 수를 넘으면 개선 폭이 완만해집니다."
> 그리고 이 묘사 문장 **바로 뒤(같은 위치, 1문단 이내)** 에 원본 이미지 줄 `![](_page_4_Figure_2.jpeg)` 을 alt 비운 채 그대로 남긴다.

**숫자·참조 번호 (규칙 9) — 오독 위험만 선택 변환:**

변환 우선순위:

1. **항상 변환**: 참조번호 · 구조/순위/측정 단위 · 시간/횟수/분류사 · 소수 · 범위 · 모델명 숫자.
2. **조건부 변환**: 긴 정수 · 연도 · 금액 · 데이터 크기는 해당 문서/엔진에서 오독이 관찰되거나 단위 때문에 헷갈릴 때만. **한 문서 안에서는 통일** — `2025년`을 한 번 풀면 모든 연도를 푼다 (`2025년`→"이천이십오 년", `1998년`→"천구백구십팔 년").
3. **읽지 않음**: DOI · URL · 버전 문자열 · 파일명 · 코드 식별자는 낭독 가치가 없으면 삭제하거나 자연어로 대체한다 (원문 문자열을 억지로 읽히지 않음).

| 분류 | 체계 | 예 |
|------|------|-----|
| 참조번호 (그림/표/식) | 한자어+`번` | `그림 2`→"그림 이 번", `표 1`→"표 일 번", `Eq. (3)`→"식 삼 번" (**원문 라벨어 보존**: 원문이 '수식'이면 "수식 삼 번") |
| 문서 구조 번호 (장/절/항/chapter/section) | **제**+한자어+단위 | `1장`→"제일 장", `2장`→"제이 장", `4장`→"제사 장", `3절`→"제삼 절", `3.1절`→"제삼 점 일 절", `2.3.1항`→"제이 점 삼 점 일 항" (원문에 '제'가 없어도 붙임 — 동음 '이 장≈this'·'사 장≈사장'·'오 장≈오장' 회피, 라벨 ID 보존) |
| 날짜·순위·측정 단위 | 한자어(+단위) | `3월 5일`→"삼 월 오 일", `2차`→"이 차", `1등`→"일 등", `3위`→"삼 위", `2배`→"이 배", `3차원`→"삼 차원", `5분 30초`→"오 분 삼십 초", `20%`→"이십 퍼센트" |
| 개수·시각·시간·횟수·나이 | 고유어 | `3개`→"세 개", `2시`→"두 시", `2시간`→"두 시간", `3번 반복`→"세 번 반복", `10명`→"열 명" |
| 순서 (실제 순서일 때) | 고유어 서수 | `2번째`→"두 번째" (단 그림·표·식 **참조번호엔 적용 안 함** — 그건 "그림 이 번") |
| 소수·퍼센트 | 한자어 자리읽기 | `3.5`→"삼 점 오", `55.34%`→"오십오 점 삼사 퍼센트", `35.1점`→"삼십오 점 일 점" (단위 보존) |
| 범위 (`~`·`-`·`–`) | "에서" | `3~5개`→"세 개에서 다섯 개", `0.1–0.3`→"영 점 일에서 영 점 삼" |
| 모델명·기술 숫자 | 음차(규칙#7) | `GPT-4`→"지피티 포", `Llama 2`→"라마 투", `T5`→"티 파이브" (한자어 강제 금지) |

참조번호 변형: **문자 suffix 보존** (`Figure 2a`→"그림 이 에이 번", `Fig. 2(b)`→"그림 이 비 번"), **복수 참조는 라벨 묶어 읽기** (`Figures 2 and 3`→"그림 이 번과 삼 번", `Equations (3)-(5)`→"식 삼 번에서 오 번").

**혼합·경계 사례 (실전 확정 규칙):**
- 연도를 digits 로 유지하는 문서에서 월·일만 변환한 "2026년 오 월 이십팔 일" 같은 **혼합 표기는 의도된 정답**이다 (시각적 어색함보다 TTS 일관성 우선).
- **연도 범위**(`1964~1965년`)는 "천구백육십사 년에서 천구백육십오 년"이 장황하면 **문장 재구성으로 회피**해도 된다 ("1964년부터 이듬해까지" 류).
- 고유어 분류사는 **스물 이상이면 한자어 허용** ("60곳"→"육십 곳", "예순 곳" 강제 아님).
- **인명 미들 이니셜**("Joseph C. Nunes"의 "C.")은 생략하거나 음차한다 — 알파벳 단독 잔존 금지.

`제`는 **구조 단위(장/절/항/chapter/section)와 결합할 때만** 붙인다. 구조 단위가 없는 소수·실험 번호에는 붙이지 않는다 — 예: "3.1의 결과"는 "제삼 점 일의 결과"가 아니라 "삼 점 일의 결과" (또는 맥락상 "제삼 점 일 절의 결과"가 맞으면 절을 명시). 실제 등장 순서를 말할 때는 서수형(`두 번째`, `세 번째`)을 쓴다.

### 제거 대상 (듣기 무가치 — 통째 삭제)

- 목차(점선 `. . . .` + 페이지번호)
- 페이지 마커 / `<span id="page-…">` / 기타 HTML 앵커
- 저자 소속줄, 이메일, URL
- 학회 푸터 ("Proceedings of the … Copyright …")
- 참고문헌(References / Bibliography) 목록 섹션 전체
- 감사의 글(Acknowledgements)
- **용어집("핵심 용어 해설") 표** — 인라인 정의의 재수록이므로 **무조건 통째 제거한다. 말미 "용어 되짚기"·용어 재정의 나열 블록도 금지.** (실측: 2026-07-22 전수 감사에서 547개 중 61%가 마무리 직전에 본문에서 이미 설명한 용어 6\~12개를 재정의하며 끝나는 결함 확인 — 글 전체를 들은 직후 같은 정의를 또 듣게 되는 청취 반복의 주범. 과거의 "원하면 3\~5문장 용어 되짚기 가능" 단서가 사실상 기본 동작이 되어 버려 조항 자체를 삭제했다.) 본문에서 정말 다뤄지지 않은 용어가 있으면 그 용어가 **처음 등장하는 본문 문장 안에** 정의를 녹인다 — 말미에 모아 나열하지 않는다. **분량 게이트의 분모에서도 제외한다.**
- **해설판이 신설한 개관/매핑 요약 표** — 곧 이어질 본문과 중복이므로 한 문장 예고("이 글은 여섯 개 차원을 차례로 다룹니다" 류)로만 처리

## Output Format

- 경로/파일명: `<basename>_ko_audio.md` (작성 중 `.part`)
- **YAML 헤더 없음 (기본값).** raw 마크다운을 직접 TTS에 넣는 경로도 지원해야 하므로 front matter를 두지 않는다 (`lang: ko` 한 줄조차 — 불완전 YAML이거나 낭독될 수 있음). 언어 메타가 필요하면 sidecar에 둔다. HTML로 듣고 싶으면 사용자가 `md-to-html` 변환 단계에서 front matter를 주입하는 것을 전제로 한다.
- 제목: `# <원제목> — 듣기판`
- **배너 blockquote 넣지 않는다 (기본값).** "이 글은 듣기용으로 다듬은 낭독판입니다…" 류의 변환 안내 문구는 매 파일 반복되면 지겹고 낭독 시작을 늦춘다. 제목(`— 듣기판`)만으로 듣기 변환본임이 충분히 드러나므로, 제목 바로 다음에는 본문(첫 섹션)으로 들어간다. 사용자가 명시적으로 요청할 때만 한 줄 안내를 넣는다.
- **도입부 상투구 금지.** 글의 출처·성격을 소개할 때 **"학술 논문이라기보다는 ~에 가깝습니다"** 류의 정형 대비 문구를 반복하지 않는다 (여러 파일에서 똑같이 반복되어 거슬린다). 출처·저자·장르 소개가 필요하면 한 번만, 매번 다른 표현으로 자연스럽게 녹인다. 굳이 "논문이 아니라 ~"로 대비시키지 말고, 필요하면 그것이 무엇인지(블로그·에세이·기술 보고서 등)만 짧게 밝히거나 곧장 내용으로 들어간다.
- **매체 설명 반복 금지 (중요).** "The Economist 는 영국의 시사주간지로…" 같이 매체·출처가 무엇인지에 대한 부연을 넣지 않는다 — 소양 있는 독자(이공계 학부 이상)는 매체를 안다. 출처가 필요하면 이름만 한 번. 특히 이코노미스트 주간호처럼 여러 기사를 연속으로 들을 때 매 편마다 매체 설명이나 기초 개념(백분율·GDP·금리 등) 풀이가 반복되면 가장 거슬린다 — 입력 해설판에 그런 군더더기가 남아 있으면 듣기판으로 옮길 때 걷어낸다. **정형 비유 마커("비유로 설명하면 이렇습니다:")·수치 재진술 문단("이 숫자를 음미해 봅시다")·순수 반복형 마감 에코("정리하면/쉽게 말해 …")도 같은 군더더기다** — 소스 해설판에 있어도 낭독판에 복제하지 않는다 (핵심 정보·숫자는 보존, 규칙#10 과 동일 원리).
- **마무리 한 줄 (필수).** 본문 맨 끝에 낭독이 끝났음을 알리는 짧은 마무리 문장 한 줄을 둔다 (들을 때 끝을 알 수 있도록). 예: "여기까지가 이 글의 듣기판이었습니다." / "이상으로 낭독을 마칩니다." 한 문장이면 충분하고 길게 늘어놓지 않는다. 매번 똑같은 문구가 되지 않도록 표현은 적절히 바꾼다.
- **소스 섹션 구조 유지** — 완전 낭독판이므로 섹션·소절 누락 금지 (제거 대상 섹션 예외)
- **본문에 메타데이터/HTML comment 금지** — 완료 메타는 sidecar에만
- 마크다운만 (HTML 태그·뷰어 연동 없음). **단 그림은 예외** — 의미 있는 figure 는 `![](경로)` 이미지 구문(**alt 비움, 논문 폴더 내부 상대경로만** — `http(s)://`·절대경로·`../` 금지)으로 임베딩하고, 그 앞 1문단 안에 자연어 묘사를 둔다. 이 임베딩은 **렌더링 경로(뷰어/HTML) 기준 기능**이다 — 거기선 그림이 보이고 TTS는 이미지를 건너뛴다. raw 마크다운을 그대로 TTS에 넣으면 파일명이 읽힐 수 있으니, **raw 낭독만 쓰고 그게 거슬리면 이미지 구문을 생략(묘사만 유지)해도 된다** (기본값은 임베딩 유지)

## Modes / Operational Stability

### 실행 모델 — 논문별 fresh 세션 순차 (Codex 배치 기본값)

**배치·재생성은 셸 오케스트레이터가 논문 하나씩 fresh `codex exec` 로 순차 실행하는 것이 기본값이다** (Codex 자가검증 반영 — 한 대화에 여러 긴 논문을 누적하면 compaction·논문 간 오염이 생긴다):

- 논문 내부만 `.part` 에 섹션별로 기록하고, 다음 논문은 **새 세션**에서 시작한다.
- 크론/비대화형 실행은 `codex exec -C <repo> -s workspace-write -c 'approval_policy="never"'` 형태로 돌리고, 출력(논문) 폴더가 writable root(`-C`, 필요 시 `--add-dir`)에 포함되게 한다. 프롬프트에는 이 스킬을 `$paper-audio-korean` 으로 명시한다.
- `spawn_agent` 병렬 위임은 **기본이 아니다** — 이 인터페이스에는 model/agent 타입 선택 인자가 없어 워커 타입을 고정할 수 없고, 실익은 벽시계 시간뿐이다. 쓰더라도 논문·run 별 임시 파일로 완전히 분리하고 최종 publish·검증은 부모가 직렬화한다.
- 워커/세션 프롬프트에는 이 SKILL.md **전체를 읽게 한다** (요약본 금지 — 규칙 누락의 원인).
- 게이트 실패분·의심분은 상위(감독) 세션이 직접 감사·수정한다. 우선 확인할 오류 패턴: **차트 축 단위 오독(예: €bn→"억" 10배 축소), 동아시아 인명 로마자 한글 음차 추정, 소스 풀쿼트 중복 이월** — 세션 프롬프트에 금지 조항으로 명시한다.
- 통과분만 폴더에 반영한다 — 구본은 `.bak-<timestamp>` 백업, sidecar(`_ko_audio.meta.json`) 기록 포함.
- **단건 대화형 요청은 현재 세션이 직접 처리해도 된다.**

운영 정책:
- **Auto 모드**: 전체 자동 변환, 섹션 순차 처리.
- **Section-safe 모드**: 긴 논문은 `.part` 에 섹션별 `apply_patch` 로 기록하고, **완료 섹션 목록 + `source_sha256` + run/session ID 를 진행 체크포인트**로 남긴다. 소스가 바뀐 stale `.part` 에 맹목 append 하지 않는다. 전체 완료·검증 후에만 `mv` 로 최종본 atomic rename.
- **승인/샌드박스**: 비대화형은 `-s workspace-write -a never`(또는 `approval_policy="never"`). `--dangerously-bypass-approvals-and-sandbox` 는 외부 격리가 확실할 때만.
- **완료 판정**: 상태 문자열이 아니라 프로세스 생존·`--json` 이벤트·종료 코드·최종 sidecar 로 판정한다(§Codex 환경). 성급히 stall 로 단정하지 않는다.

## Verification

### 변환 전 — Source Inventory 작성
소스(`_ko_explained.md`)에서 기록:
- 헤딩 목록
- 표 개수 + 각 표의 caption/근처 문맥
- 이미지 개수 + caption
- 수식 블록 개수
- **인라인 수식/변수 표현**: 모든 `$x$`를 세지 말고, **문단별로 "이 문단의 인라인 수식·변수가 자연어로 풀렸는가"** 를 확인
- 코드 fence 개수
- 각주 개수 (`<sup>` 및 Markdown `[^...]`)

### CRITICAL (반드시 통과)

> 아래 grep 검사는 `scripts/verify_audio.sh <basename>_ko_audio.md audio` 로 실행한다 — "0건=통과"를 exit code 로 안전하게 판정하고(0건일 때 GNU grep 은 exit 1 = 정상), 결과를 보고에 첨부한다. 수동 grep 시 참조 패턴은 아래와 같다.

- [ ] 출력에 다음이 **0건** (grep):

```bash
grep -nE '\$\$|\$[^$]+\$|\\\(|\\\[|^\s*\|.*---|^```|\[[0-9]+\]|\[\^|<sup|<span|<br|</?[a-zA-Z]|\]\(#|https?://' "<basename>_ko_audio.md"
```
  (수식 블록·인라인 수식·표 구분선·code fence·`[N]`인용·Markdown footnote·HTML 태그·앵커 링크·bare URL)
  — **그림 이미지 `![](경로)` 는 의도적으로 허용**하므로 grep 패턴에서 제외했다.
- [ ] **단독 라틴 변수 잔존 0건** (변수 기호가 알파벳 그대로 남지 않았는가):

```bash
grep -nE '(^|[ "(])[a-zA-Z]([ ,.는은이가의)"]|$)' "<basename>_ko_audio.md"
```
  매치가 나오면 해당 문장을 열어 변수 기호인지 확인하고 한글 음차/의미어로 교체한다 (이미지 경로 줄은 예외). 다문자 약어·모델명도 음차 대체가 기본값(규칙#7)이므로, 본문에 알파벳이 남는 경우는 원칙적으로 없어야 한다.
- [ ] **마무리 한 줄 존재** (`tail -1` 이 낭독 종료를 알리는 문장인가 — 용어 항목이나 본문 문장으로 뚝 끝나면 실패)
- [ ] **말미 용어 재정의 나열 0건** — 마무리 한 줄 직전 구간(대략 마지막 1,500자)에 "X는 \~입니다 / X란 \~를 말합니다" 형태의 용어 정의 문장이 연속 3개 이상 나열된 블록이 없다 (§제거 대상의 용어집 잔향 금지 — 본문에서 이미 설명한 용어를 말미에 다시 정의하면 실패)
- [ ] **alt 있는 이미지가 0건** (alt는 반드시 비워야 함 — alt 텍스트는 raw TTS에서 읽힘):

```bash
grep -nE '!\[[^]]+\]\(' "<basename>_ko_audio.md"
```
  허용되는 이미지는 `![](상대경로)` 뿐이며, 경로는 논문 폴더 내부 상대경로여야 한다 (절대경로·`../`·URL 금지). **title 문법 `![](경로 "title")` 도 금지** — title 텍스트가 raw TTS에서 읽힌다.
- [ ] **항목별 대응**: Source Inventory의 각 표·그림·수식·인라인수식·코드·각주가 출력에서 자연어 문장으로 대응됐는가 (통째 누락 차단). 임베딩된 그림은 **묘사 문장이 이미지 줄 바로 앞 1문단 안에** 있어야 한다 (묘사 없는 그림 단독, 또는 묘사와 이미지가 다른 섹션으로 분리되면 실패)
- [ ] **섹션 coverage**: 소스의 섹션 헤딩이 모두 출력에 존재 (제거 대상 섹션은 예외 목록으로 기록)
- [ ] **분량 비율 (침묵 축약 차단)**: 출력 자수(`wc -m`, §Codex 환경)가 낭독 대상 본문(해설판 − 제거 대상 − raw 부록)의 **70% 이상**인가 (§분량 게이트). 미달이면 섹션별 길이를 소스와 대조해 압축된 섹션을 재작성한다. **섹션 헤딩이 모두 존재해도 이 게이트 미달이면 실패다.**

### Important
- [ ] **연속 문단 패러프레이즈 중복 0건** — 소스 해설판에 [충실 번역 문단]+[같은 내용 재설명 문단] 쌍이나 인접 문단의 같은 주장·예시·비유 반복이 있었으면 고유 정보만 합쳐 한 문단으로 병합했는가(규칙#10). 둘 다 낭독한 곳이 없어야 한다. **단, 이 중복 병합으로 줄어든 분량은 §분량 게이트(70%)의 "침묵 축약"이 아니다** — 70% 하한은 소스의 *고유* 내용 기준이며, 같은 말의 반복은 분모에서 제외한다 (레거시 중복 해설판이 소스일 때 특히).
- [ ] 표본 3개 섹션에서 수식·표·그림·코드가 placeholder가 아닌 **의미 있는 서술**로 변환됐는가
- [ ] 핵심 실험 표에서 대표 수치가 보존됐는가
- [ ] 영어 약어가 첫 등장 시 음차 병기 + 낭독 사전 일관 적용
- [ ] **괄호 안에 영어만 든 표기가 0건** (`한글(English)` 금지 — 음차 병기 `(LLM, 엘엘엠)`만 허용, 고유명사·모델명·지표명은 음차로만)
- [ ] 참조 번호가 "그림 N 번 / 표 N 번 / 식 N 번" 형식, 문서구조번호가 "제N 장 / 제N 절"(제+한자어) 형식, 단위별 한자어/고유어 구분(세 개·두 시 등)이 맞는가 (오독 위험만 변환, 일반 숫자 강제 변환 아님)
- [ ] 최종 파일명이 `..._ko_audio.md`, sidecar `_ko_audio.meta.json`에 `status=complete` + freshness(mtime/size/sha256)
- [ ] 최종 `.md` 본문에 메타데이터/HTML comment가 없음 (순수 낭독 텍스트)
- [ ] YAML 헤더 없음
- [ ] 도입부에 "학술 논문이라기보다는" 류 정형 대비 상투구가 없는가 (마무리 한 줄은 CRITICAL 로 승격됨)
- [ ] **그림 묘사-실물 일치 (Codex: 핵심 그림은 실물 대조 기본)**: 포함한 핵심 그림은 `view_image` 로 이미지 파일을 열어 묘사가 실제 내용(차트 유형·축·추세)과 일치하는지 확인했는가. vision 실패 시 캡션 기반 공통 확정사항만 서술하고 "미확인 그림"으로 플래그했는가(날조 0건)

## Completion Report

완료 시 간결히 보고:
- 입력 파일(소스 해설판) / 출력 파일(`..._ko_audio.md`) 경로
- Phase 1 발생 여부 (배치는 해설판 없으면 skip — 생성하지 않음)
- 변환된 섹션 수 / 소스 총 섹션 수
- **출력 자수 / 낭독 대상 본문 자수 / 비율** (≥70% 게이트 통과 여부, §분량 게이트)
- CRITICAL grep 0건 통과 여부 (`scripts/verify_audio.sh` 결과)
- vision 미확인 그림 목록(있으면) — 캡션 기반 서술로 플래그한 그림
- (Batch) 건너뛴 소스 없는 고아 폴더 목록(있으면)
- 특이사항 (긴 표/코드 처리, OCR 노이즈 등)
