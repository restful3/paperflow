"""Books service — viewer-side read/list/progress/lifecycle for the Books tab.

The viewer is a separate deployable and cannot import repo-root book_store.py,
so book_meta.json (durable) and book_state.json (cache) are read with the tiny
loaders below. Chapter formats/content reuse papers.py *_in_dir resolvers.
The viewer never writes book_state.json (the converter owns rebuilds); it only
writes book_progress.json and moves folders for archive/restore.
"""
import datetime as _dt
import json as _json
import shutil
from pathlib import Path
from urllib.parse import quote

from ..config import settings
from . import papers as paper_svc


# ── meta / state readers ───────────────────────────────────────────────────

def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None


def load_book_meta(book_dir: Path) -> dict | None:
    return _load_json(book_dir / "book_meta.json")


def load_book_state(book_dir: Path) -> dict | None:
    return _load_json(book_dir / "book_state.json")


def _book_location(book_dir: Path) -> str:
    """books | book_archives, by resolved parent identity."""
    try:
        if book_dir.parent.resolve() == settings.book_archives_dir.resolve():
            return "book_archives"
    except (OSError, RuntimeError):
        pass
    return "books"


def _derive_chapter_status(formats: dict) -> str:
    """Fallback pipeline status when book_state.json has no entry for a chapter.

    Mirrors the converter's rebuild rule: ko -> complete, en only -> converted,
    otherwise pending.
    """
    if formats.get("md_ko"):
        return "complete"
    if formats.get("md_en"):
        return "converted"
    return "pending"


# ── listing ────────────────────────────────────────────────────────────────

def list_books(tab: str = "books") -> list[dict]:
    """Book cards for the browse list. Cheap: 2 JSON reads + progress per book,
    no per-chapter disk walk."""
    if tab == "archived":
        base = settings.book_archives_dir
        location = "book_archives"
    else:
        base = settings.books_dir
        location = "books"

    if not base.exists():
        return []

    all_progress = get_all_book_progress()
    cards: list[dict] = []
    for item in sorted(base.iterdir(), key=lambda p: p.name):
        if item.name.startswith(".") or not item.is_dir():
            continue
        if not paper_svc._is_within(base, item):
            continue
        meta = load_book_meta(item)
        if not meta:
            continue  # not a real book folder
        book_id = meta.get("book_id") or item.name
        chapters = meta.get("chapters", [])
        chapters_total = len(chapters)
        state = load_book_state(item) or {}
        chapters_translated = (state.get("aggregate") or {}).get("chapters_complete", 0)
        prog = all_progress.get(book_id, {})
        progress_pct = (
            round(sum(int(v) for v in prog.values()) / (chapters_total * 100) * 100)
            if chapters_total else 0
        )
        cover_url = None
        cover_rel = meta.get("cover")
        if cover_rel and (item / cover_rel).is_file():
            cover_url = f"/api/books/{quote(item.name, safe='')}/cover"
        cards.append({
            "name": item.name,
            "book_id": book_id,
            "title": meta.get("title") or item.name,
            "author": meta.get("author"),
            "year": meta.get("year"),
            "cover_url": cover_url,
            "chapters_total": chapters_total,
            "chapters_translated": chapters_translated,
            "progress_pct": progress_pct,
            "location": location,
        })
    return cards


def get_book(book: str) -> dict | None:
    """Book detail: durable meta + per-chapter status/formats/progress + aggregate.

    Status priority: book_state.json entry -> derived from disk formats.
    """
    book_dir = paper_svc.safe_book_dir(book)
    if not book_dir:
        return None
    meta = load_book_meta(book_dir)
    if not meta:
        return None
    location = _book_location(book_dir)
    book_id = meta.get("book_id") or book_dir.name
    state = load_book_state(book_dir) or {}
    state_chapters = state.get("chapters") or {}
    prog = get_book_progress(book_id)

    chapters: list[dict] = []
    progress_sum = 0
    for ch in meta.get("chapters", []):
        cid = ch.get("chapter_id")
        cdir = book_dir / cid if cid else None
        formats = {}
        if cdir and cdir.is_dir() and paper_svc._is_within(book_dir, cdir):
            formats = paper_svc.paper_info_from_dir(cdir, location)["formats"]
        st = state_chapters.get(cid) or {}
        status = st.get("pipeline_status") or _derive_chapter_status(formats)
        cprog = int(prog.get(cid, 0))
        progress_sum += cprog
        chapters.append({
            "chapter_id": cid,
            "order": ch.get("order"),
            "title": ch.get("title") or cid,
            "status": status,
            "formats": formats,
            "progress": cprog,
        })

    total = len(chapters)
    return {
        "name": book_dir.name,
        "book_id": book_id,
        "title": meta.get("title") or book_dir.name,
        "author": meta.get("author"),
        "year": meta.get("year"),
        "cover_url": (f"/api/books/{quote(book_dir.name, safe='')}/cover"
                      if meta.get("cover") and (book_dir / meta["cover"]).is_file() else None),
        "location": location,
        "chapters": chapters,
        "aggregate": {
            "chapters_total": total,
            "progress_pct": round(progress_sum / (total * 100) * 100) if total else 0,
        },
    }


# ── reading progress (book_progress.json, nested by book_id -> chapter_id) ───

_BOOK_PROGRESS_FILE = "book_progress.json"


def _book_progress_path() -> Path:
    return settings.books_dir / _BOOK_PROGRESS_FILE


def get_all_book_progress() -> dict[str, dict[str, int]]:
    data = _load_json(_book_progress_path())
    return data if isinstance(data, dict) else {}


def get_book_progress(book_id: str) -> dict[str, int]:
    return dict(get_all_book_progress().get(book_id, {}))


def save_chapter_progress(book_id: str, chapter_id: str, pct: int) -> bool:
    pct = max(0, min(100, int(pct)))
    data = get_all_book_progress()
    data.setdefault(book_id, {})[chapter_id] = pct
    return _write_progress(data)


def delete_book_progress(book_id: str) -> None:
    data = get_all_book_progress()
    if book_id in data:
        del data[book_id]
        _write_progress(data)


def _write_progress(data: dict) -> bool:
    try:
        settings.books_dir.mkdir(parents=True, exist_ok=True)
        path = _book_progress_path()
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        import os
        os.replace(tmp, path)
        return True
    except Exception:
        return False
