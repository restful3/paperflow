import fcntl, multiprocessing, time
import pytest
from app.gpulock import gpu_lock, try_acquire


def _hold(lockpath, q, secs):
    with gpu_lock(lockpath):
        q.put("acquired"); time.sleep(secs)


def test_mutual_exclusion(tmp_path):
    lp = str(tmp_path / ".gpu.lock")
    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=_hold, args=(lp, q, 1.0)); p.start()
    assert q.get(timeout=3) == "acquired"
    # 보유 중엔 non-blocking 획득 실패
    assert try_acquire(lp) is None
    p.join()
    # 해제 후엔 성공
    fh = try_acquire(lp); assert fh is not None; fh.close()


def test_gpu_lock_invokes_on_wait_while_blocked(tmp_path):
    # M2: while blocked waiting for the lock, gpu_lock must call on_wait each poll so a
    # healthy-but-waiting job can refresh its heartbeat (else reconcile_stale false-fails it
    # when a long-running converter holds the GPU lock near the stale threshold).
    lp = str(tmp_path / ".gpu.lock")
    holder = try_acquire(lp)                       # hold the lock so the next acquire blocks
    assert holder is not None
    beats = []
    try:
        with pytest.raises(TimeoutError):
            with gpu_lock(lp, timeout=0.25, poll=0.05, on_wait=lambda: beats.append(1)):
                pass                               # never reached — lock is held
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN); holder.close()
    assert len(beats) >= 1                          # heartbeat callback fired during the wait


def test_gpu_lock_no_on_wait_when_immediate(tmp_path):
    # 즉시 획득 시엔 on_wait 를 부르지 않는다(불필요한 heartbeat publish 회피).
    lp = str(tmp_path / ".gpu.lock")
    beats = []
    with gpu_lock(lp, on_wait=lambda: beats.append(1)):
        pass
    assert beats == []
