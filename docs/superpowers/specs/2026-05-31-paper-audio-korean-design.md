# 설계 스펙 — `paper-audio-korean` 듣기 낭독판 변환 스킬

_작성일: 2026-05-31 · 상태: **Draft (Codex Round 2 반영)**_

> **⚠️ 설계 변경 (2026-05-31, B-full):** 이 스펙은 처음 `audio/` 하위 디렉터리 방식(백엔드 변경 0)으로 작성되었으나, 사용자 결정으로 **폴더 직하위 `<basename>_ko_audio.md` + viewer/MCP 1급 포맷 통합**으로 전환되었다. 따라서 본문 중 "`audio/` 하위 디렉터리에 두어 회피", "백엔드 변경 없음" 류 서술은 이 전환으로 **대체**되었다 — 실제 출력 위치는 논문 폴더 직하위이고, viewer/backend가 `_ko_audio.md`를 인식하도록 수정되었다. 최종 동작은 `.claude/skills/paper-audio-korean/SKILL.md` 와 `CLAUDE.md` 를 따른다.


> 리뷰 트레일:
> - `docs/reviews/2026-05-31-paper-audio-korean-spec-codex.md` (Round 1, REFINE) — High 4 / Medium 5 / Low 3 전부 검증·반영(v2)
> - `docs/reviews/2026-05-31-paper-audio-korean-spec-codex-2.md` (Round 2, REFINE) — High #1 충돌 해소 확인. 남은 High 1 / Medium 3 / Low 2 검증·반영(v3)

## 1. 목적

해설판(`_ko_explained.md`)을 **아이폰 음성(사파리 "화면 읽어주기" 등)으로 들었을 때 이해되는** 한국어 낭독판으로 변환한다.

핵심 철학은 **시각장애인용 오디오 디스크립션(audio description)**: 눈으로 보는 요소(수식·표·그림·코드)를 단순 제거하거나 "수식입니다" 같은 placeholder로 처리하지 않고, **"어떤 수식인지·무엇을 보여주는지"를 들어서 이해되는 자연어 맥락**으로 옮긴다.

이 스킬은 요약본이 아니라 **완전 낭독판**이다. 소스의 모든 섹션·내용을 빠짐없이 담되, 귀로 듣기 좋은 형태로 변환한다.

**듣기 파일은 항상 해설판 기반이다.** 번역본(`_ko.md`)은 해설판 생성의 입력일 뿐, 듣기 파일의 직접 소스가 되지 않는다 (해설판이 없으면 §5에 따라 먼저 생성). 빠른 듣기를 위한 "번역본 직접 변환"은 이번 범위에서 제외한다.

## 2. 배경 / 문제

`outputs/` 의 기존 마크다운 파일들은 아이폰 듣기 기능으로 듣기에 부적합하다. 표본 조사(6개 `_ko.md`)에서 확인된 듣기 부적합 요소:

