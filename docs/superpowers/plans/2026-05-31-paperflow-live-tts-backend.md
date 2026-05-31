# PaperFlow 라이브 한국어 TTS — 백엔드 구현 플랜 (Plan 1/2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `_ko_audio.md`를 청크 단위로 합성·검증해 **단일 stitched 오디오 + 단일 manifest.json**을 원자적으로 생성하고, 뷰어 API로 제공한다(프론트엔드는 Plan 2).

**Architecture:** GPU를 쓰는 TTS 사이드카 컨테이너(Chatterbox-Multilingual)가 내부 HTTP API로 합성 job을 처리하고 공유 볼륨 `outputs/<paper>/audio/`에 산출물을 쓴다. viewer(슬림, GPU 없음)는 이 산출물을 읽어 서빙하고 job을 사이드카에 프록시한다. GPU 동시성은 공유 파일락(`outputs/.gpu.lock`, flock)으로 converter(MinerU)와 상호배제한다.

**Tech Stack:** Python 3.12, FastAPI, chatterbox-tts(torch+CUDA), ffmpeg/ffprobe, pytest, Docker Compose.

**선행 스펙:** [docs/superpowers/specs/2026-05-31-paperflow-live-tts-design.md](../specs/2026-05-31-paperflow-live-tts-design.md) (Codex 승인)

---

## File Structure

```text
tts_service/                         # 신규 사이드카 (CUDA)
├── Dockerfile                       # nvidia/cuda 베이스 + chatterbox-tts + ffmpeg
├── requirements.txt
├── app/
│   ├── main.py                      # FastAPI: POST /jobs, GET /jobs/{id}, GET /health
│   ├── chunker.py                   # _ko_audio.md → 청크 리스트(문장/헤딩, dom_id, kind)
│   ├── synth.py                     # Chatterbox 적재 + 청크 합성(perth Dummy fallback)
│   ├── stitch.py                    # ffmpeg concat(+패딩) + ffprobe duration
│   ├── manifest.py                  # 단일 manifest.json 빌드/freshness 판정
│   ├── job.py                       # 오케스트레이션: segment→synth→stitch→manifest→publish→cleanup
│   └── gpulock.py                   # flock 기반 GPU 상호배제
└── tests/
    ├── test_chunker.py
    ├── test_manifest.py
    ├── test_stitch.py
    └── test_gpulock.py

viewer/app/routers/api.py            # Modify: /audio/* 엔드포인트 6개 추가
viewer/app/services/audio.py         # 신규: 사이드카 프록시 + 산출물 경로/freshness + 듣기 진행률
viewer/tests/test_audio_api.py       # 신규 (기존 저장소 pytest 관례 viewer/tests/)

docker-compose.yml                   # Modify: paperflow-tts 서비스 추가
```

산출물(공유 볼륨):
```text
outputs/<paper>/audio/.jobs/<job_id>/   # 임시(청크 wav, manifest.draft, tmp mp3) — publish 후 삭제
outputs/<paper>/audio/<base>_ko_audio.<source_sha12>.mp3   # B1: content-versioned 단일 stitched
outputs/<paper>/audio/<base>_ko_audio.manifest.json        # audio.file이 위 버전드 파일을 가리킴(완료 마커)
```

---

## Task 1: 청커(chunker) — 문장/헤딩 segmentation

**Files:**
- Create: `tts_service/app/chunker.py`
- Test: `tts_service/tests/test_chunker.py`

청커는 `_ko_audio.md` 텍스트를 받아 청크 리스트를 만든다. 규칙(스펙 §2,§4): 헤딩(`#`\~`###`)=별도 청크(kind="heading"), 문단=문장 단위 분할(kind="text", 1문장=1청크), 배너 blockquote(`>`)=제외. 각 청크에 `dom_id="tts-s-%06d"`, `section_id`(직전 헤딩 slug), `paragraph_index`, `sentence_index` 부여.

- [ ] **Step 1: Write the failing test**

```python
# tts_service/tests/test_chunker.py
from app.chunker import chunk_markdown

def test_heading_and_sentences():
    md = "# 서론\n\n첫 문장입니다. 둘째 문장이에요.\n\n## 방법\n\n셋째 문장."
    chunks = chunk_markdown(md)
    kinds = [(c["kind"], c["text"]) for c in chunks]
    assert kinds == [
        ("heading", "서론"),
        ("text", "첫 문장입니다."),
        ("text", "둘째 문장이에요."),
        ("heading", "방법"),
        ("text", "셋째 문장."),
    ]
    assert chunks[0]["dom_id"] == "tts-s-000000"
    assert chunks[4]["dom_id"] == "tts-s-000004"
    assert chunks[3]["section_id"] == chunks[4]["section_id"]  # 둘 다 "방법" 섹션

def test_banner_blockquote_excluded():
    md = "# 제목 — 듣기판\n\n> 이 글은 듣기판입니다.\n\n본문 문장."
    chunks = chunk_markdown(md)
    assert all("듣기판입니다" not in c["text"] for c in chunks)
    assert [c["kind"] for c in chunks] == ["heading", "text"]

def test_short_sentence_is_own_chunk():
    # MVP: 1문장=1합성단위 (짧아도 묶지 않음)
    md = "네. 아니요. 그렇습니다."
    chunks = chunk_markdown(md)
    assert [c["text"] for c in chunks] == ["네.", "아니요.", "그렇습니다."]

def test_closing_quote_after_period_splits():   # nit#1
    md = '그는 "좋다." 라고 말했다. 다음 문장.'
    texts = [c["text"] for c in chunk_markdown(md)]
    assert texts == ['그는 "좋다."', "라고 말했다.", "다음 문장."]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tts_service && python -m pytest tests/test_chunker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.chunker'`

