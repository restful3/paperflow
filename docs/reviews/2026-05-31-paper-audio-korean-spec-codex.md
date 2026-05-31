# PaperFlow 신규 스킬 설계 스펙 리뷰 — Codex

검토 대상: `docs/superpowers/specs/2026-05-31-paper-audio-korean-design.md`

판정: **REFINE**

## High

1. **`_ko_audio.md`는 현재 viewer/MCP 스캔에서 영어 MD로 오분류됩니다.**

   스펙은 viewer 연동을 범위 밖으로 둔다고 하지만, 출력 파일을 `outputs/` 최상위 논문 폴더에 두는 순간 기존 스캔 대상이 됩니다. 현재 `viewer/app/services/papers.py`의 파일 감지는 `_ko_explained.md`, `_explained.md`, `_ko.md`, `.md` 순서입니다. `foo_ko_audio.md`는 `_ko.md`도 `_explained.md`도 아니므로 일반 `.md`로 떨어져 `md_en=True`가 됩니다(`papers.py:535-544`, `766-773`). `get_md_en_path()`와 `save_markdown(..., "en")`도 같은 조건이라 `foo_ko_audio.md`를 영어 원문으로 반환하거나 덮어쓸 수 있습니다(`papers.py:925-927`, `973-975`). RAG 청크 생성도 `.md` 중 `_ko.md`가 아니면 영어 후보로 잡습니다(`chat.py:157-164`). MCP zip도 `include_translation=false`일 때 `_ko_audio.md`를 거르지 못합니다(`mcp_zip.py:42-48`).

   권장 수정안: 둘 중 하나를 스펙에 명시해야 합니다.
   - 안전한 선택: 출력 위치를 논문 폴더 직하위가 아닌 `audio/` 또는 `.audio/` 하위 디렉터리로 변경해 기존 viewer 스캔에서 제외합니다.
   - `_ko_audio.md`를 유지하려면 구현 범위에 viewer/backend의 명시적 exclude를 포함합니다. 최소 수정 대상은 `_paper_info()`, `_resolve_result()`, `get_md_en_path()`, `save_markdown()`, `chat.load_paper_chunks()`의 후보 선택, `mcp_jobs._paper_has_ko_md()`의 주석/판정, `mcp_zip`의 include_translation gating입니다. detection order 문서도 `_ko_audio.md`를 `.md`보다 먼저 제외한다고 갱신해야 합니다.

2. **부분 생성 파일을 완성본으로 skip할 수 있습니다.**

   스펙 §5는 `_ko_audio.md`가 있으면 무조건 skip한다고 되어 있습니다. 그런데 §8은 section-safe append 저장을 허용합니다. 긴 논문 변환 중 중단되면 불완전한 `_ko_audio.md`가 남고, 다음 batch 실행은 이 파일을 완성본으로 오판해 영구 누락을 만들 수 있습니다.

   권장 수정안: section-safe 출력은 `<basename>_ko_audio.md.part`에 쓰고 모든 검증 통과 후 atomic rename으로 `_ko_audio.md`를 만들도록 하세요. 또는 파일 말미에 `<!-- paper-audio-korean: complete source_sha=... -->` 같은 completion marker와 source hash/mtime을 기록하고, skip 조건을 "완성 marker가 있고 source보다 최신"으로 바꾸세요.

3. **소스 정책의 2단계 의존이 실패 모드를 충분히 정의하지 않습니다.**

   §5는 해설판이 없으면 `paper-explainer`를 먼저 호출한다고만 합니다. 기존 `paper-explainer`는 긴 문서를 section-safe로 append하고 완료 리포트에 line ratio/section coverage를 보고하는 운영형 스킬입니다. 중간 실패, 부분 `_ko_explained.md`, 이미 존재하지만 품질이 낮거나 오래된 해설판, `_ko.md`만 있는 폴더에서의 재시도 기준이 없습니다. 또한 §1은 "해설판(또는 번역본)"이라고 하지만 §5는 번역본을 직접 소스로 쓰지 않는다고 하여 정책이 충돌합니다.

   권장 수정안: 두 단계를 명확히 분리하세요.
   - Phase 1: `_ko_explained.md`가 없거나 incomplete marker/coverage 실패면 `paper-explainer`를 실행한다.
   - Phase 2: 해설판 완료 검증이 통과한 경우에만 audio 변환을 시작한다.
   - 실패 시 `_ko_audio.md`를 만들지 않고 `.part`와 실패 사유만 남긴다.
   - "번역본 직접 변환"을 정말 금지할지, 사용자가 명시적으로 빠른 듣기판을 원하면 `_ko.md` 직접 변환을 허용할지 결정해 §1/§5 표현을 맞춘다.

