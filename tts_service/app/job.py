import os, json, hashlib, shutil, time, glob, fcntl, threading
from app.chunker import chunk_markdown
from app.synth import synth_chunk, model_revision
from app.stitch import stitch_chunks, pad_for
from app.hls import encode_segment, LivePlaylist, TARGETDURATION
from app.manifest import (build_manifest_v2, merge_chunk_timing,
                          is_fresh_for_playback, compute_audio_version, _now_iso)
from app.gpulock import gpu_lock

GPU_LOCK_PATH = os.environ.get("PF_GPU_LOCK", "/data/outputs/.gpu.lock")


class Preempted(Exception):
    """foreground 가 다른 논문으로 바뀌어 이 백그라운드 합성이 협조적으로 양보됨."""


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


def _paper_lock(adir, sha12):
    """같은 paper-version 동시 쓰기 차단. 이미 진행 중이면 BlockingIOError(OSError)."""
    os.makedirs(os.path.join(adir, ".locks"), exist_ok=True)
    fh = open(os.path.join(adir, ".locks", f"{sha12}.lock"), "w")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fh


def run_job(paper_dir, src_md, progress_cb=None, device="cuda", is_active=None):
    """src_md = 절대경로 <base>_ko_audio.md. HLS 증분 publish + 완료 mp3. 반환: manifest dict.
    is_active: 호출 시 False 면 foreground 가 다른 논문으로 바뀐 것 → 청크 사이에서 Preempted 로 양보."""
    base = _base(src_md)
    adir = _audio_dir(paper_dir)
    os.makedirs(adir, exist_ok=True)
    src_sha = _sha256(src_md)
    tts_over = {"model_revision": model_revision()}
    version = compute_audio_version(src_sha, tts_over)  # source sha + cache-key digest (Codex Finding 2)
    man_path = os.path.join(adir, f"{base}_ko_audio.manifest.json")
    hls_dir = os.path.join(adir, f"{base}_ko_audio.{version}")
    seg_dir = hls_dir                                  # 세그먼트는 hls_dir 직하위
    mp3_name = f"{base}_ko_audio.{version}.mp3"

    # freshness skip: 완료된 동일 버전 HLS 가 이미 있으면 재사용
    if os.path.exists(man_path):
        try:
            cur = json.load(open(man_path))
            if is_fresh_for_playback(cur, src_sha) and cur.get("audio", {}).get("hls"):
                if progress_cb:
                    progress_cb(stage="ready", done=0, total=0)
                return cur
        except Exception:
            pass

    lock = _paper_lock(adir, version)                  # 같은 아티팩트 버전 동시 쓰기 차단
    try:
        md = open(src_md, encoding="utf-8").read()
        chunks = chunk_markdown(md)
        text_chunks = [c for c in chunks if c["kind"] == "text"]
        if not text_chunks:
            raise ValueError("no synthesizable chunks")

        os.makedirs(seg_dir, exist_ok=True)
        manifest = build_manifest_v2(
            os.path.basename(src_md), src_sha, chunks, sample_rate=24000,
            source_mtime=str(os.path.getmtime(src_md)),
            tts_overrides=tts_over)                     # audio.version == 위 version 과 동일 산식
        manifest["heartbeat"] = _now_iso()             # 생성 시점부터 heartbeat 시작 →
        _publish_manifest(man_path, manifest)          # reconcile_stale 이 막 시작한 job 을 죽이지 않음
        # (전체 chunks 즉시 publish, status=streaming. 첫 세그먼트 전 GPU 대기 중에도 stale 아님)
        playlist = LivePlaylist(os.path.join(hls_dir, "stream.m3u8"))

        seg_wavs = []          # mp3 stitch 용 (heading 포함, MVP 정합)
        cursor = 0.0
        total = len(chunks)    # heading+text 전부 세그먼트(MVP 가 heading 도 합성)
        with gpu_lock(GPU_LOCK_PATH):                  # converter 와 상호배제
            for i, ch in enumerate(chunks):
                if is_active is not None and not is_active():   # foreground 가 바뀜 → 양보(gpu_lock 해제)
                    raise Preempted(f"yielded at chunk {i}/{len(chunks)}")
                wf = os.path.join(seg_dir, f".w{i:06d}.wav")
                pad = pad_for(ch["kind"], chunks[i + 1]["kind"]) if i < len(chunks) - 1 else 0.0
                seg_name = f"seg_{i:06d}.ts"
                dur = _synth_encode_with_retry(ch, wf, pad, os.path.join(seg_dir, seg_name), device)
                if dur is None:                          # 품질/과길이 재시도 후에도 실패 → partial
                    return _fail_partial(playlist, man_path, manifest,
                                         f"chunk {i} failed (quality/over-length)")
                playlist.append(seg_name, dur)
                merge_chunk_timing(manifest, ch["id"], cursor, cursor + dur)
                cursor += dur
                manifest["heartbeat"] = _now_iso()
                _publish_manifest(man_path, manifest)
                seg_wavs.append(wf)
                if progress_cb:
                    progress_cb(stage="synthesizing", done=len(seg_wavs), total=total)

        # 완료: ENDLIST + mp3 stitch(heading 포함 전체)
        playlist.finalize()
        if progress_cb:
            progress_cb(stage="stitching", done=total, total=total)
        mp3_tmp = os.path.join(seg_dir, ".out.mp3")
        stitch_chunks(seg_wavs, chunks, mp3_tmp, sample_rate=24000)
        os.replace(mp3_tmp, os.path.join(adir, mp3_name))
        manifest["audio"]["mp3"]["file"] = mp3_name
        manifest["status"] = "complete"
        manifest["generated_at"] = _now_iso()
        _publish_manifest(man_path, manifest)
        for wf in seg_wavs:                             # 임시 wav 폐기
            try:
                os.remove(wf)
            except OSError:
                pass
        _cleanup_old_versions(adir, base, keep_sha12=version)
        if progress_cb:
            progress_cb(stage="ready", done=total, total=total)
        return manifest
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def _synth_encode_with_retry(ch, wf, pad, out_ts, device):
    """합성→품질게이트→encode(길이게이트). 실패 시 1회 재합성(TTS 분산) 후 재시도.
    반환: duration 또는 None(2회 실패).
    NOTE(BLOCKING#1): chunker(Task2)가 SENTENCE_CHAR_CAP 으로 길이를 1차 제한하므로 post-encode
    과길이는 모델 이상치(glitch)다. upfront-publish 모델(전체 chunks 고정 id)을 깨지 않기 위해
    '재분할' 대신 '재합성'으로 1회 재시도하고, 그래도 초과면 failed_partial.
    (synth_chunk/_chunk_ok/encode_segment 는 모듈 전역 — 테스트 monkeypatch 가능)"""
    timeout = int(os.environ.get("SYNTH_CHUNK_TIMEOUT", "90"))   # 정상 청크 ~2~20s, wedge 는 분 단위
    for _attempt in (1, 2):
        try:
            _synth_with_timeout(ch["text"], wf, device, timeout)
        except TimeoutError:
            return None                                  # wedge → 즉시 실패(재시도 시 GPU 동시 generate 회피)
        if not _chunk_ok(wf, ch["text"]):
            continue                                     # 품질게이트 실패 → 재합성
        try:
            return encode_segment(wf, pad, out_ts)       # 길이게이트 통과 시 duration
        except ValueError:
            continue                                     # 과길이 → 재합성(분산으로 짧아질 수 있음)
    return None


