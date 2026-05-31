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
