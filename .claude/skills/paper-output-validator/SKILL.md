---
name: paper-output-validator
description: Audit and validate PaperFlow output folders (outputs/ and archives/) for problems — abstract/summary-only scrapes vs full papers, missing _ko_explained / _ko_audio, stale narrations, style-register violations (해라체 회귀 / translate-then-restate), audio image-embedding gaps, web clutter, orphan/sourceless/NFC-NFD-duplicate folders, broken image refs, and leftover cruft. Produces a per-folder classification report. READ-ONLY by default; destructive cleanup only on explicit user confirmation. Use when the user says "outputs 검증", "폴더/파일 검증해줘", "정상적으로 만들어졌는지 확인", "초록/요약본 찾아줘", "해설판/낭독판 빠진 거 찾아줘", or asks to audit the paper library.
---

# Paper Output Validator (PaperFlow 산출물 검증)

## When to Use

Use this skill when the user wants to **check the health of PaperFlow output folders** — not to *produce* a document, but to *inspect* what already exists and find what's wrong or missing. Triggers:

- "outputs 검증해줘", "폴더랑 파일들 정상인지 확인해줘"
- "초록/요약본만 있는 거(원문 아닌 거) 찾아줘"
- "해설판 없는 거 / 낭독판 없는 거 찾아줘"
- "이미지 임베딩 빠진 듣기판 찾아줘"
- "고아 폴더 / 깨진 거 정리 대상 찾아줘"
- 정기 라이브러리 감사(audit) 요청

This is a **diagnostic / classification skill**. Generation is delegated to other skills:
`paper-explainer` (해설판), `paper-audio-korean` (낭독판), `paper-audio-brief-korean` (축약 낭독판). This skill only **finds and labels**; it then **recommends** which generation/cleanup action each folder needs.

## Core Principle — Disk Is the Source of Truth, Report Before You Touch

1. **Read-only by default.** Scanning, grepping, classifying, and writing a report are always safe. Never delete, move, or overwrite as part of a plain "validate" request.
2. **Destructive actions need explicit confirmation.** Moving PDFs to `newones/`, deleting folders, or overwriting files happens ONLY after you present the exact list and the user confirms. Show the evidence (why each folder was classified that way) before asking.
3. **Classification is a judgment — surface the evidence.** Every flagged folder must come with the signal that triggered it (line count, signature hits, missing file, etc.), so the operator can sanity-check before any cleanup.
4. **Contradiction beats assumption.** If what you find contradicts the user's premise (e.g. "the PDF is the full paper" but reprocessing yields an abstract), STOP and report the contradiction instead of proceeding. (See *Gotcha: URL-first abstract trap*.)

## Base Paths & Conventions

- Working dir: the PaperFlow repo root (contains `outputs/`, `archives/`, `newones/`, `config.json`).
- A **paper folder** lives directly under `outputs/` or `archives/`. Skip names starting with `.`.
- **Source MD**: a `*_ko.md` OR a non-derived `*.md` — i.e. NOT `*_ko_explained.md`, `*_explained.md`, `*_ko_audio.md`, `*_ko_audio_brief.md`, `*_backup_*.md`.
- **Derived artifacts**: `*_ko_explained.md` / `*_explained.md` (해설판), `*_ko_audio.md` + `*_ko_audio.meta.json` (낭독판+sidecar), `*_ko_audio_brief.md` + `*_ko_audio_brief.meta.json` (축약 낭독판+sidecar).
- **CJK/Hangul folder names**: NFC vs NFD normalization bites shell globs. When a name has Hangul, **resolve paths with `find ... -name '*substr*'`** rather than typing the name or relying on `outputs/<한글>/` globs. Prefer ASCII substrings of the name in `find`.
- **Bracket folder names**: names like `[20260601 ~ 07] …` break shell globs AND Python `glob.glob` (brackets = character class). In shell, iterate `for d in "$base"/*/` (safe) — never interpolate the name into a new glob; in Python use `glob.escape()` or `pathlib.Path.iterdir()`.

## Validation Dimensions (what to check per folder)

Run these checks for every paper folder. Each produces a status tag.

