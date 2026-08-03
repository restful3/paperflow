---
name: paper-explainer
description: Convert an academic paper (any language) into an easy Korean explainer with accurate technical preservation (formulas/citations/figures), consistent analogies, glossary, and section-by-section output to avoid token overflow. Use when user asks "쉽게 설명해줘", "해설판", "알기 쉽게 풀어줘", or requests a paper-specific Korean explainer from file/path/URL/title.
---

# Paper Explainer (Any Language → Korean Easy Explanation)

## When to Use

Use this skill when:
- User requests an easy-to-understand Korean explanation of an academic paper
- Input is a markdown-formatted academic paper in **any language** (English, Korean, German, Japanese, Chinese, etc.)
- User asks to rewrite a paper with analogies, plain language, or accessible explanation
- User uses phrases like "쉽게 풀어써줘", "해설판 만들어줘", "논문 쉽게 설명해줘", "알기 쉽게 다시 써줘"

**This is NOT a translation skill.** The paper-translator-korean skill produces academic Korean. This skill produces **conversational, enriched Korean with analogies and explanations** — the output should be **richer in explanation** than the input: it covers every point of the original AND adds plain-language explanation, context, and intuition. "Richer" means *more explanation*, NOT *more words for their own sake* — see Rule 0. Restating the same content in different words is duplication, not enrichment.

**Input language handling:**
- If input is already Korean: skip translation, go directly to rewriting
- If input is in another language: translate AND explain simultaneously (no separate translation step)

**Default behavior: Full paper rewrite in one go**
- Rewrite the entire paper automatically without user approval
- Process all sections sequentially without asking for confirmation
- DO NOT summarize or omit — the output must contain ALL original content, explained more richly

## Codex 환경 (플랫폼 노트)

이 스킬은 Codex(배치 기본 모델 gpt-5.6-sol; `codex exec -m` 으로 바뀔 수 있다)에서 구동된다.
**품질 규칙(9 Rules·Step-by-Step·Quality Checks·분량 진단)은 Claude 판과 동일**하며, 아래 플랫폼 항목만 Codex 에 맞춘다.

- **자수 측정**: `wc -m < "$file"` — Codex 는 `/usr/bin/wc` 이고 rtk 훅이 없다(Claude 판의 `rtk proxy wc -m` 우회는 불필요). **`LC_ALL=C` 로 실행 금지** — 바이트 수가 되어 자수가 틀어진다. locale 은 `C.UTF-8` 유지.
- **그림 판독(vision)**: Codex 는 `view_image` 로 로컬 그림 파일을 판독할 수 있다. Quality Checks 의 **"이미지 전사"** 게이트(이미지로만 존재하는 표·차트를 텍스트로 옮기기)는 **실물 파일을 여는 것이 기본**이다 — 캡션·파일명 대응이 틀릴 수 있으므로 파일명만 믿지 마라. vision 이 실패하면 캡션+본문의 **공통 확정사항만** 서술하고 완료 보고에 "미확인 그림"으로 플래그한다. 어느 경우에도 날조 금지(Rule 1).
  - 경제 데이터 차트는 축 단위 오독(€bn→"억" 10배 축소)이 실제로 나온 오류다. 축 라벨을 먼저 읽고 단위를 확정한 뒤 수치를 옮긴다.
- **파일 쓰기**: 섹션은 `apply_patch` 로 `<basename>_ko_explained.md.part` 에 append 하고, 전체 완료·검증 후 `mv` 로 최종본에 atomic publish 한다(셸 redirection 통짜 덮어쓰기 지양). 기존 산출물이 있으면 `.bak-<timestamp>` 로 백업한 뒤 교체한다.
- **완료 신호**: Codex 에는 `Actioning…` 같은 진행 상태 문자열이 없다. **진행**은 프로세스 생존·`--json` JSONL 이벤트로 관찰하고, **완료**는 `codex exec` 정상 종료(코드 0) + 검증 통과 + 산출물 존재로 판정한다 — 프로세스 생존 자체는 완료 근거가 아니다. 성급히 stall 로 단정하지 않는다.
- **스킬 발견/호출**: 신규 심링크는 **새 세션에서만** 발견된다(hot reload 없음). 배치는 이 스킬을 `$paper-explainer` 로 명시 호출한다(description 추론에 의존하지 않는다).
- **검증기**: 정적 게이트는 직접 grep 하지 말고 리포 루트의 `scripts/verify_explainer.py` 를 쓴다. 배치는 `-C <repo>` 이므로 `python3 scripts/verify_explainer.py <파일>` 상대경로로 동작하고, 다른 cwd 에서는 `"$(git -C <paper_dir> rev-parse --show-toplevel)"/scripts/verify_explainer.py` 로 리포 루트를 붙여 호출한다.
  - 판정 3단계: `FAIL`(자동 반려·exit 1) / `REVIEW`(사람 확인 필요하나 반려 아님·exit 0) / `PASS`(exit 0). `--strict` 는 REVIEW 도 exit 1.
  - 이 스크립트는 **자동화 가능한 정적 게이트만** 본다(문체·인접 중복·정형 마커·웹 잡동사니·분량비·이미지 참조 보존). 섹션별 coverage·비유 적절성·수식 정확성·차트 전사 내용은 아래 Quality Checks 에서 별도 확인한다.

## Execution Modes

### 실행 모델 — 논문별 fresh 세션 순차 (Codex 배치 기본값)

**배치·재생성은 셸 오케스트레이터가 논문 하나씩 fresh `codex exec` 로 순차 실행하는 것이 기본값이다** (한 대화에 여러 긴 논문을 누적하면 compaction·논문 간 오염이 생긴다 — 해설판은 비유 체계가 논문마다 달라 오염 피해가 특히 크다):

- 논문 내부만 `.part` 에 섹션별로 기록하고, 다음 논문은 **새 세션**에서 시작한다.
- 크론/비대화형 실행은 `codex exec -C <repo> -s workspace-write -c 'approval_policy="never"'` 형태로 돌리고, 출력(논문) 폴더가 writable root(`-C`, 필요 시 `--add-dir`)에 포함되게 한다. 프롬프트에는 이 스킬을 `$paper-explainer` 로 명시한다.
- 각 세션 프롬프트에는 이 SKILL.md **전체를 읽게 한다** (요약본 금지 — 규칙 누락의 원인).
- **기존 산출물을 열람하지 않는다** (구버전 결함 학습 방지). 소스 MD·`paper_meta.json`·그림 파일만 읽는다.
- `spawn_agent` 병렬 위임은 **기본이 아니다** — 이 인터페이스에는 model/agent 타입 선택 인자가 없어 워커 타입을 고정할 수 없고, 실익은 벽시계 시간뿐이다. 쓰더라도 논문·run 별 임시 파일로 완전히 분리하고 최종 publish·검증은 부모가 직렬화한다.
- 게이트 실패·의심 건은 publish 하지 않고 실패로 남긴 뒤, 별도 fresh remediation 세션에서 재실행·감사한다. 우선 확인할 오류 패턴: **차트 축 단위 오독(예: €bn→"억" 10배 축소), 동아시아 인명 로마자 한글 음차 추정, 소스 풀쿼트 중복 이월** — 세션 프롬프트에 금지 조항으로 명시한다.
- 통과분만 폴더에 반영한다 — 구본은 `.bak-<timestamp>` 백업.
- **단건 대화형 요청은 현재 세션이 직접 처리해도 된다.**

### Auto Mode (default)
- Process the entire paper automatically
- For long sections, automatically split into subsection-level chunks

### 승인/샌드박스 · 대기 정책 (Codex)
- 비대화형은 `-s workspace-write -c 'approval_policy="never"'` (`codex exec` 에는 `-a/--ask-for-approval` 플래그가 없다). `--dangerously-bypass-approvals-and-sandbox` 는 외부 격리가 확실할 때만 — 이 호스트는 bwrap(user namespace) 불가라 배치 lane 이 이 경로를 쓴다.
- 긴 논문은 수십 분이 걸린다. **진행 중인 세션을 성급히 죽이지 않는다** — 프로세스 생존·JSONL 이벤트로 진행을 확인하고, 판단은 mode timeout(lane 이 강제)에 맡긴다.

### Section-safe Mode
- Automatically enters this mode when:
  - Very long documents (estimated 30+ pages)
  - A single section is abnormally long with token overflow risk
- Saves section-by-section sequentially so mid-failure recovery is possible
- If you hit the token limit mid-section:
  1. Save what you've written so far
  2. Continue from where you left off in the next turn
  3. Append seamlessly to the file

**Recommended section budgeting for very long papers:**
```
- Abstract (short — process at once)
- Introduction (medium — process at once)
- Related Work (can be long — process per subsection)
- Methods (can be very long — process per subsection)
- Experiments (includes tables/results — process per subsection)
- Conclusion (short — process at once)
- Glossary (generate last)
```

## Pre-processing

### 1. Language Detection
- Auto-detect the source language of the input file
- Korean input → proceed directly to analysis and rewriting
- Non-Korean input → apply OCR cleaning first, then rewrite with translation

### 2. OCR Artifact Cleaning (for non-Korean or OCR-derived input)
Papers converted from PDF via OCR or marker-pdf may contain noise:
- **Page numbers**: "Page 5", "5", "- 5 -", standalone numbers at top/bottom
- **Running headers/footers**: Author names, journal names, conference names repeated on pages
- **Copyright notices**: "© 2023 IEEE", "All rights reserved"
- **DOI strings**: "DOI: 10.xxxx/xxxxx"
- **Hyphenation errors**: "compu-\nter" → "computer"
- **Meaningless line breaks**: Remove mid-sentence breaks, keep paragraph breaks
- **Author code blocks**: Remove triple backticks wrapping author `<sup>` tags

**Clean first, then rewrite.**

### 3. Web Source De-cluttering (웹 출처 광고·배너·프로모 제거)

When the source is a **web-scraped document** (file name starts with `web-`, or the body carries site navigation / marketing chrome), the original page often contains **non-content clutter that is NOT part of the article**. Strip these out BEFORE rewriting — they must NEVER appear in the explainer:

- **광고/배너**: "Advertisement", "Sponsored", "AD", 제휴·프로모 배너, 애드센스/쿠팡류 삽입 블록
- **구독/뉴스레터 유도**: "Subscribe", "Sign up", "뉴스레터 구독", "구독하기", 이메일 입력 폼
- **쿠키/동의 배너**: "We use cookies", "쿠키 동의", privacy/consent 팝업 문구
- **소셜/공유 위젯**: "Share this", "Follow us", "팔로우", 좋아요·공유 버튼, SNS 아이콘 링크
- **사이트 네비게이션/푸터**: 상단 메뉴, 사이드바, "Home / About / Contact", 저작권 푸터, 사이트맵 링크
- **추천/관련 콘텐츠 유도**: "Related articles", "관련 기사", "You may also like", "Read more", "더 보기", 다른 글 썸네일 목록
- **저자 홍보 CTA**: 책 구매 링크, 강의 모집, 제품 판매 등 본문과 무관한 마케팅 문구
- **광고성 이미지**: 본문 설명과 무관한 배너/프로모 이미지(`![](...)`)는 제거. 단, 본문을 설명하는 figure/diagram/screenshot 이미지는 Special Considerations 규칙대로 **보존**

**Judgment rule (content vs. chrome)**: 저자의 실제 글(본문 텍스트, figure, 표, 코드, 인용)에 속하면 **보존**하고, *웹사이트의* 가구(선전·유도·탐색용 요소)면 **제거**한다. 이미지가 본문 설명용인지 프로모 배너인지 불확실하면, 의미 있는 캡션이 달린 콘텐츠 이미지는 남기고 장식·마케팅 배너는 버린다.

## Core Rewriting Principles — 9 Rules

### 독자 수준 가정 (Reader calibration) — 모든 규칙에 우선 적용

해설판의 독자는 **이공계 학부 이상의 소양을 갖춘 성인** (공학·경제의 기본 개념에 익숙) 이라고 가정한다. "전문지식이 전혀 없는 일반인" 이 아니다.

- **자명한 기초는 풀어 설명하지 않는다.** 백분율·평균·그래프 축·GDP·금리·표준편차·p-값·기울기(gradient) 같은 학부 교양 수준 개념은 그대로 쓴다. 정의를 덧붙이거나 비유로 풀면 오히려 거슬린다.
- **확장(Rule 0)의 예산은 "진짜 어려운 부분" 에 쓴다.** 분량은 쉬운 내용을 부풀려서가 아니라, 핵심 아이디어·수식·방법의 직관을 깊게 설명해서 확보한다. 기초 개념 패딩으로 길이를 채우지 않는다.
- **같은 설명을 반복하지 않는다.** 한 개념·용어·맥락을 한 번 풀어 설명했으면, 뒤에서 다시 나올 때는 짧게 가리키기만 한다 ("앞서 설명한 X"). 섹션마다 같은 배경을 다시 깔거나 같은 비유를 매번 처음부터 다시 설명하지 않는다.
- **그러나 친절함은 유지한다 (과교정 주의 — 중요).** 소양 독자라고 무뚝뚝·압축적으로 쓰라는 뜻이 절대 아니다. 어조는 따뜻하게, 설명은 부드럽게 흐르게 하고, "왜 이게 중요한가" 의 맥락을 적절히 깔아준다. **그 분야 비전문가일 수 있는 개념(특정 세제·생소한 제도·논문 고유 기법·고유명사)은 한 번은 친절히 풀어준다.** 걷어내는 대상은 오직 (1) 학부 교양 수준의 자명한 기초, (2) 매체·출처 부연, (3) 같은 설명의 반복, (4) 기계적 비유 마커 — **친절한 설명 그 자체가 아니다.** 짧고 메마른 출력은 이 스킬의 실패다. 군더더기는 빼되, 읽는 사람이 끝까지 편하게 따라오도록 쓴다.

### Rule 0: Completeness, Never Omit — Not Length Padding (누락 절대 금지 — 단, 분량 채우기 아님)

**Completeness, accuracy, and non-duplication are CO-EQUAL hard rules. When they conflict with any length target, length loses.**

This skill produces a **해설판 (annotated commentary)**, NOT a summary. The output must cover the **entire original** — every point, in order — with added plain-language explanation. The supreme goal is **covering every point of the original exactly once and fully explained**, NOT making the text long.

