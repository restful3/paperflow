# 뷰어 — 메타데이터 보기 버튼·모달 (Design)

**날짜**: 2026-06-07
**대상**: 뷰어 화면(`viewer/app/templates/viewer.html`). 백엔드 무변경.

## 배경 / 문제

뷰어에는 글의 서지 메타데이터(저자·venue·연도·DOI·원문 URL 등)를 한눈에 볼 곳이 없다.
상단바에는 제목·doc_type 배지·연도 정도만 노출된다.

라우트(`viewer/app/routers/pages.py`)는 이미 `paper_title`, `paper_title_ko`,
`paper_authors`, `paper_year`, `paper_venue`, `paper_doi`, `paper_url`, `paper_doc_type`
를 템플릿 컨텍스트로 넘기지만(주석: "Paper metadata for viewer info strip"),
**현재 viewer.html 어디에서도 `paper_authors`/`paper_venue`/`paper_doi`/`paper_url` 을
사용하지 않는다**(info strip 미구현). 즉 서지정보는 백엔드 변경 없이 바로 쓸 수 있다.

## 목표

뷰어에 **메타데이터 보기 버튼(ⓘ)** 을 추가하고, 누르면 글의 **서지 메타데이터를 모달**로 보여준다.
- 데스크톱: 상단바 ⓘ 아이콘 버튼.
- 모바일: 햄버거 메뉴(`mobileMenuOpen`) 안의 "메타정보" 항목.

### 비목표 (Out of scope)

- 초록·카테고리·source URL 등 추가 필드는 다루지 않는다(라우트가 안 넘기므로 백엔드 변경 필요 → 이번 범위 제외).
- 백엔드/라우트/API 변경 없음. 순수 템플릿(프런트) 변경.
- 메타데이터 편집 기능 없음(읽기 전용 표시).

## 결정 (사용자 확정)

- **메타 범위**: 서지정보만 — 제목(·한글) · 저자 · venue · 연도 · doc_type · DOI 링크 · 원문 URL 링크.
- **표시 형태**: 모달 팝업(기존 `fontSizeModal` 마크업 패턴 재사용).

## 설계

### 1. Alpine 상태

`viewerApp()` 데이터 객체(기존 `fontSizeModal: { show: false }`, 1580행 부근)에 추가:

```js
metaModal: { show: false },
```

메타 값 자체는 라우트가 넘기는 정적 Jinja 컨텍스트라 Alpine 데이터로 들 필요가 없다.
모달은 열림 상태만 Alpine 으로, 내용은 Jinja 로 직접 렌더한다.

### 2. 열기 버튼

- **데스크톱 상단바**(현 Edit/TOC 버튼 근처): ⓘ(정보) 아이콘 버튼.
  ```html
  <button @click="metaModal.show = true" title="메타정보" class="p-1.5 rounded-lg transition shrink-0"
          :class="$store.darkMode.on ? 'text-gray-400 hover:text-indigo-400 hover:bg-gray-700' : 'text-gray-400 hover:text-indigo-600 hover:bg-indigo-50'">
    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
      <path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25h1.5v5.25m-1.5 0h3M12 7.5h.008v.008H12V7.5zM21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
    </svg>
  </button>
  ```
  항상 노출(메타데이터는 모든 글에 해당).
- **모바일 햄버거 메뉴**(`mobileMenuOpen` 그리드): "메타정보" 항목 추가.
  ```html
  <button @click="metaModal.show = true; mobileMenuOpen = false"
          class="flex items-center justify-center gap-2 px-3 py-3 rounded-lg text-sm font-medium transition"
          :class="$store.darkMode.on ? 'bg-gray-600 text-gray-300 hover:bg-gray-500' : 'bg-white text-gray-700 hover:bg-gray-50'">
    <svg class="w-5 h-5" ...>…info icon…</svg>
    <span>메타정보</span>
  </button>
  ```

### 3. 모달 마크업

기존 `fontSizeModal`(1330행 부근) 패턴을 그대로 따른다: `x-cloak x-show="metaModal.show"`,
`@click.self="metaModal.show = false"`, `fixed inset-0 bg-black bg-opacity-50 ... z-50`,
카드 내부. 추가로 ESC 닫기(`@keydown.escape.window="metaModal.show = false"`)와 닫기(×) 버튼.
마커: 모달 루트 바로 앞에 `<!-- meta-modal -->`.

카드 내용(모두 Jinja 조건부, 다크모드 `:class` 일관):

- 헤더: "메타정보" 제목 + 닫기(×) 버튼
- 제목(영문): `{{ paper_title|default(paper_name, true)|e }}`
- 한글 제목(있을 때): `{% if paper_title_ko %}{{ paper_title_ko|e }}{% endif %}`
- 배지 줄: `{% if paper_doc_type and paper_doc_type != 'other' %}[{{ paper_doc_type }}]{% endif %}`
  + `{% if paper_year %}{{ paper_year }}{% endif %}`
- 저자: `{% if paper_authors %}저자: {{ paper_authors|join(', ') }}{% endif %}`
- Venue: `{% if paper_venue %}Venue: {{ paper_venue|e }}{% endif %}`
- DOI(있을 때): `<a href="https://doi.org/{{ paper_doi }}" target="_blank" rel="noopener">{{ paper_doi }} 🔗</a>`
- URL(있을 때): `<a href="{{ paper_url }}" target="_blank" rel="noopener">…도메인/축약… 🔗</a>`
- 서지 필드가 하나도 없을 때:
  `{% if not (paper_authors or paper_venue or paper_doi or paper_url or paper_year) %}추가 메타데이터 없음{% endif %}`

### 4. 동작 보존

기존 버튼·뷰 전환·다른 모달(fontSize/lightbox/chat)·편집 모드에 영향 없음. 순수 추가.
모달은 닫힌 상태(`show: false`)로 시작, `x-cloak` 으로 초기 깜빡임 방지.

## 테스트

### 템플릿 어서션 (pytest — `viewer/tests/`, 문자열 검사)

`viewer.html` 을 읽어:
- `<!-- meta-modal -->` 마커 존재.
- 열기 배선 `metaModal.show = true` 가 **2회 이상**(데스크톱 버튼 + 모바일 햄버거 항목).
- 모달 영역(마커 이후)에 서지 필드 Jinja 토큰 존재: `paper_authors`, `paper_venue`, `paper_doi`, `paper_url`.
- ESC/닫기 배선: `metaModal.show = false` 존재.

> 모달 렌더·링크 동작·레이아웃은 문자열 테스트로 검증이 제한적이라, **주 수용 기준은 수동 시각 확인**으로 둔다.

### 수동 시각 확인 (주 수용 기준)

Docker 재빌드 후 http://localhost:8090 → 임의 글 뷰어:
- 데스크톱 상단바 ⓘ 버튼 클릭 → 모달에 제목·저자·venue·연도·DOI/URL 링크 표시.
- DOI/URL 링크가 새 탭으로 정상 이동.
- 바깥 클릭·ESC·× 로 닫힘.
- 모바일 폭: 햄버거 → "메타정보" → 동일 모달.
- 다크모드에서도 깨지지 않음.
- 메타데이터가 빈약한 글: "추가 메타데이터 없음" 안내 표시.

## 영향 범위

- `viewer/app/templates/viewer.html` — Alpine 상태 1개, 열기 버튼 2곳, 모달 1개 추가.
- `viewer/tests/test_viewer_metadata_modal_template.py` — 신규 어서션 테스트.
- 백엔드·라우트·API 무변경.
