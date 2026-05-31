import subprocess, json, os

TARGETDURATION = 16        # Task 0 실측 결정 (docs/research/2026-05-31-hls-tts-measurement.md)


def _probe_duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                                   "format=duration", "-of", "json", path])
    return float(json.loads(out)["format"]["duration"])


def _probe_codec(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                   "-show_entries", "stream=codec_name", "-of", "json", path])
    s = json.loads(out).get("streams", [{}])
    return s[0].get("codec_name") if s else None


def encode_segment(wav_path, pad, out_ts, sample_rate=24000):
    """wav + 뒤 무음 pad → AAC MPEG-TS. temp→ffprobe(codec/len gate)→atomic rename. duration 반환."""
    d = os.path.dirname(out_ts)
    tmp = os.path.join(d, os.path.basename(out_ts) + f".tmp.{os.getpid()}")
    # 패딩: apad 로 뒤에 무음 덧붙임. 음량: 고정 리미터(Task 0 결정 — per-segment loudnorm 부적합).
    af = f"apad=pad_dur={pad}" if pad > 0 else "anull"
    af += ",alimiter=limit=0.95"
    subprocess.check_call(["ffmpeg", "-y", "-i", wav_path, "-af", af,
                           "-ar", str(sample_rate), "-ac", "1", "-c:a", "aac", "-b:a", "96k",
                           "-f", "mpegts", tmp],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if _probe_codec(tmp) != "aac":
            raise ValueError("segment not AAC")
        dur = _probe_duration(tmp)
        if dur <= 0:
            raise ValueError("zero duration")
        if round(dur) > TARGETDURATION:
            raise ValueError(f"segment exceeds TARGETDURATION({TARGETDURATION}): {dur:.2f}s")
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    os.replace(tmp, out_ts)            # atomic publish
    return round(dur, 3)


class LivePlaylist:
    """EVENT growing playlist. 세그먼트 URI 는 'seg/<name>'(playlist URL 기준 상대)."""

    def __init__(self, path):
        self.path = path
        self._entries = []             # (uri, dur)
        self._ended = False
        self._write()

    def append(self, seg_name, duration):
        self._entries.append((f"seg/{seg_name}", round(duration, 3)))
        self._write()

    def finalize(self):
        self._ended = True
        self._write()

    def _write(self):
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-PLAYLIST-TYPE:EVENT",
                 f"#EXT-X-TARGETDURATION:{TARGETDURATION}", "#EXT-X-MEDIA-SEQUENCE:0"]
        for uri, dur in self._entries:
            lines.append(f"#EXTINF:{dur},")
            lines.append(uri)
        if self._ended:
            lines.append("#EXT-X-ENDLIST")
        tmp = self.path + f".tmp.{os.getpid()}"
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, self.path)     # atomic rewrite
