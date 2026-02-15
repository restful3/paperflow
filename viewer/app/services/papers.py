import datetime as _dt
import json as _json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _slugify_name(text: str, max_len: int = 80) -> str:
    s = (text or "untitled").strip().lower()
    s = re.sub(r"https?://", "", s)
    s = re.sub(r"[^a-z0-9가-힣_-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:max_len] or "untitled")


def _fetch_url_html(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (PaperFlow URL Import)"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return data.decode("utf-8", errors="ignore")


def _extract_text_from_html(html: str, max_chars: int = 24000) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<noscript[\s\S]*?</noscript>", " ", html, flags=re.I)
    m = re.search(r"<(article|main)[^>]*>([\s\S]*?)</\1>", html, flags=re.I)
    body = m.group(2) if m else html
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _translate_text_ko(text: str, max_chars: int = 12000) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = text[:max_chars]
    out_parts: list[str] = []
    chunk_size = 2200
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        try:
            tr_url = (
                "https://translate.googleapis.com/translate_a/single"
                f"?client=gtx&sl=auto&tl=ko&dt=t&q={quote(chunk)}"
            )
            req = Request(tr_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            data = _json.loads(raw)
            ko = "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
            out_parts.append(ko)
        except Exception:
            out_parts.append(chunk)
    return "\n\n".join(p for p in out_parts if p)


def _extract_pdf_text_simple(pdf_path: Path, max_pages: int = 2) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(pdf_path))
        parts: list[str] = []
        for p in reader.pages[:max_pages]:
            parts.append((p.extract_text() or "").strip())
        return "\n".join(x for x in parts if x)
    except Exception:
        return ""


def import_url_as_paper(url: str, title: str | None = None) -> tuple[bool, str, str | None]:
    """Import a web URL by creating a PDF in newones/ queue.

    Pipeline alignment:
      URL -> PDF(newones) -> existing PaperFlow pipeline(main_terminal.py)
      -> metadata extraction -> markdown -> ko translation.

    Returns: (ok, message, queued_pdf_name)
    """
    if not url or not url.startswith(("http://", "https://")):
        return False, "Invalid URL. Use http(s) URL.", None

    host = (urlparse(url).netloc or "").lower()
    if not host:
        return False, "Invalid URL host.", None

    # Soft precheck only: do not fail import if HTML extraction is weak.
    # Some sites block simple fetch but still print fine in headless browser.
    try:
        html = _fetch_url_html(url)
        text = _extract_text_from_html(html)
        if len(text) < 120:
            pass
    except Exception:
        pass

    settings.newones_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify_name(title or host)
    pdf_name = f"web-{slug}-{ts}.pdf"
    pdf_path = settings.newones_dir / pdf_name

    # Generate PDF via headless browser (chrome/chromium)
    browser_bin = (
        shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    if not browser_bin:
        return False, "No headless browser found (google-chrome/chromium).", None

    cmd = [
        browser_bin,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--virtual-time-budget=10000",
        f"--print-to-pdf={pdf_path}",
        url,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return False, "Headless browser executable missing.", None
    except subprocess.TimeoutExpired:
        return False, "PDF 생성 타임아웃(60s).", None
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or "").strip()
        return False, f"PDF 생성 실패: {err[:200]}", None

    if not pdf_path.exists() or pdf_path.stat().st_size < 1024:
        return False, "PDF 생성 결과가 비정상입니다.", None

    # Basic quality gate: prevent importing pages where print CSS captured only footer/cookie banner.
    pdf_text = _extract_pdf_text_simple(pdf_path, max_pages=2)
    norm = re.sub(r"\s+", " ", (pdf_text or "")).strip().lower()
    weak_keywords = ["privacy policy", "notify me", "owner login", "terms", "copyright", "built for agents"]
    weak_hit = sum(1 for k in weak_keywords if k in norm)
    if len(norm) < 220 or weak_hit >= 3:
        try:
            pdf_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False, "원문 본문이 아닌 푸터/배너만 인쇄되어 가져오기에 실패했습니다. 원문 페이지를 직접 열어 본문이 보이는 링크인지 확인해 주세요.", None

    # Save source URL sidecar for traceability (existing pipeline can ignore safely)
    sidecar = settings.newones_dir / f"{pdf_name}.url.txt"
    try:
        sidecar.write_text(url, encoding="utf-8")
    except Exception:
        pass

    return True, f"URL queued as PDF: {pdf_name}", pdf_name

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
        "md_ko_explained": False,
        "md_en_explained": False,
    }
    for f in paper_dir.iterdir():
        if not f.is_file():
            continue
        if f.name.endswith(".pdf"):
            files["pdf"] = True
        elif f.name.endswith("_ko_explained.md"):
            files["md_ko_explained"] = True
        elif f.name.endswith("_explained.md"):
            files["md_en_explained"] = True
        elif f.name.endswith("_ko.md"):
            files["md_ko"] = True
        elif f.name.endswith(".md"):
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
        info["source_url"] = meta.get("source_url_original") or meta.get("paper_url")
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
        info["source_url"] = None

    # Sidecar fallback: if source_url still missing, check .url.txt in newones/
    if not info.get("source_url") and info.get("original_filename"):
        sidecar = settings.newones_dir / f"{info['original_filename']}.url.txt"
        try:
            if sidecar.is_file():
                info["source_url"] = sidecar.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    # Derive source_domain for display when venue is missing
    src = info.get("source_url")
    if src:
        try:
            from urllib.parse import urlparse
            host = urlparse(src).hostname or ""
            if host.startswith("www."):
                host = host[4:]
            info["source_domain"] = host
        except Exception:
            info["source_domain"] = None
    else:
        info["source_domain"] = None

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

    last_read = get_all_last_read()
    papers = []
    for item in sorted(base.iterdir(), key=lambda p: p.name):
        if item.is_dir() and not item.name.startswith("."):
            info = _paper_info(item, location)
            info["last_read_at"] = last_read.get(item.name)
            papers.append(info)
    return papers


def get_paper_info(name: str) -> dict | None:
    """Find paper in outputs or archives and return info."""
    for base, loc in [(settings.outputs_dir, "outputs"), (settings.archives_dir, "archives")]:
        paper_dir = base / name
        if paper_dir.is_dir():
            info = _paper_info(paper_dir, loc)
            info["last_read_at"] = get_all_last_read().get(name)
            return info
    return None


def find_processed_paper(original_filename: str | None = None, source_url: str | None = None) -> dict | None:
    """Resolve a processed paper folder using original filename or source URL.

    Also checks .url.txt sidecar files (created by import_url_as_paper) when
    source_url is not yet in paper_meta.json.

    Returns dict: {name, location, viewer_path} or None
    """
    if not original_filename and not source_url:
        return None

    candidates: list[tuple[Path, str]] = []
    for base, loc in [(settings.outputs_dir, "outputs"), (settings.archives_dir, "archives")]:
        if not base.exists():
            continue
        for item in base.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                candidates.append((item, loc))

    # Prefer newest first
    candidates.sort(key=lambda x: x[0].stat().st_mtime if x[0].exists() else 0, reverse=True)

    for paper_dir, loc in candidates:
        meta = _load_paper_metadata(paper_dir) or {}
        if original_filename and meta.get("original_filename") == original_filename:
            return _resolve_result(paper_dir, loc)
        if source_url and (
            meta.get("paper_url") == source_url
            or meta.get("source_url_original") == source_url
        ):
            return _resolve_result(paper_dir, loc)

        # Fallback: check .url.txt sidecar next to the original PDF
        if source_url and meta.get("original_filename"):
            sidecar = settings.newones_dir / f"{meta['original_filename']}.url.txt"
            try:
                if sidecar.is_file() and sidecar.read_text(encoding="utf-8").strip() == source_url:
                    # Backfill source_url_original into paper_meta.json for future lookups
                    meta_path = paper_dir / "paper_meta.json"
                    try:
                        import json as _json
                        meta["source_url_original"] = source_url
                        meta_path.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                    return _resolve_result(paper_dir, loc)
            except Exception:
                pass

    return None


def _resolve_result(paper_dir: Path, location: str) -> dict:
    """Build resolve result with format availability info."""
    formats: dict[str, bool] = {}
    for f in paper_dir.iterdir():
        if not f.is_file():
            continue
        if f.name.endswith(".pdf"):
            formats["pdf"] = True
        elif f.name.endswith("_ko_explained.md"):
            formats["md_ko_explained"] = True
        elif f.name.endswith("_explained.md"):
            formats["md_en_explained"] = True
        elif f.name.endswith("_ko.md"):
            formats["md_ko"] = True
        elif f.name.endswith(".md"):
            formats["md_en"] = True
    return {
        "name": paper_dir.name,
        "location": location,
        "viewer_path": f"/viewer/{quote(paper_dir.name, safe='')}",
        "formats": formats,
    }


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
        if f.name.endswith(".md") and not f.name.endswith("_ko.md") and not f.name.endswith("_explained.md"):
            return f
    return None


def get_md_ko_explained_path(name: str) -> Path | None:
    """Get Korean explained markdown file path."""
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    for f in paper_dir.iterdir():
        if f.name.endswith("_ko_explained.md"):
            return f
    return None


def get_md_en_explained_path(name: str) -> Path | None:
    """Get English explained markdown file path."""
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return None
    for f in paper_dir.iterdir():
        if f.name.endswith("_explained.md") and not f.name.endswith("_ko_explained.md"):
            return f
    return None


def save_markdown(name: str, md_type: str, content: str) -> tuple[bool, str]:
    """Save edited markdown content with timestamped backup.

    Args:
        name: Paper folder name.
        md_type: "ko" or "en".
        content: New markdown content.
    """
    paper_dir = _resolve_paper_dir(name)
    if not paper_dir:
        return False, f"Paper '{name}' not found."

    # Find the target file
    target = None
    if md_type == "ko":
        for f in paper_dir.iterdir():
            if f.name.endswith("_ko.md") and not f.name.endswith("_ko_explained.md"):
                target = f
                break
    else:
        for f in paper_dir.iterdir():
            if f.name.endswith(".md") and not f.name.endswith("_ko.md") and not f.name.endswith("_explained.md"):
                target = f
                break

    if not target:
        label = "Korean" if md_type == "ko" else "English"
        return False, f"{label} markdown file not found."

    # Create timestamped backup
    timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target.with_suffix(f".{timestamp}.bak")
    try:
        shutil.copy2(str(target), str(backup_path))
    except Exception as e:
        return False, f"Failed to create backup: {e}"

    # Write new content
    try:
        target.write_text(content, encoding="utf-8")
    except Exception as e:
        return False, f"Failed to save: {e}"

    # Invalidate RAG chat chunks cache
    chat_chunks_file = paper_dir / "chat_chunks.json"
    if chat_chunks_file.exists():
        try:
            chat_chunks_file.unlink()
        except Exception:
            pass

    return True, f"Saved. Backup: {backup_path.name}"


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
    delete_rating(name)
    delete_last_read(name)
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
                if processing.get("detail"):
                    entry["detail"] = processing["detail"]
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
    return settings.outputs_dir / _PROGRESS_FILE


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


# ── Last Read Timestamp ───────────────────────────────────────────────────

_LAST_READ_FILE = "paper_last_read.json"


def _last_read_path() -> Path:
    return settings.outputs_dir / _LAST_READ_FILE


def get_all_last_read() -> dict[str, str]:
    path = _last_read_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def touch_last_read(paper_name: str) -> bool:
    data = get_all_last_read()
    data[paper_name] = _dt.datetime.now().isoformat()
    try:
        with open(_last_read_path(), "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def delete_last_read(paper_name: str) -> None:
    data = get_all_last_read()
    if paper_name in data:
        del data[paper_name]
        try:
            with open(_last_read_path(), "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass


# ── Paper Ratings ─────────────────────────────────────────────────────────

_RATINGS_FILE = "paper_ratings.json"


def _ratings_path() -> Path:
    return settings.outputs_dir / _RATINGS_FILE


def get_all_ratings() -> dict[str, int]:
    path = _ratings_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def save_rating(paper_name: str, rating: int) -> bool:
    rating = max(0, min(5, rating))
    data = get_all_ratings()
    if rating == 0:
        data.pop(paper_name, None)
    else:
        data[paper_name] = rating
    try:
        with open(_ratings_path(), "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def delete_rating(paper_name: str) -> None:
    data = get_all_ratings()
    if paper_name in data:
        del data[paper_name]
        try:
            with open(_ratings_path(), "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass
