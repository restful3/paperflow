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

- ❌ FORBIDDEN: "수식이 있습니다", "그림 2가 있습니다", "표 1이 있습니다" (announcing the element type only)
- ✅ REQUIRED: "이 수식은 어텐션 점수를, 쿼리와 키를 곱한 뒤 차원의 제곱근으로 나눠 구한다는 뜻입니다", "그림 2는 샘플 수가 늘수록 정확도가 완만히 오르다 20개 부근에서 평평해지는 곡선을 보여줍니다", "표 1을 요약하면, ReAct가 두 작업 모두에서 행동전용 방식보다 점수가 높았습니다"

Other principles:
- **완전 낭독판**: never condense. Every section/subsection of the source appears in the output. Removing only happens for §"제거 대상" (listen-worthless) items.
- **항상 해설판 기반**: the source is always the explainer (`_ko_explained.md`). The translation (`_ko.md`) is only the explainer's input, never a direct source. If no explainer exists, generate one first (see Lifecycle).

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
Phase 1 — 해설판 확보:
  _ko_explained.md 없음 OR legacy completion validation 실패
    → paper-explainer 스킬을 실행해 _ko_explained.md 생성·완료
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

If it fails this, (re)run `paper-explainer` first.

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
- A lone `.part` is "incomplete" and must NEVER be treated as a finished file to skip.

### Batch mode (대상 미지정 시)

Inherit the `paper-explainer` batch rules and add audio conditions:
- Scan `outputs/` and `archives/` non-recursively. A directory is an **eligible paper folder** only if: name does NOT start with `.`, it contains a source MD, it is not empty/config/symlink.
- Exclusions: `_backup_`, `.bak`, `_mdlint_report.json`, and audio artifacts `*_ko_audio.md`, `*.part`.
- Among folders whose `<basename>_ko_audio.md` is missing (by completion-sidecar standard), pick the **single most recently updated source**. Treat "audio older than source" as a regeneration candidate.
- Sourceless/orphan folders: skip and list them in the completion report. **Never create, rename, or delete folders.**

## Conversion Rules — Audio Description

**Supreme rule: NO placeholders.** Never narrate just the element type ("수식입니다 / 그림입니다 / 표입니다"). Always convey *which* formula, *what* the figure shows, *what* the table says.

**Before converting, build a 낭독 사전 (pronunciation map):** collect model names, benchmarks, method names, and acronyms; decide one Korean spoken form for each, and apply it consistently throughout the whole document.

