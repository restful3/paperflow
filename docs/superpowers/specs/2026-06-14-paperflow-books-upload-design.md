# PaperFlow Books — 업로드 + 인제스천 가동 설계

- **작성일**: 2026-06-14
- **상태**: 승인됨 (사용자 검토 대기)
- **대상**: PaperFlow v2.7+ / Books 기능 (Phase 1·2a·2b·2c 완료 이후)
- **한 줄 요약**: 뷰어 `/books`에 "새 책" 업로드 UI를 추가하고, 컨버터가 `newbooks/`를 감시·처리하도록 가동해 사용자가 브라우저에서 챕터 PDF를 올려 책을 만들 수 있게 한다.

---

## 1. 배경 / 문제

현재 Books는 **브라우즈만** 가능하다 (목록/상세/챕터 뷰어/카드·리스트뷰). **업로드가 없다.** 두 가지가 모두 빠져 있다:

1. **업로드 UI 부재** — 책을 만들 화면이 없다. (논문은 `/api/upload` + Upload 탭 보유.)
2. **인제스천 미가동** — 책 입력 경로(`newbooks/<책>/NN_*.pdf`)를 처리하는 `run_book_watch.sh`가 docker-compose에 배선되지 않아 **이 배포에서 안 돌고 있다.** 컨버터 이미지도 Phase 1b 이전 버전(stale)이라 `book_ingest.py`/`process_pdf_to_output_dir`가 없다.

따라서 "업로드 버튼"만으로는 부족하다 — UI + 인제스천 가동을 함께 한다.

### 논문 vs 책 입력 모델 (왜 그대로 못 베끼나)

| | 논문(Papers) | 책(Books) |
|---|---|---|
| 입력 단위 | PDF 1개 | 챕터 PDF 여러 개 (순서 있음) + 책 메타 |
| 입력 폴더 | `newones/` | `newbooks/<책 slug>/NN_*.pdf` |
| 처리 | `run_batch_watch.sh` (컨버터에서 상시) | `run_book_watch.sh` (미배선) |
| 업로드 UI | 드롭존(Upload 탭) | **없음 → 본 설계로 신규** |

## 2. 목표 / 비목표

**목표**
1. `/books`에서 제목·저자·연도 + 챕터 PDF 여러 개를 한 번에 올려 새 책을 만든다.
2. 업로드한 챕터의 순서를 사용자가 재정렬할 수 있고, 그 순서가 보존된다.
3. 컨버터가 `newbooks/`를 감시·처리해 실제 책(`books/<slug>/…` + meta/state)을 생성한다.
4. 진행 상황은 이미 구현된 브라우즈 UI(챕터 상태 배지)로 드러난다.

**비목표 (YAGNI)**
- 기존 책에 챕터 단위 추가/재처리 UI (후속).
- 책 업로드용 실시간 처리 큐 UI (논문식). v1은 목록/배지로 충분.
- 책 표지 업로드 (수동 `cover.jpg`는 기존대로; UI 업로드는 후속).
- EPUB / 비-PDF 입력.
- 컨버터 워치 통합을 넘어선 인프라 재설계.

## 3. 아키텍처

```
[뷰어 /books "+ 새 책" 모달]
   │  POST /api/books/upload  (multipart: 제목/저자/연도 + 챕터파일[] + 순서)
   ▼
newbooks/<slug>/01_<원본>.pdf, 02_<원본>.pdf, … + book.json   ← 뷰어가 파일만 씀 (GPU 없음)
   │
   ▼
[컨버터 통합 워치]  newones/(논문) + newbooks/(책) 동시 감시
   │  book_ingest.py → mt.process_pdf_to_output_dir(mode="book_chapter")  (_gpu_lock 직렬화)
   ▼
books/<slug>/<chapter_id>/…  +  book_meta.json (durable) + book_state.json (cache)
   │
   ▼
[Phase 2c 브라우즈 UI가 결과 렌더 — 챕터 배지 pending→converted→complete]
```

**격리 단위**
- **업로드 수신**(뷰어): 파일 검증 + `newbooks/` 기록만. GPU·변환 로직 없음.
- **인제스천**(컨버터): 기존 `book_ingest.py`(Phase 1b) 그대로. 본 설계는 **가동**만 한다(코드 변경 최소).
- **결과 표시**(뷰어 브라우즈 UI): 이미 존재. 변경 없음.

