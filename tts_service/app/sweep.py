import glob
import json
import os
import threading

from app.gpulock import try_acquire

_IDLE_STAGES = ("ready", "failed", "failed_partial", "none", "cancelled")
# daemon sweep 과 on-demand run_sweep 의 후보 처리를 단일화(둘이 동시에 같은/다른 후보를 밀어넣지 않게).
_SWEEP_RUN_LOCK = threading.Lock()


def should_run(jobs, gpu_lock_path):
    """True iff no active job is running and GPU lock is acquirable.

    Conservative denylist: any stage NOT known-idle counts as active and blocks
    the sweep, so unknown/new stages block rather than risk GPU contention."""
    if any(st.get("stage") not in _IDLE_STAGES for st in jobs.values()):
        return False
    fh = try_acquire(gpu_lock_path)
    if fh is None:
        return False
    fh.close()  # 즉시 해제 (점유 가능 여부 확인용)
    return True


def _sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()


def find_candidate(outputs_root, skip=None):
    """Return one paper dict with _ko_audio.md but no fresh HLS, or None.
    skip: 이미 시도한 paper_dir 집합 — 같은 sweep 안에서 실패 후보 무한 재시도 방지."""
    from app.manifest import is_fresh_for_hls  # HIGH#4: sha 기반 freshness

    skip = skip or set()
    dirs = sorted(
        glob.glob(os.path.join(outputs_root, "*")),
        key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
        reverse=True,
    )
    for d in dirs:
        if not os.path.isdir(d) or d in skip:
            continue
        mds = glob.glob(os.path.join(d, "*_ko_audio.md"))
        if not mds:
            continue
        src_md = mds[0]
        base = os.path.basename(src_md)[: -len("_ko_audio.md")]
        man_path = os.path.join(d, f"{base}_ko_audio.manifest.json")
        fresh_hls = False
        if os.path.exists(man_path):
            try:
                m = json.load(open(man_path))
                cur_sha = _sha256_file(src_md)
                fresh_hls = is_fresh_for_hls(m, cur_sha)
            except Exception:
                pass
        if not fresh_hls:
            return {"paper_dir": d, "src_md": src_md}
    return None


def run_sweep(outputs_root, process_one, should_start, max_papers, state):
    """On-demand 배치: 오디오 없는 후보를 순차 생성. 단일 GPU라 한 번에 하나씩.
    - process_one(paper_dir, src_md) -> 종결 stage("ready"/"failed"/"failed_partial"/"preempted").
      (= _worker 의미: progress_cb 로 _jobs 갱신 + foreground 선점 + 종결 상태 보장)
    - should_start() -> bool: 활성 job/GPU 점유 없을 때만 True(idle-only 배치).
    - 실패 후보는 skip 으로 같은 sweep 내 재시도 안 함. foreground 선점(preempted) 시 배치 중단.
    state = {"running","done","current","error"} (호출자가 running=True 로 시작)."""
    if not _SWEEP_RUN_LOCK.acquire(blocking=False):   # 다른 sweep 진행 중 → 중복 실행 안 함
        state["running"] = False
        return
    seen = set()
    try:
        while state["done"] < max_papers:
            if not should_start():               # 활성 foreground/GPU 점유 → 배치 시작/계속 안 함
                break
            cand = find_candidate(outputs_root, skip=seen)
            if not cand:
                break
            seen.add(cand["paper_dir"])
            state["current"] = cand["paper_dir"]
            stage = process_one(cand["paper_dir"], cand["src_md"])
            if stage == "skipped":               # claim 실패(foreground 가 먼저 들어옴) → 시작 못 함, 배치 중단
                break
            state["done"] += 1
            if stage == "preempted":             # 처리 중 foreground 선점 → 양보하고 배치 중단
                break
    finally:
        _SWEEP_RUN_LOCK.release()
        state["current"] = None
        state["running"] = False


def sweep_loop(outputs_root, process_one, should_start, enabled, interval, max_papers, stop_event):
    """Daemon sweep: idle 일 때 후보 1건씩 생성(process_one), max_papers 까지. (기본 OFF)
    on-demand run_sweep 과 같은 worker 의미(process_one)·idle 게이트(should_start) 공유."""
    if not enabled:
        return
    done = 0
    while not stop_event.is_set() and done < max_papers:
        if should_start() and _SWEEP_RUN_LOCK.acquire(blocking=False):   # on-demand sweep 과 상호배제
            try:
                cand = find_candidate(outputs_root)
                if cand:
                    process_one(cand["paper_dir"], cand["src_md"])
                    done += 1
            finally:
                _SWEEP_RUN_LOCK.release()
        stop_event.wait(interval)
