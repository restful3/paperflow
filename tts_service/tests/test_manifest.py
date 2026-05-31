from app.manifest import build_manifest, is_fresh, CACHE_KEY_FIELDS


def test_build_manifest_shape():
    chunks = [{"id": 0, "kind": "heading", "dom_id": "tts-s-000000", "section_id": "intro",
               "paragraph_index": 0, "sentence_index": 0, "text": "서론", "start_sec": 0.0, "end_sec": 1.1}]
    m = build_manifest(source_path="a_ko_audio.md", source_sha256="abc", source_mtime="t",
                       audio_file="a_ko_audio.mp3", duration_sec=1.1, sample_rate=24000, chunks=chunks)
    assert m["status"] == "complete"
    assert m["schema_version"] == 1
    assert m["source"]["sha256"] == "abc"
    assert m["audio"]["file"] == "a_ko_audio.mp3"
    assert m["tts"]["language_id"] == "ko"
    assert m["chunks"][0]["dom_id"] == "tts-s-000000"


def test_is_fresh_detects_source_change():
    m = build_manifest("a.md", "sha_OLD", "t", "a.mp3", 1.0, 24000, [])
    assert is_fresh(m, current_sha256="sha_OLD") is True
    assert is_fresh(m, current_sha256="sha_NEW") is False


def test_is_fresh_detects_cachekey_change():
    m = build_manifest("a.md", "sha", "t", "a.mp3", 1.0, 24000, [])
    assert is_fresh(m, current_sha256="sha", tts_overrides={"voice_id": "other"}) is False


# ---------------------------------------------------------------------------
# v2 tests
# ---------------------------------------------------------------------------
from app.manifest import (build_manifest_v2, is_fresh_for_playback, is_fresh_for_hls,
                          merge_chunk_timing)


def _chunk(i, gid=None):
    return {"id": i, "kind": "text", "dom_id": f"tts-s-{i:06d}", "section_id": "s",
            "paragraph_index": 0, "sentence_index": i,
            "sentence_group_id": gid if gid is not None else i, "sub_index": 0,
            "sub_count": 1, "display_sentence_index": i,
            "start_sec": None, "end_sec": None, "text": f"t{i}"}


def test_build_v2_streaming_shape():
    m = build_manifest_v2(source_path="a_ko_audio.md", source_sha256="abc123def456ff",
                          chunks=[_chunk(0), _chunk(1)], sample_rate=24000)
    assert m["schema_version"] == 2 and m["status"] == "streaming"
    assert m["audio"]["hls"]["playlist"] == "stream.m3u8"
    assert m["audio"]["mp3"]["file"] is None
    assert all(c["start_sec"] is None for c in m["chunks"])


def test_merge_chunk_timing_idempotent():
    m = build_manifest_v2("a.md", "sha", [_chunk(0), _chunk(1)], 24000)
    merge_chunk_timing(m, chunk_id=0, start_sec=0.0, end_sec=1.2)
    merge_chunk_timing(m, chunk_id=0, start_sec=0.0, end_sec=1.2)   # 중복 — 변화 없음
    merge_chunk_timing(m, chunk_id=1, start_sec=1.2, end_sec=2.5)
    assert m["chunks"][0]["start_sec"] == 0.0 and m["chunks"][1]["end_sec"] == 2.5
    assert len(m["chunks"]) == 2
    assert m["audio"]["duration_sec"] == 2.5


def test_fresh_split_v1_vs_v2():
    v1 = {"schema_version": 1, "status": "complete", "source": {"sha256": "s"},
          "tts": {}, "audio": {"file": "a.mp3"}}
    assert is_fresh_for_playback(v1, "s") is True        # v1 재생 인정
    assert is_fresh_for_hls(v1, "s") is False            # v1 은 HLS 미생성 → sweep 대상
    v2 = build_manifest_v2("a.md", "s", [_chunk(0)], 24000)
    v2["status"] = "complete"
    assert is_fresh_for_hls(v2, "s") is True


from app.manifest import compute_audio_version


def test_audio_version_deterministic_and_cachekey_sensitive():
    v = compute_audio_version("sha_abc")
    assert v == compute_audio_version("sha_abc")                 # deterministic
    assert len(v) == 12 and all(c in "0123456789abcdef" for c in v)
    assert compute_audio_version("sha_abc") != compute_audio_version("sha_def")          # source 다름
    assert compute_audio_version("sha_abc") != compute_audio_version("sha_abc", {"model_revision": "r2"})  # cache-key 다름


def test_build_v2_stores_audio_version():
    m = build_manifest_v2("a.md", "sha_xyz", [_chunk(0)], 24000)
    assert m["audio"]["version"] == compute_audio_version("sha_xyz")
