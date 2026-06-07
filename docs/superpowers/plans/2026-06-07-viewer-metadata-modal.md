# 뷰어 메타데이터 보기 버튼·모달 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 뷰어에 메타데이터 보기 버튼(데스크톱 ⓘ + 모바일 햄버거 항목)을 추가하고, 누르면 글의 서지 메타데이터를 모달로 띄운다.

**Architecture:** 순수 템플릿(`viewer.html`) 변경. 라우트가 이미 넘기는 정적 Jinja 컨텍스트(`paper_title(_ko)`, `paper_authors`, `paper_venue`, `paper_doi`, `paper_url`, `paper_year`, `paper_doc_type`)를 모달 안에 Jinja로 직접 렌더. 모달 열림 상태만 Alpine `metaModal.show` 로 관리. 기존 `fontSizeModal` 마크업 패턴을 그대로 재사용. 백엔드 무변경.

**Tech Stack:** Jinja2 + Alpine.js + Tailwind (viewer.html), pytest(템플릿 문자열 어서션).

**Spec:** `docs/superpowers/specs/2026-06-07-viewer-metadata-modal-design.md`

---

## File Structure

- `viewer/app/templates/viewer.html` — Alpine 상태 1개, 데스크톱 ⓘ 버튼 1개, 모바일 햄버거 항목 1개, 모달 마크업 1개 추가.
- `viewer/tests/test_viewer_metadata_modal_template.py` — 신규 템플릿 어서션 테스트.

> **주의:** 행 번호는 근사값. 각 편집 전 해당 영역을 Read 로 확인하라. 카드뷰·다른 모달·기존 버튼은 건드리지 않는다.

---

## Task 1: 메타데이터 모달 + 열기 버튼(데스크톱·모바일) 구현

**Files:**
- Modify: `viewer/app/templates/viewer.html`
  - `viewerApp()` 데이터에 `metaModal` 상태 (현 `fontSizeModal: { show: false },`, 1580행 부근)
  - 데스크톱 상단바 ⓘ 버튼 (현 `<!-- Separator -->`/`<!-- Edit button (markdown views only) -->` 부근, 542\~545행)
  - 모바일 햄버거 그리드 항목 (현 Download `</a>` 다음, 456행 / 그리드 닫힘 457행 이전)
  - 모달 마크업 (현 `fontSizeModal` 모달 닫힘 `</div>` 다음, `<!-- Image lightbox` 직전, 1380\~1381행)
- Test: `viewer/tests/test_viewer_metadata_modal_template.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성**

`viewer/tests/test_viewer_metadata_modal_template.py` 생성:

```python
"""뷰어 메타데이터 모달 배선 어서션.

데스크톱 ⓘ 버튼·모바일 햄버거 항목이 모달을 열고, 모달이 서지 필드를 Jinja로
렌더하며, ESC/바깥클릭/닫기로 닫히는지 확인한다. 렌더·링크는 수동 시각 확인이 주 기준.
"""
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "viewer.html"


def test_meta_modal_marker_and_state():
    html = TPL.read_text(encoding="utf-8")
    assert "<!-- meta-modal -->" in html
    assert "metaModal: { show: false }" in html


def test_meta_modal_open_wired_desktop_and_mobile():
    html = TPL.read_text(encoding="utf-8")
    # 데스크톱 ⓘ 버튼 + 모바일 햄버거 항목 = 2회 이상
    assert html.count("metaModal.show = true") >= 2


def test_meta_modal_close_wired():
    html = TPL.read_text(encoding="utf-8")
    assert "metaModal.show = false" in html
    assert '@keydown.escape.window="metaModal.show = false"' in html


def test_meta_modal_shows_bibliographic_fields():
    html = TPL.read_text(encoding="utf-8")
    after = html.split("<!-- meta-modal -->", 1)[1]
    for token in ["paper_authors", "paper_venue", "paper_doi", "paper_url"]:
        assert token in after, f"missing meta field: {token}"
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `cd viewer && python -m pytest tests/test_viewer_metadata_modal_template.py -v`
Expected: FAIL — 마커·상태·버튼·모달 미존재.

- [ ] **Step 3: Alpine 상태 추가**

`viewer/app/templates/viewer.html` 의 `fontSizeModal: { show: false },` 줄(1580행 부근) **바로 다음 줄**에 추가:

```js
    metaModal: { show: false },
```

- [ ] **Step 4: 데스크톱 ⓘ 버튼 추가**

데스크톱 상단바의 `<!-- Edit button (markdown views only) -->` 주석(545행 부근) **바로 앞**에 삽입(즉 Separator 다음, Edit 앞):

