# 이미지 라이트박스(팬/줌) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 뷰어 본문(MD·Split) 이미지를 클릭/탭하면 라이트박스 오버레이로 확대하고, PC(휠/더블클릭/드래그)·모바일(핀치/드래그)에서 팬·줌할 수 있게 한다.

**Architecture:** 커스텀 Alpine 라이트박스(새 의존성 없음). 본문 이미지는 `x-html` 주입이라 이벤트 위임으로 클릭을 잡는다. 메인 MD는 기존 `onMarkdownClick`에 이미지 early-return을 추가하고, Split 컨테이너엔 `@click`을 새로 바인딩한다. 모바일 탭이 합성 click을 내도록 터치 핸들러의 `isInteractive` 셀렉터에 `img`를 추가한다. 줌/팬은 Pointer Events로 PC·모바일을 통합한다.

**Tech Stack:** Alpine.js 3, Tailwind CDN, Pointer Events API. 검증은 Playwright(이미 tmp venv 패턴 사용) + 라이브 docker 뷰어.

스펙: `docs/superpowers/specs/2026-06-07-image-lightbox-design.md`

---

## File Structure

- **Modify** `viewer/app/templates/viewer.html` (단일 파일):
  - CSS: `.markdown-container img`에 `cursor: zoom-in` (line ~101)
  - 마크업: viewerApp 루트 `</div>` 직전(= `<script>\nfunction viewerApp()` 바로 위 `</div>`)에 라이트박스 오버레이 추가
  - 상태: `viewerApp()` return 객체에 `lightbox` + 제스처 임시 상태 추가 (line ~1382)
  - 메서드: `openLightbox`/`closeLightbox`/`onContentImageClick`/줌·팬 핸들러 추가 (near `onMarkdownClick`, line ~2588)
  - 배선: `onMarkdownClick` early-return (line 2588), Split 컨테이너 `@click` (line 977)
  - 모바일: `handleTouchEnd`(line 3466)·`handleMarkdownTouchStart`(line 3500)의 `isInteractive`에 `img` 추가
- **Verification (비커밋, tmp/)**: Playwright 스크립트 `tmp/verify_lightbox.py`

배포: viewer 템플릿은 이미지에 baked → 검증 시 `docker compose build paperflow-viewer && docker compose up -d paperflow-viewer` 1회 필요. (per-task 재빌드는 비효율 → 구현 3개 태스크는 정적 검토, 기능 검증은 Task 4에서 1회 재빌드 후 일괄)

---

## Task 1: 라이트박스 상태 + 열기/닫기 + 오버레이 마크업 + CSS

**Files:**
- Modify: `viewer/app/templates/viewer.html`

- [ ] **Step 1: CSS cursor 추가**

`viewer.html:101` 의 기존 줄을 교체:

```css
  .markdown-container img { max-width: 100%; height: auto; }
```
→
```css
  .markdown-container img { max-width: 100%; height: auto; cursor: zoom-in; }
```

- [ ] **Step 2: viewerApp 상태 추가**

`viewer.html:1382` 부근, `return {` 직후(예: `view:` 줄 위 또는 아래 인접)에 추가:

```js
    // Image lightbox (pan/zoom)
    lightbox: { show: false, src: '', alt: '', scale: 1, tx: 0, ty: 0 },
    _lbPointers: null,   // Map<pointerId,{x,y}> during a gesture
    _lbDragged: false,   // moved during this gesture (backdrop-close guard)
    _lbStart: null,      // gesture start snapshot
```

`return {` 의 정확한 위치는 `grep -n 'function viewerApp()' viewer.html` 후 그 아래 `return {` 줄을 찾아 기존 들여쓰기(4 spaces)에 맞춘다.

- [ ] **Step 3: 열기/닫기 + clamp 메서드 추가**

`onMarkdownClick(e) {` (line ~2588) 정의 **바로 위**에 메서드들을 추가(메서드 객체 컨텍스트, 끝에 콤마):

```js
    openLightbox(src, alt) {
      this.lightbox = { show: true, src, alt, scale: 1, tx: 0, ty: 0 };
      this._lbPointers = new Map();
      this._lbDragged = false;
      this._lbStart = null;
      document.body.style.overflow = 'hidden';
    },
    closeLightbox() {
      this.lightbox.show = false;
      document.body.style.overflow = '';
    },
    _lbClamp(s) { return Math.max(1, Math.min(5, s)); },
```

