import json
import pytest


@pytest.fixture(autouse=True)
def _rebind_settings(tmp_workspace, monkeypatch):
    """papers.py and books.py bind settings at module load; rebind to tmp_workspace."""
    from app import config as _cfg
    from app.services import papers
    monkeypatch.setattr(papers, "settings", _cfg.settings)


def test_save_markdown_in_dir_ko_creates_backup_and_writes(tmp_workspace):
    from app.services import papers
    d = tmp_workspace / "outputs" / "P"
    d.mkdir(parents=True)
    (d / "P.md").write_text("# en", encoding="utf-8")
    (d / "P_ko.md").write_text("# 원본", encoding="utf-8")

    ok, msg = papers.save_markdown_in_dir(d, "ko", "# 수정본")

    assert ok is True
    assert (d / "P_ko.md").read_text(encoding="utf-8") == "# 수정본"
    backups = list(d.glob("P_ko.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "# 원본"


def test_save_markdown_in_dir_missing_target_returns_false(tmp_workspace):
    from app.services import papers
    d = tmp_workspace / "outputs" / "Q"
    d.mkdir(parents=True)
    (d / "Q.md").write_text("# en", encoding="utf-8")  # no _ko.md

    ok, msg = papers.save_markdown_in_dir(d, "ko", "x")
    assert ok is False
    assert "not found" in msg.lower()
