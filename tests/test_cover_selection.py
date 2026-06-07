"""AI 비전 커버 선별 스테이지 테스트."""
import json
import os
from unittest.mock import MagicMock

import pytest
from PIL import Image

import main_terminal as mt


def test_count_active_stages_includes_select_cover():
    pipeline = {
        "convert_to_markdown": True,
        "extract_metadata": True,
        "check_duplicate": False,
        "translate_to_korean": False,
        "select_cover": True,
    }
    # convert(1) + metadata(1) + select_cover(1) = 3
    assert mt._count_active_stages(pipeline) == 3


def test_count_active_stages_excludes_select_cover_when_off():
    pipeline = {
        "convert_to_markdown": True,
        "extract_metadata": True,
        "check_duplicate": False,
        "translate_to_korean": False,
        "select_cover": False,
    }
    assert mt._count_active_stages(pipeline) == 2


def _make_img(path, w, h, color=(120, 130, 140)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (w, h), color).save(path)


def test_gather_drops_tiny_images(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "big.jpg"), 800, 600)
    _make_img(os.path.join(d, "icon.png"), 50, 50)  # 긴 변 < 200 → 제외
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert "big.jpg" in out
    assert "icon.png" not in out


def test_gather_ranks_by_area_then_name(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "b_small.jpg"), 300, 300)   # area 90k
    _make_img(os.path.join(d, "a_large.jpg"), 800, 800)   # area 640k
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert out[0] == "a_large.jpg"  # 면적 큰 것이 먼저


def test_gather_reads_subdirs_relative_paths(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "images", "fig1.jpg"), 800, 600)
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert os.path.join("images", "fig1.jpg") in out  # 폴더 상대경로


def test_gather_only_known_extensions(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "ok.jpeg"), 800, 600)
    with open(os.path.join(d, "note.txt"), "w") as f:
        f.write("x" * 5000)
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert out == ["ok.jpeg"]


def test_gather_caps_at_max_candidates(tmp_path):
    d = str(tmp_path)
    for i in range(10):
        _make_img(os.path.join(d, f"img{i:02d}.jpg"), 800 - i, 600)
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert len(out) == 6


def test_gather_empty_when_no_images(tmp_path):
    out = mt._gather_cover_candidates(str(tmp_path), min_dimension=200, max_candidates=6)
    assert out == []
