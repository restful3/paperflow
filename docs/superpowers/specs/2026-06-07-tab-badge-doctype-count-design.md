# 탭 배지 — 선택한 타입 기준 개수 표시 (Design)

**날짜**: 2026-06-07
**대상**: 뷰어 목록 화면(`papers.html`)의 Unread/Archived 탭 배지

## 배경 / 문제

목록 화면의 탭(`Unread`, `Archived`) 이름 옆에는 개수 배지가 있다. 현재 이 배지는
`/api/stats` 가 반환하는 폴더 전체 개수(`stats.unread`, `stats.archived`)를 그대로
표시하며 **오른쪽 type 드롭다운(`filterDocType`) 과 무관하게 항상 전체값**이다.

사용자가 오른쪽에서 특정 타입(예: `video`)을 선택하면, 목록은 그 타입으로 걸러지지만
탭 배지는 전체 개수 그대로라 "지금 보고 있는 타입이 각 탭에 몇 개인지" 알 수 없다.

## 목표

오른쪽 type 드롭다운에서 타입을 선택하면 **두 탭 배지 모두** 해당 타입의 개수로 바뀐다.
- 예: `video` 선택 → `Unread (3)`, `Archived (5)`
- "All Types"(빈 값)로 돌아오면 전체값(`unread`/`archived`) 복원.

### 비목표 (Out of scope)

- 태그 칩·자유 검색어는 배지에 **반영하지 않는다**. 배지는 type 드롭다운만 반영한다
  (목록 자체는 기존대로 태그·검색까지 모두 적용해 걸러진다).
- Upload / 오디오 큐 탭 배지는 무관 — 변경 없음.

## 결정한 접근법

**백엔드 `/api/stats` 에 타입별 집계(`by_type`)를 추가한다.**

비활성 탭의 타입별 개수는 프런트가 들고 있지 않으므로(현재 탭 데이터만 로드), 단일
진실 원천을 백엔드 stats 에 두는 것이 두 탭을 모두 정확히 채우는 가장 단순한 방법이다.
프런트는 fetch 추가 없이 getter 분기만으로 해결된다.

대안(프런트에서 반대 탭을 lazy fetch)은 반대 탭 전체 메타데이터(무거움)를 받아야 하고
아카이브/복원 시 캐시 무효화가 필요해 더 복잡하므로 채택하지 않았다.

## 설계

### 1. 백엔드 — `get_stats()` 확장

파일: `viewer/app/services/papers.py` (`get_stats()`, 현재 1274행 부근)

기존 폴더 카운트는 유지하고 타입별 집계를 추가한다.

```python
def get_stats() -> dict:
    by_type = {}  # {doc_type: {"unread": n, "archived": n}}

    def count_dir(base, key):
        total = 0
        if base.exists():
            for d in base.iterdir():
                if not d.is_dir() or d.name.startswith("."):
                    continue
                total += 1
                meta = _load_paper_metadata(d)
                dt = (meta or {}).get("doc_type")
                if dt:  # null/없음/'other' 미지정은 by_type 에서 제외 (전체값에만 집계)
                    by_type.setdefault(dt, {"unread": 0, "archived": 0})[key] += 1
        return total

    unread = count_dir(settings.outputs_dir, "unread")
    archived = count_dir(settings.archives_dir, "archived")
    return {
        "unread": unread,
        "archived": archived,
        "total": unread + archived,
        "by_type": by_type,
    }
```

- `doc_type` 이 없거나 `null` 인 폴더는 `by_type` 에 들어가지 않고 전체값에만 집계된다
  → "All Types" 에서만 보인다. 프런트 `docTypeOptions` 가 `null`/`'other'` 를 제외하는
  기존 동작과 정합한다.
- 엔드포인트 `api.py:637` 의 `/stats` 핸들러는 변경 없음 — 반환 dict 만 커진다.
- 비용: stats 호출당 폴더 수만큼 작은 `paper_meta.json` 읽기. `/api/stats` 는 최초 로드 +
  아카이브/복원/삭제/업로드 완료 후에만 호출되므로 개인 라이브러리 규모에서 무시 가능.

### 2. 프런트 — 배지 표시 분기

파일: `viewer/app/templates/papers.html`

`papersApp()` 에 getter 두 개 추가:

```js
get unreadBadge() {
  return this.filterDocType
    ? (this.stats.by_type?.[this.filterDocType]?.unread ?? 0)
    : this.stats.unread;
},
get archivedBadge() {
  return this.filterDocType
    ? (this.stats.by_type?.[this.filterDocType]?.archived ?? 0)
    : this.stats.archived;
},
```

배지 바인딩 교체:
- 216행 `x-text="stats.unread"` → `x-text="unreadBadge"`
- 229행 `x-text="stats.archived"` → `x-text="archivedBadge"`

`stats` 초기값(1443행 부근 `{ unread: 0, archived: 0 }`)에 `by_type: {}` 추가
(로드 전 옵셔널 체이닝 안전망).

`filterDocType` 은 드롭다운 `x-model` 로 이미 reactive 이므로, 타입을 바꾸면 getter 가
재평가되어 배지가 자동 갱신된다. **추가 fetch·이벤트 배선 불필요.**

### 3. 엣지 케이스

- 선택한 타입이 한쪽 탭에 0개 → `?? 0` 으로 `0` 표시(배지가 사라지지 않고 0을 보여줌).
- type 드롭다운은 데스크톱(296행)·모바일(363행) 두 곳이지만 동일 `filterDocType` 을
  공유하므로 두 배지 getter 가 양쪽을 모두 커버한다.
- `stats.by_type` 가 아직 없을 때(초기/구버전 응답) `?.` 로 안전하게 `0` 폴백.

## 테스트

### 백엔드 (pytest — `viewer/tests/`)

- `get_stats()` 반환에 `by_type` 키가 존재한다.
- 알려진 폴더 구성(임시 outputs/archives 디렉터리 + `paper_meta.json` 픽스처)에서:
  - 타입별 `unread` 합 ≤ 전체 `unread`, `archived` 합 ≤ 전체 `archived`
    (doc_type 미지정 폴더가 차이를 만든다).
  - 특정 타입의 `{unread, archived}` 가 픽스처와 일치.
  - `doc_type` 없는 폴더는 `by_type` 에 나타나지 않지만 전체값에는 포함.

### 프런트 (수동)

- 타입 선택 시 두 배지가 해당 타입 개수로 바뀐다.
- "All Types" 복귀 시 전체값으로 복원된다.
- 타입이 한쪽 탭에 0개일 때 `0` 으로 표시된다.

## 영향 범위

- `viewer/app/services/papers.py` — `get_stats()` 만 수정.
- `viewer/app/templates/papers.html` — getter 2개 추가, 배지 바인딩 2곳 교체, `stats`
  초기값에 `by_type: {}` 추가.
- API 스키마는 추가만(`by_type`) — 기존 소비자 하위호환.
