import os
from app import job


def test_cleanup_grace_and_keep(tmp_path):
    adir = tmp_path; base = "P"
    for sha in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc", "dddddddddddd"):
        os.makedirs(adir / f"{base}_ko_audio.{sha}")
        (adir / f"{base}_ko_audio.{sha}.mp3").write_bytes(b"x")
    os.utime(adir / "P_ko_audio.aaaaaaaaaaaa", (1, 1))            # 아주 오래됨(grace 초과)
    os.utime(adir / "P_ko_audio.aaaaaaaaaaaa.mp3", (1, 1))
    # bbbb 는 구버전이지만 방금 생성(grace 내) → 보존돼야 함(active token race 방지)
    job._cleanup_old_versions(str(adir), base, keep_sha12="dddddddddddd", keep=1, grace_sec=3600)
    assert (adir / "P_ko_audio.dddddddddddd").exists()           # 현재버전
    assert (adir / "P_ko_audio.bbbbbbbbbbbb").exists()           # grace 내 → 보존(HIGH#2)
    assert not (adir / "P_ko_audio.aaaaaaaaaaaa").exists()       # grace 초과 + keep 밖 → 삭제
    assert not (adir / "P_ko_audio.aaaaaaaaaaaa.mp3").exists()   # mp3 도 함께


def test_synth_encode_retry_then_fail(monkeypatch, tmp_path):
    calls = {"n": 0}
    monkeypatch.setattr(job, "synth_chunk", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(job, "_chunk_ok", lambda *a, **k: True)

    def always_over(*a, **k):
        calls["n"] += 1
        raise ValueError("segment exceeds TARGETDURATION")

    monkeypatch.setattr(job, "encode_segment", always_over)
    out = job._synth_encode_with_retry({"text": "x"}, str(tmp_path / "w.wav"), 0.1,
                                       str(tmp_path / "s.ts"), "cpu")
    assert out is None and calls["n"] == 2          # 1회 재시도 후 None


def test_synth_encode_success(monkeypatch, tmp_path):
    monkeypatch.setattr(job, "synth_chunk", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(job, "_chunk_ok", lambda *a, **k: True)
    monkeypatch.setattr(job, "encode_segment", lambda wf, pad, out, **k: 3.2)
    out = job._synth_encode_with_retry({"text": "x"}, str(tmp_path / "w.wav"), 0.1,
                                       str(tmp_path / "s.ts"), "cpu")
    assert out == 3.2


def test_version_sha():
    assert job._version_sha("P_ko_audio.abc123def456") == "abc123def456"
    assert job._version_sha("P_ko_audio.abc123def456.mp3") == "abc123def456"
    assert job._version_sha("P_ko_audio.md") is None