- [ ] **Step 3: Write minimal implementation**

```python
# tts_service/app/chunker.py
import re

CHUNKER_VERSION = "paperflow-tts-chunker-v1"
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# R2-B2: 종결부호(+선택적 닫는 따옴표/괄호)를 '캡처'해 보존하고, 그 뒤에 sentinel(\x00)을 삽입한 뒤
# sentinel로 split → 닫는 따옴표가 split에 소비되지 않는다.
_SENT_BREAK = re.compile(r'([.!?…][”’"\')\]】」』]?)\s+')

def _slug(text, idx):
    s = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", text).strip("-").lower()
    return s or f"sec-{idx}"

def _split_sentences(para):
    marked = _SENT_BREAK.sub(r'\1\x00', para.strip())   # 종결부호+따옴표 보존, 뒤에 sentinel
    return [p.strip() for p in marked.split('\x00') if p.strip()]

def chunk_markdown(md: str):
    chunks = []
    section_id = "root"
    para_idx = 0
    n = 0
    # 블록 단위 분리(빈 줄 기준), 배너 blockquote(>) 제외
    blocks = re.split(r"\n\s*\n", md)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith(">"):  # 배너 blockquote → 합성 제외
            continue
        m = _HEADING.match(block)
        if m and "\n" not in block:
            text = m.group(2).strip()
            section_id = _slug(text, n)
            chunks.append({
                "id": n, "kind": "heading", "dom_id": f"tts-s-{n:06d}",
                "section_id": section_id, "paragraph_index": para_idx,
                "sentence_index": 0, "text": text,
            })
            n += 1
            continue
        # 문단: 문장 분할
        for s_i, sent in enumerate(_split_sentences(block)):
            chunks.append({
                "id": n, "kind": "text", "dom_id": f"tts-s-{n:06d}",
                "section_id": section_id, "paragraph_index": para_idx,
                "sentence_index": s_i, "text": sent,
            })
            n += 1
        para_idx += 1
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tts_service && python -m pytest tests/test_chunker.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tts_service/app/chunker.py tts_service/tests/test_chunker.py
git commit -m "feat(tts): markdown chunker for sentence/heading segmentation"
```

---

## Task 2: 매니페스트 빌더 + freshness

**Files:**
- Create: `tts_service/app/manifest.py`
- Test: `tts_service/tests/test_manifest.py`

단일 manifest dict를 만들고, 소스 변경 freshness(sha256+캐시키)를 판정한다(스펙 §3).

- [ ] **Step 1: Write the failing test**

```python
# tts_service/tests/test_manifest.py
from app.manifest import build_manifest, is_fresh, CACHE_KEY_FIELDS

def test_build_manifest_shape():
    chunks = [{"id":0,"kind":"heading","dom_id":"tts-s-000000","section_id":"intro",
               "paragraph_index":0,"sentence_index":0,"text":"서론","start_sec":0.0,"end_sec":1.1}]
    m = build_manifest(source_path="a_ko_audio.md", source_sha256="abc", source_mtime="t",
                       audio_file="a_ko_audio.mp3", duration_sec=1.1, sample_rate=24000, chunks=chunks)
    assert m["status"] == "complete"
    assert m["schema_version"] == 1
    assert m["source"]["sha256"] == "abc"
    assert m["audio"]["file"] == "a_ko_audio.mp3"
    assert m["tts"]["language_id"] == "ko"
    assert m["chunks"][0]["dom_id"] == "tts-s-000000"

def test_is_fresh_detects_source_change():
    m = build_manifest("a.md","sha_OLD","t","a.mp3",1.0,24000,[])
    assert is_fresh(m, current_sha256="sha_OLD") is True
    assert is_fresh(m, current_sha256="sha_NEW") is False

def test_is_fresh_detects_cachekey_change():
    m = build_manifest("a.md","sha","t","a.mp3",1.0,24000,[])
    assert is_fresh(m, current_sha256="sha", tts_overrides={"voice_id":"other"}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tts_service && python -m pytest tests/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# tts_service/app/manifest.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tts_service && python -m pytest tests/test_manifest.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add tts_service/app/manifest.py tts_service/tests/test_manifest.py
git commit -m "feat(tts): single manifest builder + freshness check"
```

---

## Task 3: Stitcher — ffmpeg concat + 패딩 + ffprobe

**Files:**
- Create: `tts_service/app/stitch.py`
- Test: `tts_service/tests/test_stitch.py`

