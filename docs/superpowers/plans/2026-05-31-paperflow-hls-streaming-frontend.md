# PaperFlow HLS 실시간 TTS — 프론트엔드 구현 플랜 (Plan 2/2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan 1 의 HLS 스트리밍(signed playlist + 증분 manifest)을 뷰어에서 재생한다 — iOS 네이티브/hls.js 부착, 첫 1\~3 세그먼트부터 streaming mount, sub-split 그룹 하이라이트, 토큰 만료 시 remount, 기존 mp3 폴백.

**Architecture:** `viewerApp()` 의 audio 플레이어를 HLS 로 전환한다. `audio.hls` 있으면 signed playlist URL(`/audio/stream-url`)을 받아 네이티브(`<audio src>`) 또는 hls.js 로 부착하고, streaming 중 manifest 를 주기 폴링해 `chunk.id` keyed 로 timing 을 머지하며 하이라이트를 확장한다. 401/403 시 새 signed URL 로 remount. `audio.hls` 없는 v1 매니페스트는 기존 단일 mp3 경로로 폴백.

**Tech Stack:** Alpine.js, HTML5 `<audio>` + HLS(native/hls.js pinned+SRI), 기존 viewer.html 플레이어.

**선행:** Plan 1(백엔드) 완료. 스펙 [docs/superpowers/specs/2026-05-31-paperflow-hls-streaming-design.md](../specs/2026-05-31-paperflow-hls-streaming-design.md) §10.

---

## File Structure

```text
viewer/app/templates/viewer.html    # Modify: HLS 부착·streaming mount·그룹 하이라이트·remount·폴백
viewer/app/templates/base.html      # Modify: hls.js pinned+SRI <script>(또는 vendoring), Referrer-Policy
```

기존 MVP 플레이어(Plan: live-tts-frontend) 의 상태/메서드를 확장한다. 핵심 변경점만 task 로 쪼갠다.

---

## Task 1: hls.js 로드 + Referrer-Policy (base.html)

**Files:**
- Modify: `viewer/app/templates/base.html`

비-iOS 폴백용 hls.js 를 pinned version + SRI 로 로드. 토큰 노출 축소 위해 `Referrer-Policy: same-origin`.

- [ ] **Step 1: base.html `<head>` 에 추가**

```html
<!-- Referrer-Policy: query token(?token/?ptoken) 외부 유출 축소 -->
<meta name="referrer" content="same-origin">
<!-- hls.js (비-iOS 폴백). pinned + SRI. (vendoring 옵션: static 으로 받아 self-host) -->
<script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js"
        integrity="sha384-PLACEHOLDER_SRI"
        crossorigin="anonymous" referrerpolicy="no-referrer"></script>
```

> SRI 해시는 실제 버전의 공식 해시로 교체(`curl -s <url> | openssl dgst -sha384 -binary | openssl base64 -A`). vendoring 선택 시 `viewer/app/static/hls.min.js` 로 받아 `<script src="/static/hls.min.js">`.

- [ ] **Step 2: 로드 확인**

Run: viewer 빌드·기동 후 브라우저 콘솔에서 `typeof Hls`
Expected: `"function"` (비-iOS), iOS 는 네이티브라 불필요.

- [ ] **Step 3: Commit**

```bash
git add viewer/app/templates/base.html
git commit -m "feat(hls): load pinned hls.js (SRI) + same-origin referrer policy"
```

---

## Task 2: HLS 부착 — 네이티브/hls.js 분기 + v1 폴백

**Files:**
- Modify: `viewer/app/templates/viewer.html` (`viewerApp()`)

`loadAudio()` 를 HLS 인지로 확장: manifest 에 `audio.hls` 있으면 signed playlist URL 받아 부착, 없으면 기존 mp3 경로.

- [ ] **Step 1: 상태 변수 추가** (`viewerApp()` return 객체)

```javascript
audioIsHls: false,
audioHls: null,          // hls.js 인스턴스(비-iOS)
audioStreamUrl: '',      // signed playlist URL
```

- [ ] **Step 2: loadAudio() 확장 + attachHls()**

기존 `loadAudio()`(MVP)를 아래로 교체:

```javascript
async loadAudio() {
  const r = await apiFetch('/api/papers/' + name + '/audio/manifest');
  if (!r || !r.ok) { this.audioReady = false; return; }
  this.audioManifest = await r.json();
  const hls = this.audioManifest.audio && this.audioManifest.audio.hls;
  this.audioIsHls = !!hls;
  const st = this.audioManifest.status;
  // streaming 에서도 mount(첫 세그먼트부터). complete/failed_partial 도 재생.
  this.audioReady = ['streaming','complete','failed_partial'].includes(st);
  if (!this.audioReady) return;
  await this.mountAudioHtml();          // 전체 span HTML(서버)
  if (this.audioIsHls) await this.attachHls();
  this.setupMediaSession();
  if (st === 'streaming') this.pollStreamingManifest();   // Task 3
},

async attachHls() {
  // signed playlist URL 발급(쿠키 비의존 1급 경로)
  const su = await apiFetch('/api/papers/' + name + '/audio/stream-url');
  if (!su || !su.ok) { this.audioReady = false; return; }
  this.audioStreamUrl = (await su.json()).url;
  const el = this.$refs.audioEl;
  if (this.audioHls) { this.audioHls.destroy(); this.audioHls = null; }
  if (el.canPlayType('application/vnd.apple.mpegurl')) {
    el.src = this.audioStreamUrl;       // iOS/Safari 네이티브
  } else if (window.Hls && Hls.isSupported()) {
    const hls = new Hls({ xhrSetup: (xhr) => { xhr.withCredentials = true; } });
    hls.loadSource(this.audioStreamUrl); hls.attachMedia(el);
    this.audioHls = hls;
    this.setupHlsErrorHandling(hls);    // Task 5
  } else if (this.audioManifest.audio.mp3 && this.audioManifest.audio.mp3.file) {
    el.src = '/api/papers/' + name + '/audio/file';   // mp3 폴백
  }
},
```

`audioSrc()`(MVP, mp3 전용)는 v1 폴백 전용으로 남기고, HLS 경로는 `attachHls()` 가 `el.src`/hls.js 를 직접 설정한다. 기존 `<audio :src="audioSrc()">` 바인딩은 제거하고 src 를 코드에서 설정(아래):

```html
<!-- viewer.html audio element: :src 제거(코드에서 설정) -->
<audio x-ref="audioEl" preload="metadata"
       @timeupdate="onTimeUpdate()" @play="audioPlaying=true" @pause="audioPlaying=false"
       @error="onAudioError()"></audio>
```

v1(`audio.hls` 없음): `attachHls()` 를 타지 않으므로 `loadAudio()` 끝에서 `if (!this.audioIsHls) this.$refs.audioEl.src = '/api/papers/'+name+'/audio/file';`

- [ ] **Step 3: 수동 검증**

Plan 1 으로 생성된 v2 논문 → 듣기 토글 → 네이티브/hls.js 부착·재생. 기존 v1 mp3 논문 → mp3 폴백 재생.

- [ ] **Step 4: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(hls): attach native/hls.js via signed playlist URL + v1 mp3 fallback"
```

---

## Task 3: streaming manifest 폴링 + id-keyed timing 머지

**Files:**
- Modify: `viewer/app/templates/viewer.html`

streaming 중 manifest 를 주기 재조회해 `chunk.id` keyed 로 `start_sec/end_sec` 갱신(중복 append 금지). complete/실패 시 중단.

- [ ] **Step 1: pollStreamingManifest() 추가**

```javascript
async pollStreamingManifest() {
  if (this.audioManifest.status !== 'streaming') return;
  const r = await apiFetch('/api/papers/' + name + '/audio/manifest');
  if (r && r.ok) {
    const m = await r.json();
    // id-keyed 머지: 기존 chunks 의 timing 만 갱신(텍스트/순서 불변)
    const byId = {}; this.audioManifest.chunks.forEach(c => byId[c.id] = c);
    m.chunks.forEach(c => { if (byId[c.id]) { byId[c.id].start_sec = c.start_sec; byId[c.id].end_sec = c.end_sec; } });
    this.audioManifest.status = m.status;
    this.audioManifest.audio.duration_sec = m.audio.duration_sec;
    if (m.audio.mp3) this.audioManifest.audio.mp3 = m.audio.mp3;
  }
  if (this.audioManifest.status === 'streaming') setTimeout(() => this.pollStreamingManifest(), 3000);
},
```

- [ ] **Step 2: 수동 검증**

streaming 시작 직후 manifest chunks 전체 텍스트 존재 + start_sec 가 점진적으로 채워지는지(폴링 로그/네트워크).

- [ ] **Step 3: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(hls): poll streaming manifest, id-keyed timing merge"
```

---

## Task 4: sub-split 그룹 하이라이트

**Files:**
- Modify: `viewer/app/templates/viewer.html`

`onTimeUpdate` 가 `start_sec != null` 인 chunk 만 대상으로 하고, 해당 chunk 의 `sentence_group_id` 그룹 전체를 active 처리. (group active = any sub-chunk in range)

- [ ] **Step 1: chunkAt + onTimeUpdate 수정**

```javascript
chunkAt(t) {                       // start_sec 채워진 chunk 중 최신
  const cs = this.audioManifest.chunks;
  for (let i = cs.length - 1; i >= 0; i--)
    if (cs[i].start_sec != null && t >= cs[i].start_sec) return i;
  return -1;
},
onTimeUpdate() {
  if (!this.audioManifest) return;
  const i = this.chunkAt(this.$refs.audioEl.currentTime);
  if (i < 0 || i === this.audioCurChunk) return;
  this.audioCurChunk = i;
  const gid = this.audioManifest.chunks[i].sentence_group_id;
  document.querySelectorAll('[data-tts-chunk].tts-active').forEach(n => {
    n.classList.remove('tts-active'); n.removeAttribute('aria-current');
  });
  // 같은 group 의 모든 sub-span 강조
  const groupChunks = this.audioManifest.chunks.filter(c => c.sentence_group_id === gid);
  let firstEl = null;
  groupChunks.forEach(c => {
    const el = document.querySelector('[data-tts-chunk="' + c.id + '"]');
    if (el) { el.classList.add('tts-active'); el.setAttribute('aria-current','true'); firstEl = firstEl || el; }
  });
  if (firstEl && this.audioFollow) firstEl.scrollIntoView({behavior:'smooth', block:'center'});
  this.throttledSaveListening();
},
```

> 서버 렌더 HTML(`render_audio_html`)은 sub-chunk 마다 `data-tts-chunk` span 을 만든다(Plan 1 Task9 `/audio/html` 전체 chunks). group 강조는 같은 `sentence_group_id` span 들을 묶어 칠한다. (대안: sub-span 단위 — §15. 여기선 그룹 단위 채택.)

- [ ] **Step 2: 수동 검증**

긴 문장(sub-split) 재생 시 그룹 전체가 한 문장처럼 강조되는지.

- [ ] **Step 3: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(hls): sentence-group highlight for sub-split chunks"
```

---

## Task 5: 토큰 만료 remount + hls.js 에러 처리

**Files:**
- Modify: `viewer/app/templates/viewer.html`

segment 401/403 → `/audio/stream-url` 재발급 → remount + currentTime 복원. hls.js 에러 타입별 분기.

- [ ] **Step 1: onAudioError + setupHlsErrorHandling + remount**

```javascript
async remountAudio() {
  const t = this.$refs.audioEl.currentTime;
  await this.attachHls();                 // 새 signed URL
  this.$nextTick(() => { try { this.$refs.audioEl.currentTime = t; } catch(e){} });
},
async onAudioError() {
  // 네이티브 경로 401/403 는 audio error 로 표면화 → remount 시도
  if (this.audioIsHls) await this.remountAudio();
  else await this.loadAudio();
},
setupHlsErrorHandling(hls) {
  hls.on(Hls.Events.ERROR, (evt, data) => {
    if (!data.fatal) return;
    if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
      // MANIFEST/FRAG load error(토큰 만료 등) → remount
      this.remountAudio();
    } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
      hls.recoverMediaError();
    } else {
      // 복구 불가 → mp3 폴백
      const mp3 = this.audioManifest.audio.mp3;
      if (mp3 && mp3.file) { this.audioIsHls = false; this.$refs.audioEl.src = '/api/papers/'+name+'/audio/file'; }
    }
  });
},
```

- [ ] **Step 2: 수동 검증**

(토큰 TTL 을 짧게 임시 설정해) 만료 후 segment 401 → 자동 remount·이어재생 확인. hls.js fatal 시 mp3 폴백.

- [ ] **Step 3: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(hls): token-expiry remount + hls.js error handling + mp3 fallback"
```

---

## Task 6: 이어듣기 — sentence_group + currentTime

**Files:**
- Modify: `viewer/app/templates/viewer.html`

duration/position 저장·복원을 sentence_group_id 기준으로도 복원 가능하게(스펙 §4). 기존 currentTime 복원 유지 + group 기록.

- [ ] **Step 1: saveListening/restoreListening 보강**

```javascript
async saveListening() {
  if (!this.audioManifest || !this.$refs.audioEl) return;
  const a = this.$refs.audioEl;
  const dur = this.audioManifest.audio.duration_sec || 1;
  const cur = this.audioCurChunk >= 0 ? this.audioManifest.chunks[this.audioCurChunk] : null;
  await apiFetch('/api/papers/' + name + '/audio/position', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      audio_version: (this.audioManifest.source && this.audioManifest.source.sha256) || '',
      sentence_group_id: cur ? cur.sentence_group_id : null,
      time_sec: a.currentTime, percent: Math.round(a.currentTime/dur*100)
    })
  });
},
```

`restoreListening` 은 기존 currentTime 복원 유지(streaming 중엔 해당 시점이 아직 미생성일 수 있으니 `time_sec <= duration_sec` 일 때만 적용):

```javascript
async restoreListening() {
  const r = await apiFetch('/api/papers/' + name + '/audio/position');
  if (!r || !r.ok) return;
  const p = await r.json();
  const ver = (this.audioManifest.source && this.audioManifest.source.sha256) || '';
  if (p && p.time_sec && p.audio_version === ver &&
      p.time_sec <= (this.audioManifest.audio.duration_sec || 0) && this.$refs.audioEl) {
    this.$refs.audioEl.currentTime = p.time_sec;
  }
},
```

- [ ] **Step 2: 수동 검증** — 재생 중 이동→새로고침→이어듣기(생성 완료분 내에서).

- [ ] **Step 3: Commit**

```bash
git add viewer/app/templates/viewer.html
git commit -m "feat(hls): resume by sentence_group + currentTime (streaming-safe)"
```

---

## Task 7: 통합 검증 (Playwright + 실기기 체크리스트)

**Files:** (없음 — 검증)

- [ ] **Step 1: 빌드 + 기동**

Run: `docker compose build paperflow-viewer && docker compose up -d`

- [ ] **Step 2: Playwright(Chromium + hls.js)**

검증: 듣기 토글 → (생성 중이면) streaming mount → ▶ 재생 → start_sec 채워지며 `.tts-active` 그룹 강조 등장 → ⏭/문장 탭 → seek → 토큰 만료 remount(짧은 TTL 임시) → 새로고침 이어듣기.

```javascript
// 핵심 assert
await page.locator("button:visible:has-text('듣기')").first().click();
await page.waitForTimeout(3000);
const active = await page.locator('.tts-active').count();   // 그룹 강조 ≥1
const isHls = await page.evaluate(() => Alpine.$data(document.querySelector('audio')).audioIsHls);
console.log('hls:', isHls, 'active:', active);
```

- [ ] **Step 3: 실기기 — BLOCKING preflight (스펙 §12.3)**

iPhone Safari 체크리스트(수동):
- signed playlist URL 로 m3u8/segment 요청이 **토큰만으로 통과**(쿠키 없이)하는가
- 첫 audible time(첫 1\~3 세그먼트), 첫 10문장 stall 무
- 화면잠금/백그라운드/네트워크 전환 후 지속 재생·seek
- 완료(VOD) 후 전체 seek
- MediaSession/AirPods

- [ ] **Step 4: 상태 파일 기록** (자동 커밋 아님) — 검증 결과·실기기 통과 여부·남은 이슈를 HANDOFF/상태 파일에.

---

## Self-Review 결과

- **Spec coverage (§10 UI)**: HLS 부착(네이티브/hls.js)→Task1,2 · streaming mount + manifest 머지→Task2,3 · 그룹 하이라이트→Task4 · 토큰 remount + 에러분기→Task5 · 이어듣기→Task6 · v1 폴백→Task2 · Referrer/로그→Task1 · 실기기 preflight→Task7.
- **Placeholder scan**: 모든 코드 스텝 실제 코드. SRI 해시는 "실제 해시로 교체" 명시(외부 자산 고정값).
- **Type consistency**: `audio.hls`/`audio.mp3.file`/`source.sha256`/`sentence_group_id`/`chunk.id`/`start_sec` 가 Plan 1 manifest·`/audio/html`·API 와 일치. `attachHls`/`remountAudio`/`pollStreamingManifest`/`chunkAt` 시그니처 일관.

## 의존성
- Plan 1(백엔드) 완료 후. Task 1 의 hls.js 버전/SRI 는 빌드 시점 최신 안정 버전으로 고정.
