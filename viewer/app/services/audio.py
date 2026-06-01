import json, os, re as _re, time
from html import escape
from pathlib import Path

from .papers import safe_paper_dir, safe_paper_dir_at_location   # 기존 경로 안전 헬퍼 재사용
from ..config import settings


def _resolve_paper_dir(name):
    return safe_paper_dir(name)


def _base_for(paper_dir: Path):
    for f in paper_dir.glob("*_ko_audio.md"):
        return f.name[:-len("_ko_audio.md")]
    return None


def manifest_path(name):
    d = _resolve_paper_dir(name)
    if not d:
        return None
    b = _base_for(d)
    return d / "audio" / f"{b}_ko_audio.manifest.json" if b else None


def _under_audio_dir(candidate: Path, base: Path) -> bool:
    """traversal 방어: candidate가 base(=해당 논문 audio/) 하위로 resolve 되는지 base-relative로 확인."""
    try:
        br = base.resolve()
        cr = candidate.resolve()
        return cr == br or br in cr.parents
    except Exception:
        return False


def audio_file_path(name):
    # B1: manifest의 audio.file(버전드 파일명)을 읽어 결정
    mp = manifest_path(name)
    if not mp or not mp.exists():
        return None
    try:
        man = json.loads(mp.read_text())
        fn = man.get("audio", {}).get("file")
        if not fn:
            return None
        return mp.parent / fn
    except Exception:
        return None


def _progress_file():
    # reading_progress.json 과 같은 위치(outputs/)에 듣기 진행률을 분리 저장
    return settings.outputs_dir / "listening_progress.json"


def _load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return {}


def get_listening_progress(name):
    return _load(_progress_file()).get(name, {})


def save_listening_progress(name, payload):
    pf = Path(_progress_file()); pf.parent.mkdir(parents=True, exist_ok=True)
    data = _load(pf); data[name] = payload
    tmp = pf.with_suffix(".json.tmp")                 # nit#10: atomic write
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    os.replace(tmp, pf)


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


def _audio_version(man):
    # 아티팩트 버전(Codex Finding 2). 구버전 manifest 는 source sha[:12] 로 폴백.
    v = (man.get("audio") or {}).get("version")
    if v: return v
    return ((man.get("source") or {}).get("sha256") or "")[:12] or None


def _hls_dir(name):
    man = _manifest_dict(name)
    if not man: return None
    ver = _audio_version(man)
    base = _base_for(_resolve_paper_dir(name))
    if not ver or not base: return None
    return manifest_path(name).parent / f"{base}_ko_audio.{ver}"


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
    return cand if cand.exists() else None    # ← Task 9 가 404 로 변환 (FileResponse 500 방지)


def source_id_and_sha(name):                   # 토큰 바인딩용 (sha 자리 = 아티팩트 버전)
    man = _manifest_dict(name)
    if not man: return None, None
    src = (man.get("source") or {})
    return src.get("path"), (_audio_version(man) or "")


def resolve_for_audio(name, location=None):
    """오디오 생성 대상 해석 + 검증 → (paper_dir, src_md). 불가 시 ValueError(명확한 사유).
    제약: tts 는 outputs/ 만 받음(아카이브 불가), 합성엔 _ko_audio.md(낭독본) 선행 필요."""
    d = safe_paper_dir_at_location(name, location) if location else safe_paper_dir(name)
    if not d:
        raise ValueError(f"paper not found: {name}")
    out = settings.outputs_dir.resolve()
    rd = d.resolve()
    if rd != out and out not in rd.parents:
        raise ValueError("audio generation requires the paper in outputs/ (archived papers are not supported)")
    src = next(iter(d.glob("*_ko_audio.md")), None)
    if not src:
        raise ValueError("no _ko_audio.md — create the narration with the paper-audio-korean skill first")
    return d, src


def is_synthesis_active(name, fresh_sec=120):
    """status='streaming' 이고 heartbeat 가 최근(fresh_sec 이내)이면 합성 진행 중 → True.
    재생성/삭제가 실행 중 워커의 audio 디렉터리를 지워 자폭하는 것을 막는 가드용."""
    from datetime import datetime, timezone
    man = _manifest_dict(name)
    if not man or man.get("status") != "streaming":
        return False
    hb = man.get("heartbeat")
    try:
        if hb:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb)).total_seconds()
        else:
            p = manifest_path(name)
            age = max(0.0, time.time() - p.stat().st_mtime)
    except Exception:
        return False
    return age < fresh_sec