- [ ] **Step 4: 오버레이 마크업 추가**

viewerApp 루트 컨테이너를 닫는 `</div>` (바로 아래에 빈 줄 + `<script>\nfunction viewerApp()` 가 오는 그 `</div>`) **직전**에 삽입. 위치 확인: `grep -n '<script>' viewer.html` 의 첫 결과 위쪽 `</div>`.

```html
  <!-- Image lightbox (pan/zoom) -->
  <div x-cloak x-show="lightbox.show"
       @keydown.escape.window="closeLightbox()"
       @wheel.prevent="onLightboxWheel($event)"
       @pointerdown="onLightboxPointerDown($event)"
       @pointermove="onLightboxPointerMove($event)"
       @pointerup="onLightboxPointerUp($event)"
       @pointercancel="onLightboxPointerUp($event)"
       @dblclick="onLightboxDblClick($event)"
       @click.self="onLightboxBackdrop()"
       class="fixed inset-0 z-[70] flex items-center justify-center bg-black/90 select-none overflow-hidden"
       style="touch-action: none;">
    <img :src="lightbox.src" :alt="lightbox.alt" draggable="false"
         class="max-w-[95vw] max-h-[95vh] object-contain will-change-transform"
         :style="`transform: translate(${lightbox.tx}px, ${lightbox.ty}px) scale(${lightbox.scale}); transition: ${_lbStart ? 'none' : 'transform 0.15s ease-out'};`">
    <button @click="closeLightbox()"
            class="absolute top-3 right-3 w-10 h-10 rounded-full bg-black/60 text-white text-xl flex items-center justify-center hover:bg-black/80"
            aria-label="Close">✕</button>
  </div>
```

> 줌/팬 핸들러(`onLightboxWheel` 등)는 Task 3에서 추가한다. 이 태스크 시점엔 정의 전이라 클릭 시 Alpine이 경고할 수 있으나, 열기 자체는 Task 2 배선 후 동작한다. **Task 1 단독으로 기능 테스트하지 말고**, Task 3까지 끝낸 뒤 Task 4에서 일괄 검증한다.

- [ ] **Step 5: 정적 검증**

Run:
```bash
cd /media/restful3/data/workspace/paperflow
grep -n 'cursor: zoom-in' viewer/app/templates/viewer.html
grep -n "lightbox: { show: false" viewer/app/templates/viewer.html
grep -n 'openLightbox(src, alt)' viewer/app/templates/viewer.html
grep -n 'Image lightbox (pan/zoom)' viewer/app/templates/viewer.html
```
Expected: 각 grep이 1건(마크업 주석은 1건) 매칭. (마크업 주석 문자열은 CSS/JS와 구분 위해 정확히 `<!-- Image lightbox` 로도 확인: `grep -n '<!-- Image lightbox' viewer/app/templates/viewer.html` → 1건)

- [ ] **Step 6: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(viewer): 이미지 라이트박스 상태/열기·닫기/오버레이 마크업

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 클릭 배선 (이벤트 위임) + 모바일 탭 수정

**Files:**
- Modify: `viewer/app/templates/viewer.html`

- [ ] **Step 1: onContentImageClick 메서드 추가**

`openLightbox` 정의 아래(또는 인접)에 추가:

```js
    onContentImageClick(e) {
      const t = e.target;
      if (!t || t.tagName !== 'IMG' || !t.closest('.markdown-container')) return false;
      this.openLightbox(t.currentSrc || t.src, t.alt || '');
      return true;
    },
```

- [ ] **Step 2: 메인 MD — onMarkdownClick early-return**

`viewer.html:2588` 의 기존 블록:

```js
    onMarkdownClick(e) {
      this.onSentenceTap(e);                 // 오디오 모드면 그 문장부터 재생
      this.handleMarkdownClickDesktop(e);    // 기존 데스크톱 동작 유지
    },
```
→
```js
    onMarkdownClick(e) {
      if (this.onContentImageClick(e)) return;   // 이미지면 라이트박스만 열고 종료
      this.onSentenceTap(e);                 // 오디오 모드면 그 문장부터 재생
      this.handleMarkdownClickDesktop(e);    // 기존 데스크톱 동작 유지
    },
```

- [ ] **Step 3: Split 컨테이너 @click 바인딩**

`viewer.html:974-977` 의 Split 본문 컨테이너 — 현재:
```html
          <div class="markdown-container px-4 py-6 sm:px-6 sm:py-8 w-full lg:w-1/2 h-1/2 lg:h-full overflow-y-auto min-h-0"
               :class="[$store.darkMode.on && 'dark', $store.darkMode.on ? 'border-b lg:border-b-0 lg:border-r border-gray-700' : 'border-b lg:border-b-0 lg:border-r border-gray-300']"
               :lang="activeMdLang"
               x-html="splitMdContent"></div>
```
`x-html="splitMdContent"` 줄에 `@click` 추가:
```html
               x-html="splitMdContent"
               @click="onContentImageClick($event)"></div>
```

- [ ] **Step 4: 모바일 탭 수정 — handleTouchEnd isInteractive에 img 추가**

`viewer.html:3466` 의 줄:
```js
        const isInteractive = target.closest('a, button, input, textarea, select, [contenteditable], iframe');
```
→
```js
        const isInteractive = target.closest('a, button, input, textarea, select, [contenteditable], iframe, img');
```

- [ ] **Step 5: 모바일 탭 수정 — handleMarkdownTouchStart isInteractive에 img 추가**

`viewer.html:3500` 의 줄:
```js
      const isInteractive = target.closest('a, button, input, textarea, select, [contenteditable]');
```
→
```js
      const isInteractive = target.closest('a, button, input, textarea, select, [contenteditable], img');
```

> 주의: line 3527(`handleContainerClick`)의 동일 패턴 줄은 PDF/iframe용이라 **건드리지 않는다**. line 3500(handleMarkdownTouchStart)만 수정. 정확 매칭을 위해 함수 컨텍스트로 위치를 확인한 뒤 해당 줄만 바꾼다.

- [ ] **Step 6: 정적 검증**

```bash
cd /media/restful3/data/workspace/paperflow
grep -n 'onContentImageClick(e) {' viewer/app/templates/viewer.html        # 1건
grep -n 'if (this.onContentImageClick(e)) return;' viewer/app/templates/viewer.html  # 1건
grep -n '@click="onContentImageClick($event)"' viewer/app/templates/viewer.html      # 1건 (split)
grep -nc 'contenteditable], iframe, img' viewer/app/templates/viewer.html   # handleTouchEnd: 1
grep -nc "contenteditable\], img'" viewer/app/templates/viewer.html         # handleMarkdownTouchStart: 1
```
Expected: 위 매칭 수가 각 기대치와 일치.

- [ ] **Step 7: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(viewer): 라이트박스 클릭 배선(MD/Split) + 모바일 탭 수정

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 줌 / 팬 핸들러 (휠·포인터·핀치·더블클릭·배경)

**Files:**
- Modify: `viewer/app/templates/viewer.html`

- [ ] **Step 1: 줌/팬 메서드 추가**

`_lbClamp(s)` 메서드 아래(또는 `onContentImageClick` 인접)에 추가. 좌표는 transform-origin(중앙) 기준 보정:

```js
    onLightboxWheel(e) {
      const rect = e.currentTarget.getBoundingClientRect();
      const cx = e.clientX - rect.left - rect.width / 2;
      const cy = e.clientY - rect.top - rect.height / 2;
      const prev = this.lightbox.scale;
      const next = this._lbClamp(prev * (e.deltaY < 0 ? 1.15 : 1 / 1.15));
      if (next === prev) return;
      const ratio = next / prev;
      this.lightbox.tx = cx - ratio * (cx - this.lightbox.tx);
      this.lightbox.ty = cy - ratio * (cy - this.lightbox.ty);
      this.lightbox.scale = next;
      if (next === 1) { this.lightbox.tx = 0; this.lightbox.ty = 0; }
    },
    onLightboxPointerDown(e) {
      if (e.currentTarget.setPointerCapture) {
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) {}
      }
      this._lbPointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      this._lbDragged = false;
      if (this._lbPointers.size === 1) {
        this._lbStart = { x: e.clientX, y: e.clientY, tx: this.lightbox.tx, ty: this.lightbox.ty };
      } else if (this._lbPointers.size === 2) {
        const pts = [...this._lbPointers.values()];
        this._lbStart = {
          dist: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y),
          scale: this.lightbox.scale,
        };
      }
    },
    onLightboxPointerMove(e) {
      if (!this._lbPointers || !this._lbPointers.has(e.pointerId)) return;
      this._lbPointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const n = this._lbPointers.size;
      if (n === 1 && this.lightbox.scale > 1 && this._lbStart) {
        this.lightbox.tx = this._lbStart.tx + (e.clientX - this._lbStart.x);
        this.lightbox.ty = this._lbStart.ty + (e.clientY - this._lbStart.y);
        this._lbDragged = true;
      } else if (n === 2 && this._lbStart && this._lbStart.dist) {
        const pts = [...this._lbPointers.values()];
        const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
        const next = this._lbClamp(this._lbStart.scale * (dist / this._lbStart.dist));
        this.lightbox.scale = next;
        this._lbDragged = true;
        if (next === 1) { this.lightbox.tx = 0; this.lightbox.ty = 0; }
      }
    },
    onLightboxPointerUp(e) {
      if (!this._lbPointers) return;
      this._lbPointers.delete(e.pointerId);
      if (this._lbPointers.size === 0) {
        this._lbStart = null;
      } else if (this._lbPointers.size === 1) {
        const p = [...this._lbPointers.values()][0];
        this._lbStart = { x: p.x, y: p.y, tx: this.lightbox.tx, ty: this.lightbox.ty };
      }
    },
    onLightboxDblClick(e) {
      if (this.lightbox.scale > 1) {
        this.lightbox.scale = 1; this.lightbox.tx = 0; this.lightbox.ty = 0;
      } else {
        const rect = e.currentTarget.getBoundingClientRect();
        const cx = e.clientX - rect.left - rect.width / 2;
        const cy = e.clientY - rect.top - rect.height / 2;
        const ratio = 2;
        this.lightbox.tx = cx - ratio * (cx - this.lightbox.tx);
        this.lightbox.ty = cy - ratio * (cy - this.lightbox.ty);
        this.lightbox.scale = 2;
      }
    },
    onLightboxBackdrop() {
      if (this.lightbox.scale === 1 && !this._lbDragged) this.closeLightbox();
    },
```

- [ ] **Step 2: 정적 검증**

```bash
cd /media/restful3/data/workspace/paperflow
for m in onLightboxWheel onLightboxPointerDown onLightboxPointerMove onLightboxPointerUp onLightboxDblClick onLightboxBackdrop; do
  printf "%s: " "$m"; grep -c "$m(" viewer/app/templates/viewer.html
done
```
Expected: 각 메서드는 정의 1 + 마크업 참조 1 = 2건 (단 `onLightboxBackdrop`는 정의 1 + `@click.self` 참조 1 = 2). 모두 ≥2.

- [ ] **Step 3: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(viewer): 라이트박스 줌/팬(휠·포인터·핀치·더블클릭) 핸들러

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 빌드 + Playwright 기능 검증 (열기/닫기/줌/팬/모바일/회귀)

**Files:**
- Create (비커밋): `tmp/verify_lightbox.py`

- [ ] **Step 1: 뷰어 재빌드 (idle 확인 후)**

```bash
cd /media/restful3/data/workspace/paperflow
docker compose build paperflow-viewer && docker compose up -d paperflow-viewer
sleep 3 && curl -s -o /dev/null -w "viewer HTTP %{http_code}\n" http://localhost:8090/login
```
Expected: `HTTP 200`.

- [ ] **Step 2: Playwright venv 준비 (없으면)**

```bash
cd /media/restful3/data/workspace/paperflow
test -x tmp/pwenv/bin/python || python3 -m venv tmp/pwenv
tmp/pwenv/bin/pip install --quiet playwright
tmp/pwenv/bin/python -c "from playwright.sync_api import sync_playwright; print('pw ok')"
```
Expected: `pw ok` (브라우저는 `~/.cache/ms-playwright` 캐시 재사용).

- [ ] **Step 3: 검증 대상 논문 선택 (이미지 보유, MD 있음)**

```bash
cd /media/restful3/data/workspace/paperflow
find outputs -maxdepth 1 -type d -name 'DeepSeek-V3 Technical Report*' | head -1
```
Expected: 폴더 경로 출력 (이미지 다수 보유, MD 있음). 없으면 `images/` 가 있고 `*_ko.md`/`*.md` 가 있는 다른 폴더명을 사용한다.