**Hard constraints:**
- **Cover everything**: every section, subsection, paragraph, claim, number, causal link, and exception/caveat of the original appears in the output at least once. Nothing is dropped or compressed away.
- **Say it once**: do NOT state the same point twice. Restating content you already wrote — even in different words — is **duplication, a failure as serious as omission**. See the explicit ban below.
- **Length is a diagnostic, not a target.** A faithful, fully-explained 해설판 of a plain English article is often **0.8–1.6x** the source; denser/more-technical papers run longer. If the output is *shorter than the source body*, check for skipped content — but do NOT pad to hit a number.
- Every subsection in the original MUST appear — do NOT merge away or skip subsections (you MAY merge two very short adjacent paragraphs into one, as long as both their unique facts survive).
- "한눈에 보기", "핵심 요약", "방법 요약" style summary headings are **FORBIDDEN** as replacements for original section structure. They may only appear as **additions** alongside the full content.

> **단, 광고·배너·구독유도·쿠키 동의·사이트 네비게이션 등 본문이 아닌 웹 잡동사니는 "원문"에 포함되지 않는다** (Pre-processing의 *Web Source De-cluttering* 참조). 이런 요소를 제거하는 것은 누락이 아니다. coverage·길이 비교도 **잡동사니를 제거한 본문**을 기준으로 한다.

**🚫 The duplication ban (이번 결함의 직접 원인 — 반드시 지킨다):**
```
Do NOT write a faithful-translation paragraph followed by a separate
paragraph that re-says the same content in colloquial words.
The explanation must be INTEGRATED into a SINGLE pass.

WRONG (중복):  [원문을 충실히 옮긴 문단]  →  [같은 내용을 쉬운 말로 다시 푼 문단]
RIGHT (통합):  [원문 내용 + 풀이 + 맥락을 한 번에 녹인 한 문단]

- Expansion is valid ONLY when it adds NEW explanation, context, intuition,
  interpretation, or a glossed term — content not already stated.
- If a source paragraph is already plain (a simple claim, a raw statistic),
  the right output is ONE clear sentence/paragraph, NOT a translated copy
  plus a restated twin. There is nothing to "expand" — do not invent a twin.
```

**수치 재진술 금지 (같은 결함의 변형):** 원문 수치를 옮긴 직후 별도 문단으로 "이 숫자를 음미해 봅시다", "이 숫자들은 충격적입니다" 류의 환산·감탄을 붙이지 않는다. 환산·해석이 필요하면 수치를 제시한 **같은 문장/문단 안에** 짧게 흡수한다 (예: "6.8%포인트 — 월소득 100만 원당 7만 원꼴"). 수치마다 재진술 문단이 따라붙는 패턴은 전수 감사에서 반복 확인된 실측 결함이다.

**해석성 마감 에코 절제:** 문단 끝을 "정리하면/쉽게 말해/즉 … 셈입니다/뜻입니다/것입니다"로 마감하며 직전 내용을 재요약하는 습관을 금지한다. 이런 재요약형 마감은 문서 전체 **합계 5회 이하**로 유지하고, 쓸 때는 반드시 새 해석·인과를 더해야 한다 (순수 반복 마감은 0회).

**Paragraph-level mapping rule (문단 대응 원칙):**
```
Original paragraph → Explained paragraph(s)
- Every original paragraph's content appears in the output (NEVER dropped)
- 1 original paragraph usually maps to 1 integrated output paragraph;
  use 2+ ONLY when there is genuinely new explanation/intuition to add
- Do NOT force each output paragraph to be ≥ the original's length
- If a paragraph is purely technical, weave a plain-language explanation
  INTO the rewrite (not a separate before/after restatement paragraph)
- If a paragraph contains data/numbers, add interpretation in the same pass
```