### D0. Document type — VIDEO (skip generation checks)
- If `paper_meta.json` 의 `doc_type == "video"` (HBR Premium 등 동영상): 폴더는 **VIDEO** 로 분류하고
  **D2(ABSTRACT_ONLY)·D3(NEEDS_EXPLAINER)·D4(NEEDS_AUDIO)·D5 를 적용하지 않는다.**
  동영상은 로컬 mp4 재생용 문서라 해설판·낭독판 대상이 아니며, 폴백 `*_ko.md` 가 있어도
  해설/낭독 누락으로 보고하지 않는다. (점검 대상: mp4·poster 존재, `video` 블록 유효성 정도.)
- 즉 아래 D1\~D10 검사 전에 doc_type 을 먼저 보고, video 면 생성 관련 차원은 건너뛴다.
  **스크립트로 훑을 때도 반드시 이 분기를 구현한다** — doc_type 체크가 빠진 스캔은 video 18개 폴더를
  NEEDS_EXPLAINER 로 오분류한다 (실측 사고).

### D1. Source presence — ORPHAN
- A folder with **no source MD** (only backups/derived/assets, or empty) is an **ORPHAN**.
- Never auto-delete orphans; list them for the operator.

### D1b. Folder-name duplicates — DUP_FOLDER (NFC/NFD · apostrophe)
- Two sibling folders **in the same base dir** whose names are equal after `unicodedata.normalize('NFC', name)` (or differ only by straight `'` vs curly `’`) are a **split-brain duplicate** — one is usually a stale orphan the sync/OS created. 실측: `[20260601 ~ 07] …` NFC/NFD 쌍.
- **Scan per base dir separately** — outputs 와 archives 를 한 목록에 섞으면 D1c(교차 공존)와 뒤섞여 오탐한다:
```bash
for base in outputs archives; do
  ls "$base" | python3 -c "
import sys,unicodedata,collections
names=[l.rstrip('\n') for l in sys.stdin if l.strip()]
g=collections.defaultdict(list)
for n in names: g[unicodedata.normalize('NFC',n).replace('’',chr(39)).replace('‘',chr(39))].append(n)
[print('DUP_FOLDER:', ' || '.join(map(repr,v))) for v in g.values() if len(v)>1]"
done
```
- Report which of the pair has the richer/newer content; **never merge or delete without confirmation.**

### D1c. outputs/archives 동시 존재 — LOCATION_COLLISION
- **같은 이름의 폴더가 outputs/ 와 archives/ 양쪽에 존재**하면(실측 26쌍) restore 시 충돌하고, 이름 기반 조회(`paper_name`)가 어느 쪽을 가리키는지 모호해진다 (MCP 는 `location` 필드로 핀하지만 수동 조작 경로는 아님).
- Detect: `comm -12 <(ls outputs|sort) <(ls archives|sort)`
- 보통 한쪽이 재처리·복원 잔재다. 내용물(산출물 세트·mtime)을 비교해 어느 쪽이 정본인지 증거를 제시하고, 정리는 사용자 확인 후에만.

### D2. Abstract / summary vs full text — ABSTRACT_ONLY  ⚠️ most important
The signature failure mode in this repo: the markdown is an **arXiv abstract-page scrape (HTML chrome), not the converted full paper.**

Detect with these signals (combine — any strong hit ⇒ suspect):
- **arXiv/webpage chrome signatures** (count hits): `arXivLabs`, `제출 이력`, `Submission history`, `BibTeX`, `서지 도구`, `북마크`, `Connected Papers`, `alphaXiv`, a literal `^초록:` line. **≥10 hits ⇒ almost certainly an abstract scrape.**
- **Suspiciously short** academic paper: source `*_ko.md`/`*.md` of **~150–220 lines** with only a `## 참고문헌`/`## References` H2 and no real body sections (Introduction/Method/Experiments).
- **Other web-summary tells**: "Markdown 콘텐츠:", "게시 시간:", site nav menus as the bulk of the file.

Cross-check with the PDF when present:
- `pdfinfo "<pdf>" | grep Pages` — if the PDF has **many pages (e.g. 10–60)** but the MD is tiny, that's a **full-paper-PDF + abstract-only-MD mismatch** = ABSTRACT_ONLY with a recoverable PDF.

> **Web articles are different.** A genuine web article (TechCrunch/BBC/blog) is *naturally short* and is NOT an abstract. It has **0 arXiv signatures** and reads as a complete article. Do NOT flag those as ABSTRACT_ONLY — they're valid full sources (just run de-cluttering when explaining). Distinguish by the arXiv-signature count (academic scrape = high; real article = 0).

### D3. Missing explainer — NEEDS_EXPLAINER
- Folder has a valid full source MD but **no `*_ko_explained.md` / `*_explained.md`** ⇒ NEEDS_EXPLAINER → hand to `paper-explainer`.