## 4. 업로드 UX

- `/books` 컨트롤 영역에 **"+ 새 책"** 버튼 → 모달 오픈.
- 모달 필드:
  - **제목** (필수, 텍스트)
  - **저자** (선택)
  - **연도** (선택, 숫자)
  - **챕터 파일** (필수, PDF 다중 선택 / 드래그앤드롭)
- 선택된 파일은 **순서 목록**으로 표시 (파일명 자연정렬 기본). 각 항목 **위/아래 이동 + 제거**.
- **제출**:
  1. 제목을 slug화 (논문 `sanitize_folder_name` 규칙 준용, 최대 길이/금지문자).
  2. `newbooks/<slug>/` 생성 (충돌 시 `-2`, `-3` suffix — 기존 `newbooks/`·`books/`·`book_archives/` 어느 쪽과도 충돌 회피).
  3. 확정 순서대로 각 파일을 `NN_<sanitized-원본명>.pdf`로 저장 (NN = 01부터 zero-pad).
  4. `book.json` 기록: `{title, author, year}` (book_id는 ingest 때 생성되므로 생략 가능; book_ingest/`init_book_meta`가 처리).
  5. 성공 토스트 + 모달 닫기 + 목록 새로고침.
- 업로드 후 책은 워치가 폴더를 처리하면서 목록에 등장. 챕터 배지가 상태를 반영.

## 5. 백엔드 — 뷰어 엔드포인트

`POST /api/books/upload` (multipart/form-data)

**입력**
- `title` (str, required)
- `author` (str, optional)
- `year` (int, optional)
- `files` (UploadFile[], required, ≥1) — 클라이언트가 **확정 순서대로** 전송 (전송 순서 = 챕터 순서).

**동작**
1. 인증 (`get_current_user_api`).
2. 검증: title 비어있지 않음 · files ≥1 · 각 파일 `.pdf` 확장자 + content-type · 파일당 크기 상한 200MB (논문 업로드와 동일 상수 재사용).
3. slug = `sanitize_folder_name(title)`; `newbooks/`, `books/`, `book_archives/` 중 어디든 같은 이름 존재 시 `-2`… suffix.
4. `newbooks/<slug>/` 생성, 각 파일을 `f"{i:02d}_{sanitize(orig_stem)}.pdf"` (i=1..N)로 저장.
5. `book.json`에 `{title, author, year}` 기록.
6. `{"ok": true, "slug": slug, "chapters": N}` 반환.

**삭제/취소**: v1 **제외** (후속). 처리-진행 판정(이미 컨버터가 집었는지)이 모호해 안전한 취소는 별도 설계가 필요. v1은 업로드 후 잘못 올렸으면 `/books`에서 책 삭제(이미 구현된 `DELETE /api/books/{book}`)로 정리.

서비스는 `viewer/app/services/books.py`에 `save_book_upload(title, author, year, files_in_order)` 추가, 라우터는 `viewer/app/routers/books.py`에 엔드포인트 추가.

## 6. 인제스천 가동 (컨버터)

- **컨버터 엔트리포인트**가 **두 워치를 동시 실행**: 신규 래퍼 `run_all_watch.sh`가 `run_batch_watch.sh`(논문)와 `run_book_watch.sh`(책)를 각각 백그라운드로 기동하고 `wait`한다 (기존 두 스크립트는 불변 — 수술적). docker-compose 컨버터 `command`를 `./run_all_watch.sh`로 교체.
- **GPU 직렬화**: 두 경로 모두 `mt.process_pdf_to_output_dir` → `_gpu_lock`(공유 flock, TTS와도 상호배제)을 거치므로 동시 두 워치가 안전하게 직렬화된다. 별도 조치 불필요.
- **컨버터 이미지 재빌드**: build context `.` + `COPY . .` 라 재빌드만으로 Phase 1b 책 코드(`book_ingest.py`/`book_store.py`/`run_book_watch.sh`/갱신된 `main_terminal.py`)가 포함된다.
- **book_ingest 변경 없음**: dedup/충돌/size-stable/순서 파싱(NN_)은 이미 구현됨. 업로드가 `NN_` 프리픽스로 저장하므로 순서가 그대로 해석된다.

## 7. 인프라 변경 (docker-compose)