청크 wav 리스트를 무음 패딩과 함께 이어붙여 단일 mp3로 인코딩하고, 각 청크의 `start_sec/end_sec`(패딩 포함, ffprobe 실측)을 계산한다(스펙 §3 패딩, §8 검증). `end_sec`는 다음 청크 시작 전까지의 표시 구간.

- [ ] **Step 1: Write the failing test** (ffmpeg/ffprobe 실제 호출, 합성된 사인파 wav 사용)

```python
# tts_service/tests/test_stitch.py
import subprocess, wave, struct, math, os
from app.stitch import pad_for, stitch_chunks

def _make_wav(path, sec=0.5, sr=24000, freq=440):
    n = int(sec*sr)
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        for i in range(n):
            w.writeframes(struct.pack("<h", int(3000*math.sin(2*math.pi*freq*i/sr))))

def test_pad_for_rules():
    assert pad_for("text", "text") == 0.18      # 문장 사이 대표값
    assert pad_for("text", "heading") == 0.40    # 문단/섹션 경계
    assert pad_for("heading", "text") == 0.75     # 헤딩 뒤 긴 쉼

def test_stitch_produces_timeline(tmp_path):
    files = []
    for i in range(3):
        p = tmp_path/f"c{i}.wav"; _make_wav(str(p)); files.append(str(p))
    chunks = [{"id":i,"kind":"text","text":f"s{i}"} for i in range(3)]
    out = tmp_path/"out.mp3"
    timeline, duration, sr = stitch_chunks(files, chunks, str(out), sample_rate=24000)
    assert out.exists() and duration > 1.4        # 3*0.5 + 2*패딩
    assert timeline[0]["start_sec"] == 0.0
    assert timeline[1]["start_sec"] > timeline[0]["end_sec"] - 1e-6
    assert abs(timeline[-1]["end_sec"] - duration) < 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tts_service && python -m pytest tests/test_stitch.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# tts_service/app/stitch.py
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
        "ffprobe","-v","error","-show_entries","format=duration",
        "-of","json", path])
    return float(json.loads(out)["format"]["duration"])

def _norm_wav(src, dst, sr):
    """nit#3: 입력을 pcm_s16le/mono/sr로 통일 → concat demuxer 안정."""
    subprocess.check_call([
        "ffmpeg","-y","-i",src,"-ar",str(sr),"-ac","1","-c:a","pcm_s16le", dst],
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
                pad = pad_for(ch["kind"], chunks[i+1]["kind"]) if i < len(chunks)-1 else 0.0
                end = cursor + pad   # end_sec = 다음 청크 시작 전까지(표시 구간)
                cursor += pad
                timeline.append({**ch, "start_sec": round(start, 3), "end_sec": round(end, 3)})
                lf.write(f"file '{os.path.abspath(norm)}'\n")
                if pad > 0:
                    sp = os.path.join(tmpdir, f"sil{i}.wav")
                    subprocess.check_call([
                        "ffmpeg","-y","-f","lavfi","-i",
                        f"anullsrc=r={sample_rate}:cl=mono","-t",f"{pad}","-c:a","pcm_s16le", sp],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    lf.write(f"file '{os.path.abspath(sp)}'\n")
        # concat → mp3 + loudness normalize (최종 stitched 기준)
        subprocess.check_call([
            "ffmpeg","-y","-f","concat","-safe","0","-i",list_path,
            "-af","loudnorm=I=-16:TP=-1.5:LRA=11","-c:a","libmp3lame","-q:a","2", out_mp3],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    duration = _probe_duration(out_mp3)
    return timeline, round(duration, 3), sample_rate
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tts_service && python -m pytest tests/test_stitch.py -v`
Expected: PASS (2 passed). (ffmpeg/ffprobe 필요 — 로컬엔 설치돼 있음)

- [ ] **Step 5: Commit**

```bash
git add tts_service/app/stitch.py tts_service/tests/test_stitch.py
git commit -m "feat(tts): ffmpeg stitcher with silence padding + ffprobe timeline"
```

---

## Task 4: GPU 상호배제 락 (flock)

**Files:**
- Create: `tts_service/app/gpulock.py`
- Test: `tts_service/tests/test_gpulock.py`

converter(MinerU)와 TTS가 동시에 GPU를 잡지 못하게 공유 파일락(`outputs/.gpu.lock`)을 건다(스펙 §4, §9.4). non-blocking 시도 + 대기 옵션.

- [ ] **Step 1: Write the failing test**

```python
# tts_service/tests/test_gpulock.py
import multiprocessing, time, os
from app.gpulock import gpu_lock, try_acquire

def _hold(lockpath, q, secs):
    with gpu_lock(lockpath):
        q.put("acquired"); time.sleep(secs)

def test_mutual_exclusion(tmp_path):
    lp = str(tmp_path/".gpu.lock")
    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=_hold, args=(lp,q,1.0)); p.start()
    assert q.get(timeout=3) == "acquired"
    # 보유 중엔 non-blocking 획득 실패
    assert try_acquire(lp) is None
    p.join()
    # 해제 후엔 성공
    fh = try_acquire(lp); assert fh is not None; fh.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tts_service && python -m pytest tests/test_gpulock.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# tts_service/app/gpulock.py
import fcntl, os, time
from contextlib import contextmanager

def try_acquire(lockpath):
    """non-blocking. 성공 시 열린 파일핸들(보유), 실패 시 None."""
    os.makedirs(os.path.dirname(lockpath), exist_ok=True)
    fh = open(lockpath, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None

@contextmanager
def gpu_lock(lockpath, timeout=1800, poll=2.0):
    """blocking(타임아웃). converter도 같은 경로로 flock 걸어야 상호배제됨."""
    os.makedirs(os.path.dirname(lockpath), exist_ok=True)
    fh = open(lockpath, "w")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() > deadline:
                fh.close(); raise TimeoutError("GPU lock timeout")
            time.sleep(poll)
    try:
        yield fh
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tts_service && python -m pytest tests/test_gpulock.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add tts_service/app/gpulock.py tts_service/tests/test_gpulock.py
git commit -m "feat(tts): flock-based GPU mutex for converter/TTS coexistence"
```

