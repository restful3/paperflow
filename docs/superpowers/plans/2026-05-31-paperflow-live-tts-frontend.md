# PaperFlow 라이브 한국어 TTS — 프론트엔드 구현 플랜 (Plan 2/2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan 1의 백엔드(stitched 오디오 + manifest)를 기존 뷰어에서 재생한다 — 단일 `<audio>`, 현재 문장 하이라이트, 문장 prev/next·탭 점프, auto-follow, 배속, 이어듣기, 생성 진행 UX, MediaSession.

**Architecture:** 오디오 모드 본문은 서버가 manifest.chunks로 만든 문장-span HTML(`/audio/html`)을 주입(클라 marked 우회). 브라우저는 단일 `<audio src=/audio/file>`의 `currentTime`을 manifest timeline에 매핑해 하이라이트·내비를 처리한다. 기존 viewer.html `viewerApp()` Alpine 컴포넌트와 "듣기" 토글에 통합한다.

**Tech Stack:** Alpine.js, 기존 viewer.html 패턴, HTML5 `<audio>`, MediaSession API, FastAPI(서버 렌더).

**선행:** Plan 1(백엔드) 완료 필요. 스펙 [docs/superpowers/specs/2026-05-31-paperflow-live-tts-design.md](../specs/2026-05-31-paperflow-live-tts-design.md) §6 UI.

---

## File Structure

```text
tts_service/app/chunker.py           # Modify: heading 청크에 level 추가
tts_service/tests/test_chunker.py    # Modify: level 테스트
viewer/app/services/audio.py         # Modify: render_audio_html(manifest) 추가
viewer/app/routers/api.py            # Modify: GET /audio/html 추가
viewer/app/templates/viewer.html     # Modify: audioPlayer 상태/메서드 + 플레이어 UI
```

---

## Task 1: chunker에 heading level 추가 (Plan 1 보강)

**Files:**
- Modify: `tts_service/app/chunker.py`
- Modify: `tts_service/tests/test_chunker.py`

서버 렌더가 `<h2>`/`<h3>`를 구분하려면 heading 청크에 `level`이 필요하다.

- [ ] **Step 1: Write failing test (append)**

```python
# tts_service/tests/test_chunker.py 에 추가
def test_heading_level_captured():
    chunks = chunk_markdown("# A\n\n본문.\n\n### B\n\n또 본문.")
    headings = [c for c in chunks if c["kind"] == "heading"]
    assert headings[0]["level"] == 1
    assert headings[1]["level"] == 3
```

- [ ] **Step 2: Run to verify fail**

Run: `cd tts_service && python -m pytest tests/test_chunker.py::test_heading_level_captured -v`
Expected: FAIL (`KeyError: 'level'`)

- [ ] **Step 3: Implement (chunker heading 블록 수정)**

`chunker.py`의 heading append 부분을 다음으로 교체:

```python
        if m and "\n" not in block:
            text = m.group(2).strip()
            level = len(m.group(1))          # '#' 개수
            section_id = _slug(text, n)
            chunks.append({
                "id": n, "kind": "heading", "level": level, "dom_id": f"tts-s-{n:06d}",
                "section_id": section_id, "paragraph_index": para_idx,
                "sentence_index": 0, "text": text,
            })
            n += 1
            continue
```

- [ ] **Step 4: Run all chunker tests**

Run: `cd tts_service && python -m pytest tests/test_chunker.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tts_service/app/chunker.py tts_service/tests/test_chunker.py
git commit -m "feat(tts): capture heading level in chunker for server render"
```

---

## Task 2: 서버 오디오 HTML 렌더러 + 엔드포인트

**Files:**
- Modify: `viewer/app/services/audio.py`
- Modify: `viewer/app/routers/api.py`
- Test: `viewer/tests/test_audio_api.py`

manifest.chunks만으로 문장-span HTML을 만든다(단일 진실원천, marked 우회). heading→`<hN id=dom_id>`, text→문단 안 `<span id=dom_id>`. 같은 `paragraph_index`의 text 청크는 한 `<p>`로 묶는다. HTML escape 필수.

