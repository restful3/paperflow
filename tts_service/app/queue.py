"""관리형 오디오 큐 — 등록 큐(newones/ + watch) UX 를 오디오 MP3 생성에 미러링.

영속 파일(.audio_queue.json)에 순서 있는 대기열을 두고, 단일 워커 스레드가 순차 드레인한다.
각 항목은 기존 배치 워커 의미(process_one = main._process_candidate: GPU 락·manifest·이미지 스킵
청커 + foreground 선점)로 처리된다. /sweep 의 즉석 발견(find_candidate) 대신 '명시적 영속 목록'을
드레인한다는 점만 다르다.

stage→status 매핑(process_one 반환):
  ready                  → done
  failed / failed_partial→ failed
  preempted              → pending (foreground 선점, 재방문)
  skipped                → pending (claim 실패, 다음 idle 때 재시도)
"""
import json
import os
import threading

from app.manifest import _now_iso
from app.sweep import find_candidate

_PENDING, _PROCESSING, _DONE, _FAILED = "pending", "processing", "done", "failed"
_ACTIVE = (_PENDING, _PROCESSING)   # 중복 enqueue / enqueue-missing skip 판정 대상


class AudioQueue:
    def __init__(self, path, process_one, should_start, is_fresh=None):
        """path: 영속 JSON 파일. process_one(paper_dir, src_md)->stage(_process_candidate 의미).
        should_start()->bool: idle 게이트(활성 job/GPU 점유 없을 때만 True). 비-idle 이면 드레인 보류.
        is_fresh(paper_dir, src_md)->bool: 재시작 복구 시 이미 fresh 오디오가 있으면 done 처리."""
        self.path = path
        self.process_one = process_one
        self.should_start = should_start
        self.is_fresh = is_fresh or (lambda pd, sm: False)
        self._lock = threading.RLock()
        self._items = []
        self._wake = threading.Event()      # enqueue 시 워커 깨우기
        self._stop = threading.Event()
        self._load()
        self._recover()

    # ── 영속 ──────────────────────────────────────────────────────────────
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            data = json.load(open(self.path, encoding="utf-8"))
            if isinstance(data, list):
                self._items = data
        except Exception:
            self._items = []

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._items, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def _recover(self):
        """부팅 시 중단된 processing 항목을 pending 으로(이미 fresh 면 done) 되돌린다."""
        changed = False
        with self._lock:
            for it in self._items:
                if it.get("status") == _PROCESSING:
                    it["status"] = _DONE if self.is_fresh(it["paper_dir"], it["src_md"]) else _PENDING
                    changed = True
            if changed:
                self._save()

    # ── 큐 조작 ───────────────────────────────────────────────────────────
    def enqueue(self, paper_dir, src_md):
        """대기열에 추가. 이미 pending/processing 이면 무시(중복 안 만듦)."""
        with self._lock:
            for it in self._items:
                if it["paper_dir"] == paper_dir and it["status"] in _ACTIVE:
                    return False
            self._items.append({"paper_dir": paper_dir, "src_md": src_md,
                                "status": _PENDING, "enqueued_at": _now_iso(), "error": None})
            self._save()
        self._wake.set()
        return True

    def remove(self, paper_dir):
        """pending 항목 제거. processing(진행 중)이면 거부(Phase 1: 완료까지 대기)."""
        with self._lock:
            for it in self._items:
                if it["paper_dir"] == paper_dir and it["status"] == _PROCESSING:
                    return False
            before = len(self._items)
            self._items = [it for it in self._items
                           if not (it["paper_dir"] == paper_dir and it["status"] == _PENDING)]
            if len(self._items) != before:
                self._save()
                return True
            return False

    def enqueue_missing(self, outputs_root, max_n=100):
        """_ko_audio.md 있고 fresh 오디오 없는 논문을 전부(최대 max_n) 큐 투입. 추가 건수 반환.
        (현 /sweep 역할 대체 — find_candidate 의 freshness 판정 재사용)."""
        max_n = max(1, min(int(max_n), 500))
        added = 0
        with self._lock:
            skip = {it["paper_dir"] for it in self._items if it["status"] in _ACTIVE}
        while added < max_n:
            cand = find_candidate(outputs_root, skip=skip)
            if not cand:
                break
            if self.enqueue(cand["paper_dir"], cand["src_md"]):
                added += 1
            skip.add(cand["paper_dir"])
        return added

    def snapshot(self):
        """전체 큐(복사본) + current(=processing paper_dir 또는 None)."""
        with self._lock:
            items = [dict(it) for it in self._items]
        current = next((it["paper_dir"] for it in items if it["status"] == _PROCESSING), None)
        return {"items": items, "current": current}

    # ── 드레인 ────────────────────────────────────────────────────────────
    def drain_once(self):
        """pending 1건 처리 시도. idle 아니거나 pending 없으면 False(아무것도 안 함).
        처리 시도했으면 True. stage 결과를 항목 status 로 반영하고 영속."""
        if not self.should_start():
            return False
        with self._lock:
            item = next((it for it in self._items if it["status"] == _PENDING), None)
            if item is None:
                return False
            item["status"] = _PROCESSING
            item["error"] = None
            self._save()
            paper_dir, src_md = item["paper_dir"], item["src_md"]
        stage = self.process_one(paper_dir, src_md)
        with self._lock:
            if stage == "ready":
                item["status"] = _DONE
            elif stage in ("preempted", "skipped"):
                item["status"] = _PENDING        # 선점/claim실패 → 재방문
            else:                                 # failed / failed_partial / 기타
                item["status"] = _FAILED
            self._save()
        return True

    def run_worker(self, poll=1.0):
        """백그라운드 워커 루프: pending 을 순차 드레인. 비-idle/빈 큐면 깨움 신호까지 대기."""
        while not self._stop.is_set():
            if not self.drain_once():
                self._wake.wait(timeout=poll)
                self._wake.clear()

    def stop(self):
        self._stop.set()
        self._wake.set()