def _synth_with_timeout(text, wf, device, timeout):
    """synth_chunk 를 워치독 스레드로 감싸 timeout 초 안에 안 끝나면 TimeoutError.
    이번 인시던트: 모델/GPU 열화로 첫 청크 generate() 가 wedge → 4분+ 멈춤, heartbeat 동결,
    실패도 안 함 → 무한 '준비 중'. 타임아웃이면 failed_partial 로 풀어 사용자를 멈춤에서 해방한다.
    한계: CUDA 커널은 인터럽트 불가라 wedge 된 데몬 스레드는 계속 GPU 를 쓰다 컨테이너 재시작 시 정리됨
    (job 상태/락은 즉시 풀림). synth_chunk 는 모듈 전역 — 테스트 monkeypatch 가능."""
    box = {}

    def _run():
        try:
            synth_chunk(text, wf, device=device)
            box["ok"] = True
        except BaseException as e:                       # noqa: BLE001 — 스레드 예외를 호출자로 전파
            box["err"] = e

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f"synth_chunk wedged (> {timeout}s)")
    if "err" in box:
        raise box["err"]


def _publish_manifest(path, manifest):
    tmp = path + ".tmp"
    json.dump(manifest, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, path)


def _fail_partial(playlist, man_path, manifest, reason):
    playlist.finalize()                                 # 앞부분 재생 가능
    manifest["status"] = "failed_partial"
    manifest["generated_at"] = _now_iso()
    manifest["audio"]["mp3"]["file"] = None
    _publish_manifest(man_path, manifest)
    raise RuntimeError(f"partial: {reason}")


def _version_sha(name):
    """'<base>_ko_audio.<sha12>' 또는 '<base>_ko_audio.<sha12>.mp3' → sha12."""
    import re
    m = re.search(r"_ko_audio\.([0-9a-f]{12})(?:\.mp3)?$", name)
    return m.group(1) if m else None


def _cleanup_old_versions(adir, base, keep_sha12, keep=2, grace_sec=None):
    """HLS 디렉터리 + mp3 를 version(sha12) 단위로 묶어 정리.
    삭제 조건(HIGH#2, 스펙 §8.3): 현재 버전 아님 AND 최근 keep 밖 AND
    age > max(AUDIO_TOKEN_TTL+RESUME_GRACE, 1h) — active segment token grace 보장."""
    if grace_sec is None:
        grace_sec = max(int(os.environ.get("AUDIO_TOKEN_TTL", "43200")) +
                        int(os.environ.get("AUDIO_RESUME_GRACE", "3600")), 3600)
    now = time.time()
    versions = {}   # sha12 -> [mtime, [paths]]
    for p in glob.glob(os.path.join(adir, f"{base}_ko_audio.*")):
        sha = _version_sha(os.path.basename(p))
        if not sha:
            continue
        versions.setdefault(sha, [0.0, []])
        versions[sha][1].append(p)
        try:
            versions[sha][0] = max(versions[sha][0], os.path.getmtime(p))
        except OSError:
            pass
    ordered = sorted(versions.items(), key=lambda kv: kv[1][0], reverse=True)
    for idx, (sha, (mtime, paths)) in enumerate(ordered):
        if sha == keep_sha12 or idx < keep:
            continue
        if (now - mtime) <= grace_sec:                   # 아직 active token grace 내 → 보존
            continue
        for p in paths:                                  # 구버전 HLS dir + mp3 함께 정리
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass


def _chunk_ok(wav_path, text):
    """합성 결과 sanity — 존재 + duration>0 + duration/문자수 ratio 정상."""
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
