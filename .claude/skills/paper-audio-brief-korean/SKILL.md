---
name: paper-audio-brief-korean
description: Convert a Korean paper explainer (_ko_explained.md) into an ABRIDGED listen-optimized Korean narration (<basename>_ko_audio_brief.md) — approximately 7,000자 (~20분). Keeps only the core: problem motivation, key contributions, method intuition, main results, and limitations. Use when the user asks "축약 낭독판 만들어줘", "짧은 낭독판", "brief audio 만들어줘", "20분짜리 듣기판", or wants a condensed iPhone-listenable version of a paper.
---

# Paper Audio Brief (Korean Explainer → Abridged Listen-Optimized Narration)

## When to Use

Use this skill when:
- User wants an **abridged** (~20분) version of a paper they can **listen to** on a phone (e.g. iPhone Safari "화면 읽어주기" / Speak Screen).
- User says "축약 낭독판 만들어줘", "짧은 낭독판 만들어줘", "brief audio 만들어줘", "20분짜리 듣기판".
- A processed paper folder has a Korean explainer (`_ko_explained.md`) and the user wants a **condensed** ear-friendly Korean version.

**This is NOT a full narration skill.** The output is an **축약 낭독판 (abridged narration)** — only the core message is preserved, rewritten so it makes sense when *heard*, not seen. Detailed experiments, proofs, and peripheral content are cut.

For a **complete** (full-length) narration, use the sibling skill `paper-audio-korean` instead.

## Core Philosophy — Audio Description

The guiding principle is **시각장애인용 오디오 디스크립션 (audio description for the visually impaired)**: things you normally *see* (formulas, tables, figures, code) must be turned into **meaningful spoken language**, never into placeholders.

- ❌ FORBIDDEN: "수식이 있습니다", "그림 이 번이 있습니다", "표 일 번이 있습니다" (announcing the element type only)
- ✅ REQUIRED: "이 수식은 어텐션 점수를, 쿼리와 키를 곱한 뒤 차원의 제곱근으로 나눠 구한다는 뜻입니다", "그림 이 번은 샘플 수가 늘수록 정확도가 완만히 오르다 스무 개 부근에서 평평해지는 곡선을 보여줍니다", "표 일 번을 요약하면, ReAct가 두 작업 모두에서 행동전용 방식보다 점수가 높았습니다"

Other principles:
- **축약 낭독판**: condense to core. Detailed experiments, ablations, proofs, peripheral figures are cut (see §분량 정책).
- **항상 해설판 기반**: the source is always the explainer (`_ko_explained.md`). The translation (`_ko.md`) is only the explainer's input, never a direct source. If no explainer exists, generate one first (see Lifecycle).

## 분량 정책 (요약)

해설판에서 다음만 남긴다(우선순위): 1) 문제의식·왜 중요한가 2) 핵심 기여(차별점) 3) 방법의 골자(직관 수준, 세부 유도·증명 생략) 4) 핵심 결과(주요 수치 1\~2개; 보조 실험·ablation·다수 표 생략) 5) 한계·시사점. 세부 실험 셋업·증명/유도·곁가지·반복·다수 보조 그림은 과감히 생략한다. 목표 분량 ~7,000자(약 20분). 초과 시 더 압축한다. 한 문서씩 끝내고 다음으로.

## Source Resolution & Generation Lifecycle

### Output location

```text
최종 출력:     <paper_dir>/<basename>_ko_audio_brief.md
작성 중 임시:  <paper_dir>/<basename>_ko_audio_brief.md.part      (section-safe append 대상)
완료 메타:     <paper_dir>/<basename>_ko_audio_brief.meta.json    (sidecar — 본문 밖)
```

`<basename>` = the explainer filename without `_ko_explained.md` (e.g. `Foo Paper_ko_explained.md` → `Foo Paper_ko_audio_brief.md`).

**파일은 논문 폴더 직하위에 둔다** (해설판처럼). viewer/MCP는 `_ko_audio_brief.md`를 1급 포맷으로 인식하도록 백엔드가 수정되어 있다: `papers.py`의 감지(`md_ko_audio_brief` 플래그)·`get_md_ko_audio_brief_path`·`get_md_en_path`/`save_markdown` 제외, `chat.py` RAG 제외, `mcp_zip` translation 게이팅, `/api/papers/{name}/md-ko-audio-brief` 엔드포인트, viewer.html "듣기" 토글(축약본 우선·전체 스위치). 따라서 영어 원문으로 오분류되지 않는다.

