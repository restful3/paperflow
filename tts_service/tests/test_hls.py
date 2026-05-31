import wave, struct, math, os
from app.hls import encode_segment, LivePlaylist, TARGETDURATION


def _wav(path, sec=0.5, sr=24000, freq=440):
    n = int(sec * sr)
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        for i in range(n):
            w.writeframes(struct.pack("<h", int(3000 * math.sin(2 * math.pi * freq * i / sr))))


def test_encode_segment_atomic_and_probed(tmp_path):
    wav = str(tmp_path / "c.wav"); _wav(wav)
    out = str(tmp_path / "seg_000000.ts")
    dur = encode_segment(wav, pad=0.18, out_ts=out, sample_rate=24000)
    assert os.path.exists(out)
    assert not any(p.endswith(".tmp") or ".tmp." in p for p in os.listdir(tmp_path))  # temp 정리
    assert dur > 0.5                                 # 0.5s 음성 + 0.18 패딩


def test_encode_segment_length_gate(tmp_path):
    wav = str(tmp_path / "c.wav"); _wav(wav, sec=TARGETDURATION + 2)   # TARGETDURATION 초과
    out = str(tmp_path / "seg_000000.ts")
    try:
        encode_segment(wav, pad=0.0, out_ts=out, sample_rate=24000)
        assert False, "should raise on over-length"
    except ValueError as e:
        assert "TARGETDURATION" in str(e)
    assert not os.path.exists(out)                   # publish 안 됨


def test_live_playlist_append_and_endlist(tmp_path):
    pl = LivePlaylist(str(tmp_path / "stream.m3u8"))
    pl.append("seg_000000.ts", 3.21)
    pl.append("seg_000001.ts", 2.88)
    body = open(tmp_path / "stream.m3u8").read()
    assert "#EXT-X-PLAYLIST-TYPE:EVENT" in body
    assert f"#EXT-X-TARGETDURATION:{TARGETDURATION}" in body
    assert "seg/seg_000000.ts" in body and "#EXTINF:3.21" in body
    assert "#EXT-X-ENDLIST" not in body
    pl.finalize()
    assert "#EXT-X-ENDLIST" in open(tmp_path / "stream.m3u8").read()
