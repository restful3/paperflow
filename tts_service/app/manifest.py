from app.chunker import CHUNKER_VERSION

SCHEMA_VERSION = 1
CACHE_KEY_FIELDS = ("model", "model_revision", "language_id", "voice_id", "chunker_version", "audio_format")

DEFAULT_TTS = {
    "model": "Chatterbox-Multilingual",
    "model_revision": "unknown",
    "language_id": "ko",
    "voice_id": "default",
    "chunker_version": CHUNKER_VERSION,
    "audio_format": "mp3",
}


def build_manifest(source_path, source_sha256, source_mtime, audio_file,
                   duration_sec, sample_rate, chunks, tts_overrides=None, generated_at=None):
    tts = dict(DEFAULT_TTS)
    if tts_overrides:
        tts.update(tts_overrides)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "generated_at": generated_at,          # nit#2: 호출자가 ISO8601 주입(스펙 완료마커 필드)
        "source": {"path": source_path, "sha256": source_sha256, "mtime": source_mtime},
        "tts": tts,
        "audio": {"file": audio_file, "mime_type": "audio/mpeg",
                  "duration_sec": duration_sec, "sample_rate": sample_rate},
        "chunks": chunks,
    }


def is_fresh(manifest, current_sha256, tts_overrides=None):
    if manifest.get("status") != "complete":
        return False
    if manifest.get("source", {}).get("sha256") != current_sha256:
        return False
    want = dict(DEFAULT_TTS)
    if tts_overrides:
        want.update(tts_overrides)
    have = manifest.get("tts", {})
    return all(have.get(k) == want.get(k) for k in CACHE_KEY_FIELDS)