> **NOTE (별도 작업):** `main_terminal.py`의 PDF→MD 변환부도 동일 `outputs/.gpu.lock`을 `gpu_lock()`으로 감싸야 상호배제가 완성된다. 이 변경은 Task 8에서 docker-compose 통합과 함께 명시한다.

---

## Task 5: 합성 래퍼(synth) — Chatterbox 적재 + 청크 합성

**Files:**
- Create: `tts_service/app/synth.py`

검증된 샘플 스크립트(`/tmp/cbxrun/gen_korean.py`) 기반. perth 워터마커 누락 시 Dummy 대체. 모델은 프로세스당 1회 적재(전역). 단위 테스트는 모델 다운로드가 필요해 CI에서 무거우므로 **smoke는 Task 9 통합에서** 수행하고, 여기서는 인터페이스만 고정한다.

- [ ] **Step 1: Implement synthesizer**

```python
# tts_service/app/synth.py
import torch, torchaudio as ta

_MODEL = None

def _ensure_watermarker():
    # B3: perth는 chatterbox-tts 의존성이라 보통 import 됨(샘플서 확인). 단 방어적으로 처리.
    try:
        import perth
    except ImportError:
        return  # 미설치면 chatterbox 내부 기본동작에 맡김(합성엔 영향 없음)
    if getattr(perth, "PerthImplicitWatermarker", None) is None:  # 워터마커 비활성 시 무음 대체
        perth.PerthImplicitWatermarker = perth.DummyWatermarker

def load_model(device="cuda"):
    global _MODEL
    if _MODEL is None:
        _ensure_watermarker()
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        _MODEL = ChatterboxMultilingualTTS.from_pretrained(device=device)
    return _MODEL

def model_revision():
    m = _MODEL
    return getattr(m, "revision", None) or "unknown" if m else "unknown"

def synth_chunk(text, out_wav, device="cuda", language_id="ko"):
    """청크 1개 → wav 파일. 모델 sr 반환."""
    m = load_model(device)
    wav = m.generate(text, language_id=language_id)
    ta.save(out_wav, wav.cpu() if hasattr(wav, "cpu") else wav, m.sr)
    return m.sr
```

- [ ] **Step 2: Sanity import check (모델 다운로드 없이 import만)**

Run: `cd tts_service && python -c "import app.synth; print('synth import OK')"`
Expected: `synth import OK` (chatterbox-tts 설치된 환경에서)

- [ ] **Step 3: Commit**

```bash
git add tts_service/app/synth.py
git commit -m "feat(tts): Chatterbox-Multilingual synth wrapper (perth Dummy fallback)"
```

---

## Task 6: Job 오케스트레이션 — segment→synth→stitch→manifest→publish

**Files:**
- Create: `tts_service/app/job.py`

`.jobs/<job_id>/`에서 작업 후 검증 통과 시 atomic publish, 청크 삭제(스펙 §2,§8). freshness 시 skip. GPU 락 보유 중 합성.

- [ ] **Step 1: Implement job runner**