| 요소 | 듣기 시 문제 |
|------|--------------|
| 수식 블록 `$$…$$` / 인라인 `$x$` | TTS가 LaTeX 원문 낭독 또는 묵음 |
| 마크다운 표 `\|…\|` | 셀·`\|`·`<br>`·`$\rightarrow$` 가 그대로 낭독 |
| 코드/프롬프트 블록 ` ``` ` | 코드·로그가 그대로 낭독 (REACT 16개, Search-o1 등) |
| 이미지 `![](…)` | 소리로 무의미 + 파일명 낭독 위험 |
| 인용/각주 `[1]`, `(Author, 2023)`, `<sup>` | "브래킷 1 브래킷", 앵커 링크 낭독 |
| HTML 태그 `<span id>`, `<b>`, `<br>` | 흐름 차단 |
| 목차(점선+페이지번호) | 점·숫자 나열만 낭독 |
| 미번역 영어/약어 | 한국어 TTS 오발음/철자 낭독 |
| 문어체·만연체 | 귀로 따라가기 어려움 |

→ 원본은 그대로 두고, 듣기 최적화 버전을 별도로 생성하는 스킬이 필요하다.

## 3. 범위

### 포함 (In scope)
- 듣기 낭독판 마크다운 파일 1개 생성 (위치·이름은 §5/§7)
- 해설판 소스 우선, 없으면 paper-explainer로 생성 후 변환
- 오디오 디스크립션 변환 규칙 적용
- 구현 시 README/CLAUDE.md 문서 갱신 (§10, Low #1)

### 제외 (Out of scope) — YAGNI
- HTML 변환 (필요 시 사용자가 기존 `md-to-html` 스킬을 별도 실행)
- 뷰어·백엔드 코드 변경 — **출력을 논문 폴더 직하위가 아닌 `audio/` 하위 디렉터리에 두어** 기존 viewer/MCP 파일 감지(`papers.py` `_paper_info`/`_resolve_result`/`get_md_en_path`/`save_markdown`, `chat.load_paper_chunks`, `mcp_zip` gating)를 코드 수정 없이 회피한다 (§5, High #1). 모든 감지 스캔이 비재귀 `iterdir()`임을 확인함.
- 실제 음성(mp3/오디오) 생성 — 아이폰 TTS가 담당, 스킬은 텍스트까지만
- 별도 파이썬 스크립트 — SKILL.md 하나로 완결
- 번역본(`_ko.md`) 직접 변환 경로

## 4. 아키텍처

접근법 **A: LLM 섹션별 변환** (paper-explainer 패턴 재사용).

- 별도 스크립트 없음. **SKILL.md 한 개**를 Claude가 따르는 LLM 주도 변환.
- paper-explainer와 동일한 **섹션별 처리 + section-safe 저장** 패턴 → 긴 논문 토큰 오버플로 방지.
- Claude Code 안에서 완결. 입력 1개 폴더 → 출력 파일 1개.

선택 근거:
1. "맥락 있는 자연어 묘사"는 LLM 이해가 필수 — 순수 정규식으로는 불가.
2. paper-explainer가 이미 섹션별·section-safe로 긴 문서를 다루므로 검증된 구조 재사용.
3. 정규식 전처리는 마크다운 변형이 많아 깨짐 위험 > 이득.

## 5. 입력 소스 해석 & 생성 수명주기

### 출력 위치 (High #1 반영)
```text
출력 디렉터리: <paper_dir>/
출력 파일:     <paper_dir>/<basename>_ko_audio.md
작성 중 임시:  <paper_dir>/<basename>_ko_audio.md.part   (section-safe append 대상)
완료 메타:     <paper_dir>/<basename>_ko_audio.meta.json   (sidecar — 본문 밖)
```
`audio/` 하위에 두는 이유: viewer/MCP의 마크다운 감지는 모두 논문 폴더 직하위만 비재귀 스캔하므로, 하위 디렉터리의 파일은 영어 원문으로 오분류되거나 덮어써지지 않는다. (이미 `images/` 하위 디렉터리가 같은 방식으로 스캔에서 제외됨.)

### 2단계 수명주기 (High #3 반영 / R2 High #1 반영)
```text
Phase 1 — 해설판 확보:
  _ko_explained.md 없음 또는 legacy completion validation 실패
    → paper-explainer 스킬 실행하여 _ko_explained.md 생성·완료
  legacy completion validation 통과해야만 Phase 2 진입
Phase 2 — 듣기 변환:
  검증된 _ko_explained.md 를 소스로 <basename>_ko_audio.md.part 에 섹션별 작성
  전체 완료 + §9 검증 통과 시 → .part 를 <basename>_ko_audio.md 로 atomic rename
  + <basename>_ko_audio.meta.json (sidecar) 기록
실패 시:
  _ko_audio.md(최종본)를 만들지 않는다. .part 와 실패 사유만 남긴다.
```

**Legacy completion validation (R2 High #1):** 기존 `paper-explainer`는 completion marker를 쓰지 않으며 기존 해설판에도 marker가 없다(검증 확인). 따라서 해설판 소스의 완료 판정에 marker를 요구하지 **않는다**. 대신 다음으로 판정한다 — `_ko_explained.md` 존재 + 비어 있지 않음 + 제목/본문 정상 + 소스 대비 heading coverage 통과(References/감사의 글 등 예외 제외) + 주요 섹션 존재. (completion marker 개념은 audio 산출물에만 적용 — 아래 sidecar.)

### Skip / 재생성 조건 (High #2 반영 / R2 Medium #1 반영 — sidecar)
완료 메타데이터는 **최종 `.md` 본문이 아니라 sidecar `<basename>_ko_audio.meta.json`** 에 둔다. 최종 `.md` 본문은 순수 낭독 텍스트만 담는다(본문 내 HTML comment marker는 일부 뷰어의 화면 읽기에서 낭독될 수 있어 금지).
```text
<basename>_ko_audio.md (최종본) 존재 AND
  sidecar.status == "complete" AND
  sidecar 의 source 메타가 현재 _ko_explained.md 와 일치(최신)   → skip
