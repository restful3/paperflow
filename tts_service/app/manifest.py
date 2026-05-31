import hashlib
from datetime import datetime, timezone

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


# ---------------------------------------------------------------------------
# v2 — 2-layer audio schema (hls + mp3), streaming status, id-keyed timing
# ---------------------------------------------------------------------------

SCHEMA_VERSION_V2 = 2


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _cachekey_match(manifest, tts_overrides=None):
    want = dict(DEFAULT_TTS)
    if tts_overrides:
        want.update(tts_overrides)
    have = manifest.get("tts", {})
    return all(have.get(k) == want.get(k) for k in CACHE_KEY_FIELDS)


def compute_audio_version(source_sha256, tts_overrides=None):
    """아티팩트 버전 = source sha + freshness cache-key 필드들의 digest[:12].

    Codex Finding 2: HLS dir/mp3/token 을 source sha 만으로 키잉하면 model/cache-key 변경 후
    재생성이 같은 immutable 경로를 덮어쓴다. cache-key 까지 묶으면 '재생성=새 dir' 이 되어
    구버전 세그먼트/토큰이 그대로 유효하게 남는다. is_fresh_for_playback 과 동일 입력이라
    'fresh ⟺ 같은 version' 이 성립한다."""
    tts = dict(DEFAULT_TTS)
    if tts_overrides:
        tts.update(tts_overrides)
    key = source_sha256 + "|" + "|".join(f"{k}={tts.get(k)}" for k in CACHE_KEY_FIELDS)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def build_manifest_v2(source_path, source_sha256, chunks, sample_rate,
                      source_mtime=None, tts_overrides=None):
    tts = dict(DEFAULT_TTS)
    if tts_overrides:
        tts.update(tts_overrides)
    return {
        "schema_version": SCHEMA_VERSION_V2,
        "status": "streaming",
        "generated_at": None,
        "heartbeat": None,
        "source": {"path": source_path, "sha256": source_sha256, "mtime": source_mtime},
        "tts": tts,
        "audio": {
            "version": compute_audio_version(source_sha256, tts_overrides),  # 아티팩트 버전(dir/mp3/token)
            "hls": {"playlist": "stream.m3u8",
                    "mime_type": "application/vnd.apple.mpegurl",
                    "segment_mime_type": "video/mp2t"},
            "mp3": {"file": None, "mime_type": "audio/mpeg"},
            "duration_sec": 0.0,
            "sample_rate": sample_rate,
        },
        "chunks": chunks,
    }


def merge_chunk_timing(manifest, chunk_id, start_sec, end_sec):
    for c in manifest["chunks"]:
        if c["id"] == chunk_id:
            c["start_sec"], c["end_sec"] = round(start_sec, 3), round(end_sec, 3)
            break
    ends = [c["end_sec"] for c in manifest["chunks"] if c["end_sec"] is not None]
    manifest["audio"]["duration_sec"] = round(max(ends), 3) if ends else 0.0


def is_fresh_for_playback(manifest, current_sha256, tts_overrides=None):
    if manifest.get("status") != "complete":
        return False
    if manifest.get("source", {}).get("sha256") != current_sha256:
        return False
    # v1 (schema_version < 2): legacy single-mp3 manifests accepted without cachekey check
    if manifest.get("schema_version", 1) < 2:
        return True
    return _cachekey_match(manifest, tts_overrides)


def is_fresh_for_hls(manifest, current_sha256, tts_overrides=None):
    if manifest.get("schema_version", 1) < 2:
        return False
    if not manifest.get("audio", {}).get("hls"):
        return False
    return is_fresh_for_playback(manifest, current_sha256, tts_overrides)
