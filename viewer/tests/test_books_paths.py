"""Phase 1a: books 경로 추상화 + 설정 단위/회귀 테스트."""
from pathlib import Path

import pytest


def test_books_dir_settings_under_base(tmp_workspace):
    from app import config as _cfg
    s = _cfg.settings
    assert s.books_dir == Path(tmp_workspace) / "books"
    assert s.newbooks_dir == Path(tmp_workspace) / "newbooks"
    assert s.book_archives_dir == Path(tmp_workspace) / "book_archives"


def test_tmp_workspace_creates_book_dirs(tmp_workspace):
    assert (tmp_workspace / "books").is_dir()
    assert (tmp_workspace / "newbooks").is_dir()
    assert (tmp_workspace / "book_archives").is_dir()
