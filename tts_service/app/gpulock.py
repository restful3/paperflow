import fcntl, os, time
from contextlib import contextmanager


def try_acquire(lockpath):
    """non-blocking. 성공 시 열린 파일핸들(보유), 실패 시 None."""
    os.makedirs(os.path.dirname(lockpath), exist_ok=True)
    fh = open(lockpath, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


@contextmanager
def gpu_lock(lockpath, timeout=1800, poll=2.0):
    """blocking(타임아웃). converter도 같은 경로로 flock 걸어야 상호배제됨."""
    os.makedirs(os.path.dirname(lockpath), exist_ok=True)
    fh = open(lockpath, "w")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() > deadline:
                fh.close(); raise TimeoutError("GPU lock timeout")
            time.sleep(poll)
    try:
        yield fh
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close()
