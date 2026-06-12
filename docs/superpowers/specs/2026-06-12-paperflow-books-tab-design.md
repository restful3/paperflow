# PaperFlow Books 탭 — 설계 문서 (v2)

- **작성일**: 2026-06-12
- **상태**: Draft v2 (코덱스 리뷰 반영 — 사용자 검토 대기)
- **대상**: PaperFlow v2.7+
- **한 줄 요약**: 사람이 챕터별로 미리 나눈 PDF를 책 단위로 묶어 번역·해설판·듣기판·듣기 축약판을 만들고, 챕터별 진도를 관리하는 "Books" 탭을 추가한다.
- **개정 이력**: v1 → v2 (2026-06-12, 코덱스 peer 리뷰 반영: identity/root 분리 원칙, 경로 추상화 Phase 신설, book_meta durable/cache 분층, process 파이프라인 파라미터화, dedup/충돌 정책 추가, glossary·auto-cover 후속화, 누락요소 보강).

---

## 1. 배경과 목표

PaperFlow는 현재 **논문 1편 = outputs/의 폴더 1개** 모델로 동작한다. 책은 이 모델에 자연스럽게 맞지 않는다 — 책은 여러 챕터의 모음이고, "어디까지 읽었는지"가 챕터 단위로 관리되어야 한다.

다행히 기존 자산(`~/workspace/ml4t/source/Chan E. Quantitative Trading...`)을 보면, **책의 각 챕터 폴더가 paperflow 논문 폴더와 파일 포맷이 동형**이다 (`.md` / `_ko.md` / `_ko_explained.md` / `.pdf` / `.json` / `images/`). 이 사실이 설계의 핵심 지렛대다.

### 목표

1. 사람이 챕터별로 분할한 PDF를 **책 단위로 묶어** 일괄 처리한다.
2. 각 챕터를 **번역 → 해설판 → 듣기판 → 듣기 축약판** 으로 만든다.
3. 챕터별 **읽은 위치(진도)** 를 메타데이터로 관리하고, 책 단위로 집계한다.
4. 듣기판은 **그림·표를 유지하되 낭독판답게 모든 그림·표에 음성 설명**을 붙인다.
5. 뷰어에 **Books 탭**을 추가해 책 → 챕터 목록 → 챕터 뷰어로 탐색한다.

### 비목표 (YAGNI)

- **챕터 자동 검출은 하지 않는다.** 챕터 경계는 사람이 PDF를 미리 나눠서 정한다 (capture 워크플로우 계승).
- EPUB은 1차 범위 밖 (PDF 우선). 데이터 모델은 EPUB을 막지 않지만, 인제스천 어댑터는 PDF만 구현한다.
- 책 단위 RAG/통합 검색, 챕터 간 하이퍼링크, 책 추천 등은 후속 과제.
- 자동 책 표지 선정·교차챕터 용어집(glossary)은 1차 범위 밖 (Phase 3 이후).

---

## 2. 설계 접근 — "파일 포맷 동형 + identity 분리" 하이브리드 (접근 C)

세 가지 후보 중 **접근 C(하이브리드)** 를 채택하되, v1의 "챕터=논문 100% 동형"이라는 과한 표현을 코덱스 리뷰에 따라 **정확히 한정**한다.

| 접근 | 요지 | 채택 여부 |
|------|------|-----------|
| A. 최대 재사용 | 챕터를 논문과 완전 동일 저장, 책은 가리키기만 | 책 개념이 약함 |
| B. 신규 1급 타입 | 책 전용 데이터·뷰어·스킬 전부 신규 | 코드량 過, YAGNI 위반 |
| **C. 하이브리드** | **챕터 산출물은 논문과 파일 포맷 동형 + identity/root/경로해석은 분리** | **채택** |

> **핵심 원칙 (v2 — 코덱스 권고 수용)**: 챕터 산출물의 **파일 포맷**(파일명 규칙·디렉터리 레이아웃)은 논문 폴더와 동형으로 유지한다. **다만 경로 해석·목록화·archive/restore·progress·RAG/chat/audio job의 identity 는 paper 와 book_chapter 를 명시적으로 분리한다.** 시스템 내부는 항상 `doc_kind ∈ {paper, book_chapter}` 를 명시한다.