4. **검증 기준이 완전 낭독판 보장을 하기에는 부족합니다.**

   §9의 grep 0건 체크는 "날것의 문법이 남았는지"만 확인합니다. LLM이 표/수식/그림을 통째로 빠뜨려도 `$$`, `![](`, `|---|`가 0건이면 통과합니다. 특히 표를 1~3문장으로 줄이라는 §6 규칙은 큰 실험 표에서 핵심 수치 누락을 만들 가능성이 큽니다.

   권장 수정안: 변환 전 source inventory를 만들도록 스펙에 추가하세요.
   - 헤딩 목록, 표 개수와 caption/근처 문맥, 이미지 개수와 caption, 수식 블록 개수, 코드 fence 개수, 각주 개수를 기록한다.
   - 출력에서는 각 항목이 자연어 문장으로 대응됐는지 체크한다. 예: "표 3", "그림 2", "식 1" 같은 레이블 또는 명시적 대응 표.
   - line/character ratio만 보지 말고 섹션별 coverage를 확인한다. 제거 대상 섹션은 예외 목록으로 기록한다.
   - grep 체크에는 `^````, `<br`, `</?[a-zA-Z]`, raw markdown link, bare URL, 남은 `$...$`/`\(...\)`도 포함한다.

## Medium

1. **코드 블록과 프롬프트/알고리즘 블록 처리 규칙이 없습니다.**

   실제 `outputs/REACT..._ko.md`에는 긴 prompt/code fence가 다수 있고, Search-o1 계열에는 알고리즘/프롬프트 텍스트가 있습니다. 현재 §6은 수식/표/그림/인용만 다루며 §9도 code fence 잔존을 검사하지 않습니다.

   권장 수정안: 별도 규칙을 추가하세요.
   - 짧고 핵심인 의사코드: 단계별 자연어 목록으로 변환한다.
   - 긴 prompt/log/code dump: "이 블록은 WebShop 실험용 프롬프트이며, 사용자의 목표 확인, 검색, 관찰, 최종 선택 순서로 구성됩니다"처럼 목적과 구조를 설명하고, 재현에 필요한 핵심 문구만 낭독 친화적으로 발췌한다.
   - raw appendix 성격이면 원문 전체 보존 대신 "듣기판에서는 구조와 핵심만 설명했다"고 명시한다.
   - 완료 검증에 `^```` 0건을 추가한다.

2. **표 규칙이 데이터 보존과 충돌합니다.**

   §6은 모든 표를 1~3문장으로 요약하라고 합니다. 그러나 LongLM/SelfExtend 예시의 benchmark 표, Search-o1의 대형 성능 표처럼 행/열별 비교가 논문의 주요 근거인 경우 1~3문장 요약은 "완전 낭독판" 원칙과 충돌합니다.

   권장 수정안: 표 유형별 정책으로 나누세요. glossary/비유 표는 문단이나 목록으로 풀고, 핵심 실험 표는 "최고 성능, 기준선 대비 차이, 예외, 대표 수치"를 포함한 4~8문장 설명을 허용합니다. 표 안의 수식과 `<br>`는 자연어로 풀되, 핵심 수치는 반드시 남기는 기준을 둬야 합니다.

3. **각주/인용 제거가 본문 의미 손실을 만들 수 있습니다.**

   §6은 `<sup>N</sup>` 각주와 `[1]`을 전부 제거한다고 합니다. 단순 citation marker는 제거해도 되지만, footnote 본문에는 실험 조건, 예외, 데이터셋 설명이 들어갈 수 있습니다.

   권장 수정안: "각주 표식은 제거, 각주 본문이 설명/제한/실험 조건이면 해당 문단에 자연어로 병합, 순수 서지 정보면 삭제"로 바꾸세요. 인용도 모든 author-year를 제거하기보다 선행 연구 비교가 의미를 갖는 문장은 "기존 연구들" 또는 "저자들이 비교한 선행 방법"으로 자연어화하는 기준이 필요합니다.

