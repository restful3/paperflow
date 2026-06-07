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
