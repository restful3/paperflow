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

**This is NOT a translation skill.** The paper-translator-korean skill produces academic Korean. This skill produces **conversational, enriched Korean with analogies and explanations** — the output should be RICHER than the input (1.5-2.5x longer).

**Input language handling:**
- If input is already Korean: skip translation, go directly to rewriting
- If input is in another language: translate AND explain simultaneously (no separate translation step)

**Default behavior: Full paper rewrite in one go**
- Rewrite the entire paper automatically without user approval
- Process all sections sequentially without asking for confirmation
- DO NOT summarize or omit — the output must contain ALL original content, explained more richly

## Execution Modes

### Auto Mode (default)
- Process the entire paper automatically
- For long sections, automatically split into subsection-level chunks

### Interactive Reliability Mode (TUI 운영 안정화)
When running in Claude Code TUI with permission prompts:
- For file-write/read/search confirmation prompts, **always choose Yes**.
- Prefer **"Yes, and don't ask again" / "allow all edits during this session"** whenever available.
- Avoid repeated micro-confirmation loops.

Quality-first wait policy (hard rule):
- Do **not** interrupt due to `Actioning…` / `Actualizing…` / `Perusing…` / `Blanching…` style states.
- In TUI runs, wait at least **30 minutes minimum** before judging a stall.
- During that 30-minute window, do not restart session, do not cancel, and do not switch strategy.
- Only after 30 minutes with no substantive progress, apply fallback/retry.

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

## Core Rewriting Principles — 9 Rules

### Rule 0: NO Condensation — Expand, Never Shrink (축약 절대 금지 — 확장 필수)

**THIS IS THE SUPREME RULE. It overrides all other considerations.**

This skill produces a **해설판 (annotated commentary)**, NOT a summary. The output must be a **full rewrite of the entire original** with added explanations — never a condensed version.

**Hard constraints:**
- The output MUST be **longer** than the input. Target: **1.5x–2.5x** the input length (measured in characters or lines)
- If the output is shorter than the input, **something is wrong** — go back and find what was skipped
- Every paragraph in the original MUST have a corresponding paragraph (or more) in the output
- Every subsection in the original MUST appear in the output — do NOT merge or skip subsections
- "한눈에 보기", "핵심 요약", "방법 요약" style summary headings are **FORBIDDEN** as replacements for original section structure. They may only appear as **additions** alongside the full content.

**Paragraph-level mapping rule (문단 대응 원칙):**
```
Original paragraph → Explained paragraph(s)
- 1 original paragraph = 1 or more explained paragraphs (NEVER 0)
- Each explained paragraph should be ≥ the original in length
- If a paragraph is purely technical, add a plain-language explanation BEFORE or AFTER it
- If a paragraph contains data/numbers, add interpretation
```

**What "축약" (condensation) looks like — AVOID these patterns:**
- Replacing 5 paragraphs of methodology with a 3-bullet summary
- Skipping subsections because they seem "repetitive" or "minor"
- Writing "이 부분에서는 X를 다룹니다" instead of actually rewriting X
- Using the heading structure of a summary (한눈에 보기/핵심 기여/방법 요약) instead of the original paper's heading structure

**What "해설" (commentary) looks like — DO these patterns:**
- Keep the original's structure (section → subsection → paragraph) intact
- For each paragraph: rewrite in easy Korean + add explanation/context/analogy as needed
- The result reads like a "professor's annotated version" of the full paper, not a cliff notes

### Rule 1: Accuracy First (정확성 우선)
Enrichment must never distort the original.

- Do NOT add claims, data, or conclusions not present in the original paper
- Do NOT exaggerate or speculate — only explain what the authors actually wrote
- "Why this matters" context and analogies must faithfully represent the original content
- If uncertain about a technical detail, explain what the paper states rather than interpreting beyond it

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

### Rule 3: Analogies and Metaphors (비유/은유)
Use analogies for core concepts only — not every paragraph needs one.