| # | 요소 | 규칙 |
|---|------|------|
| 1 | **수식** (`$$…$$`, 인라인 `$…$`) | placeholder 금지. **"이 수식은 ~를 ~로 계산한다는 뜻입니다"** 로 자연어 낭독. 해설판의 기존 수식 설명을 우선 활용, 없으면 맥락을 읽어 생성. 변수 기호는 한국어로 ("d는 임베딩 차원") |
| 2 | **표** (마크다운 `\|…\|`) — 유형별 | (a) glossary/비유/용어 표 → 문단 또는 목록으로 풀어 낭독. (b) **핵심 실험·성능 표 → 4\~8문장**으로 "최고 성능, 기준선 대비 차이, 예외, 대표 수치"를 반드시 포함해 서술 (1\~3문장 강제 요약 금지). 셀·`\|`·`<br>`·표 안 수식은 자연어로 풀되 핵심 수치는 보존 |
| 3 | **그림/이미지** (`![](…)`) | 이미지 구문 제거. **"그림 N은 ~를 보여줍니다"** 로 무엇을 나타내는지 묘사 (캡션+본문 맥락 기반). 순수 장식 이미지는 제거 |
| 4 | **코드/프롬프트/알고리즘 블록** (` ``` `) | (a) 짧은 핵심 의사코드 → 단계별 자연어 목록. (b) 긴 prompt/log/code dump → "이 블록은 ~용 프롬프트로, ~순서로 구성됩니다"처럼 목적·구조를 설명하고 재현에 필요한 핵심 문구만 낭독 친화적으로 발췌. (c) raw appendix 성격이면 "듣기판에서는 구조와 핵심만 설명했다"고 명시 |
| 5 | **인용·링크** (`[1]`, `(Author, 2023)`, `[text](#anchor)`) | citation marker 제거. 선행 연구 비교가 의미를 갖는 문장은 "기존 연구들"/"저자들이 비교한 선행 방법"으로 자연어화 |
| 6 | **각주** (`<sup>N</sup>` 및 Markdown footnote `[^1]` / `[^1]: …`) | 각주 표식 제거. **각주 본문이 실험 조건·예외·데이터셋 설명이면 해당 문단에 자연어로 병합**, 순수 서지 정보면 삭제 |
| 7 | **영어 용어/약어** | 첫 등장: **"대규모 언어 모델(LLM, 엘엘엠)"** 음차 병기 → 이후 한국어 용어. 약어는 낭독 사전대로 음차 ("RoPE → 로프", "MoE → 모이"). 고유명사·모델명은 자연스러운 음차 |
| 8 | **문어체·만연체** | 긴 문장을 분할하고 능동·구어체("~합니다")로. 귀로 한 번에 이해되도록 |

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
> "표 1은 네 방법의 성능을 비교합니다. HotpotQA에서는 ReAct와 사고사슬을 결합한 방식이 가장 높은 35.1점을 기록했고, 표준 프롬프팅은 28.7점에 그쳤습니다. Fever에서도 결합 방식이 64.6점으로 가장 높았습니다. 다만 지도학습 기반 최고 성능(67.5점, 89.5점)에는 아직 못 미칩니다."

**그림 (규칙 3):**

> 원본: `![](_page_4_Figure_2.jpeg)` + "그림 2: 사용된 CoT-SC 샘플 수에 따른 PaLM-540B 결과"
> 낭독판:
> "그림 2는 자기일관성 기법에서 샘플 수를 늘릴 때 성능이 어떻게 변하는지 보여줍니다. 샘플이 많아질수록 정확도가 오르지만, 일정 수를 넘으면 개선 폭이 완만해집니다."

### 제거 대상 (듣기 무가치 — 통째 삭제)

- 목차(점선 `. . . .` + 페이지번호)
- 페이지 마커 / `<span id="page-…">` / 기타 HTML 앵커
- 저자 소속줄, 이메일, URL
- 학회 푸터 ("Proceedings of the … Copyright …")
- 참고문헌(References / Bibliography) 목록 섹션 전체
- 감사의 글(Acknowledgements)

## Output Format

- 경로/파일명: `<basename>_ko_audio.md` (작성 중 `.part`)
- **YAML 헤더 없음 (기본값).** raw 마크다운을 아이폰에서 직접 듣는 것이 기본 경로이므로 front matter를 두지 않는다 (`lang: ko` 한 줄조차 — 불완전 YAML이거나 낭독될 수 있음). 언어 메타가 필요하면 sidecar에 둔다. HTML로 듣고 싶으면 사용자가 `md-to-html` 변환 단계에서 front matter를 주입하는 것을 전제로 한다.
- 제목: `# <원제목> — 듣기판`
- 배너 blockquote(선택): 이 문서가 듣기용 변환본임을 1\~2줄 안내
- **소스 섹션 구조 유지** — 완전 낭독판이므로 섹션·소절 누락 금지 (제거 대상 섹션 예외)
- **본문에 메타데이터/HTML comment 금지** — 완료 메타는 sidecar에만
- 마크다운만 (HTML·뷰어 연동 없음)

## Modes / Operational Stability

paper-explainer 운영 정책 계승:
- **Auto 모드**: 전체 자동 변환, 섹션 순차 처리.
- **Section-safe 모드**: 긴 논문은 `.part` 파일에 섹션별 append 저장, 중단 시 다음 턴에 이어쓰기. 전체 완료·검증 후에만 최종본으로 atomic rename.
- **TUI 신뢰성**: 파일 읽기/쓰기 권한 프롬프트는 Yes / "allow all" 우선, 마이크로 확인 루프 회피.
- **Quality-first wait**: `Actioning…` / `Actualizing…` 류 상태로 중단 판단 금지. TUI에서는 최소 30분 대기 후에야 stall로 본다.

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
- [ ] 출력에 다음이 **0건** (grep):

```bash
grep -nE '\$\$|\$[^$]+\$|\\\(|\\\[|^\s*\|.*---|^```|!\[\]?\(|\[[0-9]+\]|\[\^|<sup|<span|<br|</?[a-zA-Z]|\]\(#|https?://' "<basename>_ko_audio.md"
```
  (수식 블록·인라인 수식·표 구분선·code fence·이미지·`[N]`인용·Markdown footnote·HTML 태그·앵커 링크·bare URL)
- [ ] **항목별 대응**: Source Inventory의 각 표·그림·수식·인라인수식·코드·각주가 출력에서 자연어 문장으로 대응됐는가 (통째 누락 차단)
- [ ] **섹션 coverage**: 소스의 섹션 헤딩이 모두 출력에 존재 (제거 대상 섹션은 예외 목록으로 기록)

### Important
- [ ] 표본 3개 섹션에서 수식·표·그림·코드가 placeholder가 아닌 **의미 있는 서술**로 변환됐는가
- [ ] 핵심 실험 표에서 대표 수치가 보존됐는가
- [ ] 영어 약어가 첫 등장 시 음차 병기 + 낭독 사전 일관 적용
- [ ] 최종 파일명이 `..._ko_audio.md`, sidecar `_ko_audio.meta.json`에 `status=complete` + freshness(mtime/size/sha256)
- [ ] 최종 `.md` 본문에 메타데이터/HTML comment가 없음 (순수 낭독 텍스트)
- [ ] YAML 헤더 없음

## Completion Report

완료 시 간결히 보고:
- 입력 파일(소스 해설판) / 출력 파일(`..._ko_audio.md`) 경로
- Phase 1 발생 여부 (해설판을 새로 생성했는가)
- 변환된 섹션 수 / 소스 총 섹션 수
- CRITICAL grep 0건 통과 여부
- (Batch) 건너뛴 소스 없는 고아 폴더 목록(있으면)
- 특이사항 (긴 표/코드 처리, OCR 노이즈 등)