이렇게 한정하는 이유: 기존 코드는 폴더 구조보다 **`outputs`/`archives` 위치 + "paper name = 단일 디렉터리명" 가정**에 더 강하게 묶여 있다 (3.4, 6장). "100% 동형"을 밀면 paper 전용 작업(archive, duplicate, MCP result, TTS sweep)이 책 챕터를 오인하거나 책을 못 찾는다. 따라서 **파일 포맷은 재사용, identity·root 는 분리**가 정답이다.

---

## 3. 폴더 구조

### 3.1 입력: `newbooks/`

`newones/`(논문 워치)와 **별개의 입력 폴더**.

```text
newbooks/
  Chan - Quantitative Trading 2ed/     # 폴더 1개 = 책 1권 (폴더명 = 책 제목 기본 slug)
    book.json                          # (선택) {"book_id","title","author","year", "chapters":{...}}
    01_intro.pdf                       # 숫자 프리픽스 = 챕터 순서
    02_fishing_for_ideas.pdf
    03_backtesting.pdf
```

- 사람이 챕터 PDF를 **아무 때나** 떨어뜨린다 → 워치가 **챕터 단위로 증분 처리**한다.
- **챕터 순서**는 파일명의 선행 숫자(`01_`, `02_`...)로 결정. 프리픽스 없으면 자연 정렬(natural sort) 폴백.
- **챕터 식별자**(`chapter_id`/`dir` 이름)는 파일명에서 확장자를 뗀 sanitized 값으로 고정. 논문의 smart-rename 과 달리 **이름을 바꾸지 않는다**.
- **입력 readiness**: 사람이 `cp` 로 복사하는 중인 파일을 잡으면 안 된다. 워처는 PDF 의 (size, mtime) 가 **N초 간격 2회 연속 동일**할 때만 처리 대상으로 본다 (size-stable 게이트). `.part` 접미사도 무시.

### 3.2 출력: `books/`

`outputs/`와 **별개 트리**.

```text
books/
  Chan - Quantitative Trading 2ed/     # 책 폴더 (sanitized book slug; 내부 key 는 book_id)
    book_meta.json                     # durable 메타 + 챕터 목록 (4.1)
    book_state.json                    # rebuildable 캐시 (status/formats/집계) (4.2)
    book_glossary.json                 # 교차챕터 용어집 (Phase 3, 선택)
    cover.jpg                          # 책 표지 (수동 제공 우선; 자동선정은 후속)
    01_intro/                          # ★ 챕터 폴더 = 논문 폴더와 파일 포맷 동형
    │   ├── 01_intro.pdf / .md / _ko.md / _ko_explained.md
    │   ├── 01_intro_ko_audio.md / _ko_audio_brief.md
    │   ├── 01_intro.json / paper_meta.json / images/
    02_fishing_for_ideas/
    03_backtesting/
```

### 3.3 아카이브 루트 — top-level `book_archives/` (결정)

코덱스 권고 수용: `archives/` 아래에 mixed-type namespace(`archives/books/`)를 넣으면 archive/restore/delete 코드가 계속 예외를 먹는다. 대신 **top-level `book_archives/`** 를 둔다.

```text
book_archives/
  Chan - Quantitative Trading 2ed/     # 권 단위 아카이브 (책 폴더 통째로 이동)
```

이로써 기존 `archives/`(논문 전용)는 건드리지 않고, books 라이프사이클이 깔끔히 분리된다.

### 3.4 디렉터리 루트 요약 (config/Docker 반영 필수)

| 루트 | 용도 | 신규? | config | Docker volume |
|------|------|-------|--------|---------------|
| `outputs/` | 논문 출력 | 기존 | `outputs_dir` | 있음 |
| `archives/` | 논문 아카이브 | 기존 | `archives_dir` | 있음 |
| `newones/` | 논문 입력 워치 | 기존 | `newones_dir` | 있음 |
| **`books/`** | 책 출력 | **신규** | `books_dir` | **추가** |
| **`newbooks/`** | 책 입력 워치 | **신규** | `newbooks_dir` | **추가** |
| **`book_archives/`** | 책 아카이브 | **신규** | `book_archives_dir` | **추가** |

converter·viewer·tts 세 컨테이너 모두 `books`/`book_archives` 볼륨 마운트가 필요하다 (TTS 가 챕터 오디오를 생성/서빙해야 하므로 `paperflow-tts` 에도 books 루트 + sweep 대상 추가).

