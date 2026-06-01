"""synth.py 음성 선택 로직 — VOXCPM_VOICE env → 참조 wav+전사 해석, model_revision 캐시키.
엔진(voxcpm) 미로드로 테스트 가능: 해석 함수는 voices.json + env 만 읽는다."""
import os, json, importlib, pytest
from app import synth


def _reload():
    return importlib.reload(synth)


def test_default_voice_is_chaewon(monkeypatch):
    monkeypatch.delenv("VOXCPM_VOICE", raising=False)
    assert synth._voice_key() == "09_chaewon"


def test_resolve_default_returns_existing_ref(monkeypatch):
    monkeypatch.delenv("VOXCPM_VOICE", raising=False)
    wav, ref_text = synth.resolve_voice()
    assert wav.endswith("09_chaewon.wav")
    assert os.path.exists(wav)              # 번들된 참조 클립 실제 존재
    assert isinstance(ref_text, str) and ref_text.strip()


def test_env_override_selects_other_active_voice(monkeypatch):
    monkeypatch.setenv("VOXCPM_VOICE", "04_sua")
    wav, ref_text = synth.resolve_voice()
    assert wav.endswith("04_sua.wav") and os.path.exists(wav)


def test_unknown_voice_raises(monkeypatch):
    monkeypatch.setenv("VOXCPM_VOICE", "99_nobody")
    with pytest.raises(ValueError):
        synth.resolve_voice()


def test_model_revision_includes_voice_and_changes(monkeypatch):
    monkeypatch.setenv("VOXCPM_VOICE", "09_chaewon")
    r9 = synth.model_revision()
    assert "09_chaewon" in r9
    monkeypatch.setenv("VOXCPM_VOICE", "04_sua")
    assert synth.model_revision() != r9     # 음성 바꾸면 캐시키 달라짐 → 오디오 재생성


def test_load_model_loads_once_under_concurrency(monkeypatch):
    """부팅 프리로드 스레드 + job 워커가 느린 from_pretrained 중 동시에 load_model 을 불러도
    모델은 단 한 번만 로드되어야 한다(두 인스턴스 동시 로드 = VRAM 2배 → OOM)."""
    import sys, types, time, threading
    calls = []

    class FakeVoxCPM:
        @classmethod
        def from_pretrained(cls, *a, **k):
            calls.append(1)
            time.sleep(0.05)          # 느린 로드(레이스 창) 모사
            return object()

    fake = types.ModuleType("voxcpm")
    fake.VoxCPM = FakeVoxCPM
    monkeypatch.setitem(sys.modules, "voxcpm", fake)
    monkeypatch.setattr(synth, "_MODEL", None)

    results = []
    threads = [threading.Thread(target=lambda: results.append(synth.load_model("cpu")))
               for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert len(calls) == 1                       # 단 한 번만 로드
    assert len({id(r) for r in results}) == 1    # 5개 호출 모두 같은 인스턴스
    monkeypatch.setattr(synth, "_MODEL", None)
