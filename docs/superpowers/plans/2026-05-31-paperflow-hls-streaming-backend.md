# PaperFlow HLS 실시간 TTS — 백엔드 구현 플랜 (Plan 1/2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 문장별 합성과 동시에 AAC MPEG-TS 세그먼트를 라이브 HLS 플레이리스트로 증분 publish 하고, HMAC signed token 으로 인증해 뷰어 API 로 서빙한다(프론트는 Plan 2).

**Architecture:** tts 사이드카가 segmentation 직후 전체 chunks(텍스트/DOM)를 매니페스트에 publish 하고, 합성 루프가 문장→세그먼트를 원자적으로 만들어 `stream.m3u8` 에 append + chunk timing 을 id-keyed 갱신한다. 완료 시 ENDLIST + 다운로드 mp3. viewer 는 signed playlist URL 을 발급하고 토큰 검증 후 playlist/segment 를 서빙한다. 유휴 sweep(기본 OFF)가 미생성 논문을 캡 내에서 사전 생성한다.

**Tech Stack:** Python 3.12, FastAPI, ffmpeg/ffprobe(AAC TS), hmac/hashlib, pytest.

**선행 스펙:** [docs/superpowers/specs/2026-05-31-paperflow-hls-streaming-design.md](../specs/2026-05-31-paperflow-hls-streaming-design.md) (Codex R2 승인, BLOCKING 0)

**선행 MVP 코드(재사용):** `tts_service/app/{chunker,manifest,stitch,synth,gpulock,job,main}.py`, `viewer/app/{services/audio.py,routers/api.py,config.py}`.

---

## File Structure

```text
tts_service/app/
├── segtoken.py        # 신규: HMAC playlist/segment token mint·verify (§7)
├── hls.py             # 신규: encode_segment(원자/ffprobe/길이게이트) + LivePlaylist
├── chunker.py         # 수정: 문장 길이 hard cap → sub-split(sentence_group_id 등)
├── manifest.py        # 수정: schema v2(2층, audio.hls/mp3), is_fresh_for_*, id-keyed merge
├── job.py             # 수정: segmentation 선-publish, 증분 publish, heartbeat, file lock, TTL 정리, 종료 mp3
├── sweep.py           # 신규: 유휴 사전생성(기본 OFF, 캡)
└── main.py            # 수정: sweep 조건부 기동 + 설정
tts_service/tests/
├── test_segtoken.py   # 신규
├── test_hls.py        # 신규
├── test_chunker.py    # 수정(sub-split)
├── test_manifest.py   # 수정(v2)
└── test_sweep.py      # 신규

viewer/app/
├── config.py          # 수정: AUDIO_TOKEN_SECRET, AUDIO_PTOKEN_TTL, AUDIO_TOKEN_TTL, RESUME_GRACE
├── services/audio.py  # 수정: v1/v2 경로, hls playlist/seg, token mint/verify, 전체 span 렌더
└── routers/api.py     # 수정: /audio/stream-url, /audio/stream.m3u8, /audio/seg/{seg}, /audio/html 409 제거, 로그 redaction
viewer/tests/test_audio_api.py  # 수정
docker-compose.yml     # 수정: AUDIO_TOKEN_SECRET, SWEEP_* env
```

---

## Task 0: 선행 실측 — TARGETDURATION · 문장 hard cap · 음량 (스펙 §12.0, BLOCKING)

**Files:** Create: `docs/research/2026-05-31-hls-tts-measurement.md` (결정 기록)

코드 아님 — 측정·결정. 이후 Task 2/3 의 상수(`SENTENCE_CHAR_CAP`, `TARGETDURATION`, 음량 필터)를 여기 결과로 고정한다.

- [ ] **Step 1: 합성 duration 분포 측정**

기존 검증 venv 재사용. **대표 표본**(long-tail 포함): 디스크의 `_ko_audio.md` **전부**(또는 최소 10개 + 가장 긴 논문 포함)에서 **모든 text 문장**을 합성해 duration 분포를 구한다. P100(최장 문장) 이 TARGETDURATION 을 좌우하므로 표본을 줄이지 않는다.

```bash
cd /media/restful3/data/workspace/paperflow/tts_service
PLAYWRIGHT_BROWSERS_PATH= /tmp/cbx-venv/bin/python - <<'PY'
import glob, statistics, os, subprocess, json, tempfile
from app.chunker import chunk_markdown
from app.synth import synth_chunk
durs=[]
files = sorted(glob.glob("/media/restful3/data/workspace/paperflow/outputs/*/*_ko_audio.md"),
               key=lambda f: os.path.getsize(f), reverse=True)   # 큰 논문(long-tail) 우선 포함
for f in files:                                  # 전체 표본(시간 들면 상위 N + 최장 1개 보장)
    md=open(f,encoding="utf-8").read()
    for ch in chunk_markdown(md):
        if ch["kind"]!="text": continue
        wf=tempfile.mktemp(suffix=".wav"); synth_chunk(ch["text"], wf)
        out=subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","json",wf])
        d=float(json.loads(out)["format"]["duration"]); durs.append((len(ch["text"]),d)); os.remove(wf)
ds=[d for _,d in durs]
print("n",len(ds),"P50",round(statistics.median(ds),2),"P95",round(sorted(ds)[int(len(ds)*0.95)],2),
      "P99",round(sorted(ds)[int(len(ds)*0.99)],2),"P100",round(max(ds),2))
print("max sec/char(=worst char->dur):", round(max(d/max(c,1) for c,d in durs),3))
PY
```
Expected: P50/P95/P99/P100 + worst sec/char 출력. **TARGETDURATION = ceil(P100 × 1.3)**, **SENTENCE_CHAR_CAP = floor(TARGETDURATION / worst_sec_per_char × 0.9)**(안전계수). chunker cap 이 TARGETDURATION 안에 들도록 보수적으로.

- [ ] **Step 2: 결정 기록**

`docs/research/2026-05-31-hls-tts-measurement.md` 에 다음을 기록:
- 측정 분포(P50/P95/P100, 문자수↔duration)
- **`TARGETDURATION`** = ceil(P100 × 안전계수) 정수 (예: P100 12s → 16). 이 값이 Task 3 `LivePlaylist` 와 Task 2 hard cap 의 근거.
- **`SENTENCE_CHAR_CAP`** = TARGETDURATION 안에 드는 최대 문자수(측정 sec/char 상한 기반). Task 2 에서 사용.
- **음량**: 스트리밍 세그먼트 fixed gain+limiter 파라미터(예: `-af "alimiter=limit=0.95,volume=2dB"` 또는 측정 기반). mp3 는 현행 `loudnorm=I=-16:TP=-1.5:LRA=11` 유지.

- [ ] **Step 3: Commit**

```bash
git add docs/research/2026-05-31-hls-tts-measurement.md
git commit -m "docs(hls): measure synth duration distribution → TARGETDURATION/char cap/loudness"
```