---

## 4. 데이터 모델 — durable / cache 분층

코덱스 지적 4 수용: v1 의 단일 `book_meta.json`(전부 캐시)은 durable 데이터를 유실시킬 위험이 있다. **durable 파일과 rebuildable 캐시 파일을 분리**한다.

### 4.1 `book_meta.json` — DURABLE (사람·파이프라인이 만든 장기 상태)

```json
{
  "schema_version": 1,
  "book_id": "book-chan-qt2ed",
  "title": "Quantitative Trading (2nd ed.)",
  "author": "Ernest P. Chan",
  "year": 2021,
  "cover": "cover.jpg",
  "created_at": "2026-06-12T09:00:00+09:00",
  "chapters": [
    {"order": 1, "chapter_id": "01_intro", "title": "The Whats, Whos, and Whys...",
     "source_pdf": "01_intro.pdf", "source_sha256": "ab12..."},
    {"order": 2, "chapter_id": "02_fishing_for_ideas", "title": "Fishing for Ideas",
     "source_pdf": "02_fishing_for_ideas.pdf", "source_sha256": "cd34..."}
  ]
}
```

- **절대 디스크 스캔으로 덮어쓰지 않는다.** 사람이 수정할 수 있는 권위 데이터(제목·저자·순서·book_id).
- `book_id`: durable 내부 key. `book.json` 에 있으면 그 값, 없으면 **최초 ingest 때 생성**(slug + 짧은 해시)해 여기에 고정. 폴더명은 display slug 일 뿐, 내부 식별은 항상 `book_id`.
- `source_sha256`: 챕터 PDF 내용 해시 → dedup/충돌 판정용 (5.4).

### 4.2 `book_state.json` — REBUILDABLE CACHE (디스크에서 재생성 가능)

```json
{
  "schema_version": 1,
  "chapters": {
    "01_intro": {
      "pipeline_status": "complete",
      "formats": {"en": true, "ko": true, "ko_explained": true,
                  "ko_audio": true, "ko_audio_brief": false},
      "updated_at": "2026-06-12T09:30:00+09:00"
    },
    "02_fishing_for_ideas": {"pipeline_status": "translating", "formats": {"en": true, "ko": false}}
  },
  "aggregate": {"chapters_total": 2, "chapters_complete": 1}
}
```

- **불일치 시 디스크 스캔으로 재생성**하는 대상은 **오직 이 파일**. `book_meta.json` 은 건드리지 않는다.
- `pipeline_status`(파이프라인 진행)와 `formats`(파일 존재 여부)를 **분리**(코덱스 지적: status 모델). `pipeline_status=complete` 의 정의는 **"번역까지 완료"**(Phase 1 기준). 해설/듣기/축약 존재 여부는 `formats` 로만 추적하고 `complete` 게이팅에 넣지 않는다. UI 토글 표시는 `formats` 에서 집계.

### 4.3 쓰기 안전성 (atomic + lock)

- **Atomic write**: 두 파일 모두 `*.tmp` 에 쓰고 `os.replace` 로 교체.
- **File lock**: 챕터별 fresh process 가 동시에 같은 책의 `book_state.json` 을 갱신할 수 있다 → **per-book file lock**(예: `books/<book>/.lock`)으로 read-modify-write 직렬화. lock 없으면 두 챕터 동시 처리 시 lost update.

### 4.4 진도 관리

- **별도 store `book_progress.json`** (논문 진도 JSON 과 분리). 키 충돌·escaping 문제를 피하려고 **중첩 구조**를 쓴다:
  ```json
  { "book-chan-qt2ed": { "01_intro": 100, "02_fishing_for_ideas": 35 } }
  ```
  (문자열 `book::chapter` 평탄화는 `::` 충돌 위험 — 코덱스 지적. 중첩 객체로 회피.)
- **책 레벨 진도**: `완료 표시 챕터 수 / 전체` + 현재 챕터 스크롤%. 즉석 집계. "이어읽기" = 최근 본 챕터 + 그 스크롤 위치.

### 4.5 schema 마이그레이션

`schema_version` 만으로는 부족 → **마이그레이션 규칙**을 둔다: 로더가 `schema_version < CURRENT` 를 만나면 정의된 업그레이드 함수를 순차 적용 후 atomic 재기록. v1 단계에선 `CURRENT=1` 이라 no-op 이지만, 훅은 처음부터 만든다.