### D4. Missing / stale audio — NEEDS_AUDIO · STALE_AUDIO · STALE_BRIEF
- Folder has `*_ko_explained.md` but **no `*_ko_audio.md`** ⇒ NEEDS_AUDIO → hand to `paper-audio-korean`.
- **Stale narrations**: a `*_ko_audio.meta.json` / `*_ko_audio_brief.meta.json` whose source hash/size/mtime no longer matches the current `_ko_explained.md` ⇒ STALE_AUDIO / STALE_BRIEF (regeneration candidates — 해설판 소급 수정 후 흔함).
- **Missing brief is NOT a defect.** `_ko_audio_brief.md` is generated on demand; a folder without one is normal — do not create a NEEDS_BRIEF backlog unless the user asks for one.

### D5. Audio image-embedding gap — AUDIO_IMG_GAP
- For each `*_ko_audio.md` (and `*_ko_audio_brief.md`): if the source `_ko_explained.md` has `![` images but the narration has **0 `![](` embeds**, the listen-version skipped figure embedding.
- **Legit exceptions (NOT a defect, 0 embeds is correct):**
  1. All source images are **external URLs** (`](http...)`) — cannot embed (relative-path-only rule).
  2. Source images are **broken/empty refs** (`![alt](images/)` with no `images/` dir or no file).
  3. Purely decorative/author-photo/promo images that the audio rightly drops.
  4. (brief only) all figures fell outside the 축약 우선순위 — brief 는 핵심 그림만 싣는다.
  When flagging, verify whether embeddable **local** files actually exist (`find <dir>/images -type f`); only flag when real local images were available but not embedded.

### D6. Image reference health — IMG_BROKEN
- Referenced `![](images/xxx)` whose file is **missing** on disk.
- Mixed external-URL images (note them; they affect D5).

### D7. Cruft / leftovers — CRUFT
- Leftover `*.part` (an interrupted audio/explainer write — never a finished file).
- `*_backup_*.md`, `*.md.bak*`, `*.red-*.md`, `*.render.md`, `*_mdlint_report.json`, stray temp files in the folder.
- These are usually harmless but worth listing; `.part` files specifically indicate an **incomplete** generation to redo.

### D8. Length sanity — COVERAGE_SUSPECT (진단 신호, 자동 결함 아님)
- 길이 비교는 **자수(`wc -m`) 기준, coverage 의 보조 진단**일 뿐이다 — 절대 "해설판은 소스의 1.5\~2.5배" 같은 배수 목표를 적용하지 않는다 (구 기준; 현행 `paper-explainer` 는 completeness 우선 + 중복 금지라 0.8\~1.6x 도 정상).
- **외국어 소스** → `_ko_explained.md` 가 **소스의 0.6x 미만**이면 COVERAGE_SUSPECT 로 표시하되, **헤딩 커버리지 대조** 후에만 결함 확정: 소스의 섹션 헤딩이 해설판에 다 있으면 대개 정당 (벤치마크 표·참고문헌·부록 덤프 위주 소스 — 508편 감사에서 저비율 논문 전수 legitimate 판정).
- **한국어 소스** → 하한 없음. 중복 제거·군더더기 제거로 소스보다 짧아지는 것이 정상일 수 있다.
- 반대로 **비논문 뉴스가 2.5x 이상**이면 translate-then-restate 중복 의심 (D10 레지스터 스캔과 교차 확인 — 감사 실측: ratio ≥2.5x 에 BAD 중복 집중).

