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