---

## 5. 인제스천 파이프라인

### 5.1 워치 진입점

`newbooks/` 를 처리하는 진입점을 추가한다 (`run_book_watch.sh` 신규 vs 기존 워처 확장 — Phase 1b plan 에서 확정). **각 챕터 PDF 는 fresh 프로세스**(VRAM cleanup 필수).

증분 처리 단위 = 챕터 1개:

```text
newbooks/<Book>/NN_chapter.pdf 가 size-stable 로 확정됨
  → 책 폴더 books/<slug>/ 보장 (없으면 생성 + book_meta 초기화: book.json/폴더명 기반, book_id 확정)
  → dedup/충돌 판정 (5.4)
  → 챕터 폴더 books/<slug>/<NN_chapter>/ 생성
  → 챕터 파이프라인 실행 (5.3)  [doc_kind=book_chapter]
  → per-book lock 잡고 book_state.json 갱신 (status/formats) + book_meta.chapters[] 보강
  → 처리 끝난 소스 PDF 를 챕터 폴더로 이동
```

**책 식별**: 챕터 PDF 의 부모 폴더명을 **default slug** 로 쓰되, 내부 식별은 `book_meta.book_id`. 폴더명이 나중에 바뀌어도 같은 `books/<slug>/` 가 이미 있으면 그 book_id 를 따른다.

### 5.2 파이프라인 함수 분리 (Phase 1b 첫 작업)

코덱스 지적 6 수용: 현재 `process_single_pdf()` 는 `outputs/<base_name>` 하드코딩 + smart-rename/web search/duplicate/cover 가 한 함수에 엉켜 있다. **호출 전에 함수를 분리**한다.

```python
process_pdf_to_output_dir(
    pdf_path, output_dir, base_name, config,
    mode="paper" | "book_chapter",
)
```

- 기존 `process_single_pdf` 는 `outputs/<base>` 를 계산해 이 함수를 `mode="paper"` 로 호출하는 얇은 래퍼가 된다 (동작 불변 — 회귀 테스트로 보증).
- `mode="book_chapter"` 는 **smart-rename / web search / global duplicate / 챕터별 cover 를 끔**. status writer 는 book chapter key(book_id+chapter_id)를 받는다.
- CLI 진입도 `PAPERFLOW_TARGET_PDF` 단독이 아니라 `PAPERFLOW_OUTPUT_DIR`·`PAPERFLOW_BASE_NAME`·`PAPERFLOW_MODE` 를 받게 해 테스트 용이성 확보.

### 5.3 챕터 단계 매핑

| # | 단계 | 논문 | 책 챕터(`mode=book_chapter`) |
|---|------|------|------------------------------|
| 1 | PDF → MD | 그대로 | **그대로** (marker-pdf 기본; Mistral OCR 폴백은 후속) |
| 2 | Heading Fix | 그대로 | **그대로** |
| 3 | Metadata | 풀버전 | **경량**: 챕터 제목만. smart-rename **끔**. (제목 출처 우선순위 5.5) |
| 4 | Web Search | 함 | **스킵** |
| 5 | Duplicate | global | **책 내 dedup 으로 대체** (5.4) |
| 6 | Cover | 논문별 | **스킵** (책 표지는 수동 `cover.jpg`; 자동선정 후속) |
| 7 | Translation | 함 | **그대로** → `_ko.md` |
| 8 | Explainer | (스킬) | **Phase 3** → `_ko_explained.md` (book-explainer) |
| 9 | Audio | (스킬) | **Phase 3** → `_ko_audio.md` (book-audio, 6장) |
| 10 | Audio Brief | (스킬) | **Phase 3** → `_ko_audio_brief.md` |

Phase 1 의 `complete` = 1\~3,7 까지 (번역 완료). 8\~10 은 Phase 3.

### 5.4 dedup / 충돌 정책 (← v1 의 누락된 "6.5" 보강)

같은 `books/<slug>/<chapter_id>/` 에 챕터가 다시 들어올 때:

| 조건 | 동작 |
|------|------|
| 같은 `chapter_id` + `source_sha256` 동일 | **skip** (이미 처리됨) |
| 같은 `chapter_id` + `source_sha256` 다름 | 기본 **`needs_review`** 로 표시(자동 덮어쓰기 안 함). 명시적 `--replace`/UI 액션에서만 기존 백업 후 교체 |
| `order` 중복(두 챕터가 같은 번호) | **error** 로 표시하고 처리 보류 (사람이 프리픽스 정정) |
| 책 식별 모호(같은 slug 충돌) | slug 뒤에 `-2` 등 suffix (논문 폴더 규칙 준용), book_id 는 별개 유지 |

### 5.5 챕터 제목 출처 우선순위

`book.json` 의 `chapters[chapter_id].title` (사람 지정) > 단계 3 OCR/AI 추출 제목 > 파일명 유래(`01_intro` → "Intro"). 먼저 있는 것을 채택.

---

## 6. 경로 추상화 & 서빙 (Phase 1a — 최우선)

코덱스 지적 1·2·8 수용: **진짜 위험은 저장이 아니라 path abstraction**. 이것을 ingestion 보다 먼저 한다.

### 6.1 resolver 를 `*_from_dir` 하위 계층으로 분리

현재 `papers.py` resolver 는 `name: str` 만 받고 내부에서 `safe_paper_dir(name)`(outputs/archives 만 순회, 슬래시 거부)을 호출한다. 그대로는 챕터(`books/<book>/<chapter>`)를 못 서빙한다.

```python
# 신규 하위 계층 (dir 를 직접 받음, doc_kind 무관)
paper_info_from_dir(paper_dir, location, display_name) -> dict
get_md_ko_path_in_dir(paper_dir) -> Path | None
get_asset_path_in_dir(paper_dir, filename) -> Path | None
# ... 기존 resolver 들의 본체를 *_from_dir 로 이전

# 기존 paper API: safe_paper_dir(name) 후 *_from_dir 호출 (동작 불변)
# book chapter API: safe_book_chapter_dir(book, chapter) 후 같은 *_from_dir 호출
```

- 신규 안전 resolver: `safe_book_dir(book)`, `safe_book_chapter_dir(book, chapter)` — `book_archives/` 포함 2단계 경로를 검증(traversal/symlink escape 차단).
- `chat.py` 의 RAG/chat 도 `_resolve_paper_dir(paper_name)` 직결을 풀어 `*_from_dir`/dir 주입식으로.

### 6.2 viewer.html 재사용 — 복사 금지, API base 주입

현재 `viewer.html` JS 에 `/api/papers/${name}/...` 가 하드코딩돼 있다. Books 용으로 뷰어를 복사하지 말고, 템플릿 변수를 주입한다:

- `content_api_base` (예: `/api/papers/<name>` vs `/api/books/<book>/chapters/<chapter>`)
- `content_viewer_kind` (`paper` | `book_chapter`)
- `progress_key` (논문 name vs `{book_id, chapter_id}`)

### 6.3 라우팅 / 목록화 분리

- 신규 `books.py` 서비스: `list_books()`, `get_book(book)`, `get_chapter_info(book, chapter)`, book_meta/state 읽기·쓰기, 진도 집계.
- 신규 라우터: `/api/books`, `/api/books/{book}`, `/api/books/{book}/chapters/{chapter}/...` (md-ko / md-en / md-ko-explained / md-ko-audio / pdf / assets / progress).
- **asset 경로 rewriting**: 챕터 마크다운의 이미지(`![](images/..)`)는 `/api/books/<book>/chapters/<chapter>/assets/..` 로 rewrite.
- **`list_papers()` 격리 테스트**: 논문 스캐너는 `outputs/`·`archives/` 만 본다. `book_archives/` 를 top-level 로 분리했으므로 archives 오염은 원천 차단되지만, **회귀 테스트로 못박는다**(`list_papers(tab=archived)` 가 book 을 절대 포함 안 함).

---

## 7. 도서용 스킬 (Phase 3)

기존 `paper-explainer` / `paper-audio-korean` / `paper-audio-brief-korean` 의 **book-aware 변형**. 핵심 차이는 ① 교차챕터 맥락 ② 듣기판 그림·표 처리.

### 7.1 `book-explainer-korean`

`paper-explainer` 코어 재사용 + `book_glossary.json` 로 용어 일관성 강제 + (선택) 직전 챕터 1\~2줄 요약 주입. 출력: 챕터별 `_ko_explained.md`.