> **nit#11 결정 — 배너 blockquote**: chunker가 배너(`>` "듣기판입니다…")를 청크에서 제외하므로 manifest에 없고, `/audio/html`도 렌더하지 않는다. **MVP에서 오디오 모드 본문에 배너를 표시하지 않는다**(메타 안내문, 합성·표시 모두 제외). 인트로 노트가 필요하면 v1.1에서 manifest 밖 별도 필드로.

- [ ] **Step 1: Write failing test (append)**

```python
# viewer/tests/test_audio_api.py 에 추가
from app.services.audio import render_audio_html

def test_render_audio_html_from_manifest():
    manifest = {"chunks": [
        {"id":0,"kind":"heading","level":2,"dom_id":"tts-s-000000","text":"방법","paragraph_index":0},
        {"id":1,"kind":"text","dom_id":"tts-s-000001","text":"첫 문장.","paragraph_index":1},
        {"id":2,"kind":"text","dom_id":"tts-s-000002","text":"둘째 문장.","paragraph_index":1},
    ]}
    html = render_audio_html(manifest)
    assert '<h2 id="tts-s-000000" data-tts-chunk="0">방법</h2>' in html
    # 같은 문단의 두 문장은 한 <p> 안의 별도 span
    assert html.count("<p>") == 1
    assert '<span id="tts-s-000001" data-tts-chunk="1">첫 문장.</span>' in html
    assert '<span id="tts-s-000002" data-tts-chunk="2">둘째 문장.</span>' in html

def test_render_audio_html_escapes():
    manifest = {"chunks":[{"id":0,"kind":"text","dom_id":"tts-s-000000","text":"a<b>&","paragraph_index":0}]}
    assert "a&lt;b&gt;&amp;" in render_audio_html(manifest)
```

- [ ] **Step 2: Run to verify fail**

Run: `cd viewer && python -m pytest tests/test_audio_api.py::test_render_audio_html_from_manifest -v`
Expected: FAIL (`ImportError: cannot import name 'render_audio_html'`)

- [ ] **Step 3: Implement renderer (append to audio.py)**

```python
# viewer/app/services/audio.py 에 추가
from html import escape

def render_audio_html(manifest: dict) -> str:
    out = []
    cur_para = None
    para_open = False
    def close_para():
        nonlocal para_open
        if para_open: out.append("</p>"); para_open = False
    for ch in manifest.get("chunks", []):
        cid, dom, text = ch["id"], ch["dom_id"], escape(ch["text"])
        if ch["kind"] == "heading":
            close_para()
            lvl = min(max(int(ch.get("level", 2)), 1), 6)
            out.append(f'<h{lvl} id="{dom}" data-tts-chunk="{cid}">{text}</h{lvl}>')
            cur_para = None
        else:
            if ch.get("paragraph_index") != cur_para:
                close_para(); out.append("<p>"); para_open = True
                cur_para = ch.get("paragraph_index")
            out.append(f'<span id="{dom}" data-tts-chunk="{cid}">{text}</span> ')
    close_para()
    return "".join(out)
```

- [ ] **Step 4: Add endpoint to api.py**

```python
# viewer/app/routers/api.py 에 추가
import json as _json
@router.get("/papers/{name:path}/audio/html")
async def audio_html(name: str, _user: str = Depends(get_current_user_api)):
    p = audio_svc.manifest_path(name)
    if not p or not p.exists(): raise HTTPException(404)
    manifest = _json.loads(p.read_text())
    if manifest.get("status") != "complete": raise HTTPException(409, "not ready")
    return Response(content=audio_svc.render_audio_html(manifest), media_type="text/html; charset=utf-8")
```

- [ ] **Step 5: Run tests**

Run: `cd viewer && python -m pytest tests/test_audio_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add viewer/app/services/audio.py viewer/app/routers/api.py viewer/tests/test_audio_api.py
git commit -m "feat(viewer): server-render audio HTML from manifest (sentence spans)"
```

---