```html
      <!-- Metadata info -->
      <button @click="metaModal.show = true"
              class="p-1.5 rounded-lg transition shrink-0"
              :class="$store.darkMode.on ? 'text-gray-400 hover:text-indigo-400 hover:bg-gray-700' : 'text-gray-400 hover:text-indigo-600 hover:bg-indigo-50'"
              title="메타정보">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25h1.5v5.25m-1.5 0h3M12 7.5h.008v.008H12V7.5zM21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
      </button>
```

- [ ] **Step 5: 모바일 햄버거 항목 추가**

모바일 햄버거 그리드의 Download 항목(`<a ...>…<span>다운받기</span></a>`, 447\~456행)의 닫는 `</a>` **다음**, 그리드 컨테이너 닫힘 `</div>`(457행) **이전**에 삽입:

```html
        <!-- Metadata info -->
        <button @click="metaModal.show = true; mobileMenuOpen = false"
                class="flex items-center justify-center gap-2 px-3 py-3 rounded-lg text-sm font-medium transition"
                :class="$store.darkMode.on ? 'bg-gray-600 text-gray-300 hover:bg-gray-500' : 'bg-white text-gray-700 hover:bg-gray-50'">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25h1.5v5.25m-1.5 0h3M12 7.5h.008v.008H12V7.5zM21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <span>메타정보</span>
        </button>
```

- [ ] **Step 6: 모달 마크업 추가**

`fontSizeModal` 모달의 닫는 `</div>`(1380행 부근, `<!-- Image lightbox (pan/zoom) -->` 주석 직전)와 그 lightbox 주석 **사이**에 삽입:

```html
  <!-- meta-modal -->
  <div x-cloak x-show="metaModal.show"
       @click.self="metaModal.show = false"
       @keydown.escape.window="metaModal.show = false"
       class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4"
       style="display: none;">
    <div @click.stop
         class="relative rounded-2xl shadow-xl max-w-md w-full p-6 max-h-[80vh] overflow-y-auto"
         :class="$store.darkMode.on ? 'bg-gray-800' : 'bg-white'"
         x-transition:enter="transition ease-out duration-150"
         x-transition:enter-start="opacity-0 scale-95"
         x-transition:enter-end="opacity-100 scale-100">
      <!-- Header -->
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-sm font-semibold" :class="$store.darkMode.on ? 'text-gray-300' : 'text-gray-600'">메타정보</h3>
        <button @click="metaModal.show = false" title="닫기"
                class="p-1 rounded-md transition"
                :class="$store.darkMode.on ? 'text-gray-500 hover:text-gray-300 hover:bg-gray-700' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <!-- Title -->
      <h4 class="text-base font-semibold leading-snug mb-1" :class="$store.darkMode.on ? 'text-gray-100' : 'text-gray-900'">{{ paper_title|default(paper_name, true)|e }}</h4>
      {% if paper_title_ko %}
      <p class="text-sm mb-3" :class="$store.darkMode.on ? 'text-gray-400' : 'text-gray-500'">{{ paper_title_ko|e }}</p>
      {% endif %}

      <!-- Badges -->
      <div class="flex items-center gap-2 mb-4">
        {% if paper_doc_type and paper_doc_type != 'other' %}
        <span class="text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase tracking-wide border"
              :class="$store.darkMode.on ? 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30' : 'bg-indigo-50 text-indigo-600 border-indigo-200'">{{ paper_doc_type }}</span>
        {% endif %}
        {% if paper_year %}
        <span class="text-[10px] px-1.5 py-0.5 rounded font-medium border"
              :class="$store.darkMode.on ? 'bg-gray-700 text-gray-300 border-gray-600' : 'bg-gray-100 text-gray-600 border-gray-200'">{{ paper_year }}</span>
        {% endif %}
      </div>

      <!-- Fields -->
      <dl class="space-y-2.5 text-sm">
        {% if paper_authors %}
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wider mb-0.5" :class="$store.darkMode.on ? 'text-gray-500' : 'text-gray-400'">저자</dt>
          <dd :class="$store.darkMode.on ? 'text-gray-300' : 'text-gray-700'">{{ paper_authors|join(', ')|e }}</dd>
        </div>
        {% endif %}
        {% if paper_venue %}
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wider mb-0.5" :class="$store.darkMode.on ? 'text-gray-500' : 'text-gray-400'">Venue</dt>
          <dd :class="$store.darkMode.on ? 'text-gray-300' : 'text-gray-700'">{{ paper_venue|e }}</dd>
        </div>
        {% endif %}
        {% if paper_doi %}
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wider mb-0.5" :class="$store.darkMode.on ? 'text-gray-500' : 'text-gray-400'">DOI</dt>
          <dd><a href="https://doi.org/{{ paper_doi|e }}" target="_blank" rel="noopener"
                 class="inline-flex items-center gap-1 break-all"
                 :class="$store.darkMode.on ? 'text-indigo-400 hover:text-indigo-300' : 'text-indigo-600 hover:text-indigo-700'">{{ paper_doi|e }}
            <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"/></svg></a></dd>
        </div>
        {% endif %}
        {% if paper_url %}
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wider mb-0.5" :class="$store.darkMode.on ? 'text-gray-500' : 'text-gray-400'">URL</dt>
          <dd><a href="{{ paper_url|e }}" target="_blank" rel="noopener"
                 class="inline-flex items-center gap-1 break-all"
                 :class="$store.darkMode.on ? 'text-indigo-400 hover:text-indigo-300' : 'text-indigo-600 hover:text-indigo-700'">{{ paper_url|e }}
            <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"/></svg></a></dd>
        </div>
        {% endif %}
        {% if not (paper_authors or paper_venue or paper_doi or paper_url or paper_year) %}
        <p :class="$store.darkMode.on ? 'text-gray-500' : 'text-gray-400'">추가 메타데이터 없음</p>
        {% endif %}
      </dl>
    </div>
  </div>
```