### 7.2 `book-audio-korean` (듣기판 — 핵심 규칙)

> **사용자 요구 (원문)**: "표가 그림이면 남기고, 만약 마크다운이면 그냥 설명, 그림도 단지 보여주는 게 아니라 낭독판답게 그림이나 표나 다 적절한 설명이 있어야 해."

규칙:

1. **이미지(그림 `![](...)`)**: 화면에 **유지**. 단, **각 그림 앞/뒤에 일반 문단(반드시 blockquote `>` 아님)으로 음성 설명**을 붙인다.
2. **이미지로 된 표**: 이미지이므로 유지 + 음성 설명.
3. **마크다운 표(`| ... |`)**: **제거**하고 설명 문장으로 풀어 낭독.
4. 그 외 본문은 듣기 좋은 한국어 낭독.

> **TTS/RAG 경계 (코덱스 지적 7)**:
> - TTS chunker 는 이미지 라인을 청킹 전 제거하므로 **이미지 markdown 자체는 낭독되지 않는다** — 그래서 설명 문단이 반드시 일반 문단이어야 TTS 가 읽는다. **blockquote 금지**(chunker 가 `>` 제외).
> - 이미지 경로는 책 라우트(`/api/books/.../assets/`)로 rewrite.
> - **기존 논문 듣기판과의 의도적 차이**: 논문 `_ko_audio.md` 는 "순수 낭독 텍스트(이미지 미포함)". 책 듣기판은 이미지를 유지한다. 이 분기를 CLAUDE.md 에 명문화(11장).
> - **RAG 제외**: 듣기/축약은 RAG 청크에서 제외(현 `chat.py` 가 suffix 로 제외). suffix 의존 대신 **`content_role ∈ {source, translation, explainer, audio, audio_brief}` 분류 helper** 로 통일해 누락 방지.

### 7.3 `book-audio-brief-korean`

7.2 산출물의 축약(핵심 동기·기여·방법 직관·주요 결과·한계). 7.2 의 그림·표 규칙 동일 적용. 출력 `_ko_audio_brief.md`.

### 7.4 용어집 누적 (별도 파일, Phase 3b)

`book_glossary.json` 으로 분리(코덱스 YAGNI 지적). 흐름: 챕터 N 번역 완료 → 핵심 용어 추출 → glossary 병합(**먼저 정해진 번역어 우선**) → 챕터 N+1 해설/듣기에 주입. Phase 1\~2 는 glossary 없이 챕터 독립 처리. Phase 3a(산출 안정화) 후 Phase 3b 에서 도입.

---

## 8. 뷰어 UI (Books 탭)

- **네비**: "Books" 탭 추가.
- **`/books`**: 책 카드(표지·제목·저자·진도%·챕터 수·상태). 정렬/검색은 papers 패턴 재사용.
- **`/books/{book}`**: 챕터 리스트(순서·제목·상태배지·진도%·이어읽기) + 책 메타 + 전체 진도 바.
- **챕터 뷰어**: 기존 `viewer.html` 을 API base 주입(6.2)으로 재사용 — MD/PDF/Split·해설 Easy·듣기·에디터·TOC·RAG 동작 + **브레드크럼**·**이전/다음 챕터**·(선택) 목차 사이드바.
- **듣기 토글 확장**: 듣기 모드에서 `전체 / 축약` 2단계.
- **Phase 2 검증 범위**: 토글은 **파일이 있을 때 표시/숨김**까지만. 도서용 생성(해설/듣기)은 Phase 3.

---

## 9. 라이프사이클 (archive / restore / delete)

코덱스 누락 지적 수용 — 권 단위 API·UI 를 명시.

- `POST /api/books/{book}/archive` → `books/<slug>/` 통째로 `book_archives/<slug>/` 로 이동.
- `POST /api/books/{book}/restore` → 역이동.
- `DELETE /api/books/{book}` → 영구 삭제 (확인 게이트).
- `POST /api/books/{book}/repair` → `book_state.json` 재생성(디스크 스캔). `book_meta.json`(durable)은 보존.
- 챕터 단위 삭제/재처리도 동일 패턴(선택, 후속).

---

## 10. 에러 처리

