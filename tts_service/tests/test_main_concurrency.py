import sys, types
sys.modules.setdefault("torchaudio", types.ModuleType("torchaudio"))
import app.main as main


def test_batch_does_not_steal_foreground_target(monkeypatch):
    # HIGH(라운드2): 배치 후보 처리가 _current_target(=foreground 전용 우선순위)을 덮어쓰면 안 된다.
    # 배치는 epoch 스냅샷으로만 활성 판단 → 새 foreground 요청이 오면 yield.
    main._jobs.clear()
    main._current_target = "/fg"
    main._foreground_epoch = 5
    captured = {}
    monkeypatch.setattr(main, "_worker",
                        lambda pd, sm, is_active=None: (captured.update(is_active=is_active), "ready")[1])

    stage = main._process_candidate("/batch", "/batch/x_ko_audio.md")

    assert stage == "ready"
    assert main._current_target == "/fg"          # 배치가 foreground target 을 안 건드림
    ia = captured["is_active"]
    assert ia() is True                            # epoch 그대로 → 배치 활성
    main._foreground_epoch += 1                    # foreground /jobs 도착
    assert ia() is False                           # → 배치는 양보(preempt)


def test_batch_skips_when_foreground_already_active(monkeypatch):
    # HIGH(라운드3): should_start 통과와 epoch 스냅샷 사이에 foreground 가 들어오는 race.
    # _process_candidate 는 _lock 안에서 활성 job 을 재확인(atomic claim)하고, 활성이면 "skipped" 로 시작 안 함.
    main._jobs.clear()
    main._foreground_epoch = 0
    main._jobs["/fg"] = {"stage": "synthesizing", "done": 1, "total": 10, "error": None}
    called = {"worker": False}
    monkeypatch.setattr(main, "_worker",
                        lambda *a, **k: (called.__setitem__("worker", True), "ready")[1])

    stage = main._process_candidate("/batch", "/batch/x_ko_audio.md")

    assert stage == "skipped"               # foreground 활성 → claim 실패
    assert called["worker"] is False        # _worker 안 불림(배치 시작 안 함)