```python
# tts_service/app/job.py
import os, json, hashlib, shutil, tempfile, time
from datetime import datetime, timezone
from app.chunker import chunk_markdown
from app.synth import synth_chunk, model_revision
from app.stitch import stitch_chunks
from app.manifest import build_manifest, is_fresh
from app.gpulock import gpu_lock

GPU_LOCK_PATH = os.environ.get("PF_GPU_LOCK", "/data/outputs/.gpu.lock")

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()

def _audio_dir(paper_dir):     return os.path.join(paper_dir, "audio")
def _base(src_md):             return os.path.basename(src_md)[:-len("_ko_audio.md")]

def run_job(paper_dir, src_md, progress_cb=None, device="cuda"):
    """src_md = 절대경로 <base>_ko_audio.md. 반환: manifest dict."""
    base = _base(src_md)
    adir = _audio_dir(paper_dir)
    os.makedirs(adir, exist_ok=True)
    man_path = os.path.join(adir, f"{base}_ko_audio.manifest.json")
    src_sha = _sha256(src_md)
    # B1: 오디오는 content-versioned 파일명 → manifest를 마지막에 교체하면
    # "old manifest + new audio" 경합이 원천 차단(이름이 다르므로 겹침 없음).
    audio_name = f"{base}_ko_audio.{src_sha[:12]}.mp3"
    audio_pub = os.path.join(adir, audio_name)

    # skip: 최신 캐시
    if os.path.exists(man_path):
        try:
            cur = json.load(open(man_path))
            if is_fresh(cur, current_sha256=src_sha) and \
               os.path.exists(os.path.join(adir, cur["audio"]["file"])):
                return cur
        except Exception:
            pass

    md = open(src_md, encoding="utf-8").read()
    chunks = chunk_markdown(md)
    if not chunks:
        raise ValueError("no synthesizable chunks")

    import uuid
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]  # nit#5: 충돌 방지
    jdir = os.path.join(adir, ".jobs", job_id)
    cdir = os.path.join(jdir, "chunks")
    os.makedirs(cdir, exist_ok=True)

    with gpu_lock(GPU_LOCK_PATH):              # converter와 상호배제
        wavs = []
        sr = 24000
        for i, ch in enumerate(chunks):
            wf = os.path.join(cdir, f"{i:06d}.wav")
            sr = synth_chunk(ch["text"], wf, device=device)
            # nit#6: 품질 게이트 — duration=0/ffprobe 실패/극단 ratio면 1회 재시도
            if not _chunk_ok(wf, ch["text"]):
                sr = synth_chunk(ch["text"], wf, device=device)
                if not _chunk_ok(wf, ch["text"]):
                    raise RuntimeError(f"chunk {i} synth failed quality gate: {ch['text'][:30]}")
            wavs.append(wf)
            if progress_cb:
                progress_cb(stage="synthesizing", done=i+1, total=len(chunks))

    if progress_cb: progress_cb(stage="stitching", done=len(chunks), total=len(chunks))
    tmp_mp3 = os.path.join(jdir, f"{base}_ko_audio.mp3")
    timeline, duration, sr = stitch_chunks(wavs, chunks, tmp_mp3, sample_rate=sr)

    if progress_cb: progress_cb(stage="validating", done=len(chunks), total=len(chunks))
    manifest = build_manifest(
        source_path=os.path.basename(src_md), source_sha256=src_sha,
        source_mtime=str(os.path.getmtime(src_md)), audio_file=audio_name,   # B1: 버전드 파일명
        duration_sec=duration, sample_rate=sr, chunks=timeline,
        tts_overrides={"model_revision": model_revision()},
        generated_at=datetime.now(timezone.utc).isoformat())   # nit#2
    assert len(timeline) == len(chunks)

    # B1 atomic publish: 버전드 오디오 먼저 배치(이름이 달라 기존과 겹치지 않음) → manifest 마지막 교체
    os.replace(tmp_mp3, audio_pub)
    tmp_man = man_path + ".tmp"
    json.dump(manifest, open(tmp_man, "w"), ensure_ascii=False)
    os.replace(tmp_man, man_path)              # manifest publish = 완료 마커(원자적)
    # 구버전 오디오 정리(현재 manifest가 가리키는 것만 남김)
    for f in os.listdir(adir):
        if f.startswith(f"{base}_ko_audio.") and f.endswith(".mp3") and f != audio_name:
            try: os.remove(os.path.join(adir, f))
            except OSError: pass
    shutil.rmtree(jdir, ignore_errors=True)    # 성공 시 청크 삭제
    if progress_cb: progress_cb(stage="ready", done=len(chunks), total=len(chunks))
    return manifest

def _chunk_ok(wav_path, text):
    """nit#6: 합성 결과 sanity — 존재 + duration>0 + duration/문자수 ratio 정상."""
    import subprocess, json as _j
    try:
        out = subprocess.check_output(["ffprobe","-v","error","-show_entries",
            "format=duration","-of","json", wav_path])
        dur = float(_j.loads(out)["format"]["duration"])
    except Exception:
        return False
    if dur <= 0:
        return False
    n = max(len(text), 1)
    sec_per_char = dur / n
    return 0.02 <= sec_per_char <= 1.5     # 극단 이상치 차단(0.02~1.5초/자)
```

- [ ] **Step 2: Sanity import**

Run: `cd tts_service && python -c "import app.job; print('job import OK')"`
Expected: `job import OK`

- [ ] **Step 3: Commit**

```bash
git add tts_service/app/job.py
git commit -m "feat(tts): job orchestration with atomic publish + freshness skip"
```

---

## Task 7: TTS 사이드카 HTTP API

**Files:**
- Create: `tts_service/app/main.py`, `tts_service/requirements.txt`, `tts_service/Dockerfile`

viewer가 호출할 내부 API. 논문당 active job 1개(in-memory 상태), 동일 sha 중복요청은 기존 상태 반환.

- [ ] **Step 1: Implement FastAPI app**

