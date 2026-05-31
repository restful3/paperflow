import wave, struct, math
from app.stitch import pad_for, stitch_chunks


def _make_wav(path, sec=0.5, sr=24000, freq=440):
    n = int(sec * sr)
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        for i in range(n):
            w.writeframes(struct.pack("<h", int(3000 * math.sin(2 * math.pi * freq * i / sr))))


def test_pad_for_rules():
    assert pad_for("text", "text") == 0.18      # 문장 사이 대표값
    assert pad_for("text", "heading") == 0.40    # 문단/섹션 경계
    assert pad_for("heading", "text") == 0.75     # 헤딩 뒤 긴 쉼


def test_stitch_produces_timeline(tmp_path):
    files = []
    for i in range(3):
        p = tmp_path / f"c{i}.wav"; _make_wav(str(p)); files.append(str(p))
    chunks = [{"id": i, "kind": "text", "text": f"s{i}"} for i in range(3)]
    out = tmp_path / "out.mp3"
    timeline, duration, sr = stitch_chunks(files, chunks, str(out), sample_rate=24000)
    assert out.exists() and duration > 1.4        # 3*0.5 + 2*패딩
    assert timeline[0]["start_sec"] == 0.0
    assert timeline[1]["start_sec"] > timeline[0]["end_sec"] - 1e-6
    assert abs(timeline[-1]["end_sec"] - duration) < 0.05
