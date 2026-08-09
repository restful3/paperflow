"""outputs/archives 건전성 검사기 테스트.

2026-08-09 실측 사고에서 나온 결함 유형을 전부 검출해야 한다. 그날의 교훈은
"결함 자체" 보다 "결함이 66건 쌓일 때까지 아무도 몰랐다" 는 점이었다 —
이 검사기가 그 감지 공백을 메운다.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHECKER = REPO / "scripts" / "check_outputs_health.py"

GOOD_META = {
    "title": "T", "title_ko": "제목", "abstract": "a", "abstract_ko": "요약",
    "categories": ["C"], "doc_type": "paper",
}


def _paper(root: Path, name: str, meta=GOOD_META, body="# Real Title\n\nbody\n"):
    d = root / name
    d.mkdir(parents=True)
    if meta is not None:
        (d / "paper_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if body is not None:
        (d / f"{name}.md").write_text(body, encoding="utf-8")
    return d


def _run(tmp: Path):
    r = subprocess.run([sys.executable, str(CHECKER), "--root", str(tmp), "--json"],
                       capture_output=True, text=True)
    return r, json.loads(r.stdout or "{}")


def _clean(tmp: Path):
    (tmp / "outputs").mkdir()
    (tmp / "archives").mkdir()
    _paper(tmp / "outputs", "Healthy Paper")


def test_clean_tree_passes(tmp_path):
    _clean(tmp_path)
    r, out = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out["total_findings"] == 0


def test_detects_missing_meta(tmp_path):
    _clean(tmp_path)
    _paper(tmp_path / "outputs", "No Meta", meta=None)
    r, out = _run(tmp_path)
    assert r.returncode != 0
    assert any("No Meta" in f["folder"] for f in out["findings"]["missing_meta"])


def test_detects_failure_marker(tmp_path):
    _clean(tmp_path)
    d = _paper(tmp_path / "outputs", "Failed Doc")
    (d / "paper_meta.failed.json").write_text('{"stage":"extract_metadata"}', encoding="utf-8")
    r, out = _run(tmp_path)
    assert r.returncode != 0
    assert out["findings"]["failure_marker"]


def test_detects_empty_folder(tmp_path):
    _clean(tmp_path)
    (tmp_path / "outputs" / "Empty One").mkdir()
    r, out = _run(tmp_path)
    assert r.returncode != 0
    assert any("Empty One" in f["folder"] for f in out["findings"]["empty_folder"])


def test_detects_outputs_archives_duplicate(tmp_path):
    _clean(tmp_path)
    _paper(tmp_path / "outputs", "Dup Doc")
    _paper(tmp_path / "archives", "Dup Doc")
    r, out = _run(tmp_path)
    assert r.returncode != 0
    assert any("Dup Doc" in f["folder"] for f in out["findings"]["outputs_archives_dup"])


def test_detects_nfc_nfd_pair(tmp_path):
    _clean(tmp_path)
    _paper(tmp_path / "outputs", "가나")            # NFC 가나
    _paper(tmp_path / "outputs", "가나")  # NFD 가나
    r, out = _run(tmp_path)
    assert r.returncode != 0
    assert out["findings"]["unicode_dup"]


def test_detects_orphan_part_file(tmp_path):
    _clean(tmp_path)
    import os, time
    d = _paper(tmp_path / "outputs", "Partial Doc")
    p = d / "Partial Doc_ko_audio_brief.md.part"
    p.write_text("half", encoding="utf-8")
    old = time.time() - 3 * 3600
    os.utime(p, (old, old))
    r, out = _run(tmp_path)
    assert r.returncode != 0
    assert out["findings"]["orphan_part"]


def test_fresh_part_file_is_not_flagged(tmp_path):
    """작업 중인 .part 는 정상이므로 오탐하면 안 된다."""
    _clean(tmp_path)
    d = _paper(tmp_path / "outputs", "Working Doc")
    (d / "Working Doc_ko_audio_brief.md.part").write_text("half", encoding="utf-8")
    r, out = _run(tmp_path)
    assert out["findings"]["orphan_part"] == []


def test_detects_slug_h1_and_missing_korean_fields(tmp_path):
    _clean(tmp_path)
    _paper(tmp_path / "outputs", "Slug Doc",
           body="# web-some-title-20260604-054702\n\nbody\n")
    meta = dict(GOOD_META); meta["title_ko"] = None
    _paper(tmp_path / "outputs", "No Korean", meta=meta)
    r, out = _run(tmp_path)
    assert r.returncode != 0
    assert any("Slug Doc" in f["folder"] for f in out["findings"]["slug_title"])
    assert any("No Korean" in f["folder"] for f in out["findings"]["missing_korean_field"])
