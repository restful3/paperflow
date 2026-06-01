import os, json, threading

_MODEL = None
_MODEL_LOCK = threading.Lock()   # 부팅 프리로드 + job 워커가 동시에 로드해 모델 2개(VRAM 2배)를 만드는 것 방지

# 엔진: VoxCPM2 (tokenizer-free, 한국어 지원, Apache-2.0). env 로 교체 가능.
VOXCPM_MODEL = os.environ.get("VOXCPM_MODEL", "openbmb/VoxCPM2")
DEFAULT_VOICE = "09_chaewon"
# 번들된 음성 라이브러리(참조 WAV + 전사). voice-design 은 비결정적이라
# 생성된 WAV 가 그 목소리의 유일한 원본 → prompt_wav_path 클로닝으로 청크 간 음색 고정.
VOICES_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "voices"))


def _voice_key():
    # 호출 시점 env 를 읽음(테스트·런타임에서 VOXCPM_VOICE 로 전환).
    return os.environ.get("VOXCPM_VOICE", DEFAULT_VOICE)


def _load_voices():
    with open(os.path.join(VOICES_DIR, "voices.json"), encoding="utf-8") as f:
        return json.load(f)["voices"]


def resolve_voice(key=None):
    """VOXCPM_VOICE → (참조 wav 절대경로, 참조 전사). 미등록이면 ValueError."""
    key = key or _voice_key()
    voices = _load_voices()
    if key not in voices:
        raise ValueError(f"unknown VOXCPM_VOICE={key}; available={list(voices)}")
    v = voices[key]
    return os.path.join(VOICES_DIR, v["wav"]), v["ref_text"]


def model_revision():
    # artifact_version 캐시키 — 모델/화자 바뀌면 오디오 재생성되도록 둘 다 포함.
    return f"{VOXCPM_MODEL}@{_voice_key()}"


def load_model(device="cuda"):
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:                       # double-checked: 느린 from_pretrained 중 중복 로드 차단
            if _MODEL is None:
                from voxcpm import VoxCPM
                _MODEL = VoxCPM.from_pretrained(VOXCPM_MODEL, load_denoiser=False)
    return _MODEL


def synth_chunk(text, out_wav, device="cuda", language_id="ko"):
    """청크 1개 → wav 파일. 모델 sr 반환. (VoxCPM2, 선택 음성을 참조-WAV 클로닝으로 고정)"""
    import soundfile as sf
    m = load_model(device)
    ref_wav, ref_text = resolve_voice()
    wav = m.generate(text=text, prompt_wav_path=ref_wav, prompt_text=ref_text,
                     cfg_value=2.0, inference_timesteps=10)
    sr = m.tts_model.sample_rate
    sf.write(out_wav, wav, sr)
    return sr
