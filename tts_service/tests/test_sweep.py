import json, os
from app.sweep import should_run, find_candidate


def test_should_run_gated_by_active_job(tmp_path):
    lp = str(tmp_path / ".gpu.lock")
    assert should_run({}, lp) is True
    assert should_run({"/p": {"stage": "synthesizing"}}, lp) is False
    assert should_run({"/p": {"stage": "ready"}}, lp) is True


def test_find_candidate_needs_audio_md_without_fresh_hls(tmp_path):
    root = tmp_path / "outputs"
    (root / "P").mkdir(parents=True)
    (root / "P" / "P_ko_audio.md").write_text("# t\n\n본문.")
    cand = find_candidate(str(root))
    assert cand and cand["src_md"].endswith("P_ko_audio.md")
    # complete v2 manifest 있으면 후보 아님
    (root / "P" / "P_ko_audio.manifest.json").write_text(json.dumps(
        {"schema_version": 2, "status": "complete", "source": {"sha256": "x"}, "tts": {},
         "audio": {"hls": {"playlist": "stream.m3u8"}}}))
    # sha 불일치라 여전히 후보(파일 sha != "x") — 단순화: 존재만으로는 skip 안 함
    assert find_candidate(str(root)) is not None
