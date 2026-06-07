# 리스트뷰 제목 폭 확대·열 정렬 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 목록 화면 리스트뷰의 메인 행에서 제목을 넓히고 오른쪽 항목을 고정폭 정렬 열로 만들며, 별점·해시태그·venue·크기·부가날짜를 확장 패널로 옮긴다.

**Architecture:** 순수 템플릿(`papers.html`) 변경. (1) 먼저 확장 패널에 별점 setter + 메타 한 줄을 **추가**(기능 손실 없음), (2) 그다음 메인 행에서 그 항목들을 제거하고 오른쪽을 고정폭 + `invisible` 열로 재구성. 백엔드 무변경.

**Tech Stack:** Alpine.js + Tailwind (papers.html), pytest(템플릿 문자열 어서션).

**Spec:** `docs/superpowers/specs/2026-06-07-list-view-title-width-design.md`

---

## File Structure

- `viewer/app/templates/papers.html` — 리스트뷰 블록만 수정:
  - 확장 패널(876\~931행 영역)에 별점·메타 블록 추가 (Task 1)
  - 메인 행 `<a>` 요소(711\~820행)를 고정폭 열 구조로 교체 (Task 2)
- `viewer/tests/test_papers_list_view_template.py` — 템플릿 어서션 테스트 (신규, Task 1에서 생성·Task 2에서 추가)

> **주의:** 행 번호는 근사값이다. 각 편집 전 해당 영역을 Read 로 확인하고 정확한 경계를 잡아 편집하라. 카드뷰(418\~704행)·다른 화면은 절대 건드리지 않는다.

---

## Task 1: 확장 패널에 별점 setter + 메타 한 줄 추가 (additive)

**Files:**
- Modify: `viewer/app/templates/papers.html` (확장 패널 내부, 외부 링크 블록 다음 — 현재 929행 `</div>` 이후, 패널 컨테이너 닫힘 930행 이전)
- Test: `viewer/tests/test_papers_list_view_template.py` (신규)

> 이 Task는 순수 추가다. 메인 행은 아직 그대로라 별점/venue/크기가 잠시 두 곳에 보이지만 기능 손실은 없다(Task 2에서 메인 행 사본 제거).

- [ ] **Step 1: 실패하는 테스트 작성**

`viewer/tests/test_papers_list_view_template.py` 생성:

```python
"""리스트뷰 메인 행 슬림화 + 확장 패널 이동분 배선 어서션.

별점·메타(venue/크기/추가일)가 확장 패널로 이동했는지, 메인 행이 고정폭 열로
재구성됐는지를 마커/토큰으로 확인한다. 픽셀 정렬은 수동 시각 확인이 주 기준이다.
"""
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "papers.html"


def test_panel_relocations_markers_present():
    html = TPL.read_text(encoding="utf-8")
    assert "<!-- list-meta-line -->" in html
    assert "<!-- list-rating-detail -->" in html


def test_rating_setter_in_detail_panel():
    html = TPL.read_text(encoding="utf-8")
    after = html.split("<!-- list-rating-detail -->", 1)[1]
    assert "setRating(paper.name" in after
    assert "'list-rate-' + s" in after


def test_meta_line_has_venue_size_date():
    html = TPL.read_text(encoding="utf-8")
    after = html.split("<!-- list-meta-line -->", 1)[1][:800]
    assert "paper.venue || paper.source_domain" in after
    assert "paper.size_mb + ' MB'" in after
    assert "paperDateLabel(paper)" in after
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `cd viewer && python -m pytest tests/test_papers_list_view_template.py -v`
Expected: FAIL — 마커·블록 미존재.

- [ ] **Step 3: 패널에 두 블록 추가**

`viewer/app/templates/papers.html` 의 확장 패널 안쪽(`<div class="px-4 py-3 space-y-3 ...">` 컨테이너) 마지막 자식으로, **외부 링크 블록(`<div ... x-show="paper.doi || paper.paper_url || paper.source_url">...</div>`, 현재 911\~929행)의 닫는 `</div>` 바로 다음**에 아래를 삽입한다:

```html
              <!-- list-meta-line -->
              <div class="flex items-center gap-3 text-[11px] flex-wrap transition-colors"
                   :class="$store.darkMode.on ? 'text-gray-400' : 'text-gray-500'">
                <span x-show="paper.venue || paper.source_domain">
                  <span class="opacity-60">Venue</span>
                  <span x-text="paper.venue || paper.source_domain"></span>
                </span>
                <span x-show="paper.size_mb">
                  <span class="opacity-60">Size</span>
                  <span x-text="paper.size_mb + ' MB'"></span>
                </span>
                <span x-show="paperDateLabel(paper)">
                  <span class="opacity-60">Added</span>
                  <span x-text="paperDateLabel(paper)"></span>
                </span>
              </div>

              <!-- list-rating-detail -->
              <div class="flex items-center gap-2" @click.prevent.stop>
                <h4 class="text-[10px] font-semibold uppercase tracking-wider transition-colors"
                    :class="$store.darkMode.on ? 'text-gray-500' : 'text-gray-400'">Rating</h4>
                <div class="flex items-center gap-0">
                  <template x-for="s in [1,2,3,4,5]" :key="'list-rate-' + s">
                    <button @click.prevent.stop="setRating(paper.name, s)"
                            class="p-0.5 transition-colors"
                            :class="getRating(paper.name) >= s
                              ? 'text-amber-400'
                              : ($store.darkMode.on ? 'text-gray-600 hover:text-gray-500' : 'text-gray-300 hover:text-gray-400')">
                      <svg class="w-4 h-4" :fill="getRating(paper.name) >= s ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.381-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/>
                      </svg>
                    </button>
                  </template>
                </div>
              </div>
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `cd viewer && python -m pytest tests/test_papers_list_view_template.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add viewer/app/templates/papers.html viewer/tests/test_papers_list_view_template.py
git commit -m "feat(viewer): 리스트뷰 확장 패널에 별점·메타(venue/크기/추가일) 추가"
```