**What to AVOID:**
- **Paraphrased duplication** — saying the same point twice in different words (THIS audit's defect)
- Replacing 5 paragraphs of methodology with a 3-bullet summary
- Skipping subsections because they seem "repetitive" or "minor"
- Writing "이 부분에서는 X를 다룹니다" instead of actually rewriting X
- Using the heading structure of a summary instead of the original's structure

**What "해설" (commentary) looks like — DO these patterns:**
- Keep the original's structure (section → subsection → paragraph) intact
- For each paragraph: rewrite in easy Korean **with** explanation/context/analogy woven in — one integrated pass, no translate-then-restate
- The result reads like a "professor's annotated version" of the full paper, not a cliff notes, and not the same point said twice

### Rule 1: Accuracy First (정확성 우선)
Enrichment must never distort the original.

- Do NOT add claims, data, or conclusions not present in the original paper
- Do NOT exaggerate or speculate — only explain what the authors actually wrote
- "Why this matters" context and analogies must faithfully represent the original content
- If uncertain about a technical detail, explain what the paper states rather than interpreting beyond it
- **저자 소개는 사실만**: 이름·소속·직함 등 원문/`paper_meta.json` 에 있는 정보만 쓴다. "세계적 석학", "~분야의 대가" 같은 소스 밖 평가·예찬을 덧붙이지 않는다 (실측 감사에서 해설판→축약판까지 전파된 결함)
- **원문 밖 비교·인과·최상급 금지**: 원문에 없는 수치 비교("일본 인구와 맞먹는"), 인과 부연("직관적으로 납득됩니다 — ~니까요"), 최상급 수식("최초로") 을 추가하지 않는다. 이해를 돕는 환산이 꼭 필요하면 원문 수치의 산술적 재표현(단위 환산)까지만 허용된다

### Rule 2: Tone Shift (어조 전환)
Transform academic passive voice into conversational, engaging Korean.

**Do:**
- Use active voice: "저자들은 ... 제안합니다" → "이 연구에서는 ... 를 만들었습니다"
- Address the reader: "여러분이...", "...해 보세요", "...라고 상상해 보세요"
- Ask rhetorical questions: "그런데 문제는 뭐였을까요?", "왜 이게 중요할까요?"
- Express enthusiasm for key insights: "특히 주목할 점은...", "놀라운 결과는..."
- Use conversational connectors: "쉽게 말해", "다시 말하면", "즉"

**Don't:**
- Use overly casual or slangy Korean (maintain respectful 합니다체)
- Lose academic precision — be accessible but accurate
- Add personal opinions not in the original paper
- Use excessive memes, slang, or translationese (번역투)

**🚫 문체 전환 강제 (해라체 상속 금지 — 신규 게이트):**
```
소스 `_ko.md` 가 뉴스·사설 번역 관례상 해라체("~다/~했다/~한다" 평서형)로
되어 있어도, 해설판 본문 서술은 반드시 대화체 합니다체로 전환한다.
소스의 해라체 어미를 그대로 상속하지 마라 — 이는 문체 위반이다.

- 본문 해설 문장: 합니다체 (예: "…드러났습니다", "…라는 뜻입니다")
- 예외(해라체·원문 그대로 허용): 인물의 직접인용("…라고 말했다"의 인용 내부),
  상단 배너 blockquote, 표 셀, 코드/수식.
- 소스가 한국어여도 "이미 쉬우니 그대로" 두지 말고, 어조는 합니다체로 재작성한다.
- 문서 말미의 저자 소개·에디터 크레딧 등 소스에서 통째로 복사되기 쉬운 블록도
  본문 서술이다 — 합니다체로 전환한다 (실측: 낭독판은 고쳤는데 해설판만 해라체 잔존).
```

### 한국어 평이 소스 모드 — 재진술 금지, 부가가치로 승부

소스 `_ko.md` 가 이미 전문 에디터가 다듬은 평이한 한국어 기사(HBR 코리아 등 국내 매체)라면 문장을 "쉽게 풀어쓸" 여지가 거의 없다. 이때 소스 문장에 볼드만 얹어 1:1 로 옮겨 쓰면 해설판은 원문의 복사본이 된다 (실측: 1.14x 재진술 감사 사례 — "원문을 읽는 편이 낫다"는 판정). 이 모드에서 해설판의 부가가치는 재진술이 아니라 다음에서 나온다:

1. **구조화**: 흩어진 사례·수치·개념을 매핑 표/목록으로 재조직 (예: 프레임워크 차원 × 대표 사례 × 성과 수치 표)
2. **개념의 배경 보강**: 글이 한 줄로 스친 학술 개념(자기결정성 이론 등)을 한두 문장 깊이로 보강 — 단 Rule 1 범위(일반적으로 확립된 정의 수준) 안에서
3. **이미지로만 존재하는 표·도표의 전사** (Special Considerations 의 이미지 전사 규칙)
4. **문체 통일**: 해라체 소스는 합니다체로 전환 (Rule 2)
5. **소스 내부의 긴장·함의 짚기**: 서로 긴장하는 대목이나 함의를 드러내되, 근거는 소스 안에서만

소스 문장을 그대로(또는 어미만 바꿔) 옮기는 것은 이 모드의 coverage 달성 수단이 아니다 — 내용은 전부 보존하되 **압축·재구성·해설 주석**으로 커버한다. 결과물이 소스보다 짧아져도 된다 (한국어 소스는 분량 하한 없음, Rule 0/Quality Checks 참조). 단 거의 모든 문장이 고유 사실(사례·수치)인 기사에서는 완전 커버 요구 때문에 자연 착지점이 0.9\~1.1x다 — **이 모드의 차별점은 길이가 아니라 부가가치 산출물(구조화 표·전사·배경 보강)의 존재**다.

### Rule 3: Analogies and Metaphors (비유/은유) — 절제해서, 자연스럽게

비유는 **정말로 직관이 안 잡히는 핵심 개념에만** 쓴다. 소양 있는 독자(위 "독자 수준 가정" 참조)에게는 비유 없이 정확한 설명이 더 빠를 때가 많다 — **비유가 없어도 된다.**

**개수:** 한 편당 **0\~3개** 의 핵심 비유면 충분하다. 문단마다 비유를 넣지 않는다. 기본값은 "비유할 거리가 마땅치 않으면 넣지 않는다." **작성 후 서로 다른 비유 소재를 실제로 세어라** — 4개 이상이면 실패이며, 가장 덜 중요한 것부터 삭제하거나 기존 비유로 통합한다 (실측 감사에서 6\~8개 남발이 반복 확인됨).

**좋은 비유 만들기:**
- 개념의 KEY PROPERTY를 포착한다
- 한번 세운 비유는 그 개념이 다시 나올 때 일관되게 이어간다 (새 비유를 난발하지 않는다)

**기계적 마커 금지 (중요).** "**비유로 설명하면 이렇습니다:**" 같은 **정형 도입 문구를 매번 붙이지 않는다.** 이 패턴이 반복되면 글이 기계적으로 읽히고 듣기판에서 특히 거슬린다. 비유는 별도 머리표 없이 문장 안에 자연스럽게 녹인다 (예: "…인데, 이는 X 와 같은 원리다"). 도입 표현이 필요하면 매번 다르게 쓰고, 한 해설판 안에서 같은 도입구를 반복하지 않는다. **"비유:"·"비유로 정리하면:" 같은 볼드 라벨, 비유 전용 blockquote 박스, "첫 번째/두 번째 핵심 비유"·"(개혁 1)/(개혁 2)" 류 번호형 스캐폴딩도 같은 위반이다 — 전부 금지.**

**비유 시스템 설계(쓸 때만).** 비유를 쓰기로 했다면 핵심 개념 몇 개에 일관된 비유를 미리 배정해 끝까지 같은 비유로 이어간다. 예: 계층적 메모리 → 단기=책상 위, 중기=서랍장, 장기=금고. 같은 개념에는 늘 같은 비유를 쓴다.

### Rule 4: Progressive Disclosure (점진적 공개)
Structure each section with a clear narrative arc.

**Overall paper structure:**
1. "무엇이 문제인가?" (What's the problem?)
2. "어떻게 해결했나?" (How was it solved?)
3. "얼마나 좋아졌나?" (How much better is it?)
4. Deep technical details (for each component)
5. Limitations and future work

**Per-section structure:**
- Open with "why this matters" context (even if original lacks it)
- Present the core content in accessible language
- Close with key takeaway or transition to next section

**소제목이 없는 평문 기사(칼럼·에세이)에는 논지 흐름을 따라 `##` 헤딩을 새로 달아도 된다** — 이는 Rule 0(원문 구조 유지)의 위반이 아니라 구조화 부가가치다 (원문에 있는 소제목은 물론 보존).

**Section headings should include a descriptive Korean subtitle:**
- `## 3장. MemoryOS의 구조 — 핵심 설계를 파헤치기`
- `### 4.3 제거 실험 — 어떤 부분이 가장 중요한가?`

### Rule 5: Math and Formula Handling (수식 해설)
Preserve ALL original formulas but wrap them with plain-language explanations.

**Pattern:**
1. **Before the formula**: Explain what it computes and why, in plain Korean
2. **The formula itself**: Preserve exactly as-is in LaTeX/math notation
3. **After the formula**: Break down each variable/symbol with a numbered list

**Example:**
```
히트 점수는 세 가지 요소를 합산합니다:

$$Heat = \alpha \cdot N_{visit} + \beta \cdot L_{interaction} + \gamma \cdot R_{recency}$$

각 요소를 풀어 설명하면:
1. **방문 횟수($N_{visit}$)**: 이 세그먼트가 검색에서 얼마나 자주 불려 나갔는가.
2. **상호작용 길이($L_{interaction}$)**: 세그먼트 안에 대화 페이지가 몇 개나 있는가.
3. **최신성($R_{recency}$)**: 마지막으로 접근된 게 얼마나 최근인가.
```

### Rule 6: Terminology Management (용어 관리)
**On first mention** of a technical term:
- **Bold** the Korean term
- Add English (or original language) in parentheses
- Provide a one-line plain-language definition
- Example: "**컨텍스트 윈도우(context window)**란 AI가 한 번에 읽고 기억할 수 있는 텍스트의 최대 분량입니다."

**On subsequent mentions**: Use the Korean term without re-defining.

**At the end of the document**: Generate a glossary table collecting ALL defined terms:
```markdown
## 핵심 용어 해설

| 용어 | 쉬운 설명 |
|------|----------|
| **LLM (대규모 언어 모델)** | ChatGPT처럼 텍스트를 이해하고 생성하는 거대한 AI 모델 |
| **컨텍스트 윈도우** | AI가 한 번에 읽고 기억할 수 있는 텍스트의 최대 분량 |
| ... | ... |
```

### Rule 7: Structural Reformatting (구조 재편)
Transform dense academic paragraphs into scannable, readable content.

- **Short paragraphs**: 3-5 sentences max (vs. academic 8-12 sentence paragraphs)
- **Bullet points**: Use for lists, comparisons, step-by-step processes
- **Numbered lists**: For sequential steps or ranked items
- **Horizontal rules** (`---`): Between major sections (chapters)
- **Blockquotes** (`>`): For the document banner and key example scenarios
- **Bold**: Key phrases and takeaways within paragraphs
- **Tables**: For comparing methods, summarizing results, or listing terms
- **White space**: Liberal use of blank lines between concept groups

### Rule 8: Content Enrichment (내용 보강)
The output must be richer in **explanation** than the input. Never omit or summarize — but never pad with restatement either (Rule 0 duplication ban).

**Add:**
- "Why this matters" introductions where the original jumps straight into details
- Concrete scenarios or case studies to illustrate abstract points
- Interpretation of experimental results (don't just show numbers — explain what they mean)
- Comparison context: "기존 방법 대비 49% 향상은 거의 절반 가까이 개선된 것이니 상당한 성과입니다"
- Transitions between sections explaining the logical flow

**Never remove:**
- Any section, subsection, or paragraph from the original
- Any formula, table, or figure reference
- Any citation or reference

> 여기서 "original"은 **저자의 실제 글 내용**을 뜻한다. 광고·배너·구독유도·쿠키 동의·소셜 위젯·사이트 네비게이션 등 웹 잡동사니는 original 이 아니므로 이 규칙의 보호 대상이 아니다 — 반드시 제거한다 (Pre-processing의 *Web Source De-cluttering* 참조).

**Priority: omission and duplication are BOTH failures — avoid both.**
- A summarized section has lost information forever; a duplicated section has padded with restatement (the defect this audit found). Neither is acceptable.
- When in doubt, add *new explanation* (context, intuition, a glossed term) — NOT more words restating what you already said.
- **Empty repetition — saying the same thing twice in different words — is forbidden** (Rule 0 duplication ban). Do not pad to look thorough. But equally, do NOT cut genuine content to look concise.
- Every paragraph of the original must be *covered* — its claims/numbers/caveats present once, fully explained. "Covered" ≠ "copied then restated."

## Step-by-Step Rewriting Process

**CRITICAL: Automatic full-paper rewrite without user approval!**

### Step 1: Analyze the Paper
- Read the entire input file
- Detect the source language
- **Note the source body size** (clutter-removed) as a *coverage* reference, not a length quota to beat
- Identify all sections and subsections — **list them so none is dropped**
- Map key concepts and their relationships
- Classify each section:
  - Content sections (intro, methods, experiments, etc.) → full rewrite
  - References/Bibliography → keep content in original language
  - Acknowledgements → keep content in original language (translate header only)
  - Appendix → classify as content vs raw data (see Step 7)

### Step 2: Design the Analogy System (only if needed)
Before writing, decide whether analogies are even warranted (Rule 3: **0–3 per paper**, default none if the concept needs no analogy):
- Identify any genuinely hard-to-intuit concepts (often 0–3)
- Assign a consistent everyday metaphor to each such concept
- Reuse the SAME metaphor when that concept reappears (do not invent new ones)
- Do NOT force an analogy onto every concept or every paragraph

### Step 3: Write the Title and Introduction Banner
- Transform the title: `# 원제목 — 쉬운 해설판`
- Add a blockquote banner:
  ```markdown
  > 이 글은 "논문 제목" 논문의 전체 내용을 빠짐없이 담되, 전문 용어와 개념을
  > 일상적인 비유와 풀어쓴 설명으로 재구성한 해설판입니다.
  ```
- 출처·저자 소개는 **최소화하고 많아야 1회** 만 한다 (배너나 첫 문단). **논문·기사는 배너 직후에 메타 한 줄을 둔다**: 저자·소속·발표처(학회/저널/매체명)·발표일 중 **원문이나 `paper_meta.json` 에서 확인되는 사실만** 한 줄로 (확인 안 되는 항목은 조용히 생략 — 지어내지 않는다; 파일명·이미지명에서 추정한 발행호 등은 "확인된 사실"이 아니다). 경력 예찬·"세계적 석학" 류 평가는 금지 (Rule 1).
- **매체·출처가 무엇인지 설명하지 않는다 (중요).** "The Economist 는 영국의 시사주간지로…", "이 매체는 …" 같은 매체 소개·출처 부연을 넣지 않는다. 소양 있는 독자는 매체를 안다. 출처를 밝힐 필요가 있으면 이름만 한 번 적고 (예: "이코노미스트 기사") 곧장 내용으로 들어간다. 단 **원문 본문 자체의 귀속 문장**("The Economist calculates" → "이코노미스트가 계산한 바로는")은 콘텐츠이므로 이 1회 카운트에 포함하지 않는다. 특히 이코노미스트 주간호처럼 여러 기사를 잇따라 해설할 때 매 기사마다 매체 설명을 반복하면 듣기판에서 매우 거슬린다.
- **도입부 상투구 자제**: 출처·저자·글의 성격을 소개할 때 **"학술 논문이라기보다는 ~에 가깝습니다"** 류의 정형 대비 문구를 쓰지 않는다 (여러 해설판에서 똑같이 반복되어 거슬리고, 듣기판으로도 그대로 옮겨진다). 글의 성격을 밝힐 필요가 있으면 "논문이 아니라 ~"로 대비시키지 말고, 그것이 무엇인지(블로그·에세이·기술 보고서 등)만 한 번 자연스럽게 언급하거나 곧장 내용으로 들어간다. 저자 소개도 매번 같은 틀로 시작하지 않는다.

### Step 4: Rewrite Each Section (with per-section verification)
For each section in the original paper:
1. **Count the original section's paragraphs and approximate length** (mental note)
2. Transform the heading with Korean subtitle: `## N장. 제목 — 부제`
3. Add "why this matters" opening if the original lacks one
4. **Rewrite EVERY paragraph** of the original section, in ONE integrated pass:
   - If input is non-Korean: translate AND explain **simultaneously, in the same sentence/paragraph** — NEVER write a faithful-translation paragraph and then a separate paragraph re-explaining it (Rule 0 duplication ban; this is exactly the defect to avoid)
   - If input is Korean: rewrite into conversational tone, once
   - Each original paragraph → ONE integrated output paragraph by default (use 2+ only when there is genuinely new explanation to add, never to restate). NEVER drop a paragraph's content.
5. Insert analogies for abstract concepts (using the system from Step 2)
6. Explain formulas in plain language (Rule 5 pattern)
7. Break long paragraphs into shorter ones with bullet points
8. Add concrete examples or scenarios where helpful
9. Bold key terms and takeaways
10. **Self-check before saving** (coverage, not length): Is every original claim/number/caveat in this section present in the output exactly once? (a) If something is *missing* → restore it. (b) If any two adjacent paragraphs say the **same thing in different words** → merge them, keeping only the unique details (Rule 0 duplication ban). Do NOT add length by restating.
11. **Save progressively** after completing each section

### Step 5: Rewrite Experimental Results
- Convert raw numbers into interpreted statements
- Create comparison tables with commentary columns
- Highlight surprising or notable findings
- Explain what the metrics mean: "F1 점수란 '얼마나 정확하게, 빠짐없이 찾았는가'를 종합 측정한 것입니다"

### Step 6: Generate the Glossary
After all content sections are complete:
- Collect every technical term that was defined inline
- Create the glossary table at the end of the document
- Format: `| 용어 | 쉬운 설명 |`
- **이 글 고유의 개념만 5\~15개** — 소양 독자(이공계 학부 이상)에게 자명한 일반 용어(IP·게임화·GDP·스팀펑크 류)는 싣지 않는다
- 인라인 정의 문구를 그대로 복사하지 말고 더 짧게 재정리한다 (인라인과 표의 문구 중복 금지)

### Step 7: Handle References, Acknowledgements, and Appendices

- **References**: Translate the section header to "## 참고문헌 (References)" but keep all reference entries in original language
- **Acknowledgements**: Translate the section header to "## 감사의 글 (Acknowledgements)" but keep content in original language

**Appendix handling — distinguish content type:**

Appendices fall into two categories. Handle them differently:

| Appendix Type | Example | How to Handle |
|--------------|---------|---------------|
| **Content appendix** (analysis, proofs, additional experiments, ablation studies) | "A.1 GPT-3 Experiments", "B. Proof of Theorem 1", "C. Additional Ablation" | **Full rewrite** — treat like any other section (translate + explain + enrich) |
| **Raw data appendix** (prompts, trajectories, code dumps, full example logs) | "C. Prompts" (pages of raw prompts), "D. Trajectories" (verbatim agent logs) | **Preserve as-is** in original language with a brief Korean introduction explaining what this appendix contains and why it's included |

**Example for raw data appendix:**
```markdown
## 부록 C. 프롬프트 (Prompts)

> 이 부록에는 실험에 사용된 실제 프롬프트 전문이 수록되어 있습니다.
> 연구를 재현하거나 프롬프트 설계를 참고하실 때 활용하세요.

[원문 프롬프트 내용 그대로 유지]
```

**Key principle**: If an appendix contains intellectual content that benefits from explanation, explain it. If it's reference material (raw data, verbatim logs, code), preserve it with a contextual introduction.

## File Saving Protocol

### File Naming Convention
- Input: `paper_ko.md` → Output: `paper_ko_explained.md`
- Input: `paper.md` (non-Korean) → Output: `paper_ko_explained.md`
- Input: `My Paper Title_ko.md` → Output: `My Paper Title_ko_explained.md`
- **Rule**: Always end with `_ko_explained.md`
- If input already contains `_ko`, insert `_explained` before `.md`
- If input does NOT contain `_ko`, insert `_ko_explained` before `.md`

### YAML Header
- **Always prepend YAML header** before any content
- First, check if the input file has a YAML header — if so, copy it (set `lang: ko`)
- If no header exists, try to read `header.yaml` from the project root
- Fallback minimal header:
  ```yaml
  ---
  lang: ko
  format:
    html:
      toc: true
      embed-resources: true
      theme: cosmo
  ---
  ```

### Saving Behavior
1. **First section**: Create new file with YAML header + banner blockquote + first section content
2. **Subsequent sections**: Append to existing file (NO duplicate YAML header)
3. **File location**: Save in the same directory as the original file
4. **Report completion** only when entire paper is done

### Example Workflow
```
Input:  /papers/deep_learning_survey.md (English)

Step 1: Analyze → 8 sections found, English detected
Step 2: Design analogies → [brain=computer, neurons=wires, training=studying]

Step 3: Create /papers/deep_learning_survey_ko_explained.md with:
   - YAML header
   - Banner blockquote
   - Author context

Step 4-5: Rewrite each section, append progressively

Step 6: Append glossary table

Final: "전체 논문 해설이 완료되었습니다. deep_learning_survey_ko_explained.md에 저장했습니다."
```

## Special Considerations

- **Images**: Preserve all image references (`![](images/...)`) from the original. Do NOT remove or modify image paths.
- **Citations**: Keep citation format unchanged: `[1]`, `(Smith et al., 2023)`, etc.
- **Code blocks**: Preserve as-is. Add a brief explanation before/after if the code illustrates a concept.
- **Tables**: Preserve data tables. May add interpretation rows or commentary after the table.
- **Figures**: Translate figure captions to Korean if in another language. Add explanation of what the figure shows. **캡션 라벨 표기는 문서 전체에서 "그림 N:" 으로 통일한다** (앞은 "Figure 1:", 뒤는 "그림 3:" 식의 혼용 금지).
- **이미지로만 존재하는 표·차트 (전사 의무)**: 본문 텍스트로 접근할 수 없는 정보 덩어리(표가 이미지로만 수록된 경우 등)는 **이미지 파일을 직접 열어(vision) 내용을 확인하고 텍스트로 전사·해설한다.** "세부 항목은 그림 안에만 담겨 있습니다" 같은 포기 문구는 금지. 이미지가 깨져 읽을 수 없으면 그 사실만 짧게 밝힌다. 수치가 육안으로 불명확한 차트는 지어내지 말고 추세만 서술한다 (Rule 1).
- **깨진 OCR 표**: 소스의 표가 OCR 로 깨져 있으면(`<table>` 태그 잔해, 오인식 변수명) 그대로 싣지 말고 원문 맥락으로 복원한 정상 표로 재구성하고, 원문 표기가 OCR 오류였음을 한 줄로 밝힌다.
- **원문 캡션 자체가 틀린 경우** (앞 그림 캡션의 복사-붙여넣기 등 명백한 소스 오류): 본문 맥락에 맞는 캡션을 달고, 원문 캡션이 오류였음을 한 줄로 밝힌다. 캡션 번호 통일("그림 N:")은 **번호가 있는 캡션에만** 적용하고, 무번호 캡션은 무번호로 둔다.
- **동아시아 인명 로마자**: 성-이름 순서가 모호하면 참고문헌·차트 출처의 이니셜 표기("Z. Chen et al.")와 교차 확인해 성을 판별한 뒤 표기한다.

## Domain-Specific Analogy Guidelines

The analogies should be domain-adaptive. The LLM should freely choose the best analogies for each paper, but here are general guidelines:

- **CS/AI papers**: Computer, office, library, internet, smartphone analogies
  - Memory hierarchy → filing cabinet with desk/drawer/safe
  - Neural networks → interconnected team members
  - Training → studying for an exam
- **Medical/Biology papers**: Body, health, cooking analogies
  - Cell signaling → postal delivery system
  - Immune response → security guard system
  - Preserve established Korean medical terminology
- **Physics/Math papers**: Physical world, building, nature analogies
  - Forces → pushing/pulling everyday objects
  - Waves → water ripples
- **Social Science papers**: Organization, community, family analogies
  - Statistical models → survey/voting analogies
  - Economic models → household budget management

**Universal principle**: 비유를 쓸 때는 일상 경험에 매핑하되, **소양 있는 독자 기준** 으로 자명한 기초까지 비유로 풀지 않는다 (Rule 3·"독자 수준 가정" 참조). 비유는 어려운 개념의 직관을 돕는 보조 수단일 뿐, 모든 도메인 개념에 의무적으로 다는 장치가 아니다. 위 도메인별 목록은 "비유가 정말 필요할 때 고를 후보" 이지, 매 개념에 비유를 달라는 뜻이 아니다.

## Examples

### Example 1: Abstract Rewriting (Problem→Solution→Results)

**Before (academic Korean):**
```markdown
## 초록
대규모 언어 모델(LLMs)은 고정된 컨텍스트 윈도우와 불충분한 메모리 관리로 인해
중대한 도전에 직면해 있으며, 그 결과 장기 기억 능력이 심각하게 부족해지고 AI
에이전트와의 상호작용 경험에서 개인화가 제한됩니다.
```

**After (easy explanation):**
```markdown
## 초록 — 이 논문이 해결하려는 문제와 결과 한눈에 보기

### 무엇이 문제인가?

ChatGPT 같은 대규모 언어 모델(LLM)은 매우 똑똑하지만, 치명적인 약점이 하나
있습니다. 바로 **"기억력의 한계"**입니다.

이 모델들은 한 번에 읽고 쓸 수 있는 텍스트의 양(이른바 "컨텍스트 윈도우")이
정해져 있습니다. 마치 책상 위에 올려놓을 수 있는 서류 분량이 제한된 것과 같습니다.
책상이 꽉 차면 오래된 서류는 바닥에 떨어져 잊혀지죠.

### 어떻게 해결했나?

저자들은 **MemoryOS(메모리 운영체제)**라는 것을 제안했습니다...

### 얼마나 좋아졌나?

LoCoMo 벤치마크에서 **F1 점수가 평균 49.11% 향상**되었습니다. 이 숫자는
"AI가 정답과 얼마나 비슷한 대답을 했는가"를 측정한 것인데, 거의 절반 가까이
개선된 것이니 상당한 성과입니다.
```

### Example 2: Formula Explanation

**Before:**
```markdown
$$\mathcal{F}_{\mathrm{score}} = \cos(\mathbf{e}_s, \mathbf{e}_p) + \mathcal{F}_{Jaccard}(K_s, K_p)$$

여기서 $\mathbf{e}_s$와 $\mathbf{e}_p$는 세그먼트와 대화 페이지의 임베딩 벡터를 나타냅니다.
```

**After:**
```markdown
이 점수는 두 가지를 결합해 계산합니다:

$$\mathcal{F}_{\mathrm{score}} = \cos(\mathbf{e}_s, \mathbf{e}_p) + \mathcal{F}_{Jaccard}(K_s, K_p)$$

1. **코사인 유사도**: 대화 페이지와 세그먼트의 의미를 숫자 벡터(임베딩)로 변환한
   뒤, 두 벡터가 얼마나 같은 방향을 가리키는지 측정합니다. 방향이 같을수록
   의미가 비슷합니다.

2. **자카드 유사도(Jaccard Similarity)**: LLM이 세그먼트와 페이지에서 각각
   키워드를 뽑아낸 뒤, 겹치는 키워드의 비율을 계산합니다. 예를 들어 세그먼트의
   키워드가 {운동, 건강, 조깅}이고 페이지의 키워드가 {조깅, 공원, 건강}이라면,
   겹치는 건 2개이고 전체는 4개이므로 유사도는 2/4 = 0.5입니다.
```

### Example 3: Analogy Integration (정형 마커 없이 문장에 녹이기)

**Before:**
```markdown
단기 기억(STM)은 실시간 대화 데이터를 대화 페이지라고 하는 단위로 저장합니다.
```

**After:**
```markdown
#### 단기 기억 (Short-Term Memory, STM)

단기 기억은 **지금 진행 중인 대화의 내용**을 실시간으로 저장합니다. 용량이 정해진
작은 메모장과 같아서, 꽉 차면 맨 앞에 적은 내용을 지우고 새 내용을 적습니다.
(비유를 "비유로 설명하면 이렇습니다:" 같은 머리표 없이 한 문장에 녹였다.)

저장 단위는 "대화 페이지(dialogue page)"입니다. 각 대화 페이지는 세 가지로
구성됩니다:
- **Q**: 사용자가 한 질문 또는 말
- **R**: AI가 한 응답
- **T**: 그 대화가 이루어진 시각(타임스탬프)
```

## Quality Checks

**먼저 정적 검증기를 돌린다** (직접 grep 금지 — §Codex 환경):

```bash
python3 scripts/verify_explainer.py "<출력_ko_explained.md>"   # 소스는 같은 폴더에서 자동 탐색
```

`FAIL` 이면 publish 하지 말고 해당 항목을 고친 뒤 다시 돌린다. `REVIEW` 는 자동 반려가 아니지만
**각 항목의 근거를 확인**하고(예: 해라체 문단이 정말 직접인용인지), 근거가 없으면 고친다.
정적 검증기가 `PASS` 여도 아래 항목은 여전히 사람/에이전트가 확인해야 한다 —
검증기는 coverage·비유 적절성·수식 정확성·차트 전사 내용을 보지 못한다.

그 다음 **이 우선순위로** 확인한다:

**CRITICAL (must pass — if any fails, go back and fix):**
- [ ] **Content coverage (PRIMARY — not a length quota)**: every original section, subsection, paragraph, **claim, number, causal link, and exception/caveat** appears in the output **at least once**. This is the real bar — verify it section by section, not by character count.
- [ ] **No paraphrased duplication (이번 결함의 핵심 게이트)**: read consecutive paragraphs — **no adjacent pair states the same claim with only different wording.** In particular there is NO "[충실 번역 문단] → [같은 내용 재설명 문단]" pair anywhere. If found, merge into one integrated paragraph, preserving unique details. (Spot-check at least 3 sections.)
- [ ] **분량은 보조 지표일 뿐 (자수 기준, `wc -m`; Codex 는 rtk 훅이 없어 그대로 쓴다 — `LC_ALL=C` 금지)**: 줄 수로 재지 않는다. 기준 = **웹 잡동사니 제거한 소스 본문** 자수. 참고문헌은 **소스·출력 양쪽 모두 포함**한 동일 기준으로 잰다 (한쪽만 빼면 비율이 수 %p 흔들린다).
  - **목표가 아니라 진단 신호다.** 외국어 소스 → 한글 출력이 **0.6x 미만이면** 누락을 의심해 섹션별 coverage를 대조한다(그 이상이면 비율로 트집잡지 않는다). 한국어 소스 → 하한 없음, coverage만 본다.
  - 0.6x 미만이어도 **새 주제를 지어내거나 재서술로 채우지 않는다** — 누락·과압축된 문단만 복원한다. 분량을 늘리려 같은 말을 반복하면 그게 바로 이 결함이다.
- [ ] **Section completeness**: Every section AND subsection heading in the original appears in the output (compare heading counts)

**Important (should pass):**
- [ ] **No web clutter (web-sourced inputs)**: 출력에 광고·스폰서 블록("Sponsored by…", "Try X"), 구독/뉴스레터 유도("Subscribe", "Sponsor me", "구독"), 쿠키 동의, 소셜/공유 위젯, "Recent/Related articles"·태그 줄, 연도 아카이브 목록 등 **본문이 아닌 웹 잡동사니가 남아있지 않다** (Web Source De-cluttering 참조)
- [ ] **Formula preservation**: All mathematical expressions from the original are preserved
- [ ] **Accuracy**: No claims, data, or conclusions added that are not in the original
- [ ] **Analogy consistency**: Same concept uses the same metaphor throughout
- [ ] **비유 절제**: 정형 도입구("비유로 설명하면 이렇습니다:")를 반복하지 않았고, 비유는 0\~3개 핵심에만, 자명한 기초를 비유로 풀지 않았다
- [ ] **중복 없음**: 같은 개념·맥락·비유를 여러 곳에서 처음부터 다시 설명하지 않았다 (두 번째부터는 짧게 참조)
- [ ] **출처 절제**: 매체/출처가 무엇인지 설명하지 않았고, 출처 언급은 많아야 1회다 (소개 blockquote 가 2개 연속으로 중복되지 않았다)
- [ ] **수치 재진술 0건**: 수치 제시 직후 같은 수치를 환산·감탄으로 되풀이하는 별도 문단이 없다
- [ ] **마감 에코 ≤5**: "정리하면/쉽게 말해/즉 …셈입니다/뜻입니다" 류 재요약 마감이 문서 합계 5회 이하이고, 순수 반복 마감은 0회다
- [ ] **비유 소재 ≤3 · 라벨 0**: 서로 다른 비유 소재가 3개 이하, "**비유:**" 볼드 라벨·비유 blockquote·번호형 스캐폴딩 0건
- [ ] **소스 외 주장 0**: 저자 예찬·원문 밖 수치 비교/인과 부연/최상급 수식이 없다 (표본 3개 섹션 대조)
- [ ] **메타 한 줄**: 저자·발표처·발표일 중 확인 가능한 사실이 도입부에 있다 (지어낸 항목 없음)
- [ ] **이미지 전사**: 이미지로만 존재하는 표·도표가 텍스트로 전사·해설됐다 (포기 문구 0건)
- [ ] **Glossary completeness**: All technical terms defined inline appear in the glossary
- [ ] **문체 합니다체 (신규 게이트)**: 본문 해설 서술이 전부 합니다체다. 소스가 해라체(뉴스/사설 번역본)여도 어미를 상속하지 않았다 — 해라체 평서형("~다/~했다")으로 끝나는 본문 문단이 없다(직접인용 내부·배너·표·수식 예외). 스캐너 지표로는 `hae_p`(해라체 문단 수)가 0에 가까워야 하며, 0이 아니면 그 문단이 직접인용/제목 예외인지 근거를 확인한다
- [ ] **Natural Korean flow**: No awkward phrasing or translationese
- [ ] **Image references**: All `![](images/...)` paths preserved from original
- [ ] **Citations**: All `[1]`, `(Author et al., 2023)` formats unchanged
- [ ] **YAML header**: Present exactly once at the top of the file
- [ ] **File name**: Ends with `_ko_explained.md`

## Formatting Preservation Checklist
- [ ] YAML header from input file or `header.yaml` prepended (exactly once)
- [ ] All headers maintained or enhanced with subtitles
- [ ] Lists and bullet points properly formatted
- [ ] Code blocks preserved with syntax highlighting
- [ ] Tables aligned properly
- [ ] Links and references functional
- [ ] Citations in original format
- [ ] Equations/formulas unchanged (with added explanations)
- [ ] Image references intact
- [ ] Each section appended to the same output file (no duplicate YAML headers)
- [ ] References/Acknowledgements: headers translated, content in original language
- [ ] Glossary table present at end of document

## User Request Interpretation

The following requests immediately trigger this skill:
- "이 논문 쉽게 설명해줘"
- "해설판 만들어줘"
- "논문 알기 쉽게 풀어줘"
- "{논문 제목/파일/링크} 한국어로 쉽게 정리해줘"

### Single Target Mode
When the input is specified as a URL/title/file:
1. Locate the source file path
2. **Skip-without-asking guard** — before processing, skip (do NOT ask the user) when:
   - The folder already has `*_ko_explained.md`, OR
   - `paper_meta.json`의 `doc_type` 가 `"video"` (HBR Premium 등 재생용 mp4 문서 — `*_ko.md` 가 영상 임베드 스텁뿐이라 해설할 본문이 없다), OR
   - **본문 산문(prose)이 없는 이미지 전용 페이지** — 소스 MD 에서 제목(`#`)·날짜·이탤릭 메타(`*…*`)·이미지 참조(`![](…)`)·수평선을 빼면 설명할 문단이 0줄인 경우. The Economist 주간 인제스트의 고정 필러(예: "The weekly cartoon" 만평 1장, "Economic data, commodities and markets" 데이터 차트 이미지 N장, "The world this week" 류)가 대표적이다. 차트·만평 이미지를 보고 내용을 지어내면 Rule 1(정확성) 위반이며, 특히 경제 데이터 차트는 수치 오독=날조 위험이 크다.
   Report it as "skipped (video)" / "skipped (already exists)" / "skipped (image-only, no prose)" in the completion report. Do NOT fabricate an explainer from a title-only stub or from images alone.
3. Process according to this skill's rules
4. Return the output file path clearly

### Explicit Target List Mode (사용자가 경로 목록을 직접 준 경우)
When the user provides an **explicit list of source→output paths** (not an auto-scan):
1. Process each target one at a time, in order.
2. **Apply the same skip-without-asking guard as Single Target Mode to every item** — even though the user explicitly listed it. An explicit listing does NOT override the video/already-exists/image-only skip: a `doc_type=="video"` folder or an image-only filler page has no body text to explain, so generating one would be fabrication (Rule 1 violation). Skip silently and record it.
3. **Do NOT re-ask** "이건 영상/이미지뿐이라 본문이 없는데 어떻게 할까요?" for each such item — this annoys the operator who already knows the skill skips video and image-only filler pages. Just skip and move on.
4. **Path matching**: 한글 폴더명은 NFC/NFD 정규화 차이로 `[ -d ]`·`ls` 가 빗나갈 수 있으니 `find` 로 실제 디스크 경로를 잡는다.
5. 진짜 모호한 경우(예: "목록의 폴더가 없다 / 의도한 것과 다른 논문으로 보인다")에만 사용자에게 묻고, 일상적인 video/exists skip 은 절대 묻지 않는다. **비대화형 배치(`codex exec`)에서는 물을 상대가 없다** — 모호하면 그 항목만 실패로 기록하고 다음으로 넘어간다.

### Batch Mode (important)
When the user does **NOT specify a target** and says "논문 해설판 만들어줘":
1. Recursively scan **both** `/home/restful3/workspace/paperflow/outputs` **and** `/home/restful3/workspace/paperflow/archives` subdirectories.
2. Build the candidate set. A directory is an **eligible paper folder** only if ALL of these hold:
   - The folder name does NOT start with `.` (skip config/hidden folders like `.claude/`)
   - **`paper_meta.json`의 `doc_type` 가 `"video"` 가 아니다** — 동영상 폴더(HBR Premium 등)는
     폴백 `*_ko.md` 가 있어도 해설판 생성 대상이 **아니다**. 무조건 건너뛴다 (재생용 mp4 문서이므로).
   - It contains at least one **source MD**: a `*_ko.md`, OR a non-explained/non-backup `*.md`
     (excluding `*_ko_explained.md`, `*_explained.md`, `*_backup_*.md`)
   - It is missing `*_ko_explained.md`
   Folders that are empty, contain no source MD, are doc_type=="video", or are hidden/config folders are NOT candidates —
   skip them (never create, rename, or delete them). If any sourceless/orphan folders are found,
   list them in the completion report so the operator can clean them up.
3. **Select only one target per run**: the most recently updated source file among missing candidates.
4. Source preference per target:
   - Prefer `*_ko.md` when available in the same paper directory.
   - Fallback to English `*.md` (excluding `*_ko_explained.md`, `*_backup_*.md`).
5. Process the selected file in **this** session (fresh `codex exec` per paper — 위 실행 모델 참조).
6. Return concise summary for this single target:
   - selected path / generated-or-skipped / output path / failure reason(if any)

Rationale:
- Keep runs predictable and stable.
- Align with daily incremental operation (one latest missing paper at a time).

## Completion Report

On task completion, report concisely:
- Input file (with char count, `wc -m`)
- Output file (with char count)
- **Ratio (자수 기준, 진단용 — 목표 아님)**: output chars / clutter-removed source chars. 외국어 소스 < 0.6x 이면 coverage 재확인 신호. 한국어 소스는 하한 없음.
- Processing mode (auto / section-safe)
- Number of sections covered / total sections in original
- **Duplication self-check result**: 연속 문단 패러프레이즈 중복 0건 확인 여부
- Notable issues (missing risk / source quality problems / heavy OCR noise / etc.)
- (Batch mode only) Sourceless/orphan folders skipped during the scan, if any — so the operator can clean them up

**If a section's output is conspicuously short**, verify by coverage (claims/numbers/caveats present?), NOT by padding — and never by restating.