- [ ] **Step 4: Playwright 검증 스크립트 작성**

`tmp/verify_lightbox.py` 생성:

```python
import os
from urllib.parse import quote
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8090"
PAPER = "DeepSeek-V3 Technical Report"  # Step 3에서 확인한 폴더명

env = {}
for line in open(".env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); env[k.strip()] = v.strip()

def login(page):
    page.goto(f"{BASE}/login"); page.wait_for_load_state("networkidle")
    page.fill('input[type="text"]', env["LOGIN_ID"])
    page.fill('input[type="password"]', env["LOGIN_PASSWORD"])
    page.click('button[type="submit"]'); page.wait_for_load_state("networkidle")

def lb_state(page):
    return page.evaluate("""() => {
        let d=null;
        for (const el of document.querySelectorAll('[x-data]')) {
            const x = window.Alpine.$data(el);
            if (x && x.lightbox) { d = x; break; }
        }
        return d ? { show:d.lightbox.show, src:d.lightbox.src, scale:d.lightbox.scale,
                     tx:d.lightbox.tx, ty:d.lightbox.ty, overflow:document.body.style.overflow } : null;
    }""")

results = []
def check(name, cond):
    results.append((name, cond)); print(("PASS" if cond else "FAIL"), name)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    # ---- Desktop ----
    page = b.new_page(viewport={"width":1280,"height":900})
    login(page)
    page.goto(f"{BASE}/viewer/{quote(PAPER)}"); page.wait_for_load_state("networkidle")
    # ensure MD view + images present
    page.wait_for_selector(".markdown-container img", timeout=15000)
    page.wait_for_timeout(500)
    # 1. click image opens lightbox
    first_img_src = page.eval_on_selector(".markdown-container img", "el => el.currentSrc || el.src")
    page.click(".markdown-container img")
    page.wait_for_timeout(300)
    s = lb_state(page)
    check("open on click", bool(s and s["show"]))
    check("src matches clicked image", bool(s and s["src"] == first_img_src))
    check("body scroll locked", bool(s and s["overflow"] == "hidden"))
    # 2. wheel zoom increases scale
    page.mouse.move(640, 450)
    page.mouse.wheel(0, -300)
    page.wait_for_timeout(200)
    check("wheel zooms in (scale>1)", lb_state(page)["scale"] > 1)
    # 3. drag pans when zoomed
    before = lb_state(page)
    page.mouse.move(640, 450); page.mouse.down()
    page.mouse.move(740, 520, steps=5); page.mouse.up()
    page.wait_for_timeout(200)
    after = lb_state(page)
    check("drag pans (tx/ty changed)", (after["tx"] != before["tx"] or after["ty"] != before["ty"]))
    # 4. Esc closes + restores scroll
    page.keyboard.press("Escape"); page.wait_for_timeout(200)
    s = lb_state(page)
    check("Esc closes", not s["show"]); check("scroll restored", s["overflow"] == "")
    # 5. double-click toggles zoom
    page.click(".markdown-container img"); page.wait_for_timeout(200)
    page.dblclick(".markdown-container img"); page.wait_for_timeout(200)
    # dblclick lands on overlay image; scale should be 2
    check("double-click zooms to 2x", abs(lb_state(page)["scale"] - 2) < 0.01)
    page.keyboard.press("Escape"); page.wait_for_timeout(150)
    # 6. X button closes
    page.click(".markdown-container img"); page.wait_for_timeout(200)
    page.click('button[aria-label="Close"]'); page.wait_for_timeout(200)
    check("X button closes", not lb_state(page)["show"])
    # 7. backdrop click closes (scale==1)
    page.click(".markdown-container img"); page.wait_for_timeout(200)
    # click near top-left corner of overlay (backdrop, away from centered image)
    page.mouse.click(20, 20); page.wait_for_timeout(200)
    check("backdrop click closes", not lb_state(page)["show"])
    # 8. regression: non-image content click does NOT open lightbox
    page.mouse.click(2, 2)  # ensure closed
    page.wait_for_timeout(100)
    # click a heading/paragraph text region (not an image): use a P or H element
    txt = page.query_selector(".markdown-container p, .markdown-container h1, .markdown-container h2")
    if txt:
        txt.click(); page.wait_for_timeout(150)
        check("non-image click keeps lightbox closed", not lb_state(page)["show"])
    page.close()
    # ---- Mobile tap ----
    ctx = b.new_context(viewport={"width":390,"height":844}, has_touch=True, is_mobile=True)
    mp = ctx.new_page(); login(mp)
    mp.goto(f"{BASE}/viewer/{quote(PAPER)}"); mp.wait_for_load_state("networkidle")
    mp.wait_for_selector(".markdown-container img", timeout=15000); mp.wait_for_timeout(500)
    mp.tap(".markdown-container img"); mp.wait_for_timeout(400)
    check("mobile tap opens lightbox", bool(lb_state(mp) and lb_state(mp)["show"]))
    ctx.close()
    b.close()

passed = sum(1 for _, c in results if c); total = len(results)
print(f"\n=== {passed}/{total} PASSED ===")
raise SystemExit(0 if passed == total else 1)
```

