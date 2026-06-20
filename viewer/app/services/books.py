"""Books service — viewer-side read/list/progress/lifecycle for the Books tab.

The viewer is a separate deployable and cannot import repo-root book_store.py,
so book_meta.json (durable) and book_state.json (cache) are read with the tiny
loaders below. Chapter formats/content reuse papers.py *_in_dir resolvers.
The viewer never writes book_state.json (the converter owns rebuilds); it only
writes book_progress.json and moves folders for archive/restore.
"""
import json as _json
import os
import re as _re
import shutil
import unicodedata as _unicodedata
from pathlib import Path
from urllib.parse import quote

from ..config import settings
from . import papers as paper_svc

_OS_FORBIDDEN = _re.compile(r'[/\\:*?"<>|]')


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
            min(100, round(sum(int(v) for v in prog.values()) / (chapters_total * 100) * 100))
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


def list_book_processing() -> list[dict]:
    """In-flight books for the Upload-tab processing panel.

    Chapter PDFs persist in newbooks/ (sha-skip prevents reprocessing), so a book
    is "done" per book_state, not per newbooks contents. Returns only books with at
    least one non-complete chapter. Status per chapter: book_state pipeline_status
    if present (complete/converted/translating/error/needs_review); else 'processing'
    if it matches the shared converting file; else 'queued'.
    """
    base = settings.newbooks_dir
    if not base.exists():
        return []
    status = _load_json(settings.logs_dir / "processing_status.json")
    current = status.get("current_file") if isinstance(status, dict) else None

    out: list[dict] = []
    for item in sorted(base.iterdir(), key=lambda p: p.name):
        if item.name.startswith(".") or not item.is_dir():
            continue
        if not paper_svc._is_within(base, item):
            continue
        pdfs = sorted(item.glob("*.pdf"), key=lambda p: p.name)
        if not pdfs:
            continue
        meta = _load_json(item / "book.json") or {}
        title = meta.get("title") or item.name
        bdir = settings.books_dir / item.name
        st = load_book_state(bdir) if bdir.is_dir() else None
        state_chapters = (st or {}).get("chapters") or {}

        chapters = []
        all_complete = True
        for pdf in pdfs:
            cid = pdf.stem
            ps = (state_chapters.get(cid) or {}).get("pipeline_status")
            if ps == "complete":
                st_label = "complete"
            elif ps in ("converted", "translating", "error", "needs_review"):
                st_label = ps
                all_complete = False
            elif current and cid in str(current):   # best-effort shared-status hint
                st_label = "processing"
                all_complete = False
            else:
                st_label = "queued"
                all_complete = False
            chapters.append({"chapter_id": cid, "status": st_label})

        if all_complete:
            continue
        out.append({
            "slug": item.name,
            "title": title,
            "chapters": chapters,
            "pending": sum(1 for c in chapters if c["status"] in ("queued", "processing")),
        })
    return out


# ── chapter content (delegate to papers *_in_dir) ──────────────────────────

_CONTENT_RESOLVERS = {
    "pdf": paper_svc.get_pdf_path_in_dir,
    "md_ko": paper_svc.get_md_ko_path_in_dir,
    "md_en": paper_svc.get_md_en_path_in_dir,
    "md_ko_explained": paper_svc.get_md_ko_explained_path_in_dir,
    "md_en_explained": paper_svc.get_md_en_explained_path_in_dir,
    "md_ko_audio": paper_svc.get_md_ko_audio_path_in_dir,
    "md_ko_audio_brief": paper_svc.get_md_ko_audio_brief_path_in_dir,
}


def get_chapter_content_path(book: str, chapter: str, kind: str) -> Path | None:
    resolver = _CONTENT_RESOLVERS.get(kind)
    if resolver is None:
        return None
    cdir = paper_svc.safe_book_chapter_dir(book, chapter)
    if not cdir:
        return None
    return resolver(cdir)


def get_chapter_asset_path(book: str, chapter: str, filename: str) -> Path | None:
    cdir = paper_svc.safe_book_chapter_dir(book, chapter)
    if not cdir:
        return None
    return paper_svc.get_asset_path_in_dir(cdir, filename)


def get_chapter_info(book: str, chapter: str) -> dict | None:
    cdir = paper_svc.safe_book_chapter_dir(book, chapter)
    if not cdir:
        return None
    info = paper_svc.paper_info_from_dir(cdir, _book_location(cdir.parent))
    info["book"] = book
    info["chapter_id"] = chapter
    return info


def save_chapter_markdown(book: str, chapter: str, md_type: str, content: str) -> tuple[bool, str]:
    cdir = paper_svc.safe_book_chapter_dir(book, chapter)
    if not cdir:
        return False, f"Chapter '{book}/{chapter}' not found."
    return paper_svc.save_markdown_in_dir(cdir, md_type, content)