def delete_audio(name):
    """생성된 오디오 산출물(audio/ 디렉터리 전체)과 그 논문의 듣기 진행률을 제거. idempotent."""
    import shutil
    d = _resolve_paper_dir(name)
    if not d:
        return False
    adir = d / "audio"
    if adir.exists():
        shutil.rmtree(adir, ignore_errors=True)
    pf = Path(_progress_file())                       # 듣기 진행률에서 이 논문 항목만 제거
    data = _load(pf)
    if name in data:
        del data[name]
        tmp = pf.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False)); os.replace(tmp, pf)
    return True


def reconcile_stale(name, threshold_sec=1800):
    """status='streaming' 인데 heartbeat 가 threshold(기본 30분) 이상 멈췄으면 'failed' 로 atomic 전이. 전이 시 True."""
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
        if hb:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb)).total_seconds()
        else:
            # heartbeat 부재(구버전/중단된 쓰기/막 생성) → 파일 mtime 을 last-activity 대용으로.
            # 방금 쓰인 manifest 를 stale 로 오판해 죽이지 않도록(Codex 방어 제안).
            age = max(0.0, time.time() - p.stat().st_mtime)
    except Exception:
        age = 1e9
    if age < threshold_sec: return False
    # M1: 재생 가능한 prefix(HLS 세그먼트 ≥1)가 있으면 'failed' 가 아니라 'failed_partial' 로 전이한다.
    # audio_html/프론트 audioReady 는 streaming/complete/failed_partial 만 허용하므로, 평범한 'failed'
    # 는 이미 생성된 앞부분까지 통째로 막아버린다. 세그먼트가 있으면 playlist 를 finalize(ENDLIST)해
    # 앞부분이 VOD 로 끊김 없이 재생되게 한다.
    pl = hls_playlist_path(name)
    man["status"] = "failed_partial" if (pl and _finalize_playlist_if_segments(pl)) else "failed"
    tmp = str(p) + ".tmp"; Path(tmp).write_text(json.dumps(man, ensure_ascii=False)); os.replace(tmp, p)
    return True


def _finalize_playlist_if_segments(pl: Path) -> bool:
    """EVENT playlist 에 세그먼트(≥1)가 있으면 #EXT-X-ENDLIST 를 덧붙여 VOD 로 마감(idempotent)하고
    True. 세그먼트가 없으면(재생할 게 없음) False."""
    try:
        text = pl.read_text()
    except Exception:
        return False
    if not any(ln.startswith("seg/") for ln in text.splitlines()):
        return False
    if "#EXT-X-ENDLIST" not in text:
        if not text.endswith("\n"):
            text += "\n"
        text += "#EXT-X-ENDLIST\n"
        tmp = str(pl) + ".tmp"; Path(tmp).write_text(text); os.replace(tmp, pl)
    return True


def render_audio_html(manifest: dict) -> str:
    """manifest.chunks만으로 문장-span HTML 생성(단일 진실원천, marked 우회).
    heading→<hN id=dom_id>, text→문단 안 <span id=dom_id>. 같은 paragraph_index는 한 <p>."""
    out = []
    cur_para = None
    para_open = False

    def close_para():
        nonlocal para_open
        if para_open:
            out.append("</p>"); para_open = False

    for ch in manifest.get("chunks", []):
        cid, dom, text = ch["id"], ch["dom_id"], escape(ch["text"])
        if ch["kind"] == "heading":
            close_para()
            lvl = min(max(int(ch.get("level", 2)), 1), 6)
            out.append(f'<h{lvl} id="{dom}" data-tts-chunk="{cid}">{text}</h{lvl}>')
            cur_para = None
        else:
            if ch.get("paragraph_index") != cur_para:
                close_para(); out.append("<p>"); para_open = True
                cur_para = ch.get("paragraph_index")
            out.append(f'<span id="{dom}" data-tts-chunk="{cid}">{text}</span> ')
    close_para()
    return "".join(out)
