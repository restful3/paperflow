import json, os, re as _re
from html import escape
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
    return cand if cand.exists() else None    # ← Task 9 가 404 로 변환 (FileResponse 500 방지)


def source_id_and_sha(name):                   # 토큰 바인딩용
    man = _manifest_dict(name)
    if not man: return None, None
    src = (man.get("source") or {})
    return src.get("path"), (src.get("sha256") or "")[:12]


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
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb)).total_seconds() if hb else 1e9
    except Exception:
        age = 1e9
    if age < threshold_sec: return False
    man["status"] = "failed"
    tmp = str(p) + ".tmp"; Path(tmp).write_text(json.dumps(man, ensure_ascii=False)); os.replace(tmp, p)
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
