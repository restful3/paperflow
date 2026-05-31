import subprocess, json, os, tempfile


# (prev_kind, next_kind) → 청크 뒤 무음(초). 대표값(스펙 §3 범위 중앙).
def pad_for(prev_kind, next_kind):
    if prev_kind == "heading":
        return 0.75              # 헤딩 뒤 긴 쉼 (0.6~0.9)
    if next_kind == "heading":
        return 0.40              # 섹션 경계 진입 (0.3~0.5)
    return 0.18                  # 문장 사이 (0.12~0.25)


def _probe_duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", path])
    return float(json.loads(out)["format"]["duration"])


def _norm_wav(src, dst, sr):
    """nit#3: 입력을 pcm_s16le/mono/sr로 통일 → concat demuxer 안정."""
    subprocess.check_call([
        "ffmpeg", "-y", "-i", src, "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", dst],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stitch_chunks(wav_files, chunks, out_mp3, sample_rate=24000):
    """wav_files[i] ↔ chunks[i]. 무음 패딩 포함 concat → mp3. timeline 반환."""
    assert len(wav_files) == len(chunks)
    timeline = []
    cursor = 0.0
    with tempfile.TemporaryDirectory() as tmpdir:    # nit#4: 자동 정리
        list_path = os.path.join(tmpdir, "concat.txt")
        with open(list_path, "w") as lf:
            for i, (wf, ch) in enumerate(zip(wav_files, chunks)):
                norm = os.path.join(tmpdir, f"n{i:06d}.wav")
                _norm_wav(wf, norm, sample_rate)     # 정규화 후 실측
                dur = _probe_duration(norm)
                start = cursor
                cursor += dur
                pad = pad_for(ch["kind"], chunks[i + 1]["kind"]) if i < len(chunks) - 1 else 0.0
                end = cursor + pad   # end_sec = 다음 청크 시작 전까지(표시 구간)
                cursor += pad
                timeline.append({**ch, "start_sec": round(start, 3), "end_sec": round(end, 3)})
                lf.write(f"file '{os.path.abspath(norm)}'\n")
                if pad > 0:
                    sp = os.path.join(tmpdir, f"sil{i}.wav")
                    subprocess.check_call([
                        "ffmpeg", "-y", "-f", "lavfi", "-i",
                        f"anullsrc=r={sample_rate}:cl=mono", "-t", f"{pad}", "-c:a", "pcm_s16le", sp],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    lf.write(f"file '{os.path.abspath(sp)}'\n")
        # concat → mp3 + loudness normalize (최종 stitched 기준)
        subprocess.check_call([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-q:a", "2", out_mp3],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    duration = _probe_duration(out_mp3)
    return timeline, round(duration, 3), sample_rate