> 이후 태스크의 `TARGETDURATION`(hls.py)/`SENTENCE_CHAR_CAP`(chunker.py)/음량 필터는 **Task 0 결정값**으로 치환한다. 아래 코드의 `16`/`220`/필터는 플레이스홀더 기본값.
> **치환 가드(HIGH#9):** Task 2/3 커밋 전 `grep -nE "SENTENCE_CHAR_CAP = 220|TARGETDURATION = 16" tts_service/app/{chunker,hls}.py` 가 **빈 결과**여야 한다(기본값 잔존 시 커밋 금지). Task 0 측정 후 실제 값으로 바뀐 것을 확인.

---

## Task 1: segtoken.py — HMAC playlist/segment 토큰

**Files:**
- Create: `tts_service/app/segtoken.py`
- Test: `tts_service/tests/test_segtoken.py`

playlist/segment 2종 토큰. payload `kind|source_id|sha12|exp`, HMAC-SHA256 서명, base64url. verify 는 exp·서명·kind·sha 일치 확인.

- [ ] **Step 1: Write the failing test**

```python
# tts_service/tests/test_segtoken.py
import time
from app.segtoken import mint, verify

SECRET = "x" * 48

def test_roundtrip_playlist_and_segment():
    t = mint(SECRET, kind="playlist", source_id="p.pdf", sha12="abc123def456", ttl=60)
    ok, reason = verify(SECRET, t, kind="playlist", source_id="p.pdf", sha12="abc123def456", now=time.time())
    assert ok, reason
    ts = mint(SECRET, kind="segment", source_id="p.pdf", sha12="abc123def456", ttl=60)
    ok2, _ = verify(SECRET, ts, kind="segment", source_id="p.pdf", sha12="abc123def456", now=time.time())
    assert ok2

def test_expired_rejected():
    t = mint(SECRET, kind="segment", source_id="p", sha12="s", ttl=10)
    ok, reason = verify(SECRET, t, kind="segment", source_id="p", sha12="s", now=time.time() + 11)
    assert not ok and reason == "expired"

def test_wrong_kind_or_sha_rejected():
    t = mint(SECRET, kind="playlist", source_id="p", sha12="s1", ttl=60)
    assert not verify(SECRET, t, kind="segment", source_id="p", sha12="s1", now=time.time())[0]
    assert not verify(SECRET, t, kind="playlist", source_id="p", sha12="s2", now=time.time())[0]

def test_tamper_rejected():
    t = mint(SECRET, kind="segment", source_id="p", sha12="s", ttl=60)
    bad = t[:-2] + ("aa" if not t.endswith("aa") else "bb")
    assert not verify(SECRET, bad, kind="segment", source_id="p", sha12="s", now=time.time())[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tts_service && python -m pytest tests/test_segtoken.py -v`
Expected: FAIL (`ModuleNotFoundError: app.segtoken`)

- [ ] **Step 3: Write minimal implementation**

```python
# tts_service/app/segtoken.py
import hmac, hashlib, base64, time

def _sig(secret, kind, source_id, sha12, exp):
    msg = f"{kind}|{source_id}|{sha12}|{exp}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).digest()

def mint(secret, kind, source_id, sha12, ttl):
    exp = int(time.time()) + int(ttl)
    raw = str(exp).encode() + b"." + _sig(secret, kind, source_id, sha12, exp)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def verify(secret, token, kind, source_id, sha12, now):
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad)
        exp_b, sig = raw.split(b".", 1)
        exp = int(exp_b)
    except Exception:
        return False, "malformed"
    if now > exp:
        return False, "expired"
    want = _sig(secret, kind, source_id, sha12, exp)
    if not hmac.compare_digest(sig, want):
        return False, "bad_sig"
    return True, "ok"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tts_service && python -m pytest tests/test_segtoken.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tts_service/app/segtoken.py tts_service/tests/test_segtoken.py
git commit -m "feat(hls): HMAC playlist/segment signed tokens"
```

---

## Task 2: chunker — 문장 길이 hard cap + sub-split (sentence_group_id)

**Files:**
- Modify: `tts_service/app/chunker.py`
- Modify: `tts_service/tests/test_chunker.py`

긴 문장은 `SENTENCE_CHAR_CAP`(Task 0) 초과 시 구두점/길이 기준 sub-sentence 로 쪼갠다. 각 sub-chunk 는 `sentence_group_id`(같은 UI 문장 공유), `sub_index`/`sub_count`, `display_sentence_index` 를 갖는다. 짧은 문장은 `sub_count=1`.

- [ ] **Step 1: Write the failing test (append)**

```python
# tts_service/tests/test_chunker.py 에 추가
from app.chunker import chunk_markdown, SENTENCE_CHAR_CAP

def test_short_sentence_single_subchunk():
    chunks = chunk_markdown("짧은 문장입니다.")
    assert chunks[0]["sub_count"] == 1
    assert chunks[0]["sub_index"] == 0
    assert chunks[0]["sentence_group_id"] == chunks[0]["display_sentence_index"]

def test_long_sentence_subsplit_shares_group():
    long = "가" * (SENTENCE_CHAR_CAP * 2) + "."     # cap 2배 → 최소 2 sub-chunk
    chunks = [c for c in chunk_markdown(long) if c["kind"] == "text"]
    assert len(chunks) >= 2
    gids = {c["sentence_group_id"] for c in chunks}
    assert len(gids) == 1                            # 같은 UI 문장 그룹
    assert [c["sub_index"] for c in chunks] == list(range(len(chunks)))
    assert all(c["sub_count"] == len(chunks) for c in chunks)
    assert all(len(c["text"]) <= SENTENCE_CHAR_CAP for c in chunks)
```

- [ ] **Step 2: Run to verify fail**

Run: `cd tts_service && python -m pytest tests/test_chunker.py::test_long_sentence_subsplit_shares_group -v`
Expected: FAIL (`ImportError: SENTENCE_CHAR_CAP` 또는 KeyError)

- [ ] **Step 3: Implement (chunker.py 수정)**

`chunker.py` 상단에 상수 추가, 문장 emit 부를 sub-split 로 교체:

```python
SENTENCE_CHAR_CAP = 220   # Task 0 결정값으로 교체

def _subsplit(sent):
    """SENTENCE_CHAR_CAP 초과 문장을 구두점/공백 경계로 분할(없으면 강제 슬라이스)."""
    if len(sent) <= SENTENCE_CHAR_CAP:
        return [sent]
    parts, buf = [], ""
    for tok in re.split(r"(?<=[,;:、，])\s+|\s+", sent):
        cand = (buf + " " + tok).strip() if buf else tok
        if len(cand) <= SENTENCE_CHAR_CAP:
            buf = cand
        else:
            if buf:
                parts.append(buf)
            while len(tok) > SENTENCE_CHAR_CAP:        # 단일 토큰도 초과면 강제 슬라이스
                parts.append(tok[:SENTENCE_CHAR_CAP]); tok = tok[SENTENCE_CHAR_CAP:]
            buf = tok
    if buf:
        parts.append(buf)
    return parts
```

`chunk_markdown` 의 문장 루프(기존 `for s_i, sent in enumerate(_split_sentences(block))`)를 교체:

```python
        group = 0
        for s_i, sent in enumerate(_split_sentences(block)):
            subs = _subsplit(sent)
            for j, sub in enumerate(subs):
                chunks.append({
                    "id": n, "kind": "text", "dom_id": f"tts-s-{n:06d}",
                    "section_id": section_id, "paragraph_index": para_idx,
                    "sentence_index": s_i,
                    "sentence_group_id": group_seq, "sub_index": j, "sub_count": len(subs),
                    "display_sentence_index": group_seq,
                    "start_sec": None, "end_sec": None, "text": sub,
                })
                n += 1
            group_seq += 1
```

여기서 `group_seq` 는 `chunk_markdown` 시작에서 `group_seq = 0` 으로 초기화하고 heading emit 후에도 증가시키지 않는다(heading 은 그룹에서 제외, `sub_count=1`·자체 group). heading emit 부에도 `"sentence_group_id": group_seq, "sub_index":0, "sub_count":1, "display_sentence_index": group_seq, "start_sec":None,"end_sec":None` 추가 후 `group_seq += 1`.

- [ ] **Step 4: Run all chunker tests**

Run: `cd tts_service && python -m pytest tests/test_chunker.py -v`
Expected: PASS (기존 + 신규 모두). 기존 테스트가 새 키를 요구하지 않으므로 통과. dom_id/id 연속성 유지 확인.

- [ ] **Step 5: Commit**

```bash
git add tts_service/app/chunker.py tts_service/tests/test_chunker.py
git commit -m "feat(hls): sentence length cap + sub-split with sentence_group_id"
```

---

## Task 3: hls.py — 세그먼트 인코딩(원자) + 라이브 플레이리스트

**Files:**
- Create: `tts_service/app/hls.py`
- Test: `tts_service/tests/test_hls.py`

`encode_segment`: wav+패딩 → temp AAC TS → ffprobe(codec/duration/길이게이트) → atomic rename. `LivePlaylist`: append(원자 재작성)/ENDLIST. 세그먼트 URI 는 `seg/seg_NNNNNN.ts`(상대).

- [ ] **Step 1: Write the failing test**

```python
# tts_service/tests/test_hls.py
import wave, struct, math, os
from app.hls import encode_segment, LivePlaylist, TARGETDURATION

def _wav(path, sec=0.5, sr=24000, freq=440):
    n=int(sec*sr)
    with wave.open(path,"w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        for i in range(n): w.writeframes(struct.pack("<h", int(3000*math.sin(2*math.pi*freq*i/sr))))

def test_encode_segment_atomic_and_probed(tmp_path):
    wav=str(tmp_path/"c.wav"); _wav(wav)
    out=str(tmp_path/"seg_000000.ts")
    dur = encode_segment(wav, pad=0.18, out_ts=out, sample_rate=24000)
    assert os.path.exists(out)
    assert not any(p.endswith(".tmp") or ".tmp." in p for p in os.listdir(tmp_path))  # temp 정리
    assert dur > 0.5                                 # 0.5s 음성 + 0.18 패딩

def test_encode_segment_length_gate(tmp_path):
    wav=str(tmp_path/"c.wav"); _wav(wav, sec=TARGETDURATION + 2)   # TARGETDURATION 초과
    out=str(tmp_path/"seg_000000.ts")
    try:
        encode_segment(wav, pad=0.0, out_ts=out, sample_rate=24000)
        assert False, "should raise on over-length"
    except ValueError as e:
        assert "TARGETDURATION" in str(e)
    assert not os.path.exists(out)                   # publish 안 됨

def test_live_playlist_append_and_endlist(tmp_path):
    pl=LivePlaylist(str(tmp_path/"stream.m3u8"))
    pl.append("seg_000000.ts", 3.21)
    pl.append("seg_000001.ts", 2.88)
    body=open(tmp_path/"stream.m3u8").read()
    assert "#EXT-X-PLAYLIST-TYPE:EVENT" in body
    assert f"#EXT-X-TARGETDURATION:{TARGETDURATION}" in body
    assert "seg/seg_000000.ts" in body and "#EXTINF:3.21" in body
    assert "#EXT-X-ENDLIST" not in body
    pl.finalize()
    assert "#EXT-X-ENDLIST" in open(tmp_path/"stream.m3u8").read()
```

- [ ] **Step 2: Run to verify fail**

Run: `cd tts_service && python -m pytest tests/test_hls.py -v`
Expected: FAIL (`ModuleNotFoundError: app.hls`)

- [ ] **Step 3: Implement**

```python
# tts_service/app/hls.py
import subprocess, json, os, tempfile

TARGETDURATION = 16        # Task 0 결정값으로 교체
_SEG_PAD_FILTER = None     # 패딩은 wav 결합 방식(아래) — 필터 미사용

def _probe_duration(path):
    out = subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","json", path])
    return float(json.loads(out)["format"]["duration"])

def _probe_codec(path):
    out = subprocess.check_output(["ffprobe","-v","error","-select_streams","a:0",
        "-show_entries","stream=codec_name","-of","json", path])
    s = json.loads(out).get("streams", [{}])
    return s[0].get("codec_name") if s else None

def encode_segment(wav_path, pad, out_ts, sample_rate=24000):
    """wav + 뒤 무음 pad → AAC MPEG-TS. temp→ffprobe(codec/len gate)→atomic rename. duration 반환."""
    d = os.path.dirname(out_ts)
    tmp = os.path.join(d, os.path.basename(out_ts) + f".tmp.{os.getpid()}")
    # 패딩 결합: anullsrc 무음을 concat 대신 apad 로 뒤에 덧붙임(필터). 음량: fixed gain+limiter(Task 0).
    af = f"apad=pad_dur={pad}" if pad > 0 else "anull"
    af += ",alimiter=limit=0.95"      # Task 0 음량 정책으로 교체
    subprocess.check_call(["ffmpeg","-y","-i",wav_path,"-af",af,
        "-ar",str(sample_rate),"-ac","1","-c:a","aac","-b:a","96k","-f","mpegts", tmp],
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
        if os.path.exists(tmp): os.remove(tmp)
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
        lines = ["#EXTM3U","#EXT-X-VERSION:3","#EXT-X-PLAYLIST-TYPE:EVENT",
                 f"#EXT-X-TARGETDURATION:{TARGETDURATION}","#EXT-X-MEDIA-SEQUENCE:0"]
        for uri, dur in self._entries:
            lines.append(f"#EXTINF:{dur},"); lines.append(uri)
        if self._ended:
            lines.append("#EXT-X-ENDLIST")
        tmp = self.path + f".tmp.{os.getpid()}"
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, self.path)     # atomic rewrite
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tts_service && python -m pytest tests/test_hls.py -v`
Expected: PASS (3 passed). ffmpeg/ffprobe 필요(로컬 설치됨).

- [ ] **Step 5: Commit**

```bash
git add tts_service/app/hls.py tts_service/tests/test_hls.py
git commit -m "feat(hls): atomic AAC-TS segment encoder + live EVENT playlist"
```

---

## Task 4: manifest.py v2 — 2층 스키마 + is_fresh_for_* + id-keyed merge

**Files:**
- Modify: `tts_service/app/manifest.py`
- Modify: `tts_service/tests/test_manifest.py`

schema_version 2, `audio.hls`/`audio.mp3` 구조, `status` streaming/complete/failed_partial/failed, `is_fresh_for_playback`(v1 인정) / `is_fresh_for_hls`(v2+hls 필요), `merge_chunk_timing`(id-keyed).

- [ ] **Step 1: Write the failing test (append/replace)**

```python
# tts_service/tests/test_manifest.py 에 추가
from app.manifest import (build_manifest_v2, is_fresh_for_playback, is_fresh_for_hls,
                          merge_chunk_timing)

def _chunk(i, gid=None):
    return {"id":i,"kind":"text","dom_id":f"tts-s-{i:06d}","section_id":"s","paragraph_index":0,
            "sentence_index":i,"sentence_group_id":gid if gid is not None else i,"sub_index":0,
            "sub_count":1,"display_sentence_index":i,"start_sec":None,"end_sec":None,"text":f"t{i}"}

def test_build_v2_streaming_shape():
    m = build_manifest_v2(source_path="a_ko_audio.md", source_sha256="abc123def456ff",
                          chunks=[_chunk(0),_chunk(1)], sample_rate=24000)
    assert m["schema_version"] == 2 and m["status"] == "streaming"
    assert m["audio"]["hls"]["playlist"] == "stream.m3u8"
    assert m["audio"]["mp3"]["file"] is None
    assert all(c["start_sec"] is None for c in m["chunks"])

def test_merge_chunk_timing_idempotent():
    m = build_manifest_v2("a.md","sha", [_chunk(0),_chunk(1)], 24000)
    merge_chunk_timing(m, chunk_id=0, start_sec=0.0, end_sec=1.2)
    merge_chunk_timing(m, chunk_id=0, start_sec=0.0, end_sec=1.2)   # 중복 — 변화 없음
    merge_chunk_timing(m, chunk_id=1, start_sec=1.2, end_sec=2.5)
    assert m["chunks"][0]["start_sec"] == 0.0 and m["chunks"][1]["end_sec"] == 2.5
    assert len(m["chunks"]) == 2
    assert m["audio"]["duration_sec"] == 2.5

def test_fresh_split_v1_vs_v2():
    v1 = {"schema_version":1,"status":"complete","source":{"sha256":"s"},
          "tts":{}, "audio":{"file":"a.mp3"}}
    assert is_fresh_for_playback(v1, "s") is True        # v1 재생 인정
    assert is_fresh_for_hls(v1, "s") is False            # v1 은 HLS 미생성 → sweep 대상
    v2 = build_manifest_v2("a.md","s",[_chunk(0)],24000); v2["status"]="complete"
    assert is_fresh_for_hls(v2, "s") is True
```

- [ ] **Step 2: Run to verify fail**

Run: `cd tts_service && python -m pytest tests/test_manifest.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement (manifest.py 에 추가; 기존 v1 함수는 유지)**

```python
# tts_service/app/manifest.py 에 추가
from datetime import datetime, timezone

SCHEMA_VERSION_V2 = 2

def build_manifest_v2(source_path, source_sha256, chunks, sample_rate,
                      source_mtime=None, tts_overrides=None):
    tts = dict(DEFAULT_TTS)
    if tts_overrides: tts.update(tts_overrides)
    return {
        "schema_version": SCHEMA_VERSION_V2,
        "status": "streaming",
        "generated_at": None,
        "heartbeat": None,
        "source": {"path": source_path, "sha256": source_sha256, "mtime": source_mtime},
        "tts": tts,
        "audio": {
            "hls": {"playlist": "stream.m3u8",
                    "mime_type": "application/vnd.apple.mpegurl",
                    "segment_mime_type": "video/mp2t"},
            "mp3": {"file": None, "mime_type": "audio/mpeg"},
            "duration_sec": 0.0, "sample_rate": sample_rate,
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

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def is_fresh_for_playback(manifest, current_sha256, tts_overrides=None):
    if manifest.get("status") != "complete": return False
    if manifest.get("source", {}).get("sha256") != current_sha256: return False
    # HIGH#3: v1(schema<2) 은 legacy 라 cachekey 스킵(과거 tts 필드 부재 매니페스트 인정).
    if manifest.get("schema_version", 1) < 2:
        return True
    return _cachekey_match(manifest, tts_overrides)

def is_fresh_for_hls(manifest, current_sha256, tts_overrides=None):
    if manifest.get("schema_version", 1) < 2: return False
    if not manifest.get("audio", {}).get("hls"): return False
    return is_fresh_for_playback(manifest, current_sha256, tts_overrides)
```

`_cachekey_match` 는 기존 `is_fresh` 의 cachekey 비교 부분을 헬퍼로 추출(없으면 인라인):

```python
def _cachekey_match(manifest, tts_overrides=None):
    want = dict(DEFAULT_TTS)
    if tts_overrides: want.update(tts_overrides)
    have = manifest.get("tts", {})
    return all(have.get(k) == want.get(k) for k in CACHE_KEY_FIELDS)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tts_service && python -m pytest tests/test_manifest.py -v`
Expected: PASS (기존 v1 테스트 + 신규 v2)

- [ ] **Step 5: Commit**

```bash
git add tts_service/app/manifest.py tts_service/tests/test_manifest.py
git commit -m "feat(hls): manifest v2 (2-layer chunks, hls/mp3, fresh split, id-keyed merge)"
```

---

## Task 5: job.py — 증분 publish 오케스트레이션 + file lock + heartbeat + 종료 mp3

**Files:**
- Modify: `tts_service/app/job.py`

흐름: paper file lock → segmentation 후 전체 chunks publish(status=streaming) → GPU flock 안에서 문장별 synth→encode_segment→playlist.append→merge_chunk_timing(+heartbeat) → 전부 후 ENDLIST + stitch mp3(기존) + status=complete → 구버전 TTL 정리. 실패 시 §5.4.

- [ ] **Step 1: Implement (run_job 를 HLS 증분으로 재작성)**

```python
# tts_service/app/job.py — 핵심 변경(요지). 기존 import 에 추가:
from app.hls import encode_segment, LivePlaylist, TARGETDURATION
from app.stitch import pad_for, stitch_chunks
from app.manifest import build_manifest_v2, merge_chunk_timing, is_fresh_for_playback, _now_iso
import json, os, time, uuid, shutil, fcntl

def _paper_lock(adir, sha12):
    os.makedirs(os.path.join(adir, ".locks"), exist_ok=True)
    fh = open(os.path.join(adir, ".locks", f"{sha12}.lock"), "w")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)   # 실패 시 OSError → 호출자가 "이미 진행 중"
    return fh

def run_job(paper_dir, src_md, progress_cb=None, device="cuda"):
    base = _base(src_md); adir = _audio_dir(paper_dir); os.makedirs(adir, exist_ok=True)
    src_sha = _sha256(src_md); sha12 = src_sha[:12]
    man_path = os.path.join(adir, f"{base}_ko_audio.manifest.json")
    hls_dir = os.path.join(adir, f"{base}_ko_audio.{sha12}")
    seg_dir = hls_dir                                  # 세그먼트는 hls_dir 직하위(URL seg/ 는 라우팅)
    mp3_name = f"{base}_ko_audio.{sha12}.mp3"

    # freshness skip
    if os.path.exists(man_path):
        try:
            cur = json.load(open(man_path))
            if is_fresh_for_playback(cur, src_sha) and cur.get("audio",{}).get("hls"):
                if progress_cb: progress_cb(stage="ready", done=0, total=0)
                return cur
        except Exception: pass

    lock = _paper_lock(adir, sha12)                    # 같은 버전 동시 쓰기 차단
    try:
        md = open(src_md, encoding="utf-8").read()
        chunks = chunk_markdown(md)
        text_chunks = [c for c in chunks if c["kind"] == "text"]
        if not text_chunks: raise ValueError("no synthesizable chunks")

        os.makedirs(seg_dir, exist_ok=True)
        manifest = build_manifest_v2(os.path.basename(src_md), src_sha, chunks,
                                     sample_rate=24000, source_mtime=str(os.path.getmtime(src_md)),
                                     tts_overrides={"model_revision": model_revision()})
        _publish_manifest(man_path, manifest)          # 전체 chunks(텍스트) 즉시 publish
        playlist = LivePlaylist(os.path.join(hls_dir, "stream.m3u8"))

        seg_wavs = []          # mp3 stitch 용 (heading 포함, MVP 정합)
        cursor = 0.0
        total = len(chunks)    # heading+text 전부 세그먼트(MVP 가 heading 도 합성)
        with gpu_lock(GPU_LOCK_PATH):
            for i, ch in enumerate(chunks):
                wf = os.path.join(seg_dir, f".w{i:06d}.wav")
                pad = pad_for(ch["kind"], chunks[i+1]["kind"]) if i < len(chunks)-1 else 0.0
                seg_name = f"seg_{i:06d}.ts"
                dur = _synth_encode_with_retry(ch, wf, pad, os.path.join(seg_dir, seg_name), device)
                if dur is None:                          # 품질게이트/과길이 재시도 후에도 실패 → partial
                    return _fail_partial(playlist, man_path, manifest, f"chunk {i} failed (quality/over-length)")
                playlist.append(seg_name, dur)
                merge_chunk_timing(manifest, ch["id"], cursor, cursor + dur)
                cursor += dur
                manifest["heartbeat"] = _now_iso()
                _publish_manifest(man_path, manifest)
                seg_wavs.append(wf)
                if progress_cb: progress_cb(stage="synthesizing", done=len(seg_wavs), total=total)

        # 완료: ENDLIST + mp3 stitch (heading 포함 전체)
        playlist.finalize()
        if progress_cb: progress_cb(stage="stitching", done=total, total=total)
        mp3_tmp = os.path.join(seg_dir, ".out.mp3")
        stitch_chunks(seg_wavs, chunks, mp3_tmp, sample_rate=24000)
        os.replace(mp3_tmp, os.path.join(adir, mp3_name))
        manifest["audio"]["mp3"]["file"] = mp3_name
        manifest["status"] = "complete"; manifest["generated_at"] = _now_iso()
        _publish_manifest(man_path, manifest)
        for wf in seg_wavs:                             # 임시 wav 폐기
            try: os.remove(wf)
            except OSError: pass
        _cleanup_old_versions(adir, base, keep_sha12=sha12)
        if progress_cb: progress_cb(stage="ready", done=total, total=total)
        return manifest
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN); lock.close()

def _synth_encode_with_retry(ch, wf, pad, out_ts, device):
    """합성→품질게이트→encode(길이게이트). 실패 시 1회 재합성(TTS 분산) 후 재시도.
    반환: duration 또는 None(2회 실패).
    NOTE(BLOCKING#1): chunker(Task2)가 SENTENCE_CHAR_CAP 으로 이미 길이를 1차 제한하므로
    post-encode 과길이는 모델 이상치다. upfront-publish 모델(전체 chunks 고정 id)을 깨지 않기 위해
    '재분할'(동적 chunk 삽입) 대신 '재합성'으로 1회 재시도하고, 그래도 초과면 failed_partial.
    (synth_chunk/_chunk_ok/encode_segment 는 모듈 전역 — 테스트 monkeypatch 가능)"""
    for attempt in (1, 2):
        synth_chunk(ch["text"], wf, device=device)
        if not _chunk_ok(wf, ch["text"]):
            continue                                     # 품질게이트 실패 → 재합성
        try:
            return encode_segment(wf, pad, out_ts)       # 길이게이트 통과 시 duration
        except ValueError:
            continue                                     # 과길이 → 재합성(분산으로 짧아질 수 있음)
    return None

def _publish_manifest(path, manifest):
    tmp = path + ".tmp"
    json.dump(manifest, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, path)

def _fail_partial(playlist, man_path, manifest, reason):
    playlist.finalize()                                 # 앞부분 재생 가능
    manifest["status"] = "failed_partial"; manifest["generated_at"] = _now_iso()
    manifest["audio"]["mp3"]["file"] = None
    _publish_manifest(man_path, manifest)
    raise RuntimeError(f"partial: {reason}")

def _version_sha(name):
    """'<base>_ko_audio.<sha12>' 또는 '<base>_ko_audio.<sha12>.mp3' → sha12."""
    import re
    m = re.search(r"_ko_audio\.([0-9a-f]{12})(?:\.mp3)?$", name)
    return m.group(1) if m else None

def _cleanup_old_versions(adir, base, keep_sha12, keep=2):
    """HLS 디렉터리 + mp3 를 version(sha12) 단위로 묶어 최근 keep 버전 보존, 나머지 삭제.
    (active token TTL 보다 짧게 삭제 안 하려면 keep>=2 권장 — 직전 버전 grace.)"""
    import glob
    versions = {}   # sha12 -> (mtime, [paths])
    for p in glob.glob(os.path.join(adir, f"{base}_ko_audio.*")):
        sha = _version_sha(os.path.basename(p))
        if not sha:
            continue
        versions.setdefault(sha, [0.0, []])
        versions[sha][1].append(p)
        try: versions[sha][0] = max(versions[sha][0], os.path.getmtime(p))
        except OSError: pass
    ordered = sorted(versions.items(), key=lambda kv: kv[1][0], reverse=True)
    for idx, (sha, (_, paths)) in enumerate(ordered):
        if sha == keep_sha12 or idx < keep:
            continue
        for p in paths:                                  # 구버전 HLS dir + mp3 함께 정리
            if os.path.isdir(p): shutil.rmtree(p, ignore_errors=True)
            else:
                try: os.remove(p)
                except OSError: pass
```

> 주의: `_fail_partial` 는 `RuntimeError` 를 raise 하므로 `_worker`(main.py)가 잡아 status 를 덮지 않도록, main.py 의 `_worker` 는 manifest 가 이미 `failed_partial` 이면 `_jobs` stage 를 `failed_partial` 로 둔다(Task 7 에서 반영).
> **heading 정합(Codex 정합성 메모):** MVP `job.py` 는 heading 도 합성하므로 본 플랜도 **heading 포함 전체 chunk** 를 세그먼트화한다(`kind!="text" continue` 제거). heading chunk 도 `start_sec/end_sec` 가 채워지고 `/audio/html` 에서 `<hN>` 로 렌더된다.
> **과길이 처리(BLOCKING#1):** 스펙 §5.3 의 "재분할 1회 재시도" 를 upfront-publish 모델과 양립시키기 위해 **재합성(TTS 분산) 1회**로 구현한다. Task 0 cap 을 보수적으로 잡아 과길이를 사전 차단하는 것이 1차 방어이고, 재합성은 안전망이다.

- [ ] **Step 2: Write unit tests (GPU 불요 — synth/encode mock)**

```python
# tts_service/tests/test_job.py
import os
from app import job

def test_cleanup_keeps_recent_versions(tmp_path):
    adir = tmp_path; base = "P"
    for sha in ("aaaaaaaaaaaa","bbbbbbbbbbbb","cccccccccccc"):
        os.makedirs(adir/f"{base}_ko_audio.{sha}")
        (adir/f"{base}_ko_audio.{sha}.mp3").write_bytes(b"x")
    # keep_sha12=현재버전, keep=2 → 현재 + 최근1 보존, 가장 오래된 1 삭제(dir+mp3)
    os.utime(adir/"P_ko_audio.aaaaaaaaaaaa", (1,1))   # 가장 오래됨
    job._cleanup_old_versions(str(adir), base, keep_sha12="cccccccccccc", keep=2)
    assert (adir/"P_ko_audio.cccccccccccc").exists()
    assert not (adir/"P_ko_audio.aaaaaaaaaaaa").exists()
    assert not (adir/"P_ko_audio.aaaaaaaaaaaa.mp3").exists()   # mp3 도 함께 정리

def test_synth_encode_retry_then_fail(monkeypatch, tmp_path):
    calls = {"n": 0}
    monkeypatch.setattr(job, "synth_chunk", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(job, "_chunk_ok", lambda *a, **k: True)
    def always_over(*a, **k):
        calls["n"] += 1; raise ValueError("segment exceeds TARGETDURATION")
    monkeypatch.setattr(job, "encode_segment", always_over)
    out = job._synth_encode_with_retry({"text":"x"}, str(tmp_path/"w.wav"), 0.1, str(tmp_path/"s.ts"), "cpu")
    assert out is None and calls["n"] == 2          # 1회 재시도 후 None
```

Run: `cd tts_service && python -m pytest tests/test_job.py -v`
Expected: FAIL → 구현 후 PASS (2 passed). `_synth_encode_with_retry` 내부 `from app.synth import synth_chunk` 를 모듈 전역 `synth_chunk` 참조로 바꿔 monkeypatch 가능하게(이미 job.py 상단 import 있음 — 로컬 import 제거).

- [ ] **Step 3: Sanity import + 테스트 통과**

Run: `cd tts_service && /tmp/cbx-venv/bin/python -c "import app.job; print('job import OK')" && python -m pytest tests/test_job.py -v`
Expected: `job import OK` + PASS

- [ ] **Step 4: Commit**

```bash
git add tts_service/app/job.py tts_service/tests/test_job.py
git commit -m "feat(hls): incremental publish + heading-inclusive + over-length re-synth retry + version TTL cleanup"
```

---

## Task 6: sweep.py — 유휴 사전생성 (기본 OFF + 캡)

**Files:**
- Create: `tts_service/app/sweep.py`
- Test: `tts_service/tests/test_sweep.py`

`should_run(jobs, gpu_lock_path)`: 진행 중 job 없음 + GPU flock try_acquire 성공(즉시 해제)이면 True. `find_candidate(outputs_root)`: `_ko_audio.md` 있고 fresh HLS 없는 논문 1개. 루프는 main.py 에서 기동(기본 OFF).

- [ ] **Step 1: Write the failing test**

```python
# tts_service/tests/test_sweep.py
import json, os
from app.sweep import should_run, find_candidate

def test_should_run_gated_by_active_job(tmp_path):
    lp = str(tmp_path/".gpu.lock")
    assert should_run({}, lp) is True
    assert should_run({"/p": {"stage":"synthesizing"}}, lp) is False
    assert should_run({"/p": {"stage":"ready"}}, lp) is True

def test_find_candidate_needs_audio_md_without_fresh_hls(tmp_path):
    root = tmp_path/"outputs"; (root/"P").mkdir(parents=True)
    (root/"P"/"P_ko_audio.md").write_text("# t\n\n본문.")
    cand = find_candidate(str(root))
    assert cand and cand["src_md"].endswith("P_ko_audio.md")
    # complete v2 manifest 있으면 후보 아님
    (root/"P"/"P_ko_audio.manifest.json").write_text(json.dumps(
        {"schema_version":2,"status":"complete","source":{"sha256":"x"},"tts":{},
         "audio":{"hls":{"playlist":"stream.m3u8"}}}))
    # sha 불일치라 여전히 후보(파일 sha != "x") — 단순화: 존재만으로는 skip 안 함
    assert find_candidate(str(root)) is not None
```

- [ ] **Step 2: Run to verify fail**

Run: `cd tts_service && python -m pytest tests/test_sweep.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement**

```python
# tts_service/app/sweep.py
import os, glob, json, time, threading
from app.gpulock import try_acquire

def should_run(jobs, gpu_lock_path):
    if any(st.get("stage") not in ("ready","failed","failed_partial","none")
           for st in jobs.values()):
        return False
    fh = try_acquire(gpu_lock_path)
    if fh is None:
        return False
    fh.close()                       # 즉시 해제(점유 확인용)
    return True

def _sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(65536), b""): h.update(b)
    return h.hexdigest()

def find_candidate(outputs_root):
    from app.manifest import is_fresh_for_hls            # HIGH#4: sha 기반 freshness
    for d in sorted(glob.glob(os.path.join(outputs_root, "*")),
                    key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True):
        if not os.path.isdir(d): continue
        mds = glob.glob(os.path.join(d, "*_ko_audio.md"))
        if not mds: continue
        base = os.path.basename(mds[0])[:-len("_ko_audio.md")]
        man = os.path.join(d, f"{base}_ko_audio.manifest.json")
        fresh_hls = False
        if os.path.exists(man):
            try:
                m = json.load(open(man))
                cur_sha = _sha256_file(mds[0])           # 소스 sha 계산해 버전 비교
                fresh_hls = is_fresh_for_hls(m, cur_sha)  # schema>=2 + complete + hls + sha 일치
            except Exception: pass
        if not fresh_hls:
            return {"paper_dir": d, "src_md": mds[0]}
    return None

def sweep_loop(jobs, lock, run_job, outputs_root, gpu_lock_path,
               enabled, interval, max_papers, stop_event):
    if not enabled: return
    done = 0
    while not stop_event.is_set() and done < max_papers:
        if should_run(jobs, gpu_lock_path):
            cand = find_candidate(outputs_root)
            if cand:
                with lock: jobs[cand["paper_dir"]] = {"stage":"segmenting","done":0,"total":0,"error":None}
                try:
                    run_job(cand["paper_dir"], cand["src_md"])
                    done += 1
                except Exception:
                    pass
        stop_event.wait(interval)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd tts_service && python -m pytest tests/test_sweep.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tts_service/app/sweep.py tts_service/tests/test_sweep.py
git commit -m "feat(hls): idle pre-generation sweep (off by default, capped)"
```

---

## Task 7: main.py — sweep 조건부 기동 + failed_partial 처리 + 설정

**Files:**
- Modify: `tts_service/app/main.py`

- [ ] **Step 1: Implement**

`_worker` 에서 `failed_partial` 보존, 종료 후 sweep 스레드 기동(기본 OFF):

```python
# tts_service/app/main.py — _worker 수정 + sweep 기동
import os, threading
from app.sweep import sweep_loop
from app.job import run_job, GPU_LOCK_PATH

def _worker(paper_dir, src_md):
    def cb(stage, done, total):
        with _lock: _jobs[paper_dir] = {"stage": stage, "done": done, "total": total, "error": None}
    try:
        cb("segmenting", 0, 0)
        run_job(paper_dir, src_md, progress_cb=cb)
        with _lock:
            st = _jobs.get(paper_dir, {})
            if st.get("stage") not in ("ready","failed_partial"):
                _jobs[paper_dir] = {"stage":"ready","done":st.get("done",0),"total":st.get("total",0),"error":None}
    except RuntimeError as e:
        # _fail_partial 가 raise — manifest 는 이미 failed_partial. status 반영.
        with _lock: _jobs[paper_dir] = {"stage":"failed_partial","done":0,"total":0,"error":str(e)}
    except Exception as e:
        with _lock: _jobs[paper_dir] = {"stage":"failed","done":0,"total":0,"error":str(e)}

_SWEEP_ENABLED = os.environ.get("SWEEP_ENABLED","false").lower() == "true"
_SWEEP_INTERVAL = int(os.environ.get("SWEEP_INTERVAL","60"))
_SWEEP_MAX_PAPERS = int(os.environ.get("SWEEP_MAX_PAPERS","3"))
_OUTPUTS_ROOT = os.environ.get("PF_OUTPUTS_ROOT","/data/outputs")
_stop = threading.Event()

@app.on_event("startup")
def _start_sweep():
    if _SWEEP_ENABLED:
        threading.Thread(target=sweep_loop, args=(_jobs,_lock,run_job,_OUTPUTS_ROOT,GPU_LOCK_PATH,
            True,_SWEEP_INTERVAL,_SWEEP_MAX_PAPERS,_stop), daemon=True).start()
```

- [ ] **Step 2: Sanity import + health**

Run: `cd tts_service && /tmp/cbx-venv/bin/python -c "from app.main import app, health; print(health())"`
Expected: `{'ok': True}`

- [ ] **Step 3: Commit**

```bash
git add tts_service/app/main.py
git commit -m "feat(hls): sweep startup (off by default) + failed_partial status"
```

---

## Task 8: viewer audio.py — v1/v2 경로 + HLS 토큰 + 전체 span 렌더

**Files:**
- Modify: `viewer/app/services/audio.py`
- Modify: `viewer/app/config.py`
- Test: `viewer/tests/test_audio_api.py`

- [ ] **Step 1: Write failing test (append)**

```python
# viewer/tests/test_audio_api.py 에 추가
from app.services import audio as a

def test_mp3_path_v1_and_v2(tmp_path, monkeypatch):
    paper = tmp_path/"P"; (paper/"audio").mkdir(parents=True)
    (paper/"P_ko_audio.md").write_text("# t\n\n본문.")
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    # v1
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        '{"schema_version":1,"status":"complete","audio":{"file":"P_ko_audio.v1.mp3"}}')
    (paper/"audio"/"P_ko_audio.v1.mp3").write_bytes(b"x")
    assert a.mp3_file_path("P").name == "P_ko_audio.v1.mp3"
    # v2
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"complete","audio":{"hls":{"playlist":"stream.m3u8"},'
        '"mp3":{"file":"P_ko_audio.abc.mp3"}}}')
    assert a.mp3_file_path("P").name == "P_ko_audio.abc.mp3"

def test_hls_paths_resolve(tmp_path, monkeypatch):
    paper = tmp_path/"P"; (paper/"audio"/"P_ko_audio.abc123def456").mkdir(parents=True)
    (paper/"P_ko_audio.md").write_text("# t\n\n본문.")
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"streaming","source":{"sha256":"abc123def456ff"},'
        '"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}}}')
    (paper/"audio"/"P_ko_audio.abc123def456"/"stream.m3u8").write_text("#EXTM3U")
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    assert a.hls_playlist_path("P").name == "stream.m3u8"
    seg = a.hls_segment_path("P", "seg_000000.ts")
    assert seg.parent.name == "P_ko_audio.abc123def456"
    assert a.hls_segment_path("P", "../../etc") is None      # traversal 방어

def test_reconcile_stale_streaming_to_failed(tmp_path, monkeypatch):
    paper = tmp_path/"P"; (paper/"audio").mkdir(parents=True)
    (paper/"P_ko_audio.md").write_text("# t\n\n본문.")
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"streaming","heartbeat":"2000-01-01T00:00:00+00:00",'
        '"source":{"sha256":"s"},"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}},"chunks":[]}')
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    assert a.reconcile_stale("P") is True                    # 오래된 heartbeat → failed 전이
    import json as _j
    assert _j.loads((paper/"audio"/"P_ko_audio.manifest.json").read_text())["status"] == "failed"
    assert a.reconcile_stale("P") is False                   # 이미 failed → no-op
```

- [ ] **Step 2: Run to verify fail**

Run: `cd viewer && python -m pytest tests/test_audio_api.py::test_hls_paths_resolve -v`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Implement (audio.py 에 추가/수정)**

```python
# viewer/app/services/audio.py 에 추가
import re as _re

def _manifest_dict(name):
    p = manifest_path(name)
    if not p or not p.exists(): return None
    try: return json.loads(p.read_text())
    except Exception: return None

def mp3_file_path(name):                       # v1 audio.file + v2 audio.mp3.file
    man = _manifest_dict(name)
    if not man: return None
    a = man.get("audio", {})
    fn = a.get("file") or (a.get("mp3") or {}).get("file")
    if not fn: return None
    return manifest_path(name).parent / fn

def _hls_dir(name):
    man = _manifest_dict(name)
    if not man: return None
    sha = (man.get("source") or {}).get("sha256")
    base = _base_for(_resolve_paper_dir(name))
    if not sha or not base: return None
    return manifest_path(name).parent / f"{base}_ko_audio.{sha[:12]}"

def hls_playlist_path(name):
    d = _hls_dir(name)
    if not d: return None
    p = d / "stream.m3u8"
    return p if p.exists() else None

def hls_segment_path(name, seg):
    if not _re.fullmatch(r"seg_[0-9]{6}\.ts", seg): return None
    d = _hls_dir(name)
    if not d: return None
    cand = d / seg
    if not _under_audio_dir(cand, d): return None
    return cand if cand.exists() else None

def source_id_and_sha(name):                   # 토큰 바인딩용
    man = _manifest_dict(name)
    if not man: return None, None
    src = (man.get("source") or {})
    return src.get("path"), (src.get("sha256") or "")[:12]

def reconcile_stale(name, threshold_sec=1800):
    """BLOCKING#4 / 스펙 §8.4: status='streaming' 인데 heartbeat 가 threshold(기본 30분)
    이상 멈췄으면 'failed' 로 atomic 전이(사이드카 재시작 등으로 진행 유실된 케이스). 전이 시 True."""
    from datetime import datetime, timezone
    p = manifest_path(name)
    if not p or not p.exists(): return False
    try:
        man = json.loads(p.read_text())
    except Exception:
        return False
    if man.get("status") != "streaming": return False
    hb = man.get("heartbeat")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb)).total_seconds() if hb else 1e9
    except Exception:
        age = 1e9
    if age < threshold_sec: return False
    man["status"] = "failed"
    tmp = str(p) + ".tmp"; Path(tmp).write_text(json.dumps(man, ensure_ascii=False)); os.replace(tmp, p)
    return True
```

> `reconcile_stale` 는 `/audio/manifest`·`/audio/stream-url` 핸들러 및 sweep candidate 진입 시 호출(Task 9 에서 stream-url 에 이미 추가; `/audio/manifest` 핸들러에도 `audio_svc.reconcile_stale(name)` 한 줄 추가).

config.py 에 추가:

```python
# viewer/app/config.py Settings 에 추가
    AUDIO_TOKEN_SECRET: str = ""        # 빈 값이면 JWT_SECRET_KEY 사용(아래 property)
    AUDIO_PTOKEN_TTL: int = 43200       # 12h
    AUDIO_TOKEN_TTL: int = 43200
    AUDIO_RESUME_GRACE: int = 3600

    @property
    def audio_secret(self) -> str:
        return self.AUDIO_TOKEN_SECRET or self.JWT_SECRET_KEY
```

- [ ] **Step 4: Run to verify pass**

Run: `cd viewer && JWT_SECRET_KEY=$(python -c "print('x'*48)") python -m pytest tests/test_audio_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add viewer/app/services/audio.py viewer/app/config.py viewer/tests/test_audio_api.py
git commit -m "feat(hls): viewer audio service v1/v2 paths + hls path resolve + token config"
```

---

## Task 9: viewer api.py — stream-url / stream.m3u8 / seg / html + 로그 redaction

**Files:**
- Modify: `viewer/app/routers/api.py`
- Test: `viewer/tests/test_audio_api.py`

`/audio/stream-url`(쿠키 인증→ptoken 발급), `/audio/stream.m3u8`(ptoken 검증→segment token 주입), `/audio/seg/{seg}`(token 검증→FileResponse), `/audio/html` 409 제거.

- [ ] **Step 1: Write failing test (append)**

```python
# viewer/tests/test_audio_api.py 에 추가 — TestClient 기반
from fastapi.testclient import TestClient

def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("BASE_DIR", str(tmp_path)); monkeypatch.setenv("JWT_SECRET_KEY","x"*48)
    from app import config as cfg; cfg.settings = cfg.Settings()
    from app.main import create_app
    return TestClient(create_app())

def test_stream_url_then_playlist_then_seg(tmp_path, monkeypatch):
    # 준비: complete v2 manifest + playlist + 1 seg
    paper = tmp_path/"outputs"/"P"; (paper/"audio"/"P_ko_audio.abc123def456").mkdir(parents=True)
    (paper/"P_ko_audio.md").write_text("# t\n\n본문.")
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"complete","source":{"path":"P_ko_audio.md","sha256":"abc123def456ff"},'
        '"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":null}},"chunks":[]}')
    hd = paper/"audio"/"P_ko_audio.abc123def456"
    (hd/"stream.m3u8").write_text("#EXTM3U\n#EXTINF:1.0,\nseg/seg_000000.ts\n#EXT-X-ENDLIST\n")
    (hd/"seg_000000.ts").write_bytes(b"\x47" + b"\x00"*187)   # TS sync byte
    c = _client(monkeypatch, tmp_path)
    c.post("/api/login", json={"username":"admin","password":"admin"})   # 기본 자격
    su = c.get("/api/papers/P/audio/stream-url"); assert su.status_code == 200
    ptoken = su.json()["ptoken"] if "ptoken" in su.json() else su.json()["url"].split("ptoken=")[1]
    pl = c.get(f"/api/papers/P/audio/stream.m3u8?ptoken={ptoken}"); assert pl.status_code == 200
    assert "token=" in pl.text                                  # segment URI 에 토큰 주입
    seg_uri = [l for l in pl.text.splitlines() if l.startswith("seg/")][0]
    tok = seg_uri.split("token=")[1]
    sg = c.get(f"/api/papers/P/audio/seg/seg_000000.ts?token={tok}"); assert sg.status_code == 200
    bad = c.get("/api/papers/P/audio/seg/seg_000000.ts?token=bad"); assert bad.status_code == 403
```

- [ ] **Step 2: Run to verify fail**

Run: `cd viewer && python -m pytest tests/test_audio_api.py::test_stream_url_then_playlist_then_seg -v`
Expected: FAIL (404 — 라우트 없음)

- [ ] **Step 3a: Create viewer 토큰 사본 (BLOCKING#3 — import 경로 고정)**

viewer 는 `tts_service/app/segtoken.py` 를 import 할 수 없다(별 컨테이너). **byte-identical 복제**:

```bash
cp tts_service/app/segtoken.py viewer/app/services/tts_token.py
```

drift 방지 test vector 를 viewer 에도 둔다(`viewer/tests/test_tts_token.py` = `tts_service/tests/test_segtoken.py` 와 동일 assert, import 만 `from app.services.tts_token import mint, verify`).

- [ ] **Step 3b: Implement (api.py 에 추가/수정)**

```python
# viewer/app/routers/api.py 상단 import 에 추가
from ..services import audio as audio_svc
from ..services.tts_token import mint as _tok_mint, verify as _tok_verify   # ★ 정확한 경로
from ..dependencies import get_current_user_page                            # ★ 누락 import
from fastapi import Query
from fastapi.responses import Response, FileResponse
import time

def _segment_ttl(name):
    # HIGH#6: max(AUDIO_TOKEN_TTL, duration + resume_grace) — VOD 1회 fetch 후 장시간 커버
    man = audio_svc._manifest_dict(name) or {}
    dur = (man.get("audio") or {}).get("duration_sec") or 0
    return int(max(settings.AUDIO_TOKEN_TTL, dur + settings.AUDIO_RESUME_GRACE))

def _audio_token(kind, name, ttl):
    sid, sha = audio_svc.source_id_and_sha(name)
    return _tok_mint(settings.audio_secret, kind=kind, source_id=sid or "", sha12=sha or "", ttl=ttl)

@router.get("/papers/{name:path}/audio/stream-url")
async def audio_stream_url(name: str, _user: str = Depends(get_current_user_api)):
    audio_svc.reconcile_stale(name)                       # BLOCKING#4: stale streaming 복구
    if not audio_svc.hls_playlist_path(name): raise HTTPException(404)
    ptoken = _audio_token("playlist", name, settings.AUDIO_PTOKEN_TTL)
    return {"ptoken": ptoken, "url": f"/api/papers/{name}/audio/stream.m3u8?ptoken={ptoken}"}

@router.get("/papers/{name:path}/audio/stream.m3u8")
async def audio_stream(name: str, ptoken: str | None = None,
                       user_cookie=Depends(get_current_user_page)):
    sid, sha = audio_svc.source_id_and_sha(name)
    if ptoken:
        ok, _r = _tok_verify(settings.audio_secret, ptoken, "playlist", sid or "", sha or "", time.time())
        if not ok: raise HTTPException(403, "bad ptoken")
    elif not user_cookie:
        raise HTTPException(401)
    pl = audio_svc.hls_playlist_path(name)
    if not pl: raise HTTPException(404)
    man = audio_svc._manifest_dict(name) or {}
    streaming = man.get("status") == "streaming"
    seg_tok = _audio_token("segment", name, _segment_ttl(name))
    body = []
    for line in pl.read_text().splitlines():
        if line.startswith("seg/"):
            line = f"{line}?token={seg_tok}"
        body.append(line)
    # HIGH#6 cache 분리: streaming = no-store, complete tokenized = no-cache
    cache = "no-cache, no-store" if streaming else "private, no-cache"
    return Response("\n".join(body) + "\n", media_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": cache})

@router.get("/papers/{name:path}/audio/seg/{seg}")
async def audio_seg(name: str, seg: str, token: str = Query(...)):
    sid, sha = audio_svc.source_id_and_sha(name)
    ok, _r = _tok_verify(settings.audio_secret, token, "segment", sid or "", sha or "", time.time())
    if not ok: raise HTTPException(403, "bad token")
    p = audio_svc.hls_segment_path(name, seg)
    if not p: raise HTTPException(404)
    return FileResponse(p, media_type="video/mp2t",                  # segment 파일만 immutable cache
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})
```

- [ ] **Step 3c: 기존 `/audio/file` 을 v1/v2 mp3 폴백으로 (HIGH#2)**

기존 `audio_file` 핸들러가 `audio_svc.audio_file_path()`(v1 전용)를 호출 → `mp3_file_path()`(v1+v2)로 교체:

```python
# 기존 audio_file 핸들러 본문에서 audio_svc.audio_file_path(name) → audio_svc.mp3_file_path(name)
    p = audio_svc.mp3_file_path(name)
    if not p or not p.exists(): raise HTTPException(404)
    return FileResponse(p, media_type="audio/mpeg")
```

- [ ] **Step 3d: `/audio/html` 409 완화 + 로그 redaction (HIGH#1, 실제 구현)**

`/audio/html`: `if manifest.get("status") not in ("streaming","complete","failed_partial"): raise HTTPException(409)`.

로그 redaction — **uvicorn access logger 에 실제 필터 wiring**(viewer `main.py` `create_app()` 시작부):

```python
# viewer/app/main.py create_app() 에 추가
import logging, re as _re
class _TokenRedactFilter(logging.Filter):
    _RE = _re.compile(r"((?:p?token)=)[^&\s\"']+")
    def filter(self, record):
        if record.args:
            record.args = tuple(self._RE.sub(r"\1REDACTED", str(a)) for a in record.args)
        record.msg = self._RE.sub(r"\1REDACTED", str(record.msg))
        return True
logging.getLogger("uvicorn.access").addFilter(_TokenRedactFilter())
```

- [ ] **Step 4: Run tests (TestClient + redact filter)**

```python
# viewer/tests/test_audio_api.py 에 추가
def test_audio_file_v2_fallback(tmp_path, monkeypatch):
    paper = tmp_path/"outputs"/"P"; (paper/"audio").mkdir(parents=True)
    (paper/"P_ko_audio.md").write_text("# t\n\n본문.")
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        '{"schema_version":2,"status":"complete","source":{"path":"P","sha256":"abc123def456ff"},'
        '"audio":{"hls":{"playlist":"stream.m3u8"},"mp3":{"file":"P_ko_audio.abc.mp3"}},"chunks":[]}')
    (paper/"audio"/"P_ko_audio.abc.mp3").write_bytes(b"\xff\xfb")
    c = _client(monkeypatch, tmp_path); c.post("/api/login", json={"username":"admin","password":"admin"})
    assert c.get("/api/papers/P/audio/file").status_code == 200

def test_redact_filter_masks_token():
    from app.main import _TokenRedactFilter   # create_app 정의 시점에 따라 노출 위치 조정
    import logging
    rec = logging.LogRecord("x",20,"",0,'GET /a?token=SECRET&ptoken=Y',(),None)
    _TokenRedactFilter().filter(rec)
    assert "SECRET" not in rec.getMessage() and "token=REDACTED" in rec.getMessage()
```

Run: `cd viewer && JWT_SECRET_KEY=$(python -c "print('x'*48)") python -m pytest tests/test_audio_api.py tests/test_tts_token.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add viewer/app/routers/api.py viewer/app/services/tts_token.py viewer/app/main.py viewer/tests/test_audio_api.py viewer/tests/test_tts_token.py
git commit -m "feat(hls): stream-url/playlist/segment endpoints + v2 mp3 fallback + token redaction + segment TTL"
```

---

## Task 10: docker-compose env + 통합 스모크

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: compose env 추가**

`paperflow-tts.environment` 에:
```yaml
      - SWEEP_ENABLED=${SWEEP_ENABLED:-false}
      - SWEEP_INTERVAL=${SWEEP_INTERVAL:-60}
      - SWEEP_MAX_PAPERS=${SWEEP_MAX_PAPERS:-3}
      - AUDIO_TOKEN_SECRET=${AUDIO_TOKEN_SECRET:-}
```
`paperflow-viewer.environment` 에:
```yaml
      - AUDIO_TOKEN_SECRET=${AUDIO_TOKEN_SECRET:-}
      # NOTE: access log 에 ?token/?ptoken 노출 — 운영 시 proxy 마스킹 또는 --access-log 끄기
```

- [ ] **Step 2: Build + 기동**

Run: `docker compose build paperflow-tts paperflow-viewer && docker compose up -d`
Expected: 3 컨테이너 Up, tts health ok

- [ ] **Step 3: 스트리밍 스모크 (작은 듣기판 논문)**

```bash
P=$(python3 -c "import urllib.parse;print(urllib.parse.quote('<듣기판 있는 짧은 논문>'))")
curl -s -b cj -X POST localhost:8090/api/papers/$P/audio/jobs           # {"accepted":true}
sleep 5
curl -s -b cj localhost:8090/api/papers/$P/audio/manifest | python3 -c "import sys,json;m=json.load(sys.stdin);print(m['status'], len(m['chunks']), len([c for c in m['chunks'] if c['start_sec'] is not None]))"
SU=$(curl -s -b cj localhost:8090/api/papers/$P/audio/stream-url); PT=$(echo $SU | python3 -c "import sys,json;print(json.load(sys.stdin)['ptoken'])")
curl -s -b cj "localhost:8090/api/papers/$P/audio/stream.m3u8?ptoken=$PT" | head
```
Expected: status=streaming, chunks 전체 존재, start_sec 채워진 수가 증가. playlist 에 `seg/seg_000000.ts?token=...`

- [ ] **Step 4: 완료 + Range + 산출물**

```bash
curl -s -b cj localhost:8090/api/papers/$P/audio/manifest | python3 -c "import sys,json;m=json.load(sys.stdin);print(m['status'], m['audio']['mp3']['file'])"
SEG=...; TOK=...   # playlist 에서 추출
curl -s -b cj -D- -o /dev/null -H "Range: bytes=0-99" "localhost:8090/api/papers/$P/audio/seg/$SEG?token=$TOK" | grep -i "206\|content-range"
ls "outputs/<논문>/audio/"   # <base>_ko_audio.<sha12>/(stream.m3u8+seg_*.ts), <base>_ko_audio.<sha12>.mp3, manifest, .jobs 없음
```
Expected: complete, mp3 채워짐, seg 206, .jobs 폐기.

- [ ] **Step 5: Commit (검증 메모는 상태파일)**

```bash
git add docker-compose.yml
git commit -m "feat(hls): compose env (sweep off default, audio token secret) + smoke notes"
```

---

## Self-Review 결과 (Codex 플랜 리뷰 R1 반영)

- **Spec coverage**: §5 세그먼트/playlist→Task3 · §4 manifest v2→Task4 · §7 token(playlist+segment)→Task1,9 · §5.3 sub-split→Task2 · §2 증분 publish(heading 포함)→Task5 · 과길이 재합성 재시도→Task5 · §7 sweep(sha freshness)→Task6,7 · §9 API(stream-url/m3u8/seg, v2 mp3 폴백, cache 분리)→Task9 · §8 file lock/TTL(mp3 포함)→Task5 · §8.4 stale 복구→Task8(`reconcile_stale`, Task9 endpoint 호출) · §7 로그 redaction(실제 필터)→Task9 · §12.0 실측(전체 표본+가드)→Task0 · §13 하위호환(v1/v2)→Task8,9. 실기기 preflight(§12.3)·프론트(§10)→Plan 2.
- **Codex BLOCKING 반영**: #1 과길이 재시도→Task5 `_synth_encode_with_retry` · #2 streaming mount→Plan2 Task2b · #3 token import 경로/`get_current_user_page`→Task9 Step3a/3b · #4 stale 복구→Task8. **HIGH 9**: 로그 redaction 실제 필터·v2 mp3 폴백·v1 fresh 테스트·sweep sha·TTL mp3+버전그룹·segment TTL max·failed_partial(Plan2)·프론트 자동테스트(Plan2)·Task0 표본확대+가드.
- **Placeholder scan**: 모든 코드 스텝 실제 코드. `TARGETDURATION`/`SENTENCE_CHAR_CAP`/음량은 Task0 치환 + 커밋 전 grep 가드.
- **Type consistency**: chunk 키(sentence_group_id/sub_index/sub_count/display_sentence_index/start_sec/end_sec) Task2↔4↔5↔Plan2 일치. token mint/verify(kind 포함) Task1↔9 일치. manifest `audio.hls.playlist`/`audio.mp3.file` Task4↔8↔9 일치. `_manifest_dict`/`reconcile_stale`/`mp3_file_path`/`source_id_and_sha` Task8↔9 일치.

## 미해결 → Plan 2 (프론트엔드)
- 프론트 HLS 부착·생성 중 streaming mount·그룹 하이라이트·401 remount·failed_partial·hls.js·자동테스트·실기기 preflight → Plan 2.