**How to create good analogies:**
- Choose everyday objects/situations everyone knows (kitchen, office, library, school)
- The analogy should capture the KEY PROPERTY of the concept
- Extend the analogy to explain relationships between concepts
- Maintain analogy consistency throughout the entire paper
- Limit to **3-5 core analogies** per paper — do NOT force analogies on every paragraph

**Analogy introduction markers:**
- "**비유로 설명하면 이렇습니다:**"
- "마치 ...와 같습니다"
- "...라고 상상해 보세요"
- "이것은 마치 ... 하는 것과 비슷합니다"

**CRITICAL: Design an analogy system before writing.**
Before starting any section rewriting, identify 3-5 core concepts in the paper and assign consistent metaphors. For example, if the paper discusses a hierarchical memory system:
- Short-term memory = desk (책상 위)
- Mid-term memory = drawer cabinet (서랍장)
- Long-term memory = safe/vault (금고)
Use these SAME analogies every time these concepts appear.

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
The output must be RICHER than the input. Never omit or summarize.

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

**Priority: under-writing is FAR worse than over-writing.**
- A section that is too long can be trimmed later; a section that was summarized has lost information forever
- When in doubt, write MORE rather than less
- Avoid empty repetition (saying the same thing twice in different words), but do NOT cut content to avoid being "verbose"
- Every paragraph of the original deserves its own full treatment in the output

## Step-by-Step Rewriting Process

**CRITICAL: Automatic full-paper rewrite without user approval!**

### Step 1: Analyze the Paper
- Read the entire input file
- Detect the source language
- **Count total lines and note the file size** — the output must exceed this
- Identify all sections and subsections — **list them with approximate line counts**
- Map key concepts and their relationships
- Classify each section:
  - Content sections (intro, methods, experiments, etc.) → full rewrite
  - References/Bibliography → keep content in original language
  - Acknowledgements → keep content in original language (translate header only)
  - Appendix → classify as content vs raw data (see Step 7)

### Step 2: Design the Analogy System
Before writing anything, choose 3-5 core analogies:
- Identify the paper's main architectural/conceptual elements
- Assign consistent everyday metaphors to each
- Plan how these metaphors relate to each other
- These will be used consistently throughout the entire document

### Step 3: Write the Title and Introduction Banner
- Transform the title: `# 원제목 — 쉬운 해설판`
- Add a blockquote banner:
  ```markdown
  > 이 글은 "논문 제목" 논문의 전체 내용을 빠짐없이 담되, 전문 용어와 개념을
  > 일상적인 비유와 풀어쓴 설명으로 재구성한 해설판입니다.
  ```
- Add author context: briefly explain who the authors are and where they work (institution context)

### Step 4: Rewrite Each Section (with per-section verification)
For each section in the original paper:
1. **Count the original section's paragraphs and approximate length** (mental note)
2. Transform the heading with Korean subtitle: `## N장. 제목 — 부제`
3. Add "why this matters" opening if the original lacks one
4. **Rewrite EVERY paragraph** of the original section:
   - If input is non-Korean: translate AND explain simultaneously (not translate-then-explain)
   - If input is Korean: rewrite into conversational tone
   - Each original paragraph → one or more output paragraphs (NEVER skip a paragraph)
5. Insert analogies for abstract concepts (using the system from Step 2)
6. Explain formulas in plain language (Rule 5 pattern)
7. Break long paragraphs into shorter ones with bullet points
8. Add concrete examples or scenarios where helpful
9. Bold key terms and takeaways
10. **Self-check before saving**: Is this section's output at least as long as the original section? If not, go back and find what was missed or under-explained.
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
- Include 10-20 key terms (more for longer/more technical papers)

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
- **Figures**: Translate figure captions to Korean if in another language. Add explanation of what the figure shows.

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

**Universal principle**: Map to the Korean reader's everyday experience. Choose analogies from daily life that require no specialized knowledge.

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

