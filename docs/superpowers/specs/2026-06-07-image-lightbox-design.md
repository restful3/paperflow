# 이미지 라이트박스(팬/줌) — 설계

**날짜**: 2026-06-07
**대상**: PaperFlow 웹 뷰어 (`viewer/app/templates/viewer.html`)
**상태**: 설계 승인 대기 → 구현 계획 작성 예정

## 배경 / 목적

뷰어 본문(논문 figure 등)의 이미지를 클릭/탭하면 확대해서 크게 볼 수 있게 한다. 모바일과 PC 모두 지원하며, 단순 확대를 넘어 **라이트박스 오버레이 + 팬/줌**(드래그 이동, 휠/핀치 확대)을 제공한다.

현재 본문 이미지는 마크다운이 `x-html`로 주입한 HTML 안의 `<img>`라 Alpine 핸들러가 직접 붙지 않는다. 따라서 **이벤트 위임**으로 처리한다. 메인 MD 컨테이너에는 이미 `@click="onMarkdownClick($event)"` 위임이 존재한다(`viewer.html:913`).

## 결정 사항 (브레인스토밍 합의)

1. **줌 수준**: 라이트박스 + 팬/줌 (단순 라이트박스나 외부 라이브러리 아님). 커스텀 Alpine 구현으로 기존 스택(Alpine + Tailwind CDN)과 일치, 새 의존성 없음.
2. **적용 범위**: MD 본문 뷰(해설판 포함 — 같은 `activeMdContent` 컨테이너) + Split 뷰 본문. PDF 뷰(브라우저 네이티브)·챗·에디터 프리뷰는 제외.
3. **플랫폼**: PC(마우스/휠) + 모바일(탭/핀치) 모두.

## 현재 코드 맥락 (확인 완료)

| 위치 | 내용 |
|------|------|
| `viewer.html:905-913` | 메인 MD 컨테이너 `.markdown-container`, `x-html="activeMdContent"`, `@click="onMarkdownClick($event)"` + 터치 핸들러들 |
| `viewer.html:974-977` | Split 뷰 본문 컨테이너 `x-html="splitMdContent"` — **`@click` 없음** |
| `onMarkdownClick(e)` | `onSentenceTap(e)`(오디오 모드 문장 seek) + `handleMarkdownClickDesktop(e)` 호출 |
| `handleMarkdownClickDesktop(e)` | 데스크톱: 비-interactive 본문 클릭 시 `toggleTopBarManual()` (상단바 토글) |
| `handleMarkdownTouchStart(e)` / `handleTouchEnd(e)` | 모바일 탭 처리. 깔끔한 탭이면 `preventDefault()`로 합성 click 차단 + 상단바 토글. `isInteractive = closest('a, button, input, textarea, select, [contenteditable]')` — **`img` 미포함** |

**모바일 충돌**: `<img>`가 `isInteractive`에 없어, 현재는 이미지 탭이 합성 click을 못 내고 상단바만 토글된다 → 라이트박스가 안 열림. 이미지 탭이 click을 내도록 `isInteractive`에 `img` 추가가 필요하다.

## 컴포넌트

### 1. 라이트박스 오버레이 (신규 마크업, viewer.html)

`<div x-cloak x-show="lightbox.show" @keydown.escape.window="closeLightbox()">` — 전체화면 fixed, 최상위 z-index(기존 모달이 z-50이므로 z-[70]), 어두운 반투명 배경. 내부:

- `<img :src="lightbox.src" :alt="lightbox.alt">` — `style`에 `transform: translate(${tx}px, ${ty}px) scale(${scale})` 적용. 줌 전환은 `transition: transform`로 부드럽게, 드래그/핀치 중에는 transition 제거.
- 우상단 닫기(X) 버튼.
- 컨테이너에 `touch-action: none`(배경 스크롤·기본 핀치 차단), `select-none`.
- 제스처 핸들러: `@wheel.prevent`, `@pointerdown`/`@pointermove`/`@pointerup`/`@pointercancel`, `@dblclick`, `@click.self`(배경).

### 2. Alpine 상태 (viewerApp() data에 추가)

```js
lightbox: { show: false, src: '', alt: '', scale: 1, tx: 0, ty: 0 },
// 제스처용 임시 상태 (반응형 불필요 — 일반 속성)
_lbPointers: null,        // Map<pointerId, {x,y}>  (init in openLightbox)
_lbDragged: false,        // 이번 제스처에서 이동 발생 여부 (배경 닫기 판단용)
_lbStart: null,           // 드래그/핀치 시작 스냅샷
```

상수: `LB_MIN_SCALE = 1`, `LB_MAX_SCALE = 5`, `LB_DBLCLICK_SCALE = 2`.

### 3. 열기 (이벤트 위임)

```js
onContentImageClick(e) {
  const img = e.target && e.target.tagName === 'IMG' ? e.target : null;
  if (!img || !img.closest('.markdown-container')) return false;
  this.openLightbox(img.currentSrc || img.src, img.alt || '');
  return true;
}
openLightbox(src, alt) {
  this.lightbox = { show: true, src, alt, scale: 1, tx: 0, ty: 0 };
  this._lbPointers = new Map();
  this._lbDragged = false;
  document.body.style.overflow = 'hidden';   // 배경 스크롤 잠금
}
```

- **메인 MD**: `onMarkdownClick(e)` 맨 앞에 `if (this.onContentImageClick(e)) return;` 추가 (이미지면 상단바 토글·오디오 seek 건너뜀).
- **Split**: 컨테이너에 `@click="onContentImageClick($event)"` 추가 (이미지 외 클릭은 false 반환 → 무동작, 기존 동작 보존).

### 4. 모바일 탭 수정 (필수)

`handleMarkdownTouchStart`와 `handleTouchEnd`의 `isInteractive` 셀렉터에 `img` 추가:
`closest('a, button, input, textarea, select, [contenteditable], img')`
→ 이미지 탭이 상단바 토글 경로로 빠지지 않고 합성 click을 내보내 `onMarkdownClick` → `onContentImageClick`로 라이트박스를 연다.

### 5. 줌 / 팬 (Pointer Events 통합)

- **휠 (PC)**: `onLightboxWheel(e)` — `deltaY`로 scale 증감, 커서 위치 기준으로 tx/ty 보정(커서 아래 점이 고정되도록), `[LB_MIN_SCALE, LB_MAX_SCALE]` 클램프. scale이 1로 돌아오면 tx=ty=0.
- **포인터 1개 + scale>1**: 드래그 팬 (pointermove로 tx/ty 갱신, `_lbDragged=true`).
- **포인터 2개**: 핀치 줌 — 두 포인터 거리비로 scale, 중점 기준 tx/ty 보정 (모바일 핀치). `_lbDragged=true`.
- **더블클릭/더블탭** (`@dblclick`): scale이 1이면 `LB_DBLCLICK_SCALE`로(클릭 지점 중심), 아니면 1로 리셋.
- **배경 클릭** (`@click.self`): `scale === 1 && !this._lbDragged`일 때만 `closeLightbox()`. (줌/드래그 후의 포인터업이 닫기로 오인되지 않도록 pointerup에서 `_lbDragged` 플래그 관리)

### 6. 닫기 / 정리

```js
closeLightbox() {
  this.lightbox.show = false;
  document.body.style.overflow = '';   // 스크롤 복원
}
```
- Esc(`@keydown.escape.window`), X 버튼, 배경 클릭(위 조건) 모두 닫기.

### 7. 어포던스 (CSS)

`.markdown-container img { cursor: zoom-in; }` 추가 (클릭 가능 시각 힌트).

## 데이터 흐름

```text
[PC] 이미지 클릭 → onMarkdownClick → onContentImageClick(true) → openLightbox → 오버레이 표시
[Mobile] 이미지 탭 → (touchend: img가 isInteractive라 토글 스킵 → 합성 click) → onMarkdownClick → ... → openLightbox
[Split] 이미지 클릭/탭 → onContentImageClick → openLightbox
오버레이 내: wheel/pointer/dblclick → scale·tx·ty 갱신 → <img> transform
닫기: Esc / X / 배경(scale==1 & !dragged) → closeLightbox → body overflow 복원
```

## 에러 처리 / 엣지

| 상황 | 동작 |
|------|------|
| 이미지 외 본문 클릭 | `onContentImageClick` false → 기존 동작(상단바 토글 등) 유지 |
| 깨진 이미지 src | 오버레이는 열리되 빈 이미지(브라우저 기본). 치명적 아님 |
| 오버레이 열린 채 뷰 전환/언어 변경 | 라이트박스는 독립 오버레이 — 영향 없음. 필요시 닫기 |
| 배경 스크롤 | `body overflow:hidden` + 컨테이너 `touch-action:none` |
| scale==1에서 드래그 | 팬 안 함(이동 없음). 배경 닫기 정상 동작 |

## 설정

없음 (UI 상호작용 기능, 설정 토글 불필요 — YAGNI).

## 테스트 (Playwright, 라이브 뷰어 대상 — 필터 버그 검증과 동일 방식)

브라우저 자동화로 검증 (로그인 → `/viewer/{name}` MD 뷰):

1. 본문 이미지 클릭 → `lightbox.show === true`, `lightbox.src`가 클릭한 이미지 src와 일치, 오버레이 가시
2. Esc → 닫힘 (`lightbox.show === false`, body overflow 복원)
3. X 버튼 → 닫힘
4. 배경 클릭(줌 안 된 상태) → 닫힘
5. 휠 이벤트 → `lightbox.scale > 1`
6. 더블클릭 → scale 1↔2 토글
7. 줌 상태에서 포인터 드래그 → tx/ty 변경(팬)
8. 모바일 뷰포트 + 이미지 탭 → 라이트박스 열림 (isInteractive에 img 추가가 동작함을 검증)
9. 회귀: 이미지 아닌 본문 클릭 시 라이트박스 안 열림 + 기존 상단바 토글 보존

핀치 줌은 멀티터치 자동화 한계로 포인터/휠 경로로 대체 검증하고, 실기기 수동 확인을 권장(테스트 노트에 명시).

## 범위 밖

- PDF 뷰 이미지(브라우저 네이티브 줌 사용)
- 챗 패널 이미지, 에디터 프리뷰 이미지
- 이미지 갤러리/캐러셀(다음/이전 이미지 넘기기) — 단일 이미지 라이트박스만
- 다운로드/공유 버튼 등 부가 기능
