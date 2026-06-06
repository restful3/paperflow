# 목록 보기 랜덤 정렬(셔플) — 설계

**날짜**: 2026-06-06
**대상 파일**: `viewer/app/templates/papers.html` (단일 파일, 프론트엔드 Alpine.js)
**범위**: 논문 목록 페이지에 "랜덤" 정렬 옵션 추가. 카드·목록 뷰 공통.

## 목적

논문 목록을 무작위 순서로 섞어 보여주는 정렬 옵션. "오늘 뭐 읽지" 식으로 라이브러리를 무작위로 둘러보기 위함. 사용자가 명시적으로 트리거할 때만 다시 섞이고, 그 외 상호작용(검색·호버·재렌더)에는 순서가 안정적으로 유지된다.

## 핵심 원리 — 안정적 랜덤 키

`papersApp()`의 `filteredPapers`는 **매 렌더마다 재계산되는 getter**다. 비교 함수에서 `Math.random()`을 직접 호출하면 검색어 입력·호버 등 모든 reactive 재렌더마다 목록이 다시 뒤섞여 사용 불가능해진다.

해결: 각 논문 `name`에 랜덤 값을 한 번 부여한 맵 `shuffleKeys = {name: Math.random()}` 를 두고, 그 값으로 정렬한다. 맵은 **재셔플 트리거 시에만** 새로 생성한다.

## 상태 변경 (`papersApp()`)

- `sortBy` 에 `'random'` 값 허용 (기존처럼 `localStorage 'pf-sort'` 에 persist).
- 신규 상태 `shuffleKeys: {}` — `{name: number}` 맵. **localStorage에 저장하지 않음** → 새로고침 시 새 셔플(랜덤의 기대 동작).

## 로직

### `reshuffle()` 메서드 (신규)

```js
reshuffle() {
  const keys = {};
  for (const p of this.papers) keys[p.name] = Math.random();
  this.shuffleKeys = keys;
}
```

`this.papers`(필터 전 전체 목록) 기준으로 키 재생성. 새로 업로드된 논문도 다음 reshuffle에서 키를 받는다.

### `filteredPapers` getter — 정렬 분기 추가

기존 `if/else if` 정렬 체인에 분기 추가:

```js
} else if (this.sortBy === 'random') {
  results = [...results].sort((a, b) =>
    (this.shuffleKeys[a.name] ?? 0) - (this.shuffleKeys[b.name] ?? 0)
  );
}
```

- `sortOrder`(asc/desc)는 **무시**한다 (랜덤 정렬엔 방향 개념이 없음).
- 키가 없는 논문(`?? 0`)은 앞쪽에 모이지만, 정상 흐름에선 reshuffle이 항상 선행되므로 발생하지 않는다.

### 트리거

1. **드롭다운 선택**: 정렬 `<select>` 의 `@change` 에서 값이 `'random'` 이면 `reshuffle()` 호출.
2. **로드 후 보정**: 페이지/논문 로드 완료 시점에 `sortBy === 'random'` 이고 `shuffleKeys` 가 비어 있으면 `reshuffle()` 1회 호출 (새로고침으로 random이 복원된 경우 대비).

## UI — asc/desc 버튼을 🎲 재셔플 버튼으로 전환

정렬 드롭다운 옆 오름/내림차순 토글 버튼(**데스크톱·모바일 두 벌**: 약 line 282, 347)을 랜덤 모드에서 재활용한다. 새 버튼은 추가하지 않는다.

- `@click`: `sortBy === 'random'` 이면 `reshuffle()`, 아니면 기존 asc/desc 토글 로직.
- 아이콘: `x-show` 로 분기 — `sortBy !== 'random'` 이면 기존 화살표 SVG(`rotate-180` 클래스 유지), `sortBy === 'random'` 이면 🎲 글리프.
- `:title`: 랜덤 모드 "다시 섞기", 아니면 기존 "Ascending"/"Descending".

드롭다운 `<option value="random">랜덤</option>` 도 두 벌(데스크톱 ~269, 모바일 ~336) 모두에 추가.

## 적용 범위

정렬 드롭다운은 카드·목록 뷰가 **공유**하므로 두 뷰 모두에 자동 적용된다. 별도 분기 없음.

## 비목표 (YAGNI)

- 셔플 결과의 localStorage 영속화 — 새로고침마다 새 셔플이 자연스러움.
- 서버 측 랜덤/시드 동기화 — 순수 클라이언트 기능.
- "랜덤 1편 열기" 점프 버튼 — 이번 범위 아님(별도 기능).

## 검증 (수동, 브라우저)

뷰어 템플릿(Alpine.js)이라 JS 단위 테스트 환경이 없다. Docker 재빌드 후 http://localhost:8090 에서 확인:

1. 정렬에서 "랜덤" 선택 → 목록이 무작위 순서로 섞임.
2. 🎲 버튼 클릭 → 순서가 다시 섞임(이전과 다른 배열).
3. 검색어 입력/지움 → 순서가 흔들리지 않음(안정).
4. 다른 정렬(날짜/제목 등)로 전환 후 복귀 → 각 정렬 정상.
5. 카드 뷰·목록 뷰 양쪽에서 동일 동작.
6. 새로고침 후에도 "랜덤"이 유지되며 새 셔플로 표시.