- **챕터 격리**: 한 챕터 실패는 그 챕터만 `pipeline_status=error`, 나머지·뷰는 정상.
- **VRAM**: 챕터마다 fresh 프로세스 cleanup.
- **포맷 누락**: 파일 없으면 토글 숨김.
- **state 불일치**: `book_state.json` 만 재생성(repair). durable 보존.
- **부분 입력**: 들어온 챕터까지만 표시, 책은 "처리 중".
- **입력 미완성 복사**: size-stable 게이트로 차단(3.1).

---

## 11. CLAUDE.md / 문서 갱신 항목

- "Output Structure" 에 `books/` · `book_archives/` · `newbooks/` · `book_meta.json`/`book_state.json` 추가.
- 책 듣기판이 **이미지를 유지**한다는 점(논문과의 의도적 차이) 명문화.
- File Naming & Detection 에 books 탐지 분리 + `doc_kind` 규칙 추가.
- config 루트 표(3.4)·Docker volume 갱신.
- 신규 스킬 3종 등록.

---

## 12. 테스트 전략

`Development Workflow`(테스트 우선) 준수. **Phase 별 게이트**.

**Phase 1a (경로/설정)**
- `Settings.books_dir/newbooks_dir/book_archives_dir` 존재.
- `safe_book_dir`/`safe_book_chapter_dir` 의 traversal·symlink escape 차단 (book·chapter·asset filename 각각).
- `*_from_dir` resolver 라운드트립.
- **`list_papers(tab=archived)` 가 book 을 절대 포함 안 함** (회귀).
- 기존 paper API 동작 불변 (회귀).

**Phase 1b (인제스천/저장)**
- 파일명 프리픽스 → 순서 정렬(폴백 포함).
- 2챕터 샘플 책 end-to-end → 챕터 폴더·`book_meta`/`book_state`·번역 산출.
- dedup/충돌 정책(skip/needs_review/order 중복 error) 단위 테스트.
- `book_meta`(durable) 보존 + `book_state` 재생성 분리.
- atomic write + per-book lock 하 동시 2챕터 갱신에 lost update 없음.
- size-stable 게이트(복사 중 파일 미처리).

**Phase 2 (뷰어)**
- 책→챕터 탐색, 진도 저장/복원(중첩 키), 이전/다음 챕터, 토글 표시/숨김.

**Phase 3 (스킬)**
- 듣기판: 모든 이미지 전후 N줄 내 **일반 문단(비 blockquote)** 설명 존재 + raw `| .. |` 표 부재 + 이미지 유지.
- glossary 일관성(같은 용어 동일 번역).

---

## 13. 단계화 (요약)

| Phase | 범위 | 게이트 |
|-------|------|--------|
| **1a** | settings/volumes/archive-root + `*_from_dir` resolver + `safe_book(_chapter)_dir` + list_papers 격리 | 12.Phase1a |
| **1b** | `process_pdf_to_output_dir` 분리 + newbooks 워치/증분 + book_meta/state + dedup | 12.Phase1b |
| **2** | Books 탭 UI(목록/상세/챕터뷰어 재사용) + 진도 + archive/restore/delete API | 12.Phase2 |
| **3a** | book-explainer / book-audio / book-audio-brief 산출 | 12.Phase3 |
| **3b** | `book_glossary.json` 누적 + 후속 챕터 주입 + 듣기 축약 토글 | 12.Phase3 |

> 우선순위(코덱스 권고): ① books/newbooks settings + Docker volume + archive root → ② papers.py resolver `*_from_dir` 분리 → ③ list_papers 격리 테스트 → ④ book_meta durable/cache 분리 + atomic + lock → ⑤ process 파라미터화 → ⑥ 그 다음 UI·스킬.

---

## 14. 미해결/후속 (열린 질문)

- **EPUB 어댑터**: 데이터 모델은 수용하나 인제스천 미구현.
- **Mistral OCR 폴백**: 스캔 품질 낮은 책용 (capture 계승). Phase 1 이후.
- **자동 책 표지 선정**: 수동 `cover.jpg` 우선, 자동은 후속.
- **책 단위 RAG**: 챕터 횡단 질의. 후속.
- **챕터 추가/재정렬 UI**: 현재 파일명 프리픽스로만.
- **워치 통합 vs 분리**: `run_book_watch.sh` 신규 vs 기존 워처 확장 — Phase 1b plan 에서 확정.
- **챕터 단위 재처리/삭제 UI**: 권 단위 우선, 챕터 단위는 후속.
