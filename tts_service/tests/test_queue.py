import json
import os

from app.queue import AudioQueue


def _q(tmp_path, process_one=None, should_start=None, is_fresh=None):
    """기본값: 항상 idle, process_one 은 'ready' 반환, fresh 아님."""
    return AudioQueue(
        path=str(tmp_path / ".audio_queue.json"),
        process_one=process_one or (lambda pd, sm: "ready"),
        should_start=should_start or (lambda: True),
        is_fresh=is_fresh or (lambda pd, sm: False),
    )


def test_enqueue_adds_one_and_dedupes(tmp_path):
    q = _q(tmp_path)
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    snap = q.snapshot()
    assert len(snap["items"]) == 1
    assert snap["items"][0]["paper_dir"] == "/out/A"
    assert snap["items"][0]["status"] == "pending"
    # 같은 paper_dir 재투입 → 무시(중복 안 만듦)
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    assert len(q.snapshot()["items"]) == 1


def test_remove_pending_ok_processing_refused(tmp_path):
    q = _q(tmp_path)
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    assert q.remove("/out/A") is True
    assert q.snapshot()["items"] == []
    # processing 상태는 제거 거부(Phase 1: 완료까지 대기)
    q.enqueue("/out/B", "/out/B/B_ko_audio.md")
    q._items[0]["status"] = "processing"
    assert q.remove("/out/B") is False
    assert len(q.snapshot()["items"]) == 1


def test_drain_processes_pending_sequentially(tmp_path):
    order = []
    q = _q(tmp_path, process_one=lambda pd, sm: (order.append(pd) or "ready"))
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    q.enqueue("/out/B", "/out/B/B_ko_audio.md")
    assert q.drain_once() is True
    assert q.drain_once() is True
    assert q.drain_once() is False        # 더 처리할 pending 없음
    assert order == ["/out/A", "/out/B"]
    statuses = [it["status"] for it in q.snapshot()["items"]]
    assert statuses == ["done", "done"]


def test_drain_idle_gated(tmp_path):
    order = []
    q = _q(tmp_path, process_one=lambda pd, sm: (order.append(pd) or "ready"),
           should_start=lambda: False)             # 활성 foreground/GPU → 시작 안 함
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    assert q.drain_once() is False
    assert order == []
    assert q.snapshot()["items"][0]["status"] == "pending"


def test_drain_preempted_returns_to_pending(tmp_path):
    # foreground 선점 → process_one 'preempted' → 항목은 pending 으로 되돌아가 재방문 가능
    q = _q(tmp_path, process_one=lambda pd, sm: "preempted")
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    q.drain_once()
    assert q.snapshot()["items"][0]["status"] == "pending"


def test_drain_skipped_returns_to_pending(tmp_path):
    # claim 실패('skipped') → pending 유지(다음 idle 때 재시도)
    q = _q(tmp_path, process_one=lambda pd, sm: "skipped")
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    q.drain_once()
    assert q.snapshot()["items"][0]["status"] == "pending"


def test_drain_failed_marks_failed(tmp_path):
    q = _q(tmp_path, process_one=lambda pd, sm: "failed")
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    q.drain_once()
    assert q.snapshot()["items"][0]["status"] == "failed"


def test_persistence_reload(tmp_path):
    q = _q(tmp_path)
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    # 같은 경로로 새 인스턴스 → 디스크에서 복원
    q2 = _q(tmp_path)
    items = q2.snapshot()["items"]
    assert len(items) == 1 and items[0]["paper_dir"] == "/out/A"
    # 디스크 파일도 실제로 존재
    assert os.path.exists(str(tmp_path / ".audio_queue.json"))


def test_restart_recovery_processing_to_pending(tmp_path):
    # 중단된 processing 항목은 재부팅 시 pending 으로 되돌린다(이미 fresh 면 done).
    path = str(tmp_path / ".audio_queue.json")
    json.dump([
        {"paper_dir": "/out/A", "src_md": "/out/A/A_ko_audio.md",
         "status": "processing", "enqueued_at": "t", "error": None},
        {"paper_dir": "/out/B", "src_md": "/out/B/B_ko_audio.md",
         "status": "processing", "enqueued_at": "t", "error": None},
    ], open(path, "w"))
    # A 는 이미 fresh 오디오 있음 → done, B 는 없음 → pending
    q = AudioQueue(path=path, process_one=lambda pd, sm: "ready",
                   should_start=lambda: True,
                   is_fresh=lambda pd, sm: pd == "/out/A")
    by_dir = {it["paper_dir"]: it["status"] for it in q.snapshot()["items"]}
    assert by_dir == {"/out/A": "done", "/out/B": "pending"}


