import json, os
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
