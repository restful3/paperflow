import os, threading
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.job import run_job

app = FastAPI()
_jobs = {}          # paper_dir -> {"stage","done","total","error"}
_lock = threading.Lock()


class JobReq(BaseModel):
    paper_dir: str          # 절대경로(공유 볼륨)
    src_md: str             # 절대경로 <base>_ko_audio.md


def _worker(paper_dir, src_md):
    def cb(stage, done, total):
        with _lock:
            _jobs[paper_dir] = {"stage": stage, "done": done, "total": total, "error": None}
    try:
        cb("segmenting", 0, 0)
        run_job(paper_dir, src_md, progress_cb=cb)
    except Exception as e:
        with _lock:
            _jobs[paper_dir] = {"stage": "failed", "done": 0, "total": 0, "error": str(e)}


@app.get("/health")
def health():
    return {"ok": True}


_OUTPUTS_ROOT = os.environ.get("PF_OUTPUTS_ROOT", "/data/outputs")


def _under_root(p):                       # nit#7: 방어층 — 임의 절대경로 차단
    rp = os.path.realpath(p)
    return rp == os.path.realpath(_OUTPUTS_ROOT) or rp.startswith(os.path.realpath(_OUTPUTS_ROOT) + os.sep)


@app.post("/jobs")
def create(req: JobReq):
    if not (_under_root(req.paper_dir) and _under_root(req.src_md)):
        raise HTTPException(400, "path outside outputs root")
    if not os.path.exists(req.src_md):
        raise HTTPException(404, "src_md not found")
    with _lock:
        st = _jobs.get(req.paper_dir)
        if st and st["stage"] not in ("ready", "failed"):
            return {"accepted": False, "status": st}     # 이미 진행 중
        _jobs[req.paper_dir] = {"stage": "segmenting", "done": 0, "total": 0, "error": None}
    threading.Thread(target=_worker, args=(req.paper_dir, req.src_md), daemon=True).start()
    return {"accepted": True}


@app.get("/jobs")
def status(paper_dir: str):
    with _lock:
        return _jobs.get(paper_dir, {"stage": "none", "done": 0, "total": 0, "error": None})