- [ ] **Step 5: 검증 실행**

```bash
cd /media/restful3/data/workspace/paperflow
PLAYWRIGHT_BROWSERS_PATH=~/.cache/ms-playwright tmp/pwenv/bin/python tmp/verify_lightbox.py
```
Expected: `=== N/N PASSED ===` (모든 체크 PASS). 실패 시 해당 동작을 디버그→수정→재빌드(Step 1)→재실행. (핀치 줌은 멀티터치 자동화 한계로 이 스위트에서 제외 — 휠/더블클릭 줌 + 드래그 팬으로 대체 검증; 핀치는 실기기 수동 확인.)

- [ ] **Step 6: 정리 + (선택) 커밋**

```bash
cd /media/restful3/data/workspace/paperflow
rm -f tmp/verify_lightbox.py   # 검증 스크립트는 비커밋 (tmp/ gitignore)
```
구현 커밋은 Task 1~3에서 완료됨. 추가 커밋 불필요. (push/문서 커밋은 사용자 요청 시에만.)

---

## Self-Review

**Spec coverage:**
- 라이트박스 오버레이(팬/줌, z-[70], 어두운 배경, touch-action:none) → Task 1 Step 4
- 상태 lightbox{show,src,alt,scale,tx,ty} + 제스처 임시 → Task 1 Step 2
- 열기 onContentImageClick(IMG + .markdown-container) → Task 2 Step 1
- 메인 MD early-return / Split @click → Task 2 Step 2,3
- 모바일 isInteractive에 img(touchstart+touchend) → Task 2 Step 4,5
- 닫기 Esc/X/배경(scale==1 & !dragged) + body overflow 복원 → Task 1 Step 3,4 + Task 3 onLightboxBackdrop
- 줌/팬: 휠(커서기준)·포인터 팬·핀치(2포인터)·더블클릭 → Task 3 Step 1
- CSS cursor:zoom-in → Task 1 Step 1
- 테스트 9항목(열기/src/스크롤락/휠줌/팬/Esc/더블클릭/X/배경/모바일탭/비이미지 회귀) → Task 4 Step 4
- 범위 밖(PDF/챗/에디터/갤러리) → 본문 컨테이너에만 바인딩, 갤러리 미구현 ✓

**Placeholder scan:** 모든 코드 스텝에 실제 코드 포함. 정적 검증 명령 구체화. 기능 검증은 Task 4의 완전한 Playwright 스크립트로 제공(placeholder 없음).

**Type/이름 일관성:** `lightbox`/`_lbPointers`/`_lbDragged`/`_lbStart`/`_lbClamp`/`openLightbox`/`closeLightbox`/`onContentImageClick`/`onLightbox{Wheel,PointerDown,PointerMove,PointerUp,DblClick,Backdrop}` — Task 1~3 전반 동일 사용. 마크업의 `@`핸들러 이름이 Task 3 메서드명과 일치.

**주의(실행 시):** viewer.html은 사용자 WIP가 없는 상태로 가정(현재 git status에 `viewer.html` 변경 없음 — 이전 WIP는 `viewer/app/templates/viewer.html`이 아니라 동일 파일이었는지 실행 전 `git status`로 확인). 만약 미커밋 변경이 있으면 충돌 없는지 점검 후 진행.
