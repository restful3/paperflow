import glob
import json
import os

from app.gpulock import try_acquire

_IDLE_STAGES = ("ready", "failed", "failed_partial", "none")


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


def find_candidate(outputs_root):
    """Return one paper dict with _ko_audio.md but no fresh HLS, or None."""
    from app.manifest import is_fresh_for_hls  # HIGH#4: sha 기반 freshness

    dirs = sorted(
        glob.glob(os.path.join(outputs_root, "*")),
        key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
        reverse=True,
    )
    for d in dirs:
        if not os.path.isdir(d):
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


def sweep_loop(jobs, lock, run_job, outputs_root, gpu_lock_path,
               enabled, interval, max_papers, stop_event):
    """Daemon sweep: pick one idle candidate and generate HLS, up to max_papers."""
    if not enabled:
        return
    done = 0
    while not stop_event.is_set() and done < max_papers:
        if should_run(jobs, gpu_lock_path):
            cand = find_candidate(outputs_root)
            if cand:
                with lock:
                    jobs[cand["paper_dir"]] = {
                        "stage": "segmenting",
                        "done": 0,
                        "total": 0,
                        "error": None,
                    }
                try:
                    run_job(cand["paper_dir"], cand["src_md"])
                    done += 1
                except Exception:
                    pass
        stop_event.wait(interval)