```python
# tts_service/app/main.py
import os, threading
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.job import run_job

app = FastAPI()
_jobs = {}          # paper_dir -> {"stage","done","total","error"}
_lock = threading.Lock()

class JobReq(BaseModel):
    paper_dir: str          # 절대경로(공유 볼륨)
    src_md: str             # 절대경로 <base>_ko_audio.md

def _worker(paper_dir, src_md):
    def cb(stage, done, total): 
        with _lock: _jobs[paper_dir] = {"stage": stage, "done": done, "total": total, "error": None}
    try:
        cb("segmenting", 0, 0)
        run_job(paper_dir, src_md, progress_cb=cb)
    except Exception as e:
        with _lock: _jobs[paper_dir] = {"stage": "failed", "done": 0, "total": 0, "error": str(e)}

@app.get("/health")
def health(): return {"ok": True}

_OUTPUTS_ROOT = os.environ.get("PF_OUTPUTS_ROOT", "/data/outputs")

def _under_root(p):                       # nit#7: 방어층 — 임의 절대경로 차단
    rp = os.path.realpath(p)
    return rp == os.path.realpath(_OUTPUTS_ROOT) or rp.startswith(os.path.realpath(_OUTPUTS_ROOT) + os.sep)

@app.post("/jobs")
def create(req: JobReq):
    if not (_under_root(req.paper_dir) and _under_root(req.src_md)):
        raise HTTPException(400, "path outside outputs root")
    if not os.path.exists(req.src_md):
        raise HTTPException(404, "src_md not found")
    with _lock:
        st = _jobs.get(req.paper_dir)
        if st and st["stage"] not in ("ready", "failed"):
            return {"accepted": False, "status": st}     # 이미 진행 중
        _jobs[req.paper_dir] = {"stage": "segmenting", "done": 0, "total": 0, "error": None}
    threading.Thread(target=_worker, args=(req.paper_dir, req.src_md), daemon=True).start()
    return {"accepted": True}

@app.get("/jobs")
def status(paper_dir: str):
    with _lock:
        return _jobs.get(paper_dir, {"stage": "none", "done": 0, "total": 0, "error": None})
```

- [ ] **Step 2: Write requirements + Dockerfile**

```text
# tts_service/requirements.txt
chatterbox-tts
fastapi
uvicorn[standard]
```

```dockerfile
# tts_service/Dockerfile
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y python3 python3-pip ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8100
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8100"]
```

- [ ] **Step 3: Run app locally (smoke, GPU 환경)**

Run: `cd tts_service && uvicorn app.main:app --port 8100 & sleep 2 && curl -s localhost:8100/health`
Expected: `{"ok":true}`

- [ ] **Step 4: Commit**

```bash
git add tts_service/app/main.py tts_service/requirements.txt tts_service/Dockerfile
git commit -m "feat(tts): sidecar FastAPI (jobs/status/health) + Docker image"
```

---

## Task 8: docker-compose 통합 + converter GPU 락

**Files:**
- Modify: `docker-compose.yml`
- Modify: `main_terminal.py` (PDF→MD 구간을 `outputs/.gpu.lock` flock으로 감쌈)

- [ ] **Step 1: Add tts service to compose**

```yaml
# docker-compose.yml 에 추가 (nit#8: 기존 converter와 동일한 runtime: nvidia + NVIDIA env 패턴)
  paperflow-tts:
    build: ./tts_service
    container_name: paperflow_tts
    runtime: nvidia
    volumes:
      - ./outputs:/data/outputs
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,utility
      - PF_GPU_LOCK=/data/outputs/.gpu.lock      # converter의 /app/outputs/.gpu.lock 과 동일 호스트 파일
      - PF_OUTPUTS_ROOT=/data/outputs
    expose: ["8100"]
```

- [ ] **Step 2: viewer가 tts에 접근하도록 env 추가**

`docker-compose.yml`의 `paperflow-viewer.environment`에 `- TTS_SERVICE_URL=http://paperflow-tts:8100` 추가.

- [ ] **Step 3: converter도 같은 GPU 락 사용 (B2 경로 교정)**

converter 컨테이너는 outputs를 **`/app/outputs`** 로 마운트한다(viewer/TTS의 `/data/outputs`와 다름, 그러나 같은 호스트 디렉터리 `./outputs`). flock은 같은 호스트 inode면 컨테이너 간에도 상호배제되므로:
- converter: `PF_GPU_LOCK=/app/outputs/.gpu.lock`
- TTS: `PF_GPU_LOCK=/data/outputs/.gpu.lock`
- 둘은 **같은 호스트 파일 `./outputs/.gpu.lock`** → flock 상호배제 성립.

`main_terminal.py`의 `convert_pdf_to_md_dispatch()` 호출부를, `gpulock.py`의 `gpu_lock()`과 동일 로직(flock)을 인라인 복제해 감싼다. 락 경로는 환경변수 `PF_GPU_LOCK`(기본 `/app/outputs/.gpu.lock`)에서 읽는다. compose의 converter `environment`에 `- PF_GPU_LOCK=/app/outputs/.gpu.lock` 추가.

- [ ] **Step 4: Build + smoke**