| 변경 | 이유 |
|------|------|
| 뷰어 서비스에 `./newbooks:/data/newbooks` 볼륨 추가 | 업로드 엔드포인트가 `newbooks/`에 써야 함 (현재 미마운트) |
| 컨버터 `command`를 통합 워치로 교체 | `newbooks/`도 감시 |
| 컨버터 이미지 재빌드 | Phase 1b 책 코드 포함 |

> 재빌드 시 논문 워치가 잠깐 끊기지만 큐가 비어 있으면 무해. 컨버터 재시작은 되돌릴 수 있는 운영 작업.

## 8. 에러 처리

- **업로드 검증 실패** → HTTP 400 + 토스트 (제목 없음 / PDF 0개 / 비-PDF / 크기 초과).
- **slug 충돌** → suffix로 회피 (덮어쓰기 절대 안 함).
- **절반 복사 파일** → `book_ingest`의 size-stable 게이트가 미처리로 미룸 (업로드는 서버가 완결 저장하므로 사실상 무관하지만 게이트는 그대로 유효).
- **재업로드(같은 내용)** → 같은 `source_sha256` → `book_ingest`가 skip. 내용 다르면 `needs_review`.
- **챕터 1개 실패** → 그 챕터만 `book_state` `error`, 나머지·책 정상 (챕터 격리).
- **GPU 점유(TTS)** → 책 변환이 `_gpu_lock` 대기. 느릴 수 있음(운영 조건, 결함 아님).

## 9. 상태 피드백 (v1 최소)

- 업로드 직후 책이 `/books` 목록에 등장 (워치가 `book_meta`를 만드는 즉시).
- 챕터 상태는 상세 페이지(`/books/{book}`)의 배지로 `pending`→`converted`→`complete` 표시 (이미 구현, `book_state` 기반).
- 사용자가 새로고침으로 진행 확인. **논문식 실시간 처리 큐 UI는 v1 제외** (추가 범위).

## 10. 테스트 전략

**뷰어 (유닛, GPU 불필요)**
- `save_book_upload`가 `newbooks/<slug>/NN_*.pdf`를 **확정 순서대로** 생성 + `book.json`(title/author/year) 기록.
- slug 충돌 시 `-2` suffix (기존 newbooks/books/book_archives 회피).
- 엔드포인트 검증: 제목 없음 → 400, PDF 0개 → 400, 비-PDF → 400, 크기 초과 → 400, 인증 없음 → 401.
- 파일명 sanitize (경로 traversal·금지문자 차단).

**컨버터**
- `book_ingest`는 Phase 1b 테스트로 커버됨 (재사용).
- 통합 워치 스크립트 스모크: 두 워치가 모두 기동되는지 (구문/프로세스 기동 수준).

**브라우저 (수동/반자동)**
- "+ 새 책" 모달 → 필드 입력 + 파일 다중 선택 → 재정렬 → 제출 → `newbooks/<slug>/`에 `01_*.pdf, 02_*.pdf` + `book.json` 안착 확인 (API/파일 점검).
- **GPU 풀 end-to-end**(실제 변환→번역→books/ 생성→UI 반영)는 **수동/운영 검증** (GPU + 시간 + TTS VRAM 경쟁). 자동 스위트 범위 밖임을 명시.

## 11. 파일 영향 요약

**신규**
- `viewer/app/templates/books.html` — "+ 새 책" 버튼 + 업로드 모달 + JS (uploadBook).
- (컨버터) `run_all_watch.sh` 또는 동등 — 두 워치 병렬 기동.

**수정**
- `viewer/app/services/books.py` — `save_book_upload(...)`.
- `viewer/app/routers/books.py` — `POST /api/books/upload`.
- `docker-compose.yml` — 뷰어 `newbooks` 볼륨, 컨버터 `command`.
- (재빌드) 컨버터 이미지.

**변경 없음**
- `book_ingest.py` / `book_store.py` / `main_terminal.py` (가동만, 코드 불변).
- Phase 2c 브라우즈 UI(목록/상세/챕터뷰어) — 결과를 이미 렌더.

## 12. 미해결 / 후속

- 기존 책에 챕터 추가·재정렬·재처리 UI.
- 책 표지 업로드 UI.
- 업로드 처리 진행 실시간 표시(SSE/폴링 큐).
- 업로드 취소(`DELETE`) 처리-진행 판정 정교화.
