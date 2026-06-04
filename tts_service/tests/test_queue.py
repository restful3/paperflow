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