Run: `docker compose build paperflow-tts && docker compose up -d paperflow-tts && sleep 5 && docker compose exec paperflow-viewer curl -s http://paperflow-tts:8100/health`
Expected: `{"ok":true}`

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml main_terminal.py
git commit -m "feat(tts): compose sidecar + shared GPU lock with converter"
```

---

## Task 9: viewer API 엔드포인트 6개

**Files:**
- Create: `viewer/app/services/audio.py`
- Modify: `viewer/app/routers/api.py`
- Test: `viewer/tests/test_audio_api.py`   (nit#9: 기존 저장소 pytest 관례 `viewer/tests/`)

스펙 §5 엔드포인트. 경로는 `safe_paper_dir*` resolve, `audio/` 격리, 오디오는 `FileResponse`(Range). 듣기 진행률은 읽기와 분리 저장. **B1**: 오디오 파일명은 버전드(`<base>_ko_audio.<sha12>.mp3`)이므로 `audio_file_path`는 manifest의 `audio.file`을 읽어 결정한다.

- [ ] **Step 1: Write failing test (manifest/file/progress 경로)**

```python
# viewer/tests/test_audio_api.py
import json
from app.services import audio as a

def test_audio_file_path_from_manifest(tmp_path, monkeypatch):
    paper = tmp_path/"P"; (paper/"audio").mkdir(parents=True)
    (paper/"audio"/"P_ko_audio.abc123def456.mp3").write_bytes(b"x")
    (paper/"audio"/"P_ko_audio.manifest.json").write_text(
        json.dumps({"status":"complete","audio":{"file":"P_ko_audio.abc123def456.mp3"}}))
    (paper/"P_ko_audio.md").write_text("# t\n\n본문.")
    monkeypatch.setattr(a, "_resolve_paper_dir", lambda name: paper)
    assert a.audio_file_path("P").name == "P_ko_audio.abc123def456.mp3"   # B1: manifest가 가리키는 버전드 파일
    assert a.manifest_path("P").name.endswith(".manifest.json")

def test_listening_progress_separate_from_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_progress_file", lambda: tmp_path/"listen.json")
    a.save_listening_progress("P", {"chunk_id":3,"time_sec":12.0,"percent":10,"audio_version":"sha:x"})
    got = a.get_listening_progress("P")
    assert got["chunk_id"] == 3 and got["percent"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd viewer && python -m pytest tests/test_audio_api.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.audio`)

- [ ] **Step 3: Implement service**

```python
# viewer/app/services/audio.py
import json, os
from pathlib import Path
from .papers import safe_paper_dir          # 기존 경로 안전 헬퍼 재사용
from ..config import settings

def _resolve_paper_dir(name):
    return safe_paper_dir(name)

def _base_for(paper_dir: Path):
    for f in paper_dir.glob("*_ko_audio.md"):
        return f.name[:-len("_ko_audio.md")]
    return None

def manifest_path(name):
    d = _resolve_paper_dir(name)
    if not d: return None
    b = _base_for(d)
    return d/"audio"/f"{b}_ko_audio.manifest.json" if b else None

def _under_audio_dir(candidate: Path, base: Path) -> bool:
    """traversal 방어(nit#4): candidate가 base(=해당 논문 audio/) 하위로 resolve 되는지 base-relative로 확인."""
    try:
        br = base.resolve()
        cr = candidate.resolve()
        return cr == br or br in cr.parents
    except Exception:
        return False

def audio_file_path(name):
    # B1: manifest의 audio.file(버전드 파일명)을 읽어 결정
    mp = manifest_path(name)
    if not mp or not mp.exists(): return None
    try:
        man = json.loads(mp.read_text())
        fn = man.get("audio", {}).get("file")
        if not fn: return None
        return mp.parent / fn
    except Exception:
        return None

def _progress_file():
    return Path(settings.base_dir)/"listening_progress.json"

def _load(p):
    try: return json.loads(Path(p).read_text())
    except Exception: return {}

def get_listening_progress(name):
    return _load(_progress_file()).get(name, {})

def save_listening_progress(name, payload):
    pf = Path(_progress_file()); pf.parent.mkdir(parents=True, exist_ok=True)  # nit#6
    data = _load(pf); data[name] = payload
    tmp = pf.with_suffix(".json.tmp")                 # nit#10: atomic write
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    os.replace(tmp, pf)
```

- [ ] **Step 4: Add endpoints to api.py**

```python
# viewer/app/routers/api.py 에 추가
import httpx
from ..services import audio as audio_svc
from ..config import settings

@router.post("/papers/{name:path}/audio/jobs")
async def audio_job(name: str, _user: str = Depends(get_current_user_api)):
    d = audio_svc._resolve_paper_dir(name)
    if not d: raise HTTPException(404, "paper not found")
    src = next(iter(d.glob("*_ko_audio.md")), None)
    if not src: raise HTTPException(404, "no _ko_audio.md")
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{settings.tts_service_url}/jobs",
                         json={"paper_dir": str(d), "src_md": str(src)}, timeout=30)
    return r.json()

@router.get("/papers/{name:path}/audio/status")
async def audio_status(name: str, _user: str = Depends(get_current_user_api)):
    d = audio_svc._resolve_paper_dir(name)
    if not d: raise HTTPException(404)
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{settings.tts_service_url}/jobs", params={"paper_dir": str(d)}, timeout=10)
    return r.json()

@router.get("/papers/{name:path}/audio/manifest")
async def audio_manifest(name: str, _user: str = Depends(get_current_user_api)):
    p = audio_svc.manifest_path(name)
    if not p or not p.exists(): raise HTTPException(404)
    return FileResponse(p, media_type="application/json")

