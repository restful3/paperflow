"""backfill_metadata.py --twin-only — LLM 호출 없이 자동 복구되는 경로만 남긴다.

일일 cron 이 스스로 복구하려면 API 를 건드리지 않는 결정적 경로여야 한다.
twin 이 없는 폴더는 extract(LLM) 가 필요하므로 --twin-only 에서 제외된다.
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "backfill_metadata.py")


def _load():
    spec = importlib.util.spec_from_file_location("bm", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _make_folder(root, location, name, meta=None):
    d = os.path.join(root, location, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write("# heading\n\nbody\n")
    if meta is not None:
        with open(os.path.join(d, "paper_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    return d


def test_twin_only_flag_exists_and_is_documented():
    out = subprocess.run([sys.executable, SCRIPT, "--help"],
                         capture_output=True, text=True, cwd=REPO)
    assert out.returncode == 0, out.stderr
    assert "--twin-only" in out.stdout, out.stdout


def test_twin_only_keeps_twin_and_drops_extract(tmp_path, monkeypatch):
    bm = _load()
    root = str(tmp_path)
    monkeypatch.setattr(bm, "REPO", root)
    # twin 있음 → 복구 가능
    _make_folder(root, "outputs", "has-twin")
    _make_folder(root, "archives", "has-twin", meta={"title": "T", "folder_name": "has-twin"})
    # twin 없음 → extract(LLM) 필요
    _make_folder(root, "outputs", "no-twin")

    plans = {name: bm._plan(loc, name, folder)[0]
             for loc, name, folder in bm._find_broken(["outputs", "archives"])}
    assert plans["has-twin"] == "twin"
    assert plans["no-twin"] == "extract"

    twin_only = [n for n, a in plans.items() if a == "twin"]
    assert twin_only == ["has-twin"]


def test_twin_only_apply_writes_only_twin_targets(tmp_path, monkeypatch):
    """--twin-only --apply 는 twin 있는 폴더만 고치고 extract 대상은 손대지 않는다.

    extract 경로가 돌면 LLM 을 호출하므로, 여기서는 호출되면 즉시 터지도록
    막아 둔다 — 통과했다면 API 를 건드리지 않았다는 뜻이다.
    """
    bm = _load()
    root = str(tmp_path)
    monkeypatch.setattr(bm, "REPO", root)
    monkeypatch.setattr(bm.mt, "extract_paper_metadata",
                        lambda *a, **k: pytest.fail("extract 가 호출되면 안 된다"))
    _make_folder(root, "outputs", "has-twin")
    _make_folder(root, "archives", "has-twin", meta={"title": "T", "folder_name": "has-twin"})
    _make_folder(root, "outputs", "no-twin")

    monkeypatch.setattr(sys, "argv", ["backfill_metadata.py", "--twin-only", "--apply"])
    assert bm.main() == 0

    assert os.path.isfile(os.path.join(root, "outputs", "has-twin", "paper_meta.json"))
    assert not os.path.exists(os.path.join(root, "outputs", "no-twin", "paper_meta.json"))
    # twin 복사 시 folder_name 은 이 폴더를 가리켜야 한다
    meta = json.load(open(os.path.join(root, "outputs", "has-twin", "paper_meta.json"),
                          encoding="utf-8"))
    assert meta["folder_name"] == "has-twin"