## Task 3: viewerApp() 오디오 플레이어 상태 + 생성/로드 흐름

**Files:**
- Modify: `viewer/app/templates/viewer.html` (`viewerApp()` Alpine 컴포넌트)

오디오 모드 진입(기존 `audioMode` 토글) 시: manifest+html 로드, 없으면 "생성" 버튼 노출 → job POST → status 폴링 → ready면 플레이어 활성.

- [ ] **Step 1: 상태 변수 추가** (`viewerApp()` return 객체에)

```javascript
// audio player state
// B4: 논문명은 기존 closure 변수 `name`(이미 URL-encoded)을 그대로 사용 — this.paperName 없음, 재인코딩 금지.
audioPaperTitle: '{{ paper_title|default(paper_name, true)|e }}',   // MediaSession 제목용
audioEl: null,
audioManifest: null,        // {chunks:[{id,dom_id,start_sec,end_sec,...}], audio:{duration_sec}}
audioReady: false,
audioGenerating: false,
audioJobStage: '',          // segmenting|synthesizing|stitching|validating|ready|failed
audioJobDone: 0, audioJobTotal: 0,
audioPlaying: false,
audioCurChunk: -1,
audioFollow: true,          // auto-follow toggle
audioRate: 1.0,
```

- [ ] **Step 2: 로드/생성 메서드 추가**

```javascript
async loadAudio() {
  const r = await apiFetch(`/api/papers/${name}/audio/manifest`);
  if (r.ok) {
    this.audioManifest = await r.json();
    this.audioReady = this.audioManifest.status === 'complete';
    if (this.audioReady) await this.mountAudioHtml();
  } else {
    this.audioReady = false;   // 미생성 → 생성 버튼 노출
  }
},
async mountAudioHtml() {
  const r = await apiFetch(`/api/papers/${name}/audio/html`);
  if (r.ok) this.mdKoAudioContent = await r.text();   // 오디오 모드 본문 = 서버 span HTML
},
async generateAudio() {
  this.audioGenerating = true; this.audioJobStage = 'segmenting';
  await apiFetch(`/api/papers/${name}/audio/jobs`, {method:'POST'});
  this.pollAudioJob();
},
async pollAudioJob() {
  const r = await apiFetch(`/api/papers/${name}/audio/status`);
  const st = await r.json();
  this.audioJobStage = st.stage; this.audioJobDone = st.done; this.audioJobTotal = st.total;
  if (st.stage === 'ready') { this.audioGenerating = false; await this.loadAudio(); return; }
  if (st.stage === 'failed') { this.audioGenerating = false; showToast('오디오 생성 실패: '+(st.error||''), 'error'); return; }
  setTimeout(() => this.pollAudioJob(), 1500);
},
```

- [ ] **Step 3: audioMode 토글 시 loadAudio 호출 (B5: 서버 HTML이 최종값이 되도록)**

기존 `toggleAudio()`(viewer.html ~1831줄)는 끝에서 `await this.loadMdForCurrentLang()`를 호출한다(line 1845). 이게 `md-ko-audio`를 marked로 렌더해 `mdKoAudioContent`를 덮어쓰면 D3(서버 렌더 HTML)이 무력화된다. 따라서 마지막 로드 호출을 분기로 교체:

```javascript
// toggleAudio() 끝의  await this.loadMdForCurrentLang();  를 아래로 교체
if (this.audioMode) await this.loadAudio();        // 서버 렌더 HTML이 최종값
else await this.loadMdForCurrentLang();
```

또한 `loadMdForCurrentLang()`이 audio mode에서 `md-ko-audio`를 marked로 로드하지 않도록, 그 함수 내 audio 분기를 제거하거나 `if (this.audioMode) return;` 가드를 둔다(서버 HTML과 충돌 방지).

- [ ] **Step 4: 수동 검증 (브라우저)**

`docker compose up -d` 후, Plan 1로 생성된 논문에서 듣기 토글 → manifest 로드 확인, 미생성 논문에서 "생성" 버튼·진행률 표시 확인.

