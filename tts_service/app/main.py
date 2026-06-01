import os, threading
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.job import run_job, GPU_LOCK_PATH, Preempted
from app.sweep import sweep_loop, run_sweep, should_run, _IDLE_STAGES

app = FastAPI()
_jobs = {}          # paper_dir -> {"stage","done","total","error"}
_lock = threading.Lock()
_current_target = None   # 가장 최근 요청된 foreground 논문 — 다른 논문 작업은 협조적으로 양보
_foreground_epoch = 0    # foreground /jobs 가 올 때마다 +1. 배치 작업은 이 epoch 스냅샷으로 선점 판단
                         # (배치는 _current_target 을 건드리지 않는다 — foreground 전용 신호)


def _is_active(paper_dir):
    with _lock:
        return _current_target == paper_dir


def _jobs_snapshot():
    # should_run 이 dict 를 순회하므로 lock 밖에서 직접 넘기면 progress_cb 의 동시 쓰기로
    # RuntimeError(dict changed size) 가능 → lock 안에서 복사본을 떠서 넘긴다.
    with _lock:
        return dict(_jobs)


class JobReq(BaseModel):
    paper_dir: str          # 절대경로(공유 볼륨)
    src_md: str             # 절대경로 <base>_ko_audio.md


def _worker(paper_dir, src_md, is_active=None):
    if is_active is None:
        is_active = lambda: _is_active(paper_dir)   # foreground 기본: 최신 target 이 나여야 활성
    def cb(stage, done, total):
        with _lock:
            _jobs[paper_dir] = {"stage": stage, "done": done, "total": total, "error": None}
    try:
        cb("segmenting", 0, 0)
        run_job(paper_dir, src_md, progress_cb=cb, is_active=is_active)
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
    with _lock:
        return _jobs.get(paper_dir, {}).get("stage")   # 종결 stage(배치 run_sweep 가 사용)


def _try_claim_batch(paper_dir):
    """배치 후보를 atomic 하게 claim. _lock 안에서 (a) 활성(비-idle) job 이 없는지 재확인하고
    (b) 그 순간의 _foreground_epoch 스냅샷을 잡고 (c) 후보를 segmenting 으로 등록한다.
    활성 job 이 있으면(=should_start 통과 후 foreground 가 먼저 들어온 race 포함) None → 배치 시작 안 함.
    (라운드3 HIGH: should_start 통과와 epoch 스냅샷 사이 TOCTOU 차단)."""
    with _lock:
        for st in _jobs.values():
            if st.get("stage") not in _IDLE_STAGES:
                return None
        epoch0 = _foreground_epoch
        _jobs[paper_dir] = {"stage": "segmenting", "done": 0, "total": 0, "error": None}
        return epoch0


def _process_candidate(paper_dir, src_md):
    """배치 후보 1건을 _worker 의미로 처리. 종결 stage 반환("skipped"=claim 실패로 미시작).
    _current_target(=foreground 전용)을 건드리지 않는다. epoch 스냅샷으로 활성 판단 → 배치 시작 후
    foreground /jobs 가 들어오면(epoch 증가) is_active=False → 청크 경계에서 양보(preempted)."""
    epoch0 = _try_claim_batch(paper_dir)
    if epoch0 is None:
        return "skipped"
    return _worker(paper_dir, src_md, is_active=lambda: _foreground_epoch == epoch0)


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
    global _current_target, _foreground_epoch
    with _lock:
        _current_target = req.paper_dir              # 최신 요청 = foreground → 다른 논문 작업은 양보
        _foreground_epoch += 1                       # 진행 중 배치가 epoch 변화로 양보하게
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


# ── On-demand 배치 sweep (오디오 없는 논문 순차 생성) ──────────────────────────
_sweep_state = {"running": False, "done": 0, "current": None, "error": None}
_sweep_ctl_lock = threading.Lock()


@app.post("/sweep")
def start_sweep(max_papers: int = 100):
    """오디오(_ko_audio.md 있고 fresh HLS 없음) 미생성 논문을 순차 생성. 즉시 반환, GET /sweep 로 진행 조회."""
    max_papers = max(1, min(max_papers, 500))
    with _sweep_ctl_lock:
        if _sweep_state["running"]:
            return {"started": False, "running": True, "done": _sweep_state["done"]}
        _sweep_state.update({"running": True, "done": 0, "current": None, "error": None})
    threading.Thread(
        target=run_sweep,
        args=(_OUTPUTS_ROOT, _process_candidate,
              lambda: should_run(_jobs_snapshot(), GPU_LOCK_PATH), max_papers, _sweep_state),
        daemon=True).start()
    return {"started": True, "max_papers": max_papers}


@app.get("/sweep")
def sweep_status():
    with _sweep_ctl_lock:
        return dict(_sweep_state)


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
            args=(_OUTPUTS_ROOT, _process_candidate,
                  lambda: should_run(_jobs_snapshot(), GPU_LOCK_PATH),
                  True, _SWEEP_INTERVAL, _SWEEP_MAX_PAPERS, _stop),
            daemon=True).start()
