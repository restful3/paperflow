import re
import shutil
from pathlib import Path

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

from ..config import settings


def _dir_size_mb(path: Path) -> float:
    try:
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return total / (1024 * 1024)
    except Exception:
        return 0.0


def _paper_info(paper_dir: Path, location: str) -> dict:
    """Build info dict for a single paper directory."""
    files: dict[str, bool] = {
        "html": False,
        "html_ko": False,
        "pdf": False,
        "md_ko": False,
        "md_en": False,
    }
    for f in paper_dir.iterdir():
        if not f.is_file():
            continue
        if f.name.endswith("_ko.html"):
            files["html_ko"] = True
            files["html"] = True  # backward compat: at least one HTML exists
        elif f.name.endswith(".html") and not f.name.endswith("_ko.html"):
            files["html"] = True
        elif f.name.endswith(".pdf"):
            files["pdf"] = True
        elif f.name.endswith("_ko.md"):
            files["md_ko"] = True
        elif f.name.endswith(".md") and not f.name.endswith("_ko.md"):
            files["md_en"] = True

    return {
        "name": paper_dir.name,
        "location": location,
        "formats": files,
        "size_mb": round(_dir_size_mb(paper_dir), 1),
    }


def list_papers(tab: str = "unread") -> list[dict]:
    if tab == "archived":
        base = settings.archives_dir
        location = "archives"
    else:
        base = settings.outputs_dir
        location = "outputs"

    if not base.exists():
        return []

    papers = []
    for item in sorted(base.iterdir(), key=lambda p: p.name):
        if item.is_dir() and not item.name.startswith("."):
            papers.append(_paper_info(item, location))
    return papers


def get_paper_info(name: str) -> dict | None:
    """Find paper in outputs or archives and return info."""
    for base, loc in [(settings.outputs_dir, "outputs"), (settings.archives_dir, "archives")]:
        paper_dir = base / name
        if paper_dir.is_dir():
            return _paper_info(paper_dir, loc)
    return None


def _resolve_paper_dir(name: str) -> Path | None:
    for base in [settings.outputs_dir, settings.archives_dir]:
        d = base / name
        if d.is_dir():
            return d
    return None


def get_html_path(name: str) -> Path | None:
    """Get HTML file path. Prefers _ko.html, falls back to .html."""
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    ko_html = None
    en_html = None
    for f in paper_dir.iterdir():
        if f.name.endswith("_ko.html"):
            ko_html = f
        elif f.name.endswith(".html"):
            en_html = f
    return ko_html or en_html


def get_pdf_path(name: str) -> Path | None:
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    for f in paper_dir.iterdir():
        if f.name.endswith(".pdf"):
            return f
    return None


def get_md_ko_path(name: str) -> Path | None:
    """Get Korean markdown file path."""
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    for f in paper_dir.iterdir():
        if f.name.endswith("_ko.md"):
            return f
    return None


def get_md_en_path(name: str) -> Path | None:
    """Get English markdown file path."""
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    for f in paper_dir.iterdir():
        if f.name.endswith(".md") and not f.name.endswith("_ko.md"):
            return f
    return None


def get_asset_path(name: str, filename: str) -> Path | None:
    """Get path to an asset (image) in a paper directory."""
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    asset = paper_dir / filename
    if asset.is_file() and paper_dir in asset.resolve().parents:
        return asset
    return None


def archive_paper(name: str) -> tuple[bool, str]:
    src = settings.outputs_dir / name
    if not src.is_dir():
        return False, f"Paper '{name}' not found in outputs."
    dest = settings.archives_dir / name
    if dest.exists():
        return False, f"'{name}' already exists in archives."
    settings.archives_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True, f"'{name}' archived."


def restore_paper(name: str) -> tuple[bool, str]:
    src = settings.archives_dir / name
    if not src.is_dir():
        return False, f"Paper '{name}' not found in archives."
    dest = settings.outputs_dir / name
    if dest.exists():
        return False, f"'{name}' already exists in outputs."
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True, f"'{name}' restored."


def delete_paper(name: str) -> tuple[bool, str]:
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return False, f"Paper '{name}' not found."
    size = _dir_size_mb(paper_dir)
    shutil.rmtree(str(paper_dir))
    return True, f"'{name}' deleted ({size:.1f} MB freed)."


def get_stats() -> dict:
    unread = 0
    archived = 0
    if settings.outputs_dir.exists():
        unread = sum(1 for d in settings.outputs_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
    if settings.archives_dir.exists():
        archived = sum(1 for d in settings.archives_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
    return {"unread": unread, "archived": archived, "total": unread + archived}


def get_latest_log() -> dict | None:
    logs_dir = settings.logs_dir
    if not logs_dir.exists():
        return None
    log_files = sorted(logs_dir.glob("paperflow_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not log_files:
        return None
    latest = log_files[0]
    try:
        content = latest.read_text(encoding="utf-8", errors="replace")
        # Return last 200 lines to keep response size reasonable
        lines = content.splitlines()
        tail = _ANSI_RE.sub("", "\n".join(lines[-200:]))
        return {"filename": latest.name, "content": tail, "total_lines": len(lines)}
    except Exception:
        return None


def save_upload(filename: str, data: bytes) -> tuple[bool, str]:
    settings.newones_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.newones_dir / filename
    if dest.exists():
        return False, f"'{filename}' already exists in upload queue."
    dest.write_bytes(data)
    return True, f"'{filename}' uploaded."