그 외(.part만 존재 / sidecar 없음 / 소스가 더 최신/변경) → 재생성
```
- sidecar 내용: `{ "status": "complete", "source_path", "source_mtime", "source_size", "source_sha256" }` — freshness는 mtime 단독이 아니라 size/sha256 병행으로 판단 (R2 Low #1).
- `.part` 단독 존재는 "미완성"이며 절대 완성본으로 skip하지 않는다.

### Batch 모드 (대상 미지정 시, Medium #4 반영)
paper-explainer batch 규칙을 그대로 계승하고 audio 조건을 추가:
- `outputs/`·`archives/` 비재귀 스캔, **적격 논문 폴더**만 후보 (`.`으로 시작하는 폴더 제외, 소스 MD가 있는 폴더만, 빈/설정/심볼릭 폴더 제외)
- exclusion: `_backup_`, `.bak`, `_mdlint_report.json`, 그리고 audio 산출물 `*_ko_audio.md`, `*.part`
- `<basename>_ko_audio.md` 가 (완성 marker 기준) 없는 후보 중 **최신 소스 1개** 선택
- 소스보다 audio가 오래되면 재생성 후보로 본다
- 소스 없는 고아 폴더는 건너뛰고 리포트에 명시 (생성/이름변경/삭제 금지)

## 6. 변환 규칙 — 오디오 디스크립션

**최상위 원칙: placeholder 금지.** "수식입니다 / 그림입니다 / 표입니다" 처럼 요소 종류만 알리는 낭독은 금지. 항상 "어떤 수식·무엇을 보여주는 그림·무엇을 말하는 표"인지 의미를 전달한다.

**변환 시작 시 준비물 (Low #3 반영):**
- **용어/약어 낭독 사전**을 먼저 만든다. 모델명·벤치마크·방법명·약어를 수집해 한국어 낭독 표기를 1회 정하고, 본문 전체에서 일관 적용한다.

| # | 요소 | 규칙 |
|---|------|------|
| 1 | **수식** (`$$…$$`, 인라인 `$…$`) | placeholder 금지. **"이 수식은 ~를 ~로 계산한다는 뜻입니다"** 로 자연어 낭독. 해설판의 기존 수식 설명 우선 활용, 없으면 맥락 읽어 생성. 변수 기호는 한국어로("d는 임베딩 차원") |
| 2 | **표** (마크다운 `\|…\|`) — **유형별 정책** (Medium #2) | (a) glossary/비유/용어 표 → 문단 또는 목록으로 풀어 낭독. (b) **핵심 실험·성능 표 → 4\~8문장**으로 "최고 성능, 기준선 대비 차이, 예외, 대표 수치"를 반드시 포함해 서술 (1\~3문장 강제 요약 금지 — 완전 낭독판 원칙). 셀·`\|`·`<br>`·표 안 수식은 자연어로 풀되 핵심 수치는 보존 |
| 3 | **그림/이미지** (`![](…)`) | 이미지 구문 제거. **"그림 N은 ~를 보여줍니다"** 로 무엇을 나타내는지 묘사 (캡션+본문 맥락 기반). 순수 장식 이미지는 제거 |
| 4 | **코드/프롬프트/알고리즘 블록** (` ``` `) (Medium #1) | (a) 짧은 핵심 의사코드 → 단계별 자연어 목록. (b) 긴 prompt/log/code dump → "이 블록은 ~용 프롬프트로, ~순서로 구성됩니다"처럼 목적·구조를 설명하고 재현에 필요한 핵심 문구만 낭독 친화적으로 발췌. (c) raw appendix 성격이면 "듣기판에서는 구조와 핵심만 설명했다"고 명시 |
| 5 | **인용·링크** (`[1]`, `(Author, 2023)`, `[text](#anchor)`) | citation marker 제거. 선행 연구 비교가 의미를 갖는 문장은 "기존 연구들"/"저자들이 비교한 선행 방법"으로 자연어화 |
| 6 | **각주** (`<sup>N</sup>` 및 Markdown footnote `[^1]` / `[^1]: …`) (Medium #3 / R2 Low #2) | 각주 표식 제거. **각주 본문이 실험 조건·예외·데이터셋 설명이면 해당 문단에 자연어로 병합**, 순수 서지 정보면 삭제 |
| 7 | **영어 용어/약어** | 첫 등장: **"대규모 언어 모델(LLM, 엘엘엠)"** 음차 병기 → 이후 한국어. 약어는 낭독 사전대로 음차("RoPE → 로프"). 고유명사·모델명은 자연스러운 음차 |
| 8 | **문어체·만연체** | 긴 문장 분할, 능동·구어체("~합니다"). 귀로 한 번에 이해되게 |

### 제거 대상 (듣기 무가치 — 통째 삭제)
- 목차(점선 `. . . .` + 페이지번호)
- 페이지 마커 / `<span id="page-…">` / 기타 HTML 앵커
- 저자 소속줄, 이메일, URL
- 학회 푸터 ("Proceedings of the … Copyright …")
- 참고문헌(References / Bibliography) 목록 섹션 전체
- 감사의 글(Acknowledgements)

## 7. 출력 / 형식

- 경로/파일명: §5 (`<basename>_ko_audio.md`)
- **YAML 헤더 (Medium #5 / R2 Medium #3 반영):** raw 마크다운을 아이폰에서 직접 듣는 것이 기본 경로이므로 **헤더는 생략한다**(기본값). `lang: ko` 한 줄조차 두지 않는다 — 불완전 YAML이거나 raw TTS에서 낭독될 수 있기 때문. 언어 메타데이터가 필요하면 sidecar(`_ko_audio.meta.json`)에 둔다. HTML로 듣고 싶으면 사용자가 md-to-html 변환 단계에서 front matter를 주입하는 것을 전제로 한다.
- 제목: `# <원제목> — 듣기판`
- 배너 blockquote(선택): 이 문서가 듣기용 변환본임을 1\~2줄 안내
- **소스 섹션 구조 유지** — 완전 낭독판이므로 섹션·소절 누락 금지 (§6 제거 대상 섹션 예외)
- 완료 메타데이터는 본문이 아닌 sidecar(`_ko_audio.meta.json`)에 기록 (§5)
- 마크다운만 (HTML·뷰어 연동 없음)

## 8. 모드 / 운영 안정성

paper-explainer 운영 정책 계승:
- **Auto 모드**: 전체 자동 변환, 섹션 순차 처리
- **Section-safe 모드**: 긴 논문은 `.part` 파일에 섹션별 append 저장, 중단 시 다음 턴에 이어쓰기. 전체 완료·검증 후에만 최종본으로 atomic rename (§5)
- **TUI 신뢰성**: 파일 읽기/쓰기 권한 프롬프트는 Yes / "allow all" 우선
- **Quality-first wait**: `Actioning…` 류 상태로 중단 판단 금지

## 9. 검증 (완료 기준)

### 변환 전 — Source Inventory 작성 (High #4 반영)
소스(`_ko_explained.md`)에서 다음을 기록한다:
- 헤딩 목록
- 표 개수 + 각 표의 caption/근처 문맥
- 이미지 개수 + caption
- 수식 블록 개수
- **인라인 수식/변수 표현 (R2 Medium #2)**: 모든 `$x$`를 1개씩 세지 말고, **문단별로 "이 문단의 인라인 수식·변수가 자연어로 풀렸는가"** 를 확인 (인라인 수식은 변수 정의·조건·지표명을 담으므로 누락 차단 필요)
- 코드 fence 개수
- 각주 개수 (`<sup>` 및 Markdown `[^...]`)

### CRITICAL (반드시 통과)
- [ ] 출력에 다음이 **0건** (grep): `$$`, 인라인 `$...$` / `\(...\)`, 마크다운 표 구분선(`|---|`), ` ``` ` (code fence), `![](`, `[N]` 형태 인용, Markdown footnote `[^...]` / `[^...]:`, `<sup>`/`<span`/`<br`/`</?[a-zA-Z]` HTML 태그, `](#`·raw markdown link, bare URL
- [ ] **항목별 대응 검증**: Source Inventory의 각 표·그림·수식·코드·각주가 출력에서 자연어 문장으로 대응됐는지 확인 (통째 누락 차단)
- [ ] **섹션별 coverage**: 소스의 섹션 헤딩이 모두 출력에 존재 (§6 제거 대상은 예외 목록으로 기록)

### Important
- [ ] 표본 3개 섹션에서 수식·표·그림·코드가 placeholder가 아닌 **의미 있는 서술**로 변환됐는지 확인
- [ ] 핵심 실험 표에서 대표 수치가 보존됐는지 확인 (Medium #2)
- [ ] 영어 약어가 첫 등장 시 음차 병기 + 낭독 사전 일관 적용 (Low #3)
- [ ] 최종 파일명이 `..._ko_audio.md`, sidecar `_ko_audio.meta.json`에 `status=complete` + source freshness(mtime/size/sha256) 기록
- [ ] 최종 `.md` 본문에 메타데이터/HTML comment marker가 **없음** (순수 낭독 텍스트)
- [ ] YAML 헤더 없음 (기본값)

## 10. 문서화 / 후속

### 구현 시 함께 (Low #1)
- README "Claude Code Skills" 섹션에 `paper-audio-korean` 추가
- CLAUDE.md output structure / 파일 suffix 표에 `*_ko_audio.md` 정책 추가 (viewer 스캔에서 제외됨을 명시)

### 이번 범위 외 (후속 고려)
- 듣기판을 뷰어에서 직접 보려면 별도 suffix 감지 + 토글
- 듣기판 → HTML 자동 변환 파이프라인 연결
- batch 자동화 / cron 연동