@router.get("/papers/{name:path}/audio/file")
async def audio_file(name: str, file: str | None = None, _user: str = Depends(get_current_user_api)):
    # B4: 프론트가 로드한 manifest의 audio.file을 명시하면 그 버전드 파일을 서빙(timeline 정합).
    #     생략 시 현재 manifest가 가리키는 파일. 어느 경우든 traversal 방어 + 존재 검증.
    cur = audio_svc.audio_file_path(name)                 # 현재 manifest의 audio.file
    if not cur: raise HTTPException(404)
    target = cur
    if file:
        import re as _re
        if not _re.fullmatch(r"[^/\\]+_ko_audio\.[0-9a-f]{12}\.mp3", file):
            raise HTTPException(400, "bad file")
        cand = cur.parent / file
        if not audio_svc._under_audio_dir(cand, cur.parent): raise HTTPException(400, "path")
        target = cand
    if not target.exists(): raise HTTPException(404)      # 정리된 구버전 → 프론트가 onAudioError로 재로드
    return FileResponse(target, media_type="audio/mpeg")  # Starlette가 Range 처리

@router.get("/papers/{name:path}/audio/progress")
async def get_audio_progress(name: str, _user: str = Depends(get_current_user_api)):
    return audio_svc.get_listening_progress(name)

@router.post("/papers/{name:path}/audio/progress")
async def save_audio_progress(name: str, payload: dict, _user: str = Depends(get_current_user_api)):
    audio_svc.save_listening_progress(name, payload)
    return {"ok": True}
```

(config.py에 `tts_service_url: str = "http://paperflow-tts:8100"` 추가.)

- [ ] **Step 5: Run tests**

Run: `cd viewer && python -m pytest tests/test_audio_api.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add viewer/app/services/audio.py viewer/app/routers/api.py viewer/app/config.py viewer/tests/test_audio_api.py
git commit -m "feat(viewer): audio API endpoints (jobs/status/manifest/file/progress)"
```

---

## Task 10: 통합 스모크 (실제 오디오 생성 + Range)

**Files:** (없음 — 검증만)

- [ ] **Step 1: 전체 빌드 + 기동**

Run: `docker compose build && docker compose up -d`
Expected: 3개 컨테이너 Up (viewer, converter, tts)

- [ ] **Step 2: 듣기판 있는 논문으로 job 생성**

Run (로그인 쿠키 cj 획득 후):
```bash
P=$(python3 -c "import urllib.parse;print(urllib.parse.quote('Building effective agents'))")
curl -s -b cj -X POST localhost:8090/api/papers/$P/audio/jobs
# 폴링
curl -s -b cj localhost:8090/api/papers/$P/audio/status
```
Expected: `{"accepted":true}` → status가 synthesizing→stitching→ready로 진행

- [ ] **Step 3: manifest + 오디오 + Range 검증**

```bash
curl -s -b cj localhost:8090/api/papers/$P/audio/manifest | python3 -c "import sys,json;m=json.load(sys.stdin);print(m['status'], len(m['chunks']), m['audio']['duration_sec'])"
curl -s -b cj -D- -o /dev/null -H "Range: bytes=0-1023" localhost:8090/api/papers/$P/audio/file | grep -i "accept-ranges\|content-range\|206"
```
Expected: `complete N <duration>` + `HTTP/1.1 206 Partial Content` + `Accept-Ranges: bytes`

- [ ] **Step 4: 산출물 구조 확인(청크 폐기됨)**

```bash
ls outputs/Building\ effective\ agents/audio/
```
Expected: `*_ko_audio.*.mp3`(버전드), `*_ko_audio.manifest.json` 만 존재(`.jobs/` 없음, 청크 폐기됨)

- [ ] **Step 5: Commit (검증 메모는 HANDOFF/상태파일에)**

검증 결과를 상태 파일에 기록(자동 커밋 아님).

---

## Self-Review 결과

- **Spec coverage**: §2 아키텍처→Task6,8 / §3 manifest→Task2,6 / §4 컴포넌트→Task1\~7 / §5 엔드포인트→Task9 / §8 atomic publish·검증→Task6,10 / §9 Range·동시성·격리→Task4,8,9,10. 배너 제외→Task1. **읽기/듣기 진행률 분리→Task9.** UI(§6)는 Plan 2.
- **Placeholder scan**: 코드 스텝 모두 실제 코드 포함. 품질 게이트(`_chunk_ok`: duration>0·ratio 검증)와 1회 재시도는 Task6에 실제 코드로 구현됨. heading/text별 ratio 세분화만 v1.1 튜닝 대상.
- **Type consistency**: 청크 dict 키(id/kind/dom_id/section_id/paragraph_index/sentence_index/text/start_sec/end_sec)가 chunker→stitch→manifest→job 전반 일치. `is_fresh`/`build_manifest` 시그니처 일치.

## 미해결 → Plan 2 (프론트엔드)
서버 렌더 오디오 HTML(`/audio/html`), viewer.html Alpine 플레이어(단일 `<audio>`, `timeupdate` 하이라이트, 문장 prev/next, tap-to-play, auto-follow, playbackRate, 이어듣기), MediaSession, 듣기 토글 연동.