### Two-phase lifecycle

```text
Phase 1 — 해설판 확보:
  _ko_explained.md 없음 OR legacy completion validation 실패
    → paper-explainer 스킬을 실행해 _ko_explained.md 생성·완료
  legacy completion validation 통과해야만 Phase 2 진입
Phase 2 — 축약 듣기 변환:
  검증된 _ko_explained.md 를 소스로 <basename>_ko_audio_brief.md.part 에 섹션별 작성
  전체 완료 + 검증(아래 Verification) 통과 시:
    → .part 를 <basename>_ko_audio_brief.md 로 atomic rename (mv)
    → <basename>_ko_audio_brief.meta.json sidecar 기록
실패 시:
  최종 _ko_audio_brief.md 를 만들지 않는다. .part 와 실패 사유만 남긴다.
```

**Legacy completion validation (해설판 소스 완료 판정):**
`paper-explainer` does NOT write a completion marker, and existing `_ko_explained.md` files have none. So do **NOT** require a marker on the explainer source. Judge it complete when ALL hold:
- `_ko_explained.md` exists and is non-empty
- has a title / real body content (not a stub)
- heading coverage vs the upstream source is reasonable (no large truncation)
- major sections present (References / 감사의 글 etc. may be absent — that's fine)

If it fails this, (re)run `paper-explainer` first.

### Skip / regeneration

```text
<basename>_ko_audio_brief.md (최종본) 존재 AND
  sidecar.status == "complete" AND
  sidecar 의 source 메타가 현재 _ko_explained.md 와 일치(최신)   → skip
그 외(.part만 존재 / sidecar 없음 / 소스가 더 최신·변경) → 재생성
```

- The completion metadata lives in the **sidecar**, never in the `.md` body.
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
- A lone `.part` is "incomplete" and must NEVER be treated as a finished file to skip.

### Batch mode (대상 미지정 시)

Inherit the `paper-explainer` batch rules and add audio conditions:
- Scan `outputs/` and `archives/` non-recursively. A directory is an **eligible paper folder** only if: name does NOT start with `.`, it contains a source MD, it is not empty/config/symlink.
- Exclusions: `_backup_`, `.bak`, `_mdlint_report.json`, and audio artifacts `*_ko_audio_brief.md`, `*.part`.
- Among folders whose `<basename>_ko_audio_brief.md` is missing (by completion-sidecar standard), pick the **single most recently updated source**. Treat "brief audio older than source" as a regeneration candidate.
- Sourceless/orphan folders: skip and list them in the completion report. **Never create, rename, or delete folders.**

## Conversion Rules — Audio Description

**Supreme rule: NO placeholders.** Never narrate just the element type ("수식입니다 / 그림입니다 / 표입니다"). Always convey *which* formula, *what* the figure shows, *what* the table says.

**Before converting, build a 낭독 사전 (pronunciation map):** collect model names, benchmarks, method names, and acronyms; decide one Korean spoken form for each, and apply it consistently throughout the whole document. 숫자·참조 번호 읽기 방침(규칙 9 — "그림 이 번" 형식, 단위별 한자어/고유어)도 함께 정해 일관 적용한다.

**분량 정책 적용 원칙:** 각 섹션을 변환하기 전에 §분량 정책의 5개 우선순위와 대조한다. 우선순위 4\~5에 해당하지 않는 세부 실험, 보조 ablation, 긴 증명/유도, 반복적 비교표는 **변환 전에 생략** 결정을 내린다. 포함할 요소만 아래 규칙으로 변환한다.

| # | 요소 | 규칙 |
|---|------|------|
| 1 | **수식** (`$$…$$`, 인라인 `$…$`) | placeholder 금지. **"이 수식은 ~를 ~로 계산한다는 뜻입니다"** 로 자연어 낭독. 해설판의 기존 수식 설명을 우선 활용, 없으면 맥락을 읽어 생성. 변수 기호는 한국어로 ("d는 임베딩 차원"). **축약판에서는 핵심 수식만 포함하고 나머지는 생략** |
| 2 | **표** (마크다운 `\|…\|`) — 유형별 | (a) glossary/비유/용어 표 → 문단 또는 목록으로 풀어 낭독. (b) **핵심 실험·성능 표 → 4\~8문장**으로 "최고 성능, 기준선 대비 차이, 예외, 대표 수치"를 반드시 포함해 서술 (1\~3문장 강제 요약 금지). 셀·`\|`·`<br>`·표 안 수식은 자연어로 풀되 핵심 수치는 보존. **축약판에서는 주 결과 표 1\~2개만 포함, 보조 표는 생략** |
| 3 | **그림/이미지** (`![](…)`) | **이미지 구문은 유지(임베딩)** — 단 alt는 비워 `![](경로)` 형태로 둔다 (alt 텍스트는 raw TTS에서 읽힐 수 있으므로). 그리고 **기존처럼** 그림 바로 앞 본문에 **"그림 N 번은 ~를 보여줍니다"** 자연어 묘사를 함께 둔다 (캡션+본문 맥락 기반, 참조번호는 규칙#9). **축약판에서는 핵심 아키텍처/결과 그림만 포함, 보조·장식 그림은 생략** |
| 4 | **코드/프롬프트/알고리즘 블록** (` ``` `) | (a) 짧은 핵심 의사코드 → 단계별 자연어 목록. (b) 긴 prompt/log/code dump → "이 블록은 ~용 프롬프트로, ~순서로 구성됩니다"처럼 목적·구조를 설명하고 재현에 필요한 핵심 문구만 낭독 친화적으로 발췌. (c) raw appendix 성격이면 "듣기판에서는 구조와 핵심만 설명했다"고 명시. **축약판에서는 방법 직관을 전달하는 경우만 포함** |
| 5 | **인용·링크** (`[1]`, `(Author, 2023)`, `[text](#anchor)`) | citation marker 제거. 선행 연구 비교가 의미를 갖는 문장은 "기존 연구들"/"저자들이 비교한 선행 방법"으로 자연어화 |
| 6 | **각주** (`<sup>N</sup>` 및 Markdown footnote `[^1]` / `[^1]: …`) | 각주 표식 제거. **각주 본문이 실험 조건·예외·데이터셋 설명이면 해당 문단에 자연어로 병합**, 순수 서지 정보면 삭제 |
| 7 | **영어 용어/약어** | 첫 등장: **"대규모 언어 모델(LLM, 엘엘엠)"** 음차 병기 → 이후 한국어 용어. 약어는 낭독 사전대로 음차 ("RoPE → 로프", "MoE → 모이"). 고유명사·모델명은 자연스러운 음차. **괄호 안에 영어만 두지 않는다** — 괄호를 쓰면 반드시 한글 음차를 함께 넣고(`(LLM, 엘엘엠)`), 그게 아니면 괄호 없이 음차만 남긴다(`셰어지피티(ShareGPT)` ❌ → `셰어지피티` ✅). 특히 낭독 사전에 없는 고유명사·모델명·지표명(ShareGPT, MemoryOS, GPT-5, F1 등)은 음차로만 적고 `(영어)`를 붙이지 않는다 — raw TTS가 괄호 영어를 그대로 읽어 중복·오독이 생긴다 |
| 8 | **문어체·만연체** | 긴 문장을 분할하고 능동·구어체("~합니다")로. 귀로 한 번에 이해되도록 |
| 9 | **숫자·참조 번호** (오독 위험만) | 모든 숫자가 아니라 **오독 위험만** 한글로. 참조번호 `그림 N`→"그림 이 번"(한자어+`번`, 동음 '그림이' 회피·라벨 ID 보존), 문서구조번호 `2장`→"제이 장"·`3.1절`→"제삼 점 일 절"(`제`+한자어, 동음 '이 장≈this'·'사 장≈사장' 회피), 고유어 분류사 `3개`→"세 개"·`2시간`→"두 시간", 모델명 음차 `GPT-4`→"지피티 포", 소수·범위·퍼센트. **우선순위·단위별 체계·변형(suffix/복수/순서/제-접두사)은 아래 §변환 예시의 "숫자·참조 번호" 표 참조** |

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

`제`는 **구조 단위(장/절/항/chapter/section)와 결합할 때만** 붙인다. 구조 단위가 없는 소수·실험 번호에는 붙이지 않는다 — 예: "3.1의 결과"는 "제삼 점 일의 결과"가 아니라 "삼 점 일의 결과" (또는 맥락상 "제삼 점 일 절의 결과"가 맞으면 절을 명시). 실제 등장 순서를 말할 때는 서수형(`두 번째`, `세 번째`)을 쓴다.

### 제거 대상 (듣기 무가치 — 통째 삭제)

- 목차(점선 `. . . .` + 페이지번호)
- 페이지 마커 / `<span id="page-…">` / 기타 HTML 앵커
- 저자 소속줄, 이메일, URL
- 학회 푸터 ("Proceedings of the … Copyright …")
- 참고문헌(References / Bibliography) 목록 섹션 전체
- 감사의 글(Acknowledgements)

## Output Format

- 경로/파일명: `<basename>_ko_audio_brief.md` (작성 중 `<basename>_ko_audio_brief.md.part`)
- **YAML 헤더 없음 (기본값).** raw 마크다운을 직접 TTS에 넣는 경로도 지원해야 하므로 front matter를 두지 않는다 (`lang: ko` 한 줄조차 — 불완전 YAML이거나 낭독될 수 있음). 언어 메타가 필요하면 sidecar에 둔다. HTML로 듣고 싶으면 사용자가 `md-to-html` 변환 단계에서 front matter를 주입하는 것을 전제로 한다.
- 제목: `# <원제목> — 듣기 축약판`
- **배너 blockquote 넣지 않는다 (기본값).** "이 글은 듣기용으로 다듬은 축약 낭독판입니다…" 류의 변환 안내 문구는 매 파일 반복되면 지겹고 낭독 시작을 늦춘다. 제목(`— 듣기 축약판`)만으로 축약 변환본임이 충분히 드러나므로, 제목 바로 다음에는 본문(첫 섹션)으로 들어간다. 사용자가 명시적으로 요청할 때만 한 줄 안내를 넣는다.
- **도입부 상투구 금지.** 글의 출처·성격을 소개할 때 **"학술 논문이라기보다는 ~에 가깝습니다"** 류의 정형 대비 문구를 반복하지 않는다 (여러 파일에서 똑같이 반복되어 거슬린다). 출처·저자·장르 소개가 필요하면 한 번만, 매번 다른 표현으로 자연스럽게 녹인다. 굳이 "논문이 아니라 ~"로 대비시키지 말고, 필요하면 그것이 무엇인지(블로그·에세이·기술 보고서 등)만 짧게 밝히거나 곧장 내용으로 들어간다.
- **마무리 한 줄 (필수).** 본문 맨 끝에 낭독이 끝났음을 알리는 짧은 마무리 문장 한 줄을 둔다 (들을 때 끝을 알 수 있도록). 예: "여기까지가 이 글의 듣기 축약판이었습니다." / "이상으로 축약 낭독을 마칩니다." 한 문장이면 충분하고 길게 늘어놓지 않는다. 매번 똑같은 문구가 되지 않도록 표현은 적절히 바꾼다.
- **섹션 구조**: §분량 정책의 5개 우선순위에 따라 섹션을 선택·통합. 생략한 섹션은 출력에서 완전 제거 (생략 안내 문구도 넣지 않는다).
- **본문에 메타데이터/HTML comment 금지** — 완료 메타는 sidecar에만
- 마크다운만 (HTML 태그·뷰어 연동 없음). **단 그림은 예외** — 의미 있는 figure 는 `![](경로)` 이미지 구문(**alt 비움, 논문 폴더 내부 상대경로만** — `http(s)://`·절대경로·`../` 금지)으로 임베딩하고, 그 앞 1문단 안에 자연어 묘사를 둔다. 이 임베딩은 **렌더링 경로(뷰어/HTML) 기준 기능**이다 — 거기선 그림이 보이고 TTS는 이미지를 건너뛴다. raw 마크다운을 그대로 TTS에 넣으면 파일명이 읽힐 수 있으니, **raw 낭독만 쓰고 그게 거슬리면 이미지 구문을 생략(묘사만 유지)해도 된다** (기본값은 임베딩 유지)

## Modes / Operational Stability

paper-explainer 운영 정책 계승:
- **Auto 모드**: 전체 자동 변환, 섹션 순차 처리.
- **Section-safe 모드**: 긴 논문은 `.part` 파일에 섹션별 append 저장, 중단 시 다음 턴에 이어쓰기. 전체 완료·검증 후에만 최종본으로 atomic rename.
- **TUI 신뢰성**: 파일 읽기/쓰기 권한 프롬프트는 Yes / "allow all" 우선, 마이크로 확인 루프 회피.
- **Quality-first wait**: `Actioning…` / `Actualizing…` 류 상태로 중단 판단 금지. TUI에서는 최소 30분 대기 후에야 stall로 본다.

## Verification

### 변환 전 — Source Inventory 작성
소스(`_ko_explained.md`)에서 기록:
- 헤딩 목록 (→ §분량 정책 기준으로 포함/생략 결정 미리 수립)
- 포함할 핵심 표 목록 (주 결과 1\~2개만)
- 포함할 핵심 그림 목록 (아키텍처·주 결과 그림만)
- 포함할 수식 목록 (방법 직관 전달에 필수인 것만)
- 코드 fence 개수 (포함 대상 결정)
- 각주 개수 (`<sup>` 및 Markdown `[^...]`)

### CRITICAL (반드시 통과)
- [ ] 출력에 다음이 **0건** (grep):

```bash
grep -nE '\$\$|\$[^$]+\$|\\\(|\\\[|^\s*\|.*---|^```|\[[0-9]+\]|\[\^|<sup|<span|<br|</?[a-zA-Z]|\]\(#|https?://' "<basename>_ko_audio_brief.md"
```
  (수식 블록·인라인 수식·표 구분선·code fence·`[N]`인용·Markdown footnote·HTML 태그·앵커 링크·bare URL)
  — **그림 이미지 `![](경로)` 는 의도적으로 허용**하므로 grep 패턴에서 제외했다.
- [ ] **alt 있는 이미지가 0건** (alt는 반드시 비워야 함 — alt 텍스트는 raw TTS에서 읽힘):

```bash
grep -nE '!\[[^]]+\]\(' "<basename>_ko_audio_brief.md"
```
  허용되는 이미지는 `![](상대경로)` 뿐이며, 경로는 논문 폴더 내부 상대경로여야 한다 (절대경로·`../`·URL 금지). **title 문법 `![](경로 "title")` 도 금지** — title 텍스트가 raw TTS에서 읽힌다.
- [ ] **분량 정책 준수**: 출력이 ~7,000자 이하인가 (`wc -m` 기준). 초과 시 더 압축해 재작성한다.
- [ ] **항목별 대응**: 포함하기로 결정한 표·그림·수식이 출력에서 자연어 문장으로 대응됐는가 (포함 대상 누락 차단). 임베딩된 그림은 **묘사 문장이 이미지 줄 바로 앞 1문단 안에** 있어야 한다.
- [ ] **섹션 coverage**: §분량 정책 5개 우선순위(문제의식·기여·방법 골자·핵심 결과·한계)가 모두 출력에 존재

### Important
- [ ] 표본 3개 섹션에서 수식·표·그림·코드가 placeholder가 아닌 **의미 있는 서술**로 변환됐는가
- [ ] 핵심 실험 표에서 대표 수치가 보존됐는가
- [ ] 영어 약어가 첫 등장 시 음차 병기 + 낭독 사전 일관 적용
- [ ] **괄호 안에 영어만 든 표기가 0건** (`한글(English)` 금지 — 음차 병기 `(LLM, 엘엘엠)`만 허용, 고유명사·모델명·지표명은 음차로만)
- [ ] 참조 번호가 "그림 N 번 / 표 N 번 / 식 N 번" 형식, 문서구조번호가 "제N 장 / 제N 절"(제+한자어) 형식, 단위별 한자어/고유어 구분(세 개·두 시 등)이 맞는가 (오독 위험만 변환, 일반 숫자 강제 변환 아님)
- [ ] 최종 파일명이 `..._ko_audio_brief.md`, sidecar `_ko_audio_brief.meta.json`에 `status=complete` + freshness(mtime/size/sha256)
- [ ] 최종 `.md` 본문에 메타데이터/HTML comment가 없음 (순수 낭독 텍스트)
- [ ] YAML 헤더 없음
- [ ] 도입부에 "학술 논문이라기보다는" 류 정형 대비 상투구가 없고, 본문 맨 끝에 낭독 종료를 알리는 짧은 마무리 한 줄이 있는가

## Completion Report

완료 시 간결히 보고:
- 입력 파일(소스 해설판) / 출력 파일(`..._ko_audio_brief.md`) 경로
- Phase 1 발생 여부 (해설판을 새로 생성했는가)
- 출력 분량 (자 수, `wc -m` 기준) / 목표 분량 ~7,000자 대비
- CRITICAL grep 0건 통과 여부
- 생략한 주요 섹션 목록 (§분량 정책 기준)
- (Batch) 건너뛴 소스 없는 고아 폴더 목록(있으면)
- 특이사항 (긴 표/코드 처리, OCR 노이즈 등)
