# PaperFlow Books Upload v2 — papers 업로드와 정렬 설계

- **작성일**: 2026-06-14
- **상태**: 승인됨 (사용자 검토 대기)
- **대상**: PaperFlow v2.7+ / Books Upload(이미 구현됨) 위에 UX 정렬
- **한 줄 요약**: 책 업로드를 논문 업로드와 정렬한다 — 모달 대신 **Upload 탭**, **드래그앤드롭**, 그리고 **경량 처리 큐/로그 뷰**.

---

## 1. 배경 / 문제

Books Upload(직전 작업)는 동작하지만 논문 업로드와 UX가 다르다. 사용자 요청: 도메인상 불가피한 차이(제목 폼 필요·다중 파일+순서)는 두되, **v2 선택 차이**를 논문에 맞춘다.

| | 논문 Upload | 책 Upload (현재) | v2 목표 |
|---|---|---|---|
| 진입점 | Upload 탭 | "+ 새 책" 버튼 → 모달 | **Upload 탭** |
| 입력 | 드래그앤드롭 존 | 파일 피커 | **드롭존 + 피커** |
| 진행 표시 | 처리 큐 + 로그 | 없음 | **경량 큐 + 로그** |
| 메타 폼 | 없음(AI 추출) | 제목/저자/연도 | 유지(도메인상 필요) |

## 2. 목표 / 비목표

**목표**
1. `/books`에 **Upload 탭** 추가. 업로드 폼을 모달에서 탭 본문으로 이동(모달·"+ 새 책" 버튼 제거).
2. Upload 탭에 **드래그앤드롭 존**(PDF 필터) + 파일 피커 폴백.
3. **경량 처리 뷰**: `newbooks/` 스캔 + `book_state` 상관으로 대기/처리 중 책·챕터 표시 + 공유 컨버터 로그.

**비목표 (YAGNI)**
- 논문식 **단계별 진행바**(stage_num/total_stages) — 무거운 옵션, 제외. 코어스 상태 배지만.
- 업로드 시 **중복-책 경고 UI** — 인제스천의 sha skip은 그대로 동작, UI는 후속.
- **컨버터 스크립트/상태파일 변경** — 본 작업은 뷰어 전용. `run_book_watch.sh`/`book_ingest.py` 무수정.
- 처리 취소(DELETE) — 후속.

## 3. 핵심 사실 (설계 근거 — 확인됨)

- **챕터 PDF는 `newbooks/`에 영속**한다. `run_book_watch.sh`는 처리 후 PDF를 이동/삭제하지 않고, 재처리는 `book_ingest.classify_chapter`의 **sha-skip**으로 막는다. 따라서 `newbooks/<책>/*.pdf` 스캔은 "대기"가 아니라 "그 책의 전체 챕터 입력"이다 → **완료/대기 판정은 `book_state`/`book_meta`에서** 한다.
- **상태 파일은 공유**다. 책 변환도 `process_pdf_to_output_dir`(논문과 동일 함수)를 거쳐 `logs/processing_status.json`의 `current_file`을 갱신한다 — 논문/책이 한 파일을 공유.
- **로그**: `get_latest_log()`는 `logs/paperflow_*.log`(공유 컨버터 로그)를 읽는다. 책 전용 로그 파일은 없으므로 이 뷰는 **공유 컨버터 로그(best-effort)**다.
- 뷰어는 이제 `newbooks/`를 마운트(직전 작업)하므로 스캔 가능. `settings.newbooks_dir` 사용.

## 4. 아키텍처

```
[Upload 탭]
 ├── 업로드 폼(제목/저자/연도 + 드롭존/피커 + 순서 목록 + 업로드)  ──POST /api/books/upload (기존)──▶ newbooks/<slug>/
 └── 처리 패널 ──GET /api/books/processing (신규, 폴링)──▶ newbooks 스캔 + book_state 상관
                ──GET /api/logs/latest (기존, 재사용)──▶ 공유 컨버터 로그
```

뷰어 전용. 컨버터는 직전 작업의 통합 워치 그대로 처리. 결과는 Books 탭(목록/배지)에도 그대로 반영.

## 5. UI — `books.html`

### 5.1 탭 바
현재 `Books / Archived` → `Books / Archived / Upload` (논문 탭 스타일 재사용). `tab` 상태에 `'upload'` 추가.

### 5.2 Upload 탭 본문 (`x-show="tab === 'upload'"`)
- **업로드 폼**: 기존 모달 내용을 이식 — 제목(필수)/저자/연도, 챕터 목록(▲▼✕ 재정렬), 업로드 버튼. **모달 래퍼와 "+ 새 책" 버튼은 제거.**
- **드롭존**: `@dragover.prevent`/`@dragleave`/`@drop.prevent="handleDrop($event)"` + `.drop-active` 하이라이트(스타일을 `books.html`의 `{% block head %}`에 추가). 드롭존 안에 `<input type=file multiple>` 폴백.
- **처리 패널**: 폼 아래. `processingBooks` 폴링 결과를 행으로(책 제목 + 대기/처리 중 챕터 수 + 상태 배지). 비어 있으면 "처리 중인 책 없음". 하단에 공유 로그(`logContent`, `<pre>`).