### D9. Output cleanliness for audio (deep check, optional)
Run the audio CRITICAL grep on each `*_ko_audio.md` / `*_ko_audio_brief.md` (must be 0 hits) and confirm no alt-text images:
```bash
grep -nE '\$\$|\$[^$]+\$|\\\(|\\\[|^\s*\|.*---|^```|\[[0-9]+\]|\[\^|<sup|<span|<br|</?[a-zA-Z]|\]\(#|https?://' "<audio>.md"   # want: 0
grep -nE '!\[[^]]+\]\(' "<audio>.md"                                                                                            # alt-text images: want 0
```
(`![](path)` empty-alt images are intentionally allowed.)

### D10. Style register — DUP_REGISTER · TONE_HAERACHE (해설판 문체 스캔)
해설판 본문은 합니다체가 규칙이다. 두 가지 실패 모드를 문단 어미 레지스터로 잡는다 (508편 감사에서 검증된 지표 — difflib 복제율보다 패러프레이즈형 중복을 잘 잡는다):

- **DUP_REGISTER** (translate-then-restate 의심): 해라체 평서형("\~다/\~했다/\~한다")으로 끝나는 본문 문단 ≥4 **이면서** 합니다체 문단도 ≥3 공존 — 번역 문단+재설명 문단 이중 구조의 신호.
- **TONE_HAERACHE** (전체 해라체 회귀): 해라체 문단 다수 **이면서** 합니다체 문단 <3 — 해라체 소스(`_ko.md` 뉴스 번역 관례)의 어미를 상속한 문체 위반.

```bash
# 해설판별 문단 어미 레지스터 카운트 (읽기 전용, 근사 휴리스틱)
for f in outputs/*/*_ko_explained.md; do [ -f "$f" ]||continue
  hae=$(grep -vE '^[[:space:]]' "$f" | grep -vE '^(#|\||>|!|\`|-|[0-9]+\.)' | grep -cE '(었다|았다|한다|이다|된다|났다|왔다|랐다|셨다|없다|있다)\.?\s*$')
  hap=$(grep -vE '^[[:space:]]' "$f" | grep -vE '^(#|\||>|!|\`|-|[0-9]+\.)' | grep -cE '(습니다|ㅂ니다|입니다|합니다|됩니다|랍니다|어요|아요|지요|죠)[.?!]?\s*$')
  if [ "$hae" -ge 4 ] && [ "$hap" -ge 3 ]; then echo "DUP_REGISTER  hae=$hae hap=$hap : $(basename "$(dirname "$f")")"
  elif [ "$hae" -ge 4 ] && [ "$hap" -lt 3 ]; then echo "TONE_HAERACHE hae=$hae hap=$hap : $(basename "$(dirname "$f")")"
  fi
done
```
- **False-positive 함정 (실측)**: ① "\~된다"로 끝나는 **논문 제목 헤딩**을 문단으로 세지 않도록 헤딩/표/인용/목록 줄을 먼저 걸러라 (위 스크립트의 `grep -v`). ② **직접인용**("…라고 말했다"의 인용 내부)은 해라체가 정당 — 플래그된 편은 해당 문단을 열어 인용인지 확인한 뒤 결함 확정.
- 정형 비유마커 잔존 스캔(보너스): `grep -c '비유로 설명하면\|비유하자면' <exp>` — 라이브러리 전수 0 이 정상 (2026-07 소급 제거 완료).

## Reference Scan Scripts

These are read-only. Run from the repo root. Adjust `outputs archives` as needed.

**Master classification sweep:**
```bash
for base in outputs archives; do [ -d "$base" ] || continue
  for d in "$base"/*/; do d="${d%/}"; bn=$(basename "$d"); case "$bn" in .*) continue;; esac
    # D0: video 폴더는 생성 검사 제외 (이 분기 없으면 18개 오분류)
    if grep -q '"doc_type": *"video"' "$d/paper_meta.json" 2>/dev/null; then echo "VIDEO               | $bn"; continue; fi
    exp=$(find "$d" -maxdepth 1 \( -name '*_ko_explained.md' -o -name '*_explained.md' \) 2>/dev/null|head -1)
    aud=$(find "$d" -maxdepth 1 -name '*_ko_audio.md' 2>/dev/null|head -1)
    src=$(find "$d" -maxdepth 1 -name '*_ko.md' ! -name '*_explained.md' ! -name '*_audio*.md' 2>/dev/null|head -1)
    [ -n "$src" ] || src=$(find "$d" -maxdepth 1 -name '*.md' ! -name '*_ko*.md' ! -name '*_explained.md' ! -name '*_backup_*.md' ! -name '*_audio*.md' 2>/dev/null|head -1)
    pdf=$(find "$d" -maxdepth 1 -name '*.pdf' 2>/dev/null|head -1)
    if [ -z "$src" ]; then echo "ORPHAN              | $bn"; continue; fi
    sig=$(grep -cE 'arXivLabs|제출 이력|Submission history|BibTeX|서지 도구|북마크|^초록:|Connected Papers|alphaXiv' "$src")
    L=$(wc -l <"$src")
    if [ "$sig" -ge 10 ]; then
      pg=""; [ -n "$pdf" ] && pg=$(pdfinfo "$pdf" 2>/dev/null | awk '/Pages/{print $2}')
      echo "ABSTRACT_ONLY(sig=$sig,L=$L,pdf=${pg:-none}p) | $bn"; continue
    fi
    [ -z "$exp" ] && { echo "NEEDS_EXPLAINER     | $bn"; continue; }
    [ -z "$aud" ] && { echo "NEEDS_AUDIO         | $bn"; continue; }
    echo "OK                  | $bn"
  done
