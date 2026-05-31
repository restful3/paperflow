import os

_MODEL = None

# 한국어 여성 내장 화자(참조 WAV 불필요). env 로 교체 가능.
QWEN_MODEL = os.environ.get("QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
QWEN_SPEAKER = os.environ.get("QWEN_TTS_SPEAKER", "Sohee")


def load_model(device="cuda"):
    global _MODEL
    if _MODEL is None:
        import torch
        from qwen_tts import Qwen3TTSModel
        dev = "cuda:0" if device == "cuda" else device
        _MODEL = Qwen3TTSModel.from_pretrained(
            QWEN_MODEL, device_map=dev, dtype=torch.bfloat16)
    return _MODEL


def model_revision():
    # artifact_version 캐시키에 들어감 — 모델/화자 바뀌면 오디오 재생성되도록 화자도 포함.
    return f"{QWEN_MODEL}@{QWEN_SPEAKER}"


def synth_chunk(text, out_wav, device="cuda", language_id="ko"):
    """청크 1개 → wav 파일. 모델 sr 반환. (Qwen3-TTS CustomVoice, 한국어 내장 여성화자)"""
    import soundfile as sf
    m = load_model(device)
    wavs, sr = m.generate_custom_voice(text=text, language="Korean", speaker=QWEN_SPEAKER)
    sf.write(out_wav, wavs[0], sr)
    return sr