def test_enqueue_missing_selects_only_audio_md_without_fresh(tmp_path):
    root = tmp_path / "outputs"
    (root / "P").mkdir(parents=True)
    (root / "P" / "P_ko_audio.md").write_text("# t\n\n본문.")
    (root / "Q").mkdir(parents=True)
    (root / "Q" / "Q.md").write_text("no audio md here")   # 낭독본 없음 → 제외
    q = _q(tmp_path)
    added = q.enqueue_missing(str(root), max_n=10)
    assert added == 1
    items = q.snapshot()["items"]
    assert len(items) == 1 and items[0]["paper_dir"].endswith("/P")


def test_enqueue_missing_respects_max(tmp_path):
    root = tmp_path / "outputs"
    for name in ("A", "B", "C"):
        (root / name).mkdir(parents=True)
        (root / name / f"{name}_ko_audio.md").write_text("# t\n\n본문.")
    q = _q(tmp_path)
    added = q.enqueue_missing(str(root), max_n=2)
    assert added == 2
    assert len(q.snapshot()["items"]) == 2


def test_snapshot_reports_current_processing(tmp_path):
    q = _q(tmp_path)
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    q._items[0]["status"] = "processing"
    assert q.snapshot()["current"] == "/out/A"


# ── 하드닝: 크래시/예외 시 failed 마킹 ────────────────────────────────────────


def test_drain_marks_failed_and_records_error_on_exception(tmp_path):
    """process_one 이 예외를 던지면(예: CUDA assert RuntimeError) 항목을 failed 로
    마킹하고 error 를 기록한다. drain_once 는 예외를 전파하지 않는다(True 반환)."""
    def boom(pd, sm):
        raise RuntimeError("CUDA error: device-side assert triggered")
    q = _q(tmp_path, process_one=boom)
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    assert q.drain_once() is True                 # 예외 전파 안 함
    it = q.snapshot()["items"][0]
    assert it["status"] == "failed"
    assert it["error"] and "RuntimeError" in it["error"]


def test_drain_continues_to_next_item_after_exception(tmp_path):
    """한 항목이 예외로 죽어도 워커는 살아남아 다음 pending 을 계속 처리한다."""
    def po(pd, sm):
        if pd == "/out/A":
            raise RuntimeError("boom")
        return "ready"
    q = _q(tmp_path, process_one=po)
    q.enqueue("/out/A", "/out/A/A_ko_audio.md")
    q.enqueue("/out/B", "/out/B/B_ko_audio.md")
    assert q.drain_once() is True                 # A 예외 → failed
    assert q.drain_once() is True                 # B 정상 처리
    by = {it["paper_dir"]: it["status"] for it in q.snapshot()["items"]}
    assert by == {"/out/A": "failed", "/out/B": "done"}


def test_recover_requeues_first_interruption_with_counter(tmp_path):
    """중단된 processing 항목의 첫 복구는 pending 재큐 + interrupts=1
    (일시적 재시작 1회 흡수)."""
    path = str(tmp_path / ".audio_queue.json")
    json.dump([{"paper_dir": "/out/A", "src_md": "/out/A/A_ko_audio.md",
                "status": "processing", "enqueued_at": "t", "error": None}],
              open(path, "w"))
    q = AudioQueue(path=path, process_one=lambda pd, sm: "ready",
                   should_start=lambda: True, is_fresh=lambda pd, sm: False)
    it = q.snapshot()["items"][0]
    assert it["status"] == "pending"
    assert it["interrupts"] == 1


def test_recover_marks_failed_after_repeated_interruption(tmp_path):
    """이미 한 번 중단(interrupts=1)된 항목이 또 processing 으로 죽어 있으면
    재큐 대신 failed 로 마킹(무한 재시도 차단) + error 기록."""
    path = str(tmp_path / ".audio_queue.json")
    json.dump([{"paper_dir": "/out/A", "src_md": "/out/A/A_ko_audio.md",
                "status": "processing", "enqueued_at": "t", "error": None,
                "interrupts": 1}],
              open(path, "w"))
    q = AudioQueue(path=path, process_one=lambda pd, sm: "ready",
                   should_start=lambda: True, is_fresh=lambda pd, sm: False)
    it = q.snapshot()["items"][0]
    assert it["status"] == "failed"
    assert it["error"] and ("중단" in it["error"] or "재시도" in it["error"])
