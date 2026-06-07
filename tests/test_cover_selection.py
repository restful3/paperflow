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