- [ ] **Step 7: 테스트 실행 — 통과 확인**

Run: `cd viewer && python -m pytest tests/test_viewer_metadata_modal_template.py -v`
Expected: PASS (4 passed)

- [ ] **Step 8: Jinja 템플릿 파싱 무결성 확인**

추가한 `{% if %}`/`{% endif %}` 짝이 맞는지 템플릿을 실제로 렌더 엔진이 파싱할 수 있는지 확인:

Run: `cd viewer && python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('viewer.html'); print('jinja parse OK')"`
Expected: `jinja parse OK` (구문 오류 시 TemplateSyntaxError 발생 → Step 6 점검)

- [ ] **Step 9: 커밋**

```bash
git add viewer/app/templates/viewer.html viewer/tests/test_viewer_metadata_modal_template.py
git commit -m "feat(viewer): 메타데이터 보기 버튼(ⓘ·햄버거)·모달 추가"
```

---

## Task 2: 통합 확인 (수동 시각 — 주 수용 기준)

**Files:** (코드 변경 없음 — 검증만)

- [ ] **Step 1: 테스트 회귀**

Run: `cd viewer && python -m pytest tests/test_viewer_metadata_modal_template.py -v`
Expected: PASS (4 passed)

- [ ] **Step 2: 뷰어 재빌드·기동**

Run: `docker compose build paperflow-viewer && docker compose up -d paperflow-viewer`
Expected: 컨테이너 정상 기동.

- [ ] **Step 3: 기동 로그 무에러 확인**

Run: `docker compose logs paperflow-viewer 2>&1 | tail -8`
Expected: error 0건 (특히 Jinja TemplateSyntaxError 없음).

- [ ] **Step 4: 수동 시각 확인 (http://localhost:8090 → 임의 글 뷰어)**

확인 항목:
- 데스크톱 상단바 ⓘ 버튼 클릭 → 모달에 제목·(한글제목)·doc_type·연도·저자·venue·DOI/URL 표시.
- DOI/URL 링크가 새 탭으로 정상 이동.
- 바깥 클릭·ESC·× 버튼으로 닫힘.
- 모바일 폭(개발자도구): 햄버거 → "메타정보" → 동일 모달, 클릭 시 햄버거 닫힘.
- 다크모드에서도 깨지지 않음.
- 메타데이터가 빈약한 글: "추가 메타데이터 없음" 표시.

> 모달 렌더·링크·레이아웃은 자동 검증이 제한적이라 이 단계는 사람이 확인한다. 실패 시 Task 1 해당 Step 으로 복귀.

---

## Self-Review 기록

- **Spec coverage:** Alpine 상태(Step 3), 데스크톱 ⓘ 버튼(Step 4), 모바일 햄버거 항목(Step 5), 모달+서지필드+빈값 안내+ESC/×/바깥닫기(Step 6), 테스트(Step 1·7), Jinja 파싱(Step 8), 수동 시각(Task 2) — 스펙 항목 모두 매핑.
- **Placeholder scan:** 모든 편집 단계에 실제 마크업/코드 포함, 모호 지시 없음.
- **Type/토큰 consistency:** `metaModal.show`(상태·열기·닫기), 마커 `<!-- meta-modal -->`, 서지 토큰(`paper_authors`/`paper_venue`/`paper_doi`/`paper_url`), ESC 배선 문자열이 편집·테스트에서 일관. 정보 아이콘 SVG path 는 데스크톱·모바일 동일.
