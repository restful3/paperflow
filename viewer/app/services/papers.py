import datetime as _dt
import json as _json
import os
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


def _load_paper_metadata(paper_dir: Path) -> dict | None:
    """Load paper_meta.json from a paper directory if it exists."""
    meta_path = paper_dir / "paper_meta.json"
    if meta_path.is_file():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return _json.load(f)
        except Exception:
            return None
    return None


def _paper_info(paper_dir: Path, location: str) -> dict:
    """Build info dict for a single paper directory."""
    files: dict[str, bool] = {
        "pdf": False,
        "md_ko": False,
        "md_en": False,
    }
    for f in paper_dir.iterdir():
        if not f.is_file():
            continue
        if f.name.endswith(".pdf"):
            files["pdf"] = True
        elif f.name.endswith("_ko.md"):
            files["md_ko"] = True
        elif f.name.endswith(".md") and not f.name.endswith("_ko.md"):
            files["md_en"] = True

    # Folder modification time as fallback date
    try:
        mtime = paper_dir.stat().st_mtime
        added_at = _dt.datetime.fromtimestamp(mtime).isoformat()
    except Exception:
        added_at = None

    info = {
        "name": paper_dir.name,
        "location": location,
        "formats": files,
        "size_mb": round(_dir_size_mb(paper_dir), 1),
        "added_at": added_at,
    }

    # Load AI-extracted metadata if available
    meta = _load_paper_metadata(paper_dir)
    if meta:
        info["title"] = meta.get("title")
        info["title_ko"] = meta.get("title_ko")
        info["authors"] = meta.get("authors", [])
        info["abstract"] = meta.get("abstract")
        info["abstract_ko"] = meta.get("abstract_ko")
        info["categories"] = meta.get("categories", [])
        info["original_filename"] = meta.get("original_filename")
        info["extracted_at"] = meta.get("extracted_at")
        info["publication_year"] = meta.get("publication_year")
        info["venue"] = meta.get("venue")
        info["doi"] = meta.get("doi")
        info["paper_url"] = meta.get("paper_url")
    else:
        info["title"] = None
        info["title_ko"] = None
        info["authors"] = []
        info["abstract"] = None
        info["abstract_ko"] = None
        info["categories"] = []
        info["original_filename"] = None
        info["extracted_at"] = None
        info["publication_year"] = None
        info["venue"] = None
        info["doi"] = None
        info["paper_url"] = None

    # Check for chat history
    chat_history_file = paper_dir / "chat_history.json"
    has_chat_history = chat_history_file.exists()
    chat_message_count = 0

    if has_chat_history:
        try:
            with open(chat_history_file, "r", encoding="utf-8") as f:
                chat_data = _json.load(f)
                chat_message_count = len(chat_data.get("messages", []))
        except Exception:
            pass

    info["chat"] = {
        "has_history": has_chat_history,
        "message_count": chat_message_count
    }

    return info


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

    # Clean up chatbot files before deletion
    chat_history_file = paper_dir / "chat_history.json"
    if chat_history_file.exists():
        try:
            chat_history_file.unlink()
        except Exception:
            pass  # Continue even if deletion fails

    chat_chunks_file = paper_dir / "chat_chunks.json"
    if chat_chunks_file.exists():
        try:
            chat_chunks_file.unlink()
        except Exception:
            pass  # Continue even if deletion fails

    size = _dir_size_mb(paper_dir)
    shutil.rmtree(str(paper_dir))
    delete_progress(name)
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


def _extract_pdf_text(pdf_path: Path, max_pages: int = 3) -> str:
    """Extract text from first few pages of PDF using PyPDF2."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(pdf_path))
        text = ""
        for page in reader.pages[:max_pages]:
            text += page.extract_text() or ""
        return text[:3000]
    except Exception:
        return ""


def _get_existing_papers_summary() -> list[dict]:
    """Collect title+authors from all existing paper_meta.json files."""
    papers = []
    for base, location in [(settings.outputs_dir, "outputs"), (settings.archives_dir, "archives")]:
        if not base.exists():
            continue
        for paper_dir in base.iterdir():
            if not paper_dir.is_dir() or paper_dir.name.startswith("."):
                continue
            meta = _load_paper_metadata(paper_dir)
            if meta and meta.get("title"):
                papers.append({
                    "title": meta["title"],
                    "authors": meta.get("authors", []),
                    "location": location,
                    "folder": paper_dir.name,
                })
    return papers


async def check_duplicate_paper(pdf_path: Path) -> list[dict]:
    """Extract title/authors from uploaded PDF via AI, compare against existing papers.

    Returns list of similar papers: [{title, authors, location, folder}]
    Returns empty list if no duplicates or on any error (fail-open).
    """
    text = _extract_pdf_text(pdf_path)
    if not text.strip():
        return []

    existing = _get_existing_papers_summary()
    if not existing:
        return []

    existing_list = "\n".join(
        f"- [{i}] \"{p['title']}\" by {', '.join(p['authors'][:3]) if p['authors'] else 'Unknown'}"
        for i, p in enumerate(existing)
    )

    prompt = f"""From the following PDF text, extract the paper title and authors.
Then compare against the existing papers list below and identify any that appear to be the same paper (same title or very similar title with same authors).

