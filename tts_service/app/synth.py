import os

_MODEL = None

# 한국어 여성 내장 화자(참조 WAV 불필요). env 로 교체 가능.
QWEN_MODEL = os.environ.get("QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
QWEN_SPEAKER = os.environ.get("QWEN_TTS_SPEAKER", "Sohee")
# 전달 톤 지시 — 중립 아나운서(Sohee 기본이 감정 풍부라 절제시킴). env 로 조정 가능.
QWEN_INSTRUCT = os.environ.get(
    "QWEN_TTS_INSTRUCT",
    "뉴스 아나운서처럼 중립적이고 차분한 톤으로, 감정을 절제하고 또박또박 명료하게 읽어주세요.")


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
    # artifact_version 캐시키 — 모델/화자/톤지시 바뀌면 오디오 재생성되도록 모두 포함.
    return f"{QWEN_MODEL}@{QWEN_SPEAKER}#{QWEN_INSTRUCT}"


def synth_chunk(text, out_wav, device="cuda", language_id="ko"):
    """청크 1개 → wav 파일. 모델 sr 반환. (Qwen3-TTS CustomVoice, 한국어 내장 여성화자 + 아나운서 톤 instruct)"""
    import soundfile as sf
    m = load_model(device)
    wavs, sr = m.generate_custom_voice(
        text=text, language="Korean", speaker=QWEN_SPEAKER, instruct=QWEN_INSTRUCT)
    sf.write(out_wav, wavs[0], sr)
    return sr