def get_book_cover_path(book: str) -> Path | None:
    book_dir = paper_svc.safe_book_dir(book)
    if not book_dir:
        return None
    meta = load_book_meta(book_dir)
    rel = (meta or {}).get("cover")
    if not rel:
        return None
    return paper_svc.get_asset_path_in_dir(book_dir, rel)


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
        os.replace(tmp, path)
        return True
    except Exception:
        return False


# ── upload ────────────────────────────────────────────────────────────────

def _slugify_book_title(title: str, max_length: int = 80) -> str | None:
    """Filesystem-safe book slug. Mirrors the converter's sanitize_folder_name
    so newbooks/<slug> survives the converter's re-sanitization unchanged."""
    name = _unicodedata.normalize("NFKD", title or "")
    name = _OS_FORBIDDEN.sub("", name)
    name = _re.sub(r"[\n\r\t]", " ", name)
    name = _re.sub(r"\s+", " ", name).strip()
    name = name.strip(".")
    if len(name) > max_length:
        truncated = name[:max_length]
        sp = truncated.rfind(" ")
        if sp > max_length * 0.6:
            truncated = truncated[:sp]
        name = truncated.rstrip()
    return name or None


def _unique_book_slug(slug: str) -> str:
    """Append -2, -3, … if slug collides with an existing book folder in
    newbooks/, books/, or book_archives/."""
    roots = [settings.newbooks_dir, settings.books_dir, settings.book_archives_dir]

    def taken(s: str) -> bool:
        return any((r / s).exists() for r in roots)

    if not taken(slug):
        return slug
    i = 2
    while taken(f"{slug}-{i}"):
        i += 1
    return f"{slug}-{i}"


def save_book_upload(title, author, year, files) -> tuple[bool, str, str | None]:
    """Write an uploaded book to newbooks/<slug>/ for the converter watch.

    files: list of (original_filename, bytes) in chapter order.
    Writes NN_<sanitized-stem>.pdf (NN from 01) + book.json {title, author?, year?}.
    Returns (ok, message, slug).
    """
    base = _slugify_book_title(title)
    if not base:
        return False, "Invalid or empty book title.", None
    if not files:
        return False, "At least one chapter PDF is required.", None
    slug = _unique_book_slug(base)
    book_dir = settings.newbooks_dir / slug
    if not paper_svc._is_within(settings.newbooks_dir, book_dir):
        return False, "Invalid book title.", None
    book_dir.mkdir(parents=True, exist_ok=True)
    for i, (orig, data) in enumerate(files, 1):
        safe = paper_svc._safe_filename(orig or "") or "chapter.pdf"
        stem = safe[:-4] if safe.lower().endswith(".pdf") else safe
        stem = _OS_FORBIDDEN.sub("", stem).strip().strip(".") or "chapter"
        (book_dir / f"{i:02d}_{stem}.pdf").write_bytes(data)
    meta = {"title": title.strip()}
    if author and author.strip():
        meta["author"] = author.strip()
    if year is not None:
        meta["year"] = int(year)
    (book_dir / "book.json").write_text(
        _json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return True, f"'{slug}' uploaded ({len(files)} chapters).", slug


# ── lifecycle (archive / restore / delete) ─────────────────────────────────

def archive_book(book: str) -> tuple[bool, str]:
    if not paper_svc._is_safe_paper_name(book):
        return False, "Invalid book name."
    src = settings.books_dir / book
    if not src.is_dir() or not paper_svc._is_within(settings.books_dir, src):
        return False, f"Book '{book}' not found in books."
    dest = settings.book_archives_dir / book
    if dest.exists():
        return False, f"'{book}' already exists in book_archives."
    settings.book_archives_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True, f"'{book}' archived."


def restore_book(book: str) -> tuple[bool, str]:
    if not paper_svc._is_safe_paper_name(book):
        return False, "Invalid book name."
    src = settings.book_archives_dir / book
    if not src.is_dir() or not paper_svc._is_within(settings.book_archives_dir, src):
        return False, f"Book '{book}' not found in book_archives."
    dest = settings.books_dir / book
    if dest.exists():
        return False, f"'{book}' already exists in books."
    settings.books_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True, f"'{book}' restored."


def delete_book(book: str) -> tuple[bool, str]:
    book_dir = paper_svc.safe_book_dir(book)
    if not book_dir:
        return False, f"Book '{book}' not found."
    meta = load_book_meta(book_dir)
    book_id = (meta or {}).get("book_id")
    size_mb = paper_svc._dir_size_mb(book_dir)
    shutil.rmtree(str(book_dir))
    if book_id:
        delete_book_progress(book_id)
    return True, f"'{book}' deleted ({size_mb:.1f} MB freed)."
