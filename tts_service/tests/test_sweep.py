import json, os, threading
import app.sweep as sweep
from app.sweep import should_run, find_candidate, run_sweep


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


def _state():
    return {"running": True, "done": 0, "current": None, "error": None}


def _fake_finder(paper_dirs):
    # 실제 find_candidate 처럼 skip 을 존중: skip 에 없는 첫 후보 반환.
    def f(root, skip=None):
        skip = skip or set()
        for pd in paper_dirs:
            if pd not in skip:
                return {"paper_dir": pd, "src_md": pd + "/x_ko_audio.md"}
        return None
    return f


def test_run_sweep_processes_all_then_stops(monkeypatch):
    monkeypatch.setattr(sweep, "find_candidate", _fake_finder(["/A", "/B"]))
    processed = []
    st = _state()
    run_sweep("/out", lambda pd, sm: (processed.append(pd) or "ready"),
              should_start=lambda: True, max_papers=10, state=st)
    assert processed == ["/A", "/B"]
    assert st["done"] == 2
    assert st["running"] is False               # 끝나면 running=False


def test_run_sweep_respects_max_papers(monkeypatch):
    monkeypatch.setattr(sweep, "find_candidate", _fake_finder(["/A", "/B", "/C"]))
    processed = []
    run_sweep("/out", lambda pd, sm: (processed.append(pd) or "ready"),
              should_start=lambda: True, max_papers=2, state=_state())
    assert len(processed) == 2                   # cap 에서 멈춤


def test_run_sweep_stops_on_preempt(monkeypatch):
    # foreground 가 배치 후보를 선점(process_one→"preempted")하면 배치 중단(GPU 양보).
    monkeypatch.setattr(sweep, "find_candidate", _fake_finder(["/A", "/B"]))
    processed = []
    run_sweep("/out", lambda pd, sm: (processed.append(pd) or "preempted"),
              should_start=lambda: True, max_papers=10, state=_state())
    assert processed == ["/A"]


def test_run_sweep_idle_gated(monkeypatch):
    # should_start()=False(활성 job/GPU 점유) → 배치 시작 안 함.
    monkeypatch.setattr(sweep, "find_candidate", _fake_finder(["/A"]))
    processed = []
    st = _state()
    run_sweep("/out", lambda pd, sm: (processed.append(pd) or "ready"),
              should_start=lambda: False, max_papers=10, state=st)
    assert processed == []
    assert st["running"] is False


def test_run_sweep_stops_on_skipped(monkeypatch):
    # claim 실패("skipped", foreground 가 먼저 들어옴)면 배치 중단, done 증가 안 함.
    monkeypatch.setattr(sweep, "find_candidate", _fake_finder(["/A", "/B"]))
    processed = []
    st = _state()
    run_sweep("/out", lambda pd, sm: (processed.append(pd) or "skipped"),
              should_start=lambda: True, max_papers=10, state=st)
    assert processed == ["/A"]
    assert st["done"] == 0


def test_run_sweep_single_flight(monkeypatch):
    # daemon ↔ on-demand 상호배제: 다른 sweep 가 이미 돌면(_SWEEP_RUN_LOCK 점유) 새 run_sweep 은
    # 후보를 처리하지 않고 즉시 반환(중복 처리 방지).
    monkeypatch.setattr(sweep, "find_candidate", _fake_finder(["/A"]))
    sweep._SWEEP_RUN_LOCK.acquire()
    try:
        processed = []
        st = _state()
        run_sweep("/out", lambda pd, sm: (processed.append(pd) or "ready"),
                  should_start=lambda: True, max_papers=10, state=st)
        assert processed == []
        assert st["running"] is False
    finally:
        sweep._SWEEP_RUN_LOCK.release()


def test_run_sweep_does_not_retry_failed_candidate(monkeypatch):
    # 실패 후보는 같은 sweep 안에서 재시도하지 않는다(skip) — 무한 루프 방지.
    monkeypatch.setattr(sweep, "find_candidate", _fake_finder(["/A", "/B"]))
    processed = []
    run_sweep("/out", lambda pd, sm: (processed.append(pd) or "failed"),
              should_start=lambda: True, max_papers=10, state=_state())
    assert processed == ["/A", "/B"]            # 각 1회만, A 무한 반복 없음
