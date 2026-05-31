import torchaudio as ta

_MODEL = None


def _ensure_watermarker():
    # B3: perth는 chatterbox-tts 의존성이라 보통 import 됨(샘플서 확인). 단 방어적으로 처리.
    try:
        import perth
    except ImportError:
        return  # 미설치면 chatterbox 내부 기본동작에 맡김(합성엔 영향 없음)
    if getattr(perth, "PerthImplicitWatermarker", None) is None:  # 워터마커 비활성 시 무음 대체
        perth.PerthImplicitWatermarker = perth.DummyWatermarker


def load_model(device="cuda"):
    global _MODEL
    if _MODEL is None:
        _ensure_watermarker()
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        _MODEL = ChatterboxMultilingualTTS.from_pretrained(device=device)
    return _MODEL


def model_revision():
    m = _MODEL
    return getattr(m, "revision", None) or "unknown" if m else "unknown"


def synth_chunk(text, out_wav, device="cuda", language_id="ko"):
    """청크 1개 → wav 파일. 모델 sr 반환."""
    m = load_model(device)
    wav = m.generate(text, language_id=language_id)
    ta.save(out_wav, wav.cpu() if hasattr(wav, "cpu") else wav, m.sr)
    return m.sr
