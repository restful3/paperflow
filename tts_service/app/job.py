import os, json, hashlib, shutil, time
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


def _audio_dir(paper_dir):
    return os.path.join(paper_dir, "audio")


def _base(src_md):
    return os.path.basename(src_md)[:-len("_ko_audio.md")]


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
                progress_cb(stage="synthesizing", done=i + 1, total=len(chunks))

    if progress_cb:
        progress_cb(stage="stitching", done=len(chunks), total=len(chunks))
    tmp_mp3 = os.path.join(jdir, f"{base}_ko_audio.mp3")
    timeline, duration, sr = stitch_chunks(wavs, chunks, tmp_mp3, sample_rate=sr)

    if progress_cb:
        progress_cb(stage="validating", done=len(chunks), total=len(chunks))
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
            try:
                os.remove(os.path.join(adir, f))
            except OSError:
                pass
    shutil.rmtree(jdir, ignore_errors=True)    # 성공 시 청크 삭제
    try:
        os.rmdir(os.path.join(adir, ".jobs"))  # 비어있을 때만 성공(동시 job 있으면 OSError → 무시)
    except OSError:
        pass
    if progress_cb:
        progress_cb(stage="ready", done=len(chunks), total=len(chunks))
    return manifest


def _chunk_ok(wav_path, text):
    """nit#6: 합성 결과 sanity — 존재 + duration>0 + duration/문자수 ratio 정상."""
    import subprocess, json as _j
    try:
        out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "json", wav_path])
        dur = float(_j.loads(out)["format"]["duration"])
    except Exception:
        return False
    if dur <= 0:
        return False
    n = max(len(text), 1)
    sec_per_char = dur / n
    return 0.02 <= sec_per_char <= 1.5     # 극단 이상치 차단(0.02~1.5초/자)