4. **batch 후보/소스 선택 정책이 paper-explainer보다 덜 구체적입니다.**

   paper-explainer는 batch에서 source MD 조건, `*_ko_explained.md` 부재, 최신 source 1개 선택, `_ko.md` 우선, non-backup exclusion을 명확히 둡니다. 새 스펙은 "소스 MD가 있는 폴더"와 "`_ko_audio.md`가 없는 후보"만 말해, `_ko_ko_explained.md` 같은 기존 이상 파일, backup, stale audio, archives/outputs 중복, hidden/symlink 안전성 처리가 빠져 있습니다.

   권장 수정안: paper-explainer batch 규칙을 그대로 복사한 뒤 audio용 조건을 추가하세요. 특히 `_backup_`, `.bak`, `_ko_audio.md`, `_ko_audio.md.part`, `_mdlint_report.json` exclusion과 "source보다 audio가 오래되면 재생성" 기준을 넣는 것이 좋습니다.

5. **YAML 헤더 1회 요구가 듣기 품질과 충돌할 수 있습니다.**

   §7은 source YAML을 복사한다고 합니다. Quarto용 `format/html/toc/embed-resources` 헤더는 md-to-html에는 유용하지만, raw markdown을 iPhone에서 열어 듣는 경우 낭독될 수 있습니다. 반대로 HTML 변환을 염두에 두면 YAML이 필요합니다.

   권장 수정안: 목적을 분리하세요. raw TTS 우선이면 YAML을 생략하거나 최소 `lang: ko`만 허용합니다. md-to-html 호환을 우선하면 YAML은 유지하되 "렌더된 HTML에서 듣는다"를 전제로 명시하고, raw markdown 직접 낭독은 권장하지 않는다고 적어야 합니다.

## Low

1. **스킬 discoverability 문서 갱신이 빠져 있습니다.**

   README의 "Claude Code Skills" 섹션은 현재 `paper-explainer`, `md-to-html`만 나열합니다. 신규 스킬을 구현한다면 README와 CLAUDE.md의 output structure/suffix 표에도 `paper-audio-korean`과 `_ko_audio.md` 정책을 추가해야 합니다. 특히 viewer에서 제외할지, subdir에 둘지 결정한 뒤 문서화가 필요합니다.

2. **스펙 상태가 리뷰 전부터 "승인됨"입니다.**

   문서 line 3이 이미 "상태: 승인됨"입니다. 이번 리뷰에서 High 이슈가 있으므로 구현 전 상태는 "Draft" 또는 "Refinement required"로 낮추는 편이 맞습니다.

3. **약어 음차 규칙은 paper별 pronunciation map이 필요합니다.**

   "RoPE → 로프", "MoE → 모이" 같은 일반 규칙은 유용하지만 모델명/벤치마크/방법명은 논문마다 다릅니다. 변환 시작 시 "용어/약어 낭독 사전"을 만들고 본문 전체에서 일관 적용하도록 추가하면 품질이 안정됩니다.

## 잘 된 점

- 핵심 철학이 명확합니다. 수식/표/그림을 placeholder로 지우지 않고 의미 있는 audio description으로 바꾸겠다는 방향은 PaperFlow의 해설판 품질 목표와 잘 맞습니다.
- `paper-explainer`의 section-safe, batch 1개 처리, TUI 안정성 정책을 재사용하려는 선택은 현실적입니다.
- viewer/HTML/mp3 생성을 분리한 범위 설정은 기능을 작게 시작하려는 의도가 분명합니다. 다만 파일이 `outputs/`에 생기는 순간 viewer/backend와 상호작용하므로 suffix 안전성만은 범위 밖으로 둘 수 없습니다.

## 구현 단계 이관 판정

**REFINE**

현재 스펙은 목적과 변환 철학은 좋지만, `_ko_audio.md`가 기존 viewer/MCP 파일 감지와 충돌하는 문제가 구현 전에 반드시 정리되어야 합니다. 또한 partial output skip, code block 처리, coverage 검증을 보강해야 "완전 낭독판"이라는 약속을 운영상 지킬 수 있습니다. 위 High 항목을 반영한 뒤 구현으로 넘기는 것이 적절합니다.