### Example 3: Analogy Introduction

**Before:**
```markdown
단기 기억(STM)은 실시간 대화 데이터를 대화 페이지라고 하는 단위로 저장합니다.
```

**After:**
```markdown
#### 단기 기억 (Short-Term Memory, STM)

단기 기억은 **지금 진행 중인 대화의 내용**을 실시간으로 저장합니다.

**비유로 설명하면 이렇습니다:**

여러분이 친구와 카페에서 대화를 나누는데, 대화 내용을 작은 메모장에만 기록할 수
있다고 상상해 보세요. 메모장이 꽉 차면 맨 앞에 적은 내용을 지우고 새 내용을
적어야 합니다. 이 메모장이 바로 단기 기억입니다.

저장 단위는 "대화 페이지(dialogue page)"입니다. 각 대화 페이지는 세 가지로
구성됩니다:
- **Q**: 사용자가 한 질문 또는 말
- **R**: AI가 한 응답
- **T**: 그 대화가 이루어진 시각(타임스탬프)
```

## Quality Checks

After completing the full rewrite, verify **in this priority order**:

**CRITICAL (must pass — if any fails, go back and fix):**
- [ ] **Output length >= input length**: The explained file MUST be at least as long as the source file (in lines). If shorter, content was lost — find and fix the gap. Target is 1.5x–2.5x.
- [ ] **Section completeness**: Every section AND subsection heading in the original appears in the output (compare heading counts)
- [ ] **Paragraph coverage**: Spot-check 3 random sections — does each original paragraph have a corresponding output paragraph?

**Important (should pass):**
- [ ] **Formula preservation**: All mathematical expressions from the original are preserved
- [ ] **Accuracy**: No claims, data, or conclusions added that are not in the original
- [ ] **Analogy consistency**: Same concept uses the same metaphor throughout
- [ ] **Glossary completeness**: All technical terms defined inline appear in the glossary
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
2. Process according to this skill's rules
3. Return the output file path clearly

### Batch Mode (important)
When the user does **NOT specify a target** and says "논문 해설판 만들어줘":
1. Recursively scan **both** `/home/restful3/workspace/paperflow/outputs` **and** `/home/restful3/workspace/paperflow/archives` subdirectories.
2. Build the candidate set. A directory is an **eligible paper folder** only if ALL of these hold:
   - The folder name does NOT start with `.` (skip config/hidden folders like `.claude/`)
   - It contains at least one **source MD**: a `*_ko.md`, OR a non-explained/non-backup `*.md`
     (excluding `*_ko_explained.md`, `*_explained.md`, `*_backup_*.md`)
   - It is missing `*_ko_explained.md`
   Folders that are empty, contain no source MD, or are hidden/config folders are NOT candidates —
   skip them (never create, rename, or delete them). If any sourceless/orphan folders are found,
   list them in the completion report so the operator can clean them up.
3. **Select only one target per run**: the most recently updated source file among missing candidates.
4. Source preference per target:
   - Prefer `*_ko.md` when available in the same paper directory.
   - Fallback to English `*.md` (excluding `*_ko_explained.md`, `*_backup_*.md`).
5. Process the selected file in the main interactive agent (TUI/write prompts expected).
6. Return concise summary for this single target:
   - selected path / generated-or-skipped / output path / failure reason(if any)

Rationale:
- Keep runs predictable and stable.
- Align with daily incremental operation (one latest missing paper at a time).

## Completion Report

On task completion, report concisely:
- Input file (with line count)
- Output file (with line count)
- **Ratio**: output lines / input lines (MUST be >= 1.0, target 1.5-2.5)
- Processing mode (auto / section-safe)
- Number of sections covered / total sections in original
- Notable issues (missing risk / source quality problems / heavy OCR noise / etc.)
- (Batch mode only) Sourceless/orphan folders skipped during the scan, if any — so the operator can clean them up

**If ratio < 1.0**, explicitly note which sections or content were not covered and why.
