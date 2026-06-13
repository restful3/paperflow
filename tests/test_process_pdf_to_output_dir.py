"""Phase 1b-1: process_single_pdf → process_pdf_to_output_dir 리팩터 회귀/게이팅 테스트."""
import contextlib
import os

import main_terminal as mt


def _paper_pipeline(**over):
    base = {
        "convert_to_markdown": True,
        "normalize_headings": False,
        "extract_metadata": False,
        "translate_to_korean": False,
    }
    base.update(over)
    return {"processing_pipeline": base}


def test_process_single_pdf_paper_minimal(tmp_path, monkeypatch):
    """convert만 켠 최소 경로: outputs/<base>에 쓰고 PDF를 옮기고 True 반환."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "newones").mkdir()
    (tmp_path / "logs").mkdir()
    pdf = tmp_path / "newones" / "mypaper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    captured = {}

    def fake_convert(pdf_path, output_dir, config, status_info=None):
        captured["output_dir"] = output_dir
        md = os.path.join(output_dir, "mypaper.md")
        with open(md, "w", encoding="utf-8") as f:
            f.write("# Title\n\nbody")
        return md

    monkeypatch.setattr(mt, "convert_pdf_to_md_dispatch", fake_convert)
    monkeypatch.setattr(mt, "_gpu_lock", lambda: contextlib.nullcontext())

    ok = mt.process_single_pdf(str(pdf), _paper_pipeline(), "PROMPT")

    assert ok is True
    assert captured["output_dir"] == os.path.join("outputs", "mypaper")
    assert os.path.isfile(os.path.join("outputs", "mypaper", "mypaper.md"))
    assert os.path.isfile(os.path.join("outputs", "mypaper", "mypaper.pdf"))  # moved in
    assert not pdf.exists()  # moved away from newones


def test_book_chapter_mode_skips_paper_only_stages(tmp_path, monkeypatch):
    """book_chapter 모드: web search / rename / duplicate / cover는 호출 안 됨.
    convert·metadata·translation은 그대로 동작하고 출력 폴더명은 안 바뀐다."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    out = tmp_path / "books" / "MyBook" / "01_intro"
    out.mkdir(parents=True)
    pdf = tmp_path / "01_intro.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    called = set()

    def fake_convert(pdf_path, output_dir, config, status_info=None):
        md = os.path.join(output_dir, "01_intro.md")
        with open(md, "w", encoding="utf-8") as f:
            f.write("# Chapter 1\n\nbody")
        return md

    def fake_translate(md_path, output_dir, config, prompt, progress_callback=None):
        ko = os.path.join(output_dir, "01_intro_ko.md")
        with open(ko, "w", encoding="utf-8") as f:
            f.write("# 1장\n\n본문")
        called.add("translate")
        return ko

    monkeypatch.setattr(mt, "convert_pdf_to_md_dispatch", fake_convert)
    monkeypatch.setattr(mt, "_gpu_lock", lambda: contextlib.nullcontext())
    monkeypatch.setattr(mt, "extract_paper_metadata",
                        lambda md_path, output_dir, config: {"title": "Intro Chapter", "source_language": "en"})
    monkeypatch.setattr(mt, "translate_md_to_korean_openai", fake_translate)
    # paper-only stages — must NOT be called in book_chapter mode
    monkeypatch.setattr(mt, "enrich_metadata_with_web_search",
                        lambda *a, **k: called.add("enrich") or {})
    monkeypatch.setattr(mt, "rename_output_directory",
                        lambda *a, **k: called.add("rename"))
    monkeypatch.setattr(mt, "check_duplicate_batch",
                        lambda *a, **k: called.add("duplicate") or [])
    monkeypatch.setattr(mt, "select_cover_image",
                        lambda *a, **k: called.add("cover"))

    pipeline = {"processing_pipeline": {
        "convert_to_markdown": True, "normalize_headings": False,
        "extract_metadata": True, "enrich_with_web_search": True,
        "check_duplicate": True, "select_cover": True,
        "translate_to_korean": True,
    }}

    ok = mt.process_pdf_to_output_dir(
        str(pdf), str(out), "01_intro", pipeline, "PROMPT", mode="book_chapter")

    assert ok is True
    assert "translate" in called          # translation still runs
    assert "enrich" not in called         # web search skipped
    assert "rename" not in called         # smart-rename skipped
    assert "duplicate" not in called      # global dup skipped
    assert "cover" not in called          # cover skipped
    # output folder unchanged (chapter dir preserved)
    assert os.path.isfile(os.path.join(str(out), "01_intro_ko.md"))
    assert os.path.isfile(os.path.join(str(out), "01_intro.pdf"))  # PDF moved in
    # progress stage count must reflect skipped stages (3 = convert + metadata + translate, not 5)
    import json
    status = json.load(open(os.path.join("logs", "processing_status.json"), encoding="utf-8"))
    assert status["total_stages"] == 3