- [ ] **Step 5: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(viewer): audio player state + generate/poll/load flow"
```

---

## Task 4: 재생 컨트롤 (play/pause, 배속, prev/next, tap-to-play)

**Files:**
- Modify: `viewer/app/templates/viewer.html`

단일 `<audio>` element 1개 유지. 첫 play는 사용자 클릭 핸들러에서.

- [ ] **Step 1: `<audio>` element + 컨트롤 UI 추가** (오디오 모드 본문 상단, `x-show="audioMode && audioReady"`)

```html
<div x-show="audioMode && audioReady" class="sticky top-0 z-20 flex items-center gap-2 p-2 rounded-lg"
     :class="$store.darkMode.on ? 'bg-gray-800' : 'bg-white shadow'">
  <audio x-ref="audioEl" :src="audioSrc()" preload="metadata"
         @timeupdate="onTimeUpdate()" @play="audioPlaying=true" @pause="audioPlaying=false"
         @error="onAudioError()"></audio>
  <button @click="togglePlay()" x-text="audioPlaying ? '⏸' : '▶'"></button>
  <button @click="prevSentence()" title="이전 문장">⏮</button>
  <button @click="nextSentence()" title="다음 문장">⏭</button>
  <select x-model.number="audioRate" @change="$refs.audioEl.playbackRate=audioRate">
    <template x-for="r in [0.8,1.0,1.25,1.5,2.0]"><option :value="r" x-text="r+'x'"></option></template>
  </select>
  <label class="text-xs flex items-center gap-1"><input type="checkbox" x-model="audioFollow"> 따라가기</label>
</div>
```

- [ ] **Step 2: 컨트롤 메서드 추가**

```javascript
// B4: 로드한 manifest의 audio.file을 URL에 고정 → old timeline + new audio race 차단.
audioSrc() {
  const f = this.audioManifest?.audio?.file || '';
  return `/api/papers/${name}/audio/file?file=${encodeURIComponent(f)}`;
},
togglePlay() {
  const a = this.$refs.audioEl;
  if (a.paused) { a.playbackRate = this.audioRate; a.play().catch(e => showToast('재생 실패: '+e.message,'error')); }
  else a.pause();
},
chunkAt(t) {                       // currentTime → chunk index
  const cs = this.audioManifest.chunks;
  for (let i = cs.length-1; i >= 0; i--) if (t >= cs[i].start_sec) return i;
  return 0;
},
seekToChunk(i) {
  const cs = this.audioManifest.chunks;
  if (i < 0 || i >= cs.length) return;
  this.$refs.audioEl.currentTime = cs[i].start_sec + 0.001;
},
prevSentence() { this.seekToChunk(this.audioCurChunk - 1); },
nextSentence() { this.seekToChunk(this.audioCurChunk + 1); },
// B4: 버전드 파일이 재생성으로 정리돼 404면 manifest/html을 다시 로드해 최신 버전과 정합.
async onAudioError() {
  await this.loadAudio();          // 최신 manifest+html → audioSrc()가 새 버전 가리킴
},
```

- [ ] **Step 3: tap-to-play (문장 클릭 → 그 청크부터) — B7: 기존 핸들러 보존**

기존 markdown 컨테이너(viewer.html line 734)는 이미 `@click="handleMarkdownClickDesktop($event)"`를 가진다. 이를 제거하지 말고 **결합 핸들러**로 교체한다(기존 데스크톱 동작 회귀 방지):

```html
<!-- line 734: @click="handleMarkdownClickDesktop($event)" → 아래로 교체 -->
<div @click="onMarkdownClick($event)" ...></div>
```
```javascript
onMarkdownClick(e) {
  this.onSentenceTap(e);                 // 오디오 모드면 그 문장부터 재생
  this.handleMarkdownClickDesktop(e);    // 기존 동작 유지
},
onSentenceTap(e) {
  if (!this.audioMode || !this.audioReady) return;
  const el = e.target.closest('[data-tts-chunk]');
  if (!el) return;
  this.seekToChunk(parseInt(el.dataset.ttsChunk, 10));
  if (this.$refs.audioEl.paused) this.togglePlay();
},
```

- [ ] **Step 4: 수동 검증** — 재생/일시정지, 배속, prev/next, 문장 탭 점프 동작 확인(iPhone 뷰포트 Playwright 또는 실제 기기).

- [ ] **Step 5: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(viewer): audio playback controls + tap-to-play (single <audio> + currentTime)"
```

