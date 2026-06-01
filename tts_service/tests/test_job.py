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


def test_synth_timeout_fails_fast(monkeypatch, tmp_path):
    # 워치독: synth_chunk 가 wedge(타임아웃 초과 hang)하면 전체 job 을 무한 대기시키지 않고
    # 빠르게 실패(None)해야 한다. (이번 인시던트: 첫 청크 generate() 가 wedge → 4분+ 멈춤)
    import time
    def hang(*a, **k):
        time.sleep(5)          # 타임아웃(1s)보다 훨씬 오래 → wedge 모사
    monkeypatch.setattr(job, "synth_chunk", hang, raising=False)
    monkeypatch.setattr(job, "_chunk_ok", lambda *a, **k: True)
    monkeypatch.setattr(job, "encode_segment", lambda *a, **k: 3.0)
    monkeypatch.setenv("SYNTH_CHUNK_TIMEOUT", "1")
    t0 = time.time()
    out = job._synth_encode_with_retry({"text": "x"}, str(tmp_path / "w.wav"), 0.1,
                                       str(tmp_path / "s.ts"), "cpu")
    elapsed = time.time() - t0
    assert out is None                 # wedge → 실패 반환(failed_partial 로 이어짐)
    assert elapsed < 4                  # 무한/5s 대기 아님 — 타임아웃으로 빠르게 끊김


def test_run_job_preempts_between_chunks(monkeypatch, tmp_path):
    # 협조적 선점: is_active 가 False 가 되면 청크 사이에서 Preempted 로 양보(gpu_lock 해제).
    import pytest
    paper = tmp_path / "P"; paper.mkdir()
    md = paper / "P_ko_audio.md"
    md.write_text("# 제목\n\n첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다.\n", encoding="utf-8")
    monkeypatch.setattr(job, "GPU_LOCK_PATH", str(tmp_path / ".gpu.lock"))
    monkeypatch.setattr(job, "synth_chunk", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(job, "_chunk_ok", lambda *a, **k: True)

    def fake_encode(wf, pad, out_ts, **k):
        open(out_ts, "wb").close()
        return 1.0
    monkeypatch.setattr(job, "encode_segment", fake_encode)

    calls = {"n": 0}
    def is_active():
        calls["n"] += 1
        return calls["n"] <= 1          # 첫 청크만 허용, 그 다음 양보

    with pytest.raises(job.Preempted):
        job.run_job(str(paper), str(md), is_active=is_active)
    # 첫 청크 1개만 세그먼트 생성되고 중단됐어야 함
    segs = [p for p in (tmp_path).rglob("seg_*.ts")]
    assert len(segs) == 1


def test_run_job_refreshes_heartbeat_during_lock_wait(monkeypatch, tmp_path):
    # M2: run_job must hand gpu_lock an on_wait callback that re-publishes the manifest
    # heartbeat, so a long lock wait (converter busy) keeps a healthy job from being marked
    # stale/failed by the viewer's reconcile_stale.
    import contextlib, json
    paper = tmp_path / "P"; paper.mkdir()
    md = paper / "P_ko_audio.md"
    md.write_text("# 제목\n\n첫 문장입니다. 둘째 문장입니다.\n", encoding="utf-8")
    man_path = paper / "audio" / "P_ko_audio.manifest.json"

    monkeypatch.setattr(job, "synth_chunk", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(job, "_chunk_ok", lambda *a, **k: True)

    def fake_encode(wf, pad, out_ts, **k):
        open(out_ts, "wb").close()
        return 1.0
    monkeypatch.setattr(job, "encode_segment", fake_encode)

    def fake_stitch(seg_wavs, chunks, out, **k):    # avoid real ffmpeg on empty wavs
        open(out, "wb").close()
    monkeypatch.setattr(job, "stitch_chunks", fake_stitch)

    captured = {}

    @contextlib.contextmanager
    def fake_lock(path, on_wait=None, **k):
        captured["on_wait"] = on_wait
        if on_wait:
            # wipe the on-disk heartbeat, then the wait callback must rewrite it
            m = json.load(open(man_path)); m["heartbeat"] = None
            json.dump(m, open(man_path, "w"))
            on_wait()
            captured["hb_after_wait"] = json.load(open(man_path))["heartbeat"]
        yield object()
    monkeypatch.setattr(job, "gpu_lock", fake_lock)

    job.run_job(str(paper), str(md))
    assert callable(captured.get("on_wait"))            # run_job wired a heartbeat refresher
    assert captured.get("hb_after_wait")                # callback actually re-published heartbeat


def test_version_sha():
    assert job._version_sha("P_ko_audio.abc123def456") == "abc123def456"
    assert job._version_sha("P_ko_audio.abc123def456.mp3") == "abc123def456"
    assert job._version_sha("P_ko_audio.md") is None
