import multiprocessing, time
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