---

## Task 5: 현재 문장 하이라이트 + auto-follow 스크롤

**Files:**
- Modify: `viewer/app/templates/viewer.html`

`timeupdate`에서 currentTime→chunk 매핑, 해당 `data-tts-chunk` span 강조(`aria-current`), follow면 스크롤.

- [ ] **Step 1: onTimeUpdate 메서드**

```javascript
onTimeUpdate() {
  if (!this.audioManifest) return;
  const i = this.chunkAt(this.$refs.audioEl.currentTime);
  if (i === this.audioCurChunk) return;
  this.audioCurChunk = i;
  // 이전 강조 제거 + 현재 강조
  this.$el.querySelectorAll('[data-tts-chunk].tts-active').forEach(n => {
    n.classList.remove('tts-active'); n.removeAttribute('aria-current');
  });
  const cur = this.$el.querySelector(`[data-tts-chunk="${i}"]`);
  if (cur) {
    cur.classList.add('tts-active'); cur.setAttribute('aria-current', 'true');
    if (this.audioFollow) cur.scrollIntoView({behavior:'smooth', block:'center'});
  }
  if (this.throttledSaveListening) this.throttledSaveListening();   // B6: Task6에서 정의 → guard
},
```

- [ ] **Step 2: 하이라이트 스타일 추가** (viewer.html `<style>`)

```css
.tts-active { background: rgba(56,189,248,0.25); border-radius: 4px; transition: background .2s; }
```

- [ ] **Step 3: 수동 검증** — 재생 중 현재 문장이 강조되고, 따라가기 켜짐 시 자동 스크롤, 끄면 멈추는지 확인.

- [ ] **Step 4: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(viewer): current-sentence highlight + auto-follow scroll on timeupdate"
```

---

## Task 6: 이어듣기 (듣기 진행률 저장/복원)

**Files:**
- Modify: `viewer/app/templates/viewer.html`

듣기 진행률을 `/audio/progress`에 저장(읽기와 분리), 재진입 시 복원. throttle로 과빈도 저장 방지.

- [ ] **Step 1: 저장/복원 메서드**

```javascript
throttledSaveListening() {
  clearTimeout(this._lisT);
  this._lisT = setTimeout(() => this.saveListening(), 2000);
},
async saveListening() {
  if (!this.audioManifest) return;
  const a = this.$refs.audioEl;
  const dur = this.audioManifest.audio.duration_sec || 1;
  await apiFetch(`/api/papers/${name}/audio/progress`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      audio_version: this.audioManifest.source?.sha256 || '',
      chunk_id: this.audioCurChunk, time_sec: a.currentTime,
      percent: Math.round(a.currentTime/dur*100)
    })
  });
},
async restoreListening() {
  const r = await apiFetch(`/api/papers/${name}/audio/progress`);
  if (!r.ok) return;
  const p = await r.json();
  if (p && p.time_sec && p.audio_version === (this.audioManifest.source?.sha256||'')) {
    this.$refs.audioEl.currentTime = p.time_sec;     // 이어듣기
  }
},
```

- [ ] **Step 2: 로드 완료 후 복원 호출** — Task 3 `mountAudioHtml()` 끝에서 `$nextTick(() => this.restoreListening())`.

- [ ] **Step 3: 수동 검증** — 재생 중 이동 후 페이지 새로고침 → 같은 지점에서 이어지는지(읽기 진행률과 독립인지) 확인.

- [ ] **Step 4: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(viewer): resume listening via separate audio progress"
```

---

## Task 7: MediaSession (잠금화면/제어센터 — progressive enhancement)

**Files:**
- Modify: `viewer/app/templates/viewer.html`

지원 시 metadata + play/pause/prev/next/seek 연결. 미지원이어도 인앱 컨트롤 동작.

- [ ] **Step 1: setupMediaSession 메서드**

```javascript
setupMediaSession() {
  if (!('mediaSession' in navigator) || !this.audioManifest) return;
  navigator.mediaSession.metadata = new MediaMetadata({
    title: this.audioPaperTitle, artist: 'PaperFlow 듣기판',
  });
  const a = this.$refs.audioEl;
  navigator.mediaSession.setActionHandler('play', () => a.play().catch(() => {}));  // nit#7
  navigator.mediaSession.setActionHandler('pause', () => a.pause());
  navigator.mediaSession.setActionHandler('previoustrack', () => this.prevSentence());
  navigator.mediaSession.setActionHandler('nexttrack', () => this.nextSentence());
  navigator.mediaSession.setActionHandler('seekbackward', (d) => { a.currentTime -= (d.seekOffset||10); });
  navigator.mediaSession.setActionHandler('seekforward', (d) => { a.currentTime += (d.seekOffset||10); });
},
```

- [ ] **Step 2: ready 후 호출** — Task 3 `loadAudio()`에서 `audioReady` 설정 후 `this.setupMediaSession()`.

- [ ] **Step 3: 실기기 검증 항목(스펙 §9)** — iPhone Safari: 화면 잠금 재생 지속, 잠금화면 prev/next, AirPods 컨트롤. (자동화 불가 — 체크리스트로 수동 확인)

- [ ] **Step 4: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(viewer): MediaSession lock-screen controls (progressive enhancement)"
```

---

## Task 8: 통합 검증 (iPhone 뷰포트 Playwright + 실기기 체크리스트)

**Files:** (없음 — 검증)

- [ ] **Step 1: 빌드 + 기동**

Run: `docker compose build paperflow-viewer && docker compose up -d`

- [ ] **Step 2: Playwright iPhone 뷰포트 스모크** (기존 `/tmp/cbx-venv` 방식 또는 node playwright)

검증: 듣기 토글 → (필요시 생성→ready) → ▶ 재생 → 현재 문장 `.tts-active` 강조 등장 → ⏭ 다음 문장 currentTime 점프 → 문장 탭 점프 → 새로고침 후 이어듣기.

```javascript
// 핵심 assert 예
const active = await page.locator('.tts-active').count();   // 재생 중 1개 강조
console.log('active spans:', active);
```

- [ ] **Step 3: 실기기 체크리스트(수동)** — iPhone Safari 화면잠금 재생 지속 / 잠금화면 컨트롤 / 배경 전환 / Range seek.

- [ ] **Step 4: 상태 파일 기록** (자동 커밋 아님) — 검증 결과·남은 이슈를 HANDOFF/상태 파일에.

---

## Self-Review 결과

- **Spec coverage (§6 UI)**: 단일 `<audio>`+currentTime→Task4 / 하이라이트→Task5 / prev·next·tap→Task4 / auto-follow→Task5 / 배속→Task4 / 이어듣기·진행률 분리→Task6 / 생성 UX→Task3 / MediaSession→Task7 / 서버 렌더 HTML→Task2. heading level 의존성→Task1.
- **Placeholder scan**: 모든 코드 스텝 실제 코드 포함. UI 검증은 단위테스트가 어려워 Playwright/수동으로 명시(서버 렌더러·chunker는 pytest).
- **Type consistency**: manifest.chunks 키(id/dom_id/kind/level/start_sec/end_sec/paragraph_index/text)가 Plan 1 chunker/manifest 산출과 일치. `data-tts-chunk`=chunk id, `id`=dom_id 규약 Task2↔4↔5 일관. `chunkAt`/`seekToChunk`/`audioCurChunk` 시그니처 일관.

## 의존성
- Plan 1(백엔드) 완료 후 진행. Task 1은 Plan 1의 chunker(Task 1)를 보강하므로 Plan 1 머지 후 적용.