PDF text (first pages):
---
{text}
---

Existing papers:
{existing_list}

Respond in JSON format only:
{{
  "extracted_title": "the paper title",
  "extracted_authors": ["author1", "author2"],
  "matches": [0, 3]
}}

Rules:
- A match means the same paper (not just related topic)
- Consider title variations (e.g., with/without subtitle, abbreviations)
- If unsure, do NOT include as match
- Return empty matches [] if no duplicates found"""

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=os.getenv("OPENAI_BASE_URL", ""),
            api_key=os.getenv("OPENAI_API_KEY", "")
        )

        response = await client.chat.completions.create(
            model=os.getenv("TRANSLATION_MODEL", "gemini-2.5-flash"),
            messages=[
                {"role": "system", "content": "You are a metadata extraction assistant. Respond only in valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=512,
        )

        result_text = response.choices[0].message.content.strip()
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        result = _json.loads(result_text)
        matches = result.get("matches", [])

        if not matches:
            return []

        similar = []
        for idx in matches:
            if 0 <= idx < len(existing):
                paper = existing[idx]
                similar.append({
                    "title": paper["title"],
                    "authors": paper["authors"],
                    "location": paper["location"],
                    "folder": paper["folder"],
                })
        return similar

    except Exception:
        return []


def delete_uploaded_file(filename: str) -> tuple[bool, str]:
    """Remove an uploaded file from newones/ (for duplicate skip)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return False, "Invalid filename."
    path = settings.newones_dir / filename
    if path.is_file():
        path.unlink()
        return True, f"'{filename}' removed."
    return False, "File not found in upload queue."


def get_processing_status() -> dict:
    """Read processing status file and combine with queued files in newones/."""
    from datetime import datetime, timezone

    status_path = settings.logs_dir / "processing_status.json"
    processing = {
        "current_file": None,
        "stage": "idle",
        "stage_num": 0,
        "total_stages": 0,
        "stage_label": "Idle",
        "updated_at": None,
        "error": None,
    }

    # Read status file if exists
    if status_path.is_file():
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                processing = _json.load(f)
        except Exception:
            pass

    # Check for stale status (>120s old, not idle/complete)
    stale = False
    if processing.get("updated_at") and processing.get("stage") not in ("idle", "complete"):
        try:
            updated = datetime.fromisoformat(processing["updated_at"])
            age = (datetime.now() - updated).total_seconds()
            if age > 600:
                stale = True
        except Exception:
            pass

    # List PDF files in newones/ directory (queued for processing)
    files = []
    newones = settings.newones_dir
    if newones.exists():
        pdf_files = sorted(
            [f for f in newones.iterdir() if f.is_file() and f.name.lower().endswith(".pdf")],
            key=lambda f: f.stat().st_mtime,
        )
        current_file = processing.get("current_file")
        queue_pos = 0
        for pdf in pdf_files:
            size_mb = round(pdf.stat().st_size / (1024 * 1024), 1)
            entry = {"filename": pdf.name, "size_mb": size_mb}

            if current_file and pdf.name == current_file:
                entry["status"] = "stale" if stale else "processing"
                entry["stage"] = processing.get("stage", "")
                entry["stage_num"] = processing.get("stage_num", 0)
                entry["total_stages"] = processing.get("total_stages", 0)
                entry["stage_label"] = processing.get("stage_label", "")
                if processing.get("error"):
                    entry["error"] = processing["error"]
            else:
                queue_pos += 1
                entry["status"] = "queued"
                entry["queue_position"] = queue_pos

            files.append(entry)

    return {"files": files, "processing": processing}


def delete_queued_file(filename: str) -> tuple[bool, str]:
    """Delete a queued PDF from newones/ directory. Only allows deleting files not currently being processed."""
    from datetime import datetime

    # Sanitize: prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return False, "Invalid filename."

    filepath = settings.newones_dir / filename
    if not filepath.is_file():
        return False, f"'{filename}' not found in queue."

    # Check if this file is currently being processed
    status_path = settings.logs_dir / "processing_status.json"
    if status_path.is_file():
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                processing = _json.load(f)
            current = processing.get("current_file")
            stage = processing.get("stage", "idle")
            if current == filename and stage not in ("idle", "complete", "error"):
                return False, f"'{filename}' is currently being processed. Cannot delete."
        except Exception:
            pass

    try:
        filepath.unlink()
        return True, f"'{filename}' removed from queue."
    except Exception as e:
        return False, f"Failed to delete '{filename}': {e}"


# ── Reading Progress ───────────────────────────────────────────────────────

_PROGRESS_FILE = "reading_progress.json"


def _progress_path() -> Path:
    return Path(settings.BASE_DIR) / _PROGRESS_FILE


def get_all_progress() -> dict[str, int]:
    path = _progress_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def save_progress(paper_name: str, progress: int) -> bool:
    progress = max(0, min(100, progress))
    data = get_all_progress()
    if progress <= data.get(paper_name, 0):
        return True
    data[paper_name] = progress
    try:
        with open(_progress_path(), "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def delete_progress(paper_name: str) -> None:
    data = get_all_progress()
    if paper_name in data:
        del data[paper_name]
        try:
            with open(_progress_path(), "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass
