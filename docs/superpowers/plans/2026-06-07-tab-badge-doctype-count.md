# 탭 배지 — 선택한 타입 기준 개수 표시 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 목록 화면 오른쪽 type 드롭다운에서 타입을 선택하면 Unread/Archived 탭 배지 둘 다 해당 타입의 개수로 바뀐다.

**Architecture:** 백엔드 `get_stats()` 가 폴더별 `paper_meta.json` 의 `doc_type` 을 읽어 `by_type: {타입: {unread, archived}}` 집계를 추가 반환한다. 프런트는 `filterDocType` 유무에 따라 전체값 또는 타입별 개수를 보여주는 getter 두 개로 배지를 분기한다. 추가 fetch·이벤트 배선은 없다 (`filterDocType` 이 이미 reactive).

**Tech Stack:** FastAPI (Python), Alpine.js (papers.html), pytest.

**Spec:** `docs/superpowers/specs/2026-06-07-tab-badge-doctype-count-design.md`

---

## File Structure

- `viewer/app/services/papers.py` — `get_stats()` 만 수정 (집계 추가 + 테스트 픽스처용 lazy settings import).
- `viewer/app/templates/papers.html` — `stats` 초기값에 `by_type: {}`, getter 2개 추가, 배지 바인딩 2곳 교체.
- `viewer/tests/test_stats_by_type.py` — `get_stats()` 백엔드 단위 테스트 (신규).
- `viewer/tests/test_papers_badge_doctype_template.py` — `papers.html` 배선 어서션 테스트 (신규).

---

## Task 1: 백엔드 `get_stats()` 타입별 집계

**Files:**
- Modify: `viewer/app/services/papers.py` (`get_stats()`, 현재 1274–1281행)
- Test: `viewer/tests/test_stats_by_type.py` (신규)

> **참고 — 왜 lazy import 가 필요한가:** `papers.py` 는 모듈 최상단(510행)에서 `from ..config import settings` 로 `settings` 를 한 번 바인딩한다. 테스트 픽스처 `tmp_workspace` 는 `app.config.settings` 를 새 객체로 교체하므로, 모듈에 일찍 바인딩된 `settings` 는 교체를 반영하지 못한다. 이 코드베이스의 기존 관례(1570행 `from ..config import settings  # lazy import so test fixtures can replace settings`)대로, `get_stats()` 안에서 lazy import 해야 픽스처의 임시 워크스페이스를 읽는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`viewer/tests/test_stats_by_type.py` 생성:

```python
"""Tests for get_stats() by_type aggregation.

선택한 doc_type 기준 탭 배지 개수를 위해, get_stats()는 폴더별 paper_meta.json의
doc_type을 읽어 by_type: {타입: {unread, archived}}를 추가 반환한다. doc_type이
없는 폴더는 by_type에서 제외되지만 전체값(unread/archived)에는 포함된다.
"""
import json
from pathlib import Path

from app.services import papers


def _make_paper(base: Path, name: str, doc_type=None):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    if doc_type is not None:
        (d / "paper_meta.json").write_text(
            json.dumps({"doc_type": doc_type}), encoding="utf-8"
        )
    return d


def test_by_type_counts_split_unread_and_archived(tmp_workspace):
    outputs = tmp_workspace / "outputs"
    archives = tmp_workspace / "archives"
    _make_paper(outputs, "v1", "video")
    _make_paper(outputs, "v2", "video")
    _make_paper(outputs, "p1", "paper")
    _make_paper(archives, "v3", "video")
    _make_paper(archives, "p2", "paper")
    _make_paper(archives, "p3", "paper")

    stats = papers.get_stats()

    assert stats["unread"] == 3
    assert stats["archived"] == 3
    assert stats["total"] == 6
    assert stats["by_type"]["video"] == {"unread": 2, "archived": 1}
    assert stats["by_type"]["paper"] == {"unread": 1, "archived": 2}


def test_paper_without_doc_type_excluded_from_by_type_but_in_totals(tmp_workspace):
    outputs = tmp_workspace / "outputs"
    _make_paper(outputs, "typed", "video")
    _make_paper(outputs, "untyped", None)  # paper_meta.json 없음

    stats = papers.get_stats()

    assert stats["unread"] == 2  # 둘 다 전체값에 집계
    assert stats["by_type"]["video"] == {"unread": 1, "archived": 0}
    assert "untyped" not in stats["by_type"]  # 타입 키 자체가 없음
    # by_type unread 합(1) <= 전체 unread(2): doc_type 없는 폴더가 차이를 만든다
    assert sum(v["unread"] for v in stats["by_type"].values()) == 1


def test_empty_workspace_returns_empty_by_type(tmp_workspace):
    stats = papers.get_stats()
    assert stats == {"unread": 0, "archived": 0, "total": 0, "by_type": {}}
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `cd viewer && python -m pytest tests/test_stats_by_type.py -v`
Expected: FAIL — `KeyError: 'by_type'` (현재 `get_stats()` 는 `by_type` 미반환). `test_empty_workspace...` 는 dict 불일치로 실패. (lazy import 미적용이면 `unread` 개수도 실제 폴더를 읽어 불일치 가능 — Step 3에서 함께 해결)

- [ ] **Step 3: 구현**

`viewer/app/services/papers.py` 의 `get_stats()` (1274–1281행)를 통째로 교체:

```python
def get_stats() -> dict:
    from ..config import settings  # lazy import so test fixtures can replace settings

    by_type: dict = {}  # {doc_type: {"unread": n, "archived": n}}

    def count_dir(base, key):
        total = 0
        if base.exists():
            for d in base.iterdir():
                if not d.is_dir() or d.name.startswith("."):
                    continue
                total += 1
                meta = _load_paper_metadata(d)
                dt = (meta or {}).get("doc_type")
                if dt:  # null/없음/미지정은 by_type 제외, 전체값에만 집계
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

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `cd viewer && python -m pytest tests/test_stats_by_type.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add viewer/app/services/papers.py viewer/tests/test_stats_by_type.py
git commit -m "feat(viewer): get_stats()에 doc_type별 by_type 집계 추가"
```

---

## Task 2: 프런트 배지 분기 (papers.html)

**Files:**
- Modify: `viewer/app/templates/papers.html`
  - `stats` 초기값 (1443행 부근)
  - getter 추가 (`docTypeOptions` getter 근처, 1498행 부근)
  - 배지 바인딩 (216행, 229행)
- Test: `viewer/tests/test_papers_badge_doctype_template.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성**

`viewer/tests/test_papers_badge_doctype_template.py` 생성:

```python
"""papers.html 배지 타입별 개수 배선 어서션.

토큰 존재만 보지 않고, 배지가 실제로 getter에 연결되고 getter가 filterDocType +
stats.by_type에 의존하는지 확인한다.
"""
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "papers.html"


def test_badge_getters_defined():
    html = TPL.read_text(encoding="utf-8")
    assert "get unreadBadge()" in html
    assert "get archivedBadge()" in html
    # getter가 filterDocType + by_type에 의존
    assert "this.stats.by_type?.[this.filterDocType]?.unread" in html
    assert "this.stats.by_type?.[this.filterDocType]?.archived" in html


def test_badges_bound_to_getters_not_raw_stats():
    html = TPL.read_text(encoding="utf-8")
    # 배지 바인딩이 getter로 교체됨
    assert 'x-text="unreadBadge"' in html
    assert 'x-text="archivedBadge"' in html
    # 기존 raw stats 바인딩은 배지에서 사라짐
    assert 'x-text="stats.unread"' not in html
    assert 'x-text="stats.archived"' not in html


def test_stats_init_has_by_type():
    html = TPL.read_text(encoding="utf-8")
    assert "by_type:" in html
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `cd viewer && python -m pytest tests/test_papers_badge_doctype_template.py -v`
Expected: FAIL — getter·바인딩 미존재, `x-text="stats.unread"` 가 아직 존재.

- [ ] **Step 3: `stats` 초기값에 `by_type` 추가**

`viewer/app/templates/papers.html` 1443행 부근. 현재:

```js
      stats: { unread: 0, archived: 0 },
```

로 교체:

```js
      stats: { unread: 0, archived: 0, by_type: {} },
```

> 만약 해당 줄이 멀티라인 형태라면(예: `stats: {`\n`  unread: 0, archived: 0`\n`},`) `by_type: {}` 를 같은 객체 안에 추가하면 된다. 핵심은 초기 `stats` 객체에 `by_type: {}` 키가 존재할 것.

- [ ] **Step 4: getter 두 개 추가**

`viewer/app/templates/papers.html` 의 `get docTypeOptions() { ... }` (1498행 부근) 바로 다음 줄에 삽입:

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

- [ ] **Step 5: 배지 바인딩 교체**

216행: `x-text="stats.unread"` → `x-text="unreadBadge"`
229행: `x-text="stats.archived"` → `x-text="archivedBadge"`

(`<span ... x-text="stats.unread"></span>` 의 `x-text` 속성값만 교체. 주변 `:class` 등은 그대로 둔다.)

- [ ] **Step 6: 테스트 실행 — 통과 확인**

Run: `cd viewer && python -m pytest tests/test_papers_badge_doctype_template.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: 커밋**

```bash
git add viewer/app/templates/papers.html viewer/tests/test_papers_badge_doctype_template.py
git commit -m "feat(viewer): 탭 배지를 선택한 doc_type 개수로 분기"
```

---

## Task 3: 통합 확인 (수동 + 회귀)

**Files:** (코드 변경 없음 — 검증만)

- [ ] **Step 1: 전체 백엔드 테스트 회귀**

Run: `cd viewer && python -m pytest tests/test_stats_by_type.py tests/test_papers_badge_doctype_template.py -v`
Expected: PASS (6 passed)

- [ ] **Step 2: 뷰어 재빌드·기동**

Run: `docker compose build paperflow-viewer && docker compose up -d paperflow-viewer`
Expected: 컨테이너 정상 기동.

- [ ] **Step 3: 수동 확인 (http://localhost:8090 → 목록)**

확인 항목:
- "All Types" 상태에서 Unread/Archived 배지 = 전체 개수 (기존과 동일).
- 오른쪽 type 드롭다운에서 특정 타입 선택 → 두 배지 모두 해당 타입 개수로 변경.
- 한쪽 탭에 0개인 타입 선택 시 그 배지가 `0` 으로 표시 (사라지지 않음).
- "All Types" 복귀 시 전체값 복원.
- 데스크톱·모바일 드롭다운 어느 쪽으로 바꿔도 동일 동작 (동일 `filterDocType` 공유).

> 자동화 불가한 시각 동작이므로 이 단계는 사람이 확인한다. 실패 시 Task 1/2의 해당 단계로 복귀.

---

## Self-Review 기록

- **Spec coverage:** 백엔드 `by_type`(Task 1), 프런트 getter·바인딩·`by_type` 초기값(Task 2), 두 탭 모두/엣지 0개/데스크톱·모바일 공유(Task 2 getter + Task 3 수동), 테스트(Task 1·2) — 스펙 항목 모두 매핑됨.
- **Placeholder scan:** 코드 단계는 모두 실제 코드 포함, "적절히 처리" 류 없음.
- **Type consistency:** `by_type` 키, getter 이름(`unreadBadge`/`archivedBadge`), `filterDocType` 가 백엔드 반환 구조·프런트 소비 코드·테스트에서 일관.
