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
