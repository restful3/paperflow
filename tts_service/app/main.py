import os, threading
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.job import run_job, GPU_LOCK_PATH, Preempted
from app.sweep import sweep_loop

app = FastAPI()
_jobs = {}          # paper_dir -> {"stage","done","total","error"}
_lock = threading.Lock()
_current_target = None   # 가장 최근 요청된 foreground 논문 — 다른 논문 작업은 협조적으로 양보


def _is_active(paper_dir):
    with _lock:
        return _current_target == paper_dir


class JobReq(BaseModel):
    paper_dir: str          # 절대경로(공유 볼륨)
    src_md: str             # 절대경로 <base>_ko_audio.md


def _worker(paper_dir, src_md):
    def cb(stage, done, total):
        with _lock:
            _jobs[paper_dir] = {"stage": stage, "done": done, "total": total, "error": None}
    try:
        cb("segmenting", 0, 0)
        run_job(paper_dir, src_md, progress_cb=cb, is_active=lambda: _is_active(paper_dir))
        # freshness-skip 경로는 progress_cb("ready")를 부르지 않으므로 완료를 보장한다.
        with _lock:
            st = _jobs.get(paper_dir, {})
            if st.get("stage") not in ("ready", "failed_partial"):
                _jobs[paper_dir] = {"stage": "ready", "done": st.get("done", 0),
                                    "total": st.get("total", 0), "error": None}
    except Preempted:
        # foreground 가 다른 논문으로 바뀜 → 양보. 비종결 상태(preempted)로 두어 재방문 시 재트리거 가능.
        with _lock:
            _jobs[paper_dir] = {"stage": "preempted", "done": 0, "total": 0, "error": None}
    except RuntimeError as e:
        # _fail_partial 가 raise — manifest 는 이미 failed_partial. status 반영(앞부분 재생 가능).
        with _lock:
            _jobs[paper_dir] = {"stage": "failed_partial", "done": 0, "total": 0, "error": str(e)}
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
    global _current_target
    with _lock:
        _current_target = req.paper_dir              # 최신 요청 = foreground → 다른 논문 작업은 양보
        st = _jobs.get(req.paper_dir)
        if st and st["stage"] not in ("ready", "failed", "failed_partial", "preempted"):
            return {"accepted": False, "status": st}     # 이미 진행 중
        _jobs[req.paper_dir] = {"stage": "segmenting", "done": 0, "total": 0, "error": None}
    threading.Thread(target=_worker, args=(req.paper_dir, req.src_md), daemon=True).start()
    return {"accepted": True}


@app.get("/jobs")
def status(paper_dir: str):
    with _lock:
        return _jobs.get(paper_dir, {"stage": "none", "done": 0, "total": 0, "error": None})


# ── 유휴 사전생성 sweep (기본 OFF) ─────────────────────────────────────────────
_SWEEP_ENABLED = os.environ.get("SWEEP_ENABLED", "false").lower() == "true"
_SWEEP_INTERVAL = int(os.environ.get("SWEEP_INTERVAL", "60"))
_SWEEP_MAX_PAPERS = int(os.environ.get("SWEEP_MAX_PAPERS", "3"))
_stop = threading.Event()


@app.on_event("startup")
def _preload_model():
    # 부팅 시 모델을 미리 로드(백그라운드) → 첫 작업이 ~80s 콜드 로드를 안 치르고 바로 합성 시작.
    def _warm():
        try:
            from app.synth import load_model
            load_model("cuda")
        except Exception:
            pass
    threading.Thread(target=_warm, daemon=True).start()


@app.on_event("startup")
def _start_sweep():
    if _SWEEP_ENABLED:
        threading.Thread(
            target=sweep_loop,
            args=(_jobs, _lock, run_job, _OUTPUTS_ROOT, GPU_LOCK_PATH,
                  True, _SWEEP_INTERVAL, _SWEEP_MAX_PAPERS, _stop),
            daemon=True).start()