done
```

**Stale narration sweep (sidecar freshness):**
```bash
python3 - <<'EOF'
import json,hashlib,glob,os
for meta in glob.glob('outputs/*/*_ko_audio*.meta.json')+glob.glob('archives/*/*_ko_audio*.meta.json'):
    d=os.path.dirname(meta)
    try: m=json.load(open(meta))
    except Exception: print(f"BAD_SIDECAR  {meta}"); continue
    src=os.path.join(d, m.get('source_path',''))
    if not os.path.isfile(src): print(f"STALE(no-src) {meta}"); continue
    if m.get('source_size')!=os.path.getsize(src) or \
       (m.get('source_sha256') and m['source_sha256']!=hashlib.sha256(open(src,'rb').read()).hexdigest()):
        kind='BRIEF' if 'brief' in meta else 'AUDIO'
        print(f"STALE_{kind} | {os.path.basename(d)}")
EOF
```

**Audio image-embedding gap (re-derive AUDIO_IMG_GAP):**
```bash
for base in outputs archives; do for f in "$base"/*/*_ko_audio.md; do [ -f "$f" ]||continue
  dir=$(dirname "$f"); exp=$(find "$dir" -maxdepth 1 -name '*_ko_explained.md'|head -1); [ -n "$exp" ]||continue
  ia=$(grep -cE '!\[\]\(' "$f"); ie=$(grep -cE '!\[' "$exp")
  if [ "$ie" -gt 0 ] && [ "$ia" -eq 0 ]; then
    loc=$(grep -oE '!\[[^]]*\]\(images/[^)]+\)' "$exp" | grep -v 'images/)' | wc -l)   # embeddable local refs
    ext=$(grep -cE '!\[[^]]*\]\(https?://' "$exp")
    echo "[src ${ie}img local=${loc} ext=${ext}] $(basename "$dir")"
  fi
done; done
# local>0 → real gap to fix; local=0 & ext>0 (or broken) → legit describe-only exception
```

**Audio cleanliness violations:**
```bash
for base in outputs archives; do for f in "$base"/*/*_ko_audio.md "$base"/*/*_ko_audio_brief.md; do [ -f "$f" ]||continue
  n=$(grep -cE '\$\$|\$[^$]+\$|\\\(|\\\[|^\s*\|.*---|^```|\[[0-9]+\]|\[\^|<sup|<span|<br|</?[a-zA-Z]|\]\(#|https?://' "$f")
  a=$(grep -cE '!\[[^]]+\]\(' "$f")
  [ "$n" -ne 0 ] || [ "$a" -ne 0 ] && echo "VIOLATION crit=$n alt=$a : $(basename "$f")"
done; done
```

**Leftover .part / cruft:**
```bash
find outputs archives -maxdepth 2 \( -name '*.part' -o -name '*_backup_*.md' -o -name '*.md.bak*' -o -name '*.red-*.md' -o -name '*.render.md' \) 2>/dev/null
```

## Gotcha: URL-first abstract trap (critical institutional knowledge)

When `config.json` has **URL-first extraction enabled**, the converter, given a `pfmcp-*-arxiv.org.pdf` (or any arxiv-sourced PDF), will **scrape the arxiv.org abstract page HTML instead of converting the PDF body** — producing a ~190-line abstract scrape *even though the PDF is the real full multi-page paper*. Converter log tell:
```
Step 1: Converting PDF to Markdown...
URL-first enabled, trying HTML extraction: https://arxiv.org/abs/XXXX
URL-first extraction complete (NNNN chars)
```

**Consequence:** moving such a PDF to `newones/` for "reprocessing" just **regenerates the same abstract** (and burns translation API). So the naive fix ("move PDF → newones → get full paper") does NOT work while URL-first is on.

**Correct remediation (only with user go-ahead):**
1. Confirm the PDF is genuinely full text: `pdfinfo` page count + `pdftotext -f 1 -l 1` shows paper body (not arxiv web UI).
2. Disable URL-first in `config.json` (or force PDF conversion / use mineru on the PDF directly) so the converter parses the PDF body.
3. Only then reprocess via `newones/`. Watch `docker compose logs -f paperflow-converter` to confirm it converts the PDF (not HTML).
4. Once the full paper MD lands, hand to `paper-explainer` then `paper-audio-korean`.

If you can't/shouldn't change config, **flag ABSTRACT_ONLY folders for the operator with the page-count evidence** and stop — do not loop PDFs through `newones/`.

## Output: the Validation Report

Default deliverable is a concise report (print to chat; optionally save to `VALIDATION_REPORT.md` only if the user asks). Structure:

```
## PaperFlow Output Validation — <date>

총 폴더: N (outputs M / archives K) · VIDEO V (생성검사 제외)

### 정상 (OK): X
### 조치 필요
- NEEDS_EXPLAINER (n): <목록>
- NEEDS_AUDIO (n): <목록>
- STALE_AUDIO / STALE_BRIEF (n): <목록>          ← 해설판 수정 후 재생성 대상
- DUP_REGISTER / TONE_HAERACHE (n): <목록 + hae/hap 카운트>  ← 문단 열어 직접인용 예외 확인 후 확정
- AUDIO_IMG_GAP (n, 실제 갭만): <목록>   ← describe-only 예외는 별도로 구분
- COVERAGE_SUSPECT (n): <목록 + 헤딩 커버리지 대조 결과>
### 문제 / 정리 후보 (파괴적 — 확인 필요)
- ABSTRACT_ONLY (n): <폴더 | 시그니처수 | 소스줄수 | PDF페이지수>
- ORPHAN (n): <목록>
- DUP_FOLDER (n): <NFC/NFD·아포스트로피 쌍>
- LOCATION_COLLISION (n): <outputs·archives 동시 존재 쌍 + 정본 판단 근거>
- IMG_BROKEN (n): <목록>
- CRUFT (.part/backup/bak/red/render) (n): <목록>
### 권고 조치
- (예) ABSTRACT_ONLY 27건: PDF는 전문이나 URL-first 모드로 초록만 생성됨 → config URL-first 비활성화 후 재변환 권장
- (예) NEEDS_EXPLAINER 5건 → paper-explainer 배치
- (예) STALE_AUDIO 18건 → 오디오 배치가 sidecar freshness 로 자동 재생성 (수동 조치 불필요, 확인만)
- (예) describe-only 예외 3건(외부 URL/깨진 참조) → 정상, 조치 불필요
```

Always separate **non-destructive recommendations** (run explainer/audio) from **destructive ones** (delete/move), and require explicit confirmation for the latter.

## Operational Notes

- **Batch generation after validation**: when handing many folders to `paper-explainer`/`paper-audio-korean`, the main agent writes files directly; sub-agents can't reach write-permission prompts when backgrounded, and long papers (>~50KB) overflow sub-agent output limits — process the largest section-by-section in the main agent.
- **Scan both `outputs/` and `archives/`** — archived papers also need explainers/audio.
- **describe-only exceptions are permanent**: AUDIO_IMG_GAP folders whose images are all external URLs or broken refs will keep showing in the gap scan forever; record them once (e.g. in `HANDOFF.md`) so they aren't re-investigated each audit.
- **Don't recreate state files** just to write a report unless asked; if `HANDOFF.md`/`STATUS.md` exists, append findings there.

## Quality Checks (for the validator's own run)

- [ ] Scanned both outputs/ and archives/, skipped `.`-folders.
- [ ] **D0 video branch actually executed in the sweep** (video folders reported as VIDEO, not NEEDS_*).
- [ ] Hangul-named folders resolved via `find` (no NFC/NFD path misses); bracket-named folders iterated safely (no glob interpolation).
- [ ] ABSTRACT_ONLY backed by signature count AND (when PDF present) page-count evidence.
- [ ] Web articles NOT misflagged as ABSTRACT_ONLY (arXiv-sig = 0 ⇒ valid).
- [ ] COVERAGE_SUSPECT confirmed by heading-coverage diff, not by ratio alone (저비율 논문 다수가 legitimate).
- [ ] DUP_REGISTER / TONE_HAERACHE flags manually spot-checked for 직접인용·헤딩 false positives before reporting as defects.
- [ ] AUDIO_IMG_GAP separates real gaps (local images exist) from describe-only exceptions (external/broken).
- [ ] No destructive action taken without explicit user confirmation and an evidence list shown first.
