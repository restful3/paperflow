"""PDF 1페이지 상단 밴드를 커버로 쓰는 백필 테스트.

표·플롯뿐인 문서(비전 모델이 정당하게 커버를 거절하는 부류)와 이미지가 아예
없는 문서는 어떤 방식으로도 hero 이미지를 못 만든다. 그런 문서에는 원본 PDF
1페이지 상단(제목·저자·리드)이 가장 유용한 썸네일이다.
"""
import importlib.util
import json
import os

import pytest
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "backfill_pdf_page_covers.py")


def _load():
    spec = importlib.util.spec_from_file_location("bppc", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _make_pdf(path, color=(255, 255, 255), text_band=True):
    """세로형 A4 비율 1페이지 PDF. text_band=True 면 상단에 잉크를 넣는다."""
    im = Image.new("RGB", (620, 877), color)
    if text_band:
        for y in range(40, 200, 8):
            for x in range(60, 560):
                im.putpixel((x, y), (0, 0, 0))
    im.save(path, "PDF", resolution=110.0)


def _folder(root, loc, name, meta, pdfs=(), images=()):
    d = os.path.join(root, loc, name)
    os.makedirs(os.path.join(d, "images"), exist_ok=True)
    with open(os.path.join(d, "paper_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    for fn, kwargs in pdfs:
        _make_pdf(os.path.join(d, fn), **kwargs)
    for fn, size in images:
        Image.new("RGB", size, (10, 90, 200)).save(os.path.join(d, "images", fn))
    return d


def test_picks_largest_pdf(tmp_path):
    m = _load()
    d = str(tmp_path)
    _make_pdf(os.path.join(d, "small.pdf"))
    big = Image.new("RGB", (1200, 1600), (255, 255, 255))
    big.save(os.path.join(d, "big.pdf"), "PDF", resolution=110.0)
    assert m._pick_pdf(d) == "big.pdf"


def test_no_pdf_returns_none(tmp_path):
    m = _load()
    assert m._pick_pdf(str(tmp_path)) is None


def test_blank_first_page_is_skipped(tmp_path, monkeypatch):
    """첫 페이지가 사실상 백지면 커버로 쓰지 않는다 — 회색 카드보다 나을 게 없다."""
    m = _load()
    root = str(tmp_path)
    monkeypatch.setattr(m, "REPO", root)
    d = _folder(root, "outputs", "blank", {"doc_type": "paper"},
                pdfs=[("doc.pdf", {"text_band": False})])
    assert m._render_cover(d, "doc.pdf") is None
    assert not os.path.exists(os.path.join(d, "images", m.COVER_NAME))


def test_writes_cover_and_records_provenance(tmp_path, monkeypatch):
    m = _load()
    root = str(tmp_path)
    monkeypatch.setattr(m, "REPO", root)
    d = _folder(root, "outputs", "withpdf", {"doc_type": "paper"},
                pdfs=[("doc.pdf", {})])

    rel = m._render_cover(d, "doc.pdf")
    assert rel == os.path.join("images", m.COVER_NAME)
    out = os.path.join(d, rel)
    assert os.path.isfile(out)
    with Image.open(out) as im:
        w, h = im.size
    assert abs(w / h - 16 / 9) < 0.02, (w, h)   # 카드 비율(aspect-video)에 맞춘 밴드

    m._write_cover(d, rel)
    meta = json.load(open(os.path.join(d, "paper_meta.json"), encoding="utf-8"))
    assert meta["cover"] == rel
    assert meta["cover_source"] == "pdf_page1"   # 되돌릴 수 있도록 출처를 남긴다


def test_targets_skip_folders_that_already_have_a_cover(tmp_path, monkeypatch):
    m = _load()
    root = str(tmp_path)
    monkeypatch.setattr(m, "REPO", root)
    _folder(root, "outputs", "has-cover",
            {"doc_type": "paper", "cover": "images/x.jpg"},
            pdfs=[("doc.pdf", {})], images=[("x.jpg", (400, 300))])
    _folder(root, "outputs", "needs-cover", {"doc_type": "paper"},
            pdfs=[("doc.pdf", {})])
    _folder(root, "outputs", "video-doc",
            {"doc_type": "video", "video": {"poster": "images/p.jpg"}},
            pdfs=[("doc.pdf", {})], images=[("p.jpg", (400, 300))])

    names = {name for _loc, name, _folder_path, _pdf in m._targets(["outputs"])}
    assert names == {"needs-cover"}