---

## Task 2: 메인 행 슬림화 + 고정폭 열 재구성

**Files:**
- Modify: `viewer/app/templates/papers.html` (메인 행 `<a :href...>...</a>` 요소, 현재 711\~820행)
- Test: `viewer/tests/test_papers_list_view_template.py` (테스트 2개 추가)

> 이 Task는 메인 행에서 별점·해시태그·venue·부가날짜·크기를 제거하고(이미 Task 1에서 패널에 존재), 오른쪽을 `doc_type → 파일점들 → 발행일 → 진행률` 고정폭 열로 재구성한다.

- [ ] **Step 1: 실패하는 테스트 추가**

`viewer/tests/test_papers_list_view_template.py` 끝에 아래 두 테스트를 추가:

```python
def test_main_row_single_category_tag_removed():
    html = TPL.read_text(encoding="utf-8")
    # 리스트뷰 메인 행의 단일 카테고리 칩만 slice(0, 1)을 쓴다(파일 내 유일).
    assert "(paper.categories || []).slice(0, 1)" not in html


def test_main_row_fixed_width_columns():
    html = TPL.read_text(encoding="utf-8")
    assert 'class="hidden sm:flex w-16 justify-end shrink-0"' in html  # doc_type 열
    assert 'class="w-14 flex justify-end items-center gap-1 shrink-0"' in html  # 파일점 열
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `cd viewer && python -m pytest tests/test_papers_list_view_template.py -v`
Expected: FAIL — 새 두 테스트 실패(`slice(0, 1)` 아직 존재, 고정폭 열 미존재). 기존 3개는 PASS.

- [ ] **Step 3: 메인 행 `<a>` 요소 교체**

`viewer/app/templates/papers.html` 에서 메인 행의 `<a :href="'/viewer/' + encodeURIComponent(paper.name)" ...>` 부터 그 짝이 되는 `</a>`(현재 711\~820행) **전체**를 아래로 교체한다. (이 범위 안에 기존 doc_type·해시태그·파일점·발행일·venue·부가날짜·크기·진행률·별점이 모두 들어있다. 교체로 해시태그·venue·부가날짜·크기·별점은 사라지고, 진행률은 오른쪽 클러스터로 편입된다.)

Read 로 711행 `<a` 시작과 820행 `</a>` 끝을 먼저 확인한 뒤 교체:

```html
            <a :href="'/viewer/' + encodeURIComponent(paper.name)" class="flex-1 min-w-0 flex items-center gap-3 sm:gap-4">
              <!-- Title + authors (widened) -->
              <div class="flex-1 min-w-0">
                <h3 class="font-medium text-sm truncate transition-colors"
                    :class="$store.darkMode.on ? 'text-gray-100' : 'text-gray-900'"
                    x-text="($store.lang.ko && paper.title_ko) ? paper.title_ko : (paper.title || paper.name)"></h3>
                <p x-show="paper.authors && paper.authors.length > 0"
                   class="hidden sm:block text-[10px] truncate transition-colors mt-0.5"
                   :class="$store.darkMode.on ? 'text-gray-500' : 'text-gray-400'"
                   x-text="paper.authors.slice(0, 2).join(', ') + (paper.authors.length > 2 ? ' et al.' : '')"></p>
              </div>

              <!-- Right columns: fixed-width cells so they align row-to-row -->
              <div class="flex items-center gap-2 sm:gap-3 shrink-0">
                <!-- doc_type (desktop only, fixed-width column) -->
                <div class="hidden sm:flex w-16 justify-end shrink-0">
                  <span x-show="paper.doc_type && paper.doc_type !== 'other'"
                        class="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide truncate"
                        :class="$store.darkMode.on
                          ? { 'bg-indigo-500/15 text-indigo-400 border border-indigo-500/30': paper.doc_type === 'paper',
                              'bg-purple-500/15 text-purple-400 border border-purple-500/30': paper.doc_type === 'report',
                              'bg-green-500/15 text-green-400 border border-green-500/30': paper.doc_type === 'blog',
                              'bg-rose-500/15 text-rose-400 border border-rose-500/30': paper.doc_type === 'news',
                              'bg-orange-500/15 text-orange-400 border border-orange-500/30': paper.doc_type === 'essay',
                              'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30': paper.doc_type === 'article', 'bg-red-500/15 text-red-400 border border-red-500/30': paper.doc_type === 'video' }[paper.doc_type] || 'bg-gray-700/40 text-gray-300 border border-gray-600/50'
                          : { 'bg-indigo-50 text-indigo-600 border border-indigo-200': paper.doc_type === 'paper',
                              'bg-purple-50 text-purple-600 border border-purple-200': paper.doc_type === 'report',
                              'bg-green-50 text-green-600 border border-green-200': paper.doc_type === 'blog',
                              'bg-rose-50 text-rose-600 border border-rose-200': paper.doc_type === 'news',
                              'bg-orange-50 text-orange-600 border border-orange-200': paper.doc_type === 'essay',
                              'bg-cyan-50 text-cyan-600 border border-cyan-200': paper.doc_type === 'article', 'bg-red-50 text-red-600 border border-red-200': paper.doc_type === 'video' }[paper.doc_type] || 'bg-gray-100 text-gray-500 border border-gray-200'"
                        x-text="paper.doc_type"></span>
                </div>

                <!-- File type dots (fixed-width column) -->
                <div class="w-14 flex justify-end items-center gap-1 shrink-0">
                  <!-- 원본 소스: PDF (+ EN MD 있으면 회색 링) -->
                  <span x-show="paper.formats.pdf || paper.formats.md_en" class="w-1.5 h-1.5 rounded-full"
                        :class="(paper.formats.pdf ? 'bg-blue-500' : 'bg-gray-400') + ((paper.formats.pdf && paper.formats.md_en) ? ' ring-[1.5px] ring-gray-400' : '')"
                        :title="(paper.formats.pdf && paper.formats.md_en) ? 'PDF + MD-EN' : (paper.formats.pdf ? 'PDF' : 'MD-EN')"></span>
                  <!-- 한국어 자산: 번역 → +해설 → +듣기 → +mp3 -->
                  <span x-show="paper.formats.md_ko" class="inline-flex items-center gap-0.5">
                    <span class="w-1.5 h-1.5 rounded-full bg-purple-500"
                          :class="paper.formats.md_ko_explained && 'ring-[1.5px] ring-amber-400'"
                          :title="paper.formats.md_ko_audio ? 'MD-KO + Easy + 듣기' : (paper.formats.md_ko_explained ? 'MD-KO + Easy' : 'MD-KO')"></span>
                    <svg x-show="paper.formats.md_ko_audio" class="w-2.5 h-2.5 rounded-full"
                         :class="[paper.formats.md_ko_audio_brief ? 'text-teal-500' : 'text-sky-500', paper.formats.audio_mp3 && 'ring-[1.5px] ring-emerald-400']"
                         fill="currentColor" viewBox="0 0 24 24">
                      <title x-text="(paper.formats.md_ko_audio_brief ? '듣기판 + 축약본' : '듣기판') + (paper.formats.audio_mp3 ? ' — mp3 재생 가능' : ' (텍스트)')">듣기판 (TTS)</title>
                      <path d="M3 9v6h4l5 5V4L7 9H3z"/>
                    </svg>
                  </span>
                </div>

                <!-- Publication date (fixed-width column) -->
                <span class="inline-block text-[10px] px-1.5 py-0.5 rounded font-medium transition-colors w-auto sm:w-[5.5rem] text-center shrink-0"
                      :class="[$store.darkMode.on ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-600', !(paper.pub_label || paper.extracted_at) && 'invisible']"
                      x-text="paper.pub_label || (paper.extracted_at ? paper.extracted_at.substring(0, 10) : '')"></span>

                <!-- Reading progress (desktop only, fixed-width column) -->
                <span class="hidden sm:inline-block text-[10px] w-12 text-center px-1.5 py-0.5 rounded font-medium tabular-nums shrink-0 transition-colors"
                      :class="[getProgress(paper.name) >= 95
                        ? ($store.darkMode.on ? 'bg-emerald-900/30 text-emerald-400' : 'bg-emerald-50 text-emerald-700')
                        : ($store.darkMode.on ? 'bg-indigo-900/30 text-indigo-400' : 'bg-indigo-50 text-indigo-700'),
                        getProgress(paper.name) <= 0 && 'invisible']"
                      x-text="getProgress(paper.name) > 0 ? (getProgress(paper.name) + '%') : ''"></span>
              </div>
            </a>
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `cd viewer && python -m pytest tests/test_papers_list_view_template.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 액션 버튼 영역 무손상 확인**

메인 행의 `<a>` 다음에 오는 액션 버튼 컨테이너(`<div class="flex items-center space-x-1 ml-3 shrink-0">`, 현재 821행)와 확장 패널(876행)이 그대로 남아있는지 Read 로 확인. (교체 범위는 `</a>`까지이므로 영향 없어야 한다.)

Run: `cd viewer && python -c "import pathlib; h=pathlib.Path('app/templates/papers.html').read_text(); assert h.count('toggleCardDetail(paper)')>=1 and 'confirmAction(' in h; print('actions intact')"`
Expected: `actions intact`

- [ ] **Step 6: 커밋**

```bash
git add viewer/app/templates/papers.html viewer/tests/test_papers_list_view_template.py
git commit -m "feat(viewer): 리스트뷰 메인 행 슬림화·고정폭 열 정렬, 제목 폭 확대"
```

---

## Task 3: 통합 확인 (수동 시각 — 주 수용 기준)

**Files:** (코드 변경 없음 — 검증만)

- [ ] **Step 1: 전체 리스트뷰 테스트 회귀**

Run: `cd viewer && python -m pytest tests/test_papers_list_view_template.py -v`
Expected: PASS (5 passed)

- [ ] **Step 2: 뷰어 재빌드·기동**

Run: `docker compose build paperflow-viewer && docker compose up -d paperflow-viewer`
Expected: 컨테이너 정상 기동.

- [ ] **Step 3: 기동 로그 무에러 확인**

Run: `docker compose logs paperflow-viewer 2>&1 | tail -8`
Expected: error 0건.

- [ ] **Step 4: 수동 시각 확인 (http://localhost:8090 → 목록 → 리스트뷰)**

확인 항목:
- 제목이 이전보다 눈에 띄게 넓다(긴 제목이 덜 잘림).
- 오른쪽 열(doc_type · 파일점들 · 발행일 · 진행률)이 **행마다 세로로 정렬**된다 — 값이 없는 행도 어긋나지 않는다.
- 확장(⌄) 시 별점·venue·크기·추가일·전체 해시태그가 패널에 보이고, 별점 클릭 설정이 동작한다.
- 다크모드·모바일 폭에서도 깨지지 않는다.

> 행 레이아웃은 자동 픽셀 검증이 어려워 이 단계는 사람이 확인한다. 실패 시 Task 2 Step 3으로 복귀.

---

## Self-Review 기록

- **Spec coverage:** 메인 행 제목 확대·고정폭 열(Task 2), 별점·메타 패널 이동(Task 1), 해시태그 단일 칩 제거(Task 2), 모바일 영향(Task 2의 `hidden sm:*`), 테스트(Task 1·2)·수동 시각(Task 3) — 스펙 항목 모두 매핑.
- **Placeholder scan:** 모든 편집 단계에 실제 마크업/코드 포함, 모호 지시 없음.
- **Type/토큰 consistency:** 마커(`<!-- list-meta-line -->`, `<!-- list-rating-detail -->`), 고정폭 클래스 문자열(`w-16 justify-end`, `w-14 flex justify-end items-center gap-1`), 헬퍼명(`setRating`/`getRating`/`getProgress`/`paperDateLabel`)이 편집·테스트에서 일관. 별점 setter는 `'list-rate-' + s` 키로 카드뷰와 구분.