### 5.3 booksApp() 상태/메서드
- 상태: 기존 업로드 필드 유지(`upTitle/upAuthor/upYear/upFiles/_fileKey/uploading`) + `dropActive`, `processingBooks: []`, `bookLog: ''`, `_procTimer`.
- 메서드: `handleDrop(e)`(드롭 파일을 `onFilesSelected`와 동일 처리), `switchTab` 확장(`'upload'` 진입 시 폴링 시작/타 탭 이탈 시 정지), `loadProcessing()`(`/api/books/processing` + `/api/logs/latest` 폴링). `openUpload`는 제거(탭이 대체), `submitUpload` 성공 시 모달 close 대신 폼 리셋 + `loadProcessing()`.

## 6. 백엔드 — 신규 (뷰어 전용)

### 6.1 `book_svc.list_book_processing() -> list[dict]`
`newbooks/`를 스캔해 **아직 완료되지 않은** 책·챕터를 반환.

로직:
- `newbooks/`의 각 책 폴더에 대해: `book.json`에서 제목, `NN_*.pdf` 챕터들을 순서대로 수집.
- 같은 slug의 `books/<slug>/`가 있으면 `book_state`(또는 `get_book`)로 각 챕터 상태를 읽음. 없으면 모든 챕터 = `queued`.
- 챕터 상태 매핑: `book_state`에 `complete`/`converted` → 완료(제외 후보), 없음 → `queued`, `logs/processing_status.json`의 `current_file`과 챕터 base_name 일치 → `processing`, `error`/`needs_review` → 그대로.
- **모든 챕터가 완료된 책은 결과에서 제외**(처리 패널은 in-flight만).
- 반환: `[{ "slug", "title", "chapters": [{"chapter_id", "status"}], "pending": N, "processing": bool }]`.

### 6.2 라우터 `GET /api/books/processing`
`get_current_user_api` 인증 → `book_svc.list_book_processing()` 반환. (로그는 기존 `GET /api/logs/latest` 재사용 — 신규 불필요.)

## 7. 데이터 흐름 (처리 패널)

1. Upload 탭 진입 → `loadProcessing()` 즉시 + 4초 폴링(기존 systemStat 케이던스와 동일) 시작.
2. `GET /api/books/processing` → in-flight 책·챕터 리스트 렌더.
3. `GET /api/logs/latest` → 공유 로그 tail 렌더.
4. 타 탭 이탈/`destroy` → 폴링 정지.

## 8. 에러 처리

- `/api/books/processing` 실패 → 패널 빈 상태 + 조용히(토스트 남발 금지, 폴링이라). 
- `newbooks/` 없음/빈 → 빈 리스트.
- 깨진 `book.json` → 제목 fallback(slug).
- 폴링은 `apiFetch` 401 → `/login`.

## 9. 테스트 전략

**뷰어 서비스 (유닛, GPU 불필요)**
- `list_book_processing`: newbooks에 책 2개(하나는 book_state 일부 complete, 하나는 book/ 없음) → in-flight만, 완료 책 제외, queued/complete 상태 정확. 빈 newbooks → `[]`. 깨진 book.json → slug fallback.

**뷰어 라우터**
- `GET /api/books/processing` 200 + 형태, 401(미인증).

**페이지 (`test_books_pages.py`)**
- `/books`에 Upload 탭 마커, 드롭존(`drop-active`/`handleDrop`), 처리 패널(`processingBooks`), 그리고 모달/"+ 새 책" **부재** 단언.

**브라우저 e2e**
- Books→Upload 탭 전환 → 드롭(또는 피커)으로 PDF 추가 → 재정렬 → 업로드 → 처리 패널에 책 등장 → cleanup.

## 10. 파일 영향

**수정**
- `viewer/app/templates/books.html` — 탭 추가, Upload 탭 본문(폼 이식 + 드롭존 + 처리 패널), 모달·"+ 새 책" 제거, head에 `.drop-active`, booksApp 상태/메서드.
- `viewer/app/services/books.py` — `list_book_processing()`.
- `viewer/app/routers/books.py` — `GET /api/books/processing`.
- `viewer/tests/test_books_upload.py` / `test_books_pages.py` — 테스트.

**변경 없음**
- 컨버터(`run_*_watch.sh`/`book_ingest.py`/`main_terminal.py`), docker-compose, `/api/books/upload`(기존), `/api/logs/latest`(기존).

## 11. 미해결 / 후속

- 책 전용 로그(공유 로그 한계 해소), 단계별 진행바, 중복-책 경고 UI, 처리 취소.
