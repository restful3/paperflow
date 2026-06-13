from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..dependencies import get_current_user_page
from ..services import mcp_jobs
from ..services import papers as paper_svc
from ..services import books as book_svc

router = APIRouter(tags=["pages"])

templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, user: str | None = Depends(get_current_user_page)):
    if user:
        return RedirectResponse("/papers", status_code=302)
    return RedirectResponse("/login", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user: str | None = Depends(get_current_user_page)):
    if user:
        return RedirectResponse("/papers", status_code=302)
    return templates.TemplateResponse(request=request, name="login.html", context={})


@router.get("/papers", response_class=HTMLResponse)
async def papers_page(request: Request, user: str | None = Depends(get_current_user_page)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request=request, name="papers.html", context={"username": user})


def _by_id_redirect(target: str) -> RedirectResponse:
    resp = RedirectResponse(target, status_code=302)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get("/viewer/by-id/{source_id}", response_class=HTMLResponse)
async def viewer_by_id(source_id: str,
                       user: str | None = Depends(get_current_user_page)):
    if not user:
        return _by_id_redirect("/login")
    resolved = mcp_jobs.resolve_paper_by_source_id(source_id)
    if not resolved:
        return _by_id_redirect("/papers")
    paper_name, _location = resolved
    return _by_id_redirect(f"/viewer/{quote(paper_name, safe='')}")


@router.get("/viewer/{paper_name:path}", response_class=HTMLResponse)
async def viewer_page(paper_name: str, request: Request, user: str | None = Depends(get_current_user_page)):
    if not user:
        return RedirectResponse("/login", status_code=302)

    name = unquote(paper_name)
    info = paper_svc.get_paper_info(name)
    if not info:
        return RedirectResponse("/papers", status_code=302)
    # Mark as recently read only after the paper resolves safely
    paper_svc.touch_last_read(name)

    has_pdf = info["formats"]["pdf"] if info else False
    has_md_ko = info["formats"]["md_ko"] if info else False
    has_md_en = info["formats"]["md_en"] if info else False
    has_md_ko_explained = info["formats"].get("md_ko_explained", False) if info else False
    has_md_en_explained = info["formats"].get("md_en_explained", False) if info else False
    has_md_ko_audio = info["formats"].get("md_ko_audio", False) if info else False
    has_md_ko_audio_brief = info["formats"].get("md_ko_audio_brief", False) if info else False
    has_audio_mp3 = info["formats"].get("audio_mp3", False) if info else False
    has_video = info["formats"].get("video", False) if info else False
    location = info["location"] if info else "outputs"

    # Video block (doc_type == "video"): poster + duration for the player
    video_meta = info.get("video") if info else None
    video_poster_rel = (video_meta or {}).get("poster") if video_meta else None
    video_duration_hms = (video_meta or {}).get("duration_hms") if video_meta else None
    # Build full poster URL via the assets endpoint (keep "/" between path segments)
    video_poster_url = (
        f"/api/papers/{quote(name, safe='')}/assets/{quote(video_poster_rel, safe='/')}"
        if video_poster_rel else ""
    )

    # Default view priority: video > md > pdf
    if has_video:
        default_view = "video"
    elif has_md_ko or has_md_en:
        default_view = "md"
    elif has_pdf:
        default_view = "pdf"
    else:
        default_view = "md"

    paper_title = info.get("title") if info else None
    paper_title_ko = info.get("title_ko") if info else None

    # Paper metadata for viewer info strip
    paper_authors = info.get("authors", []) if info else []
    paper_year = info.get("publication_year") if info else None
    paper_venue = info.get("venue") if info else None
    paper_doi = info.get("doi") if info else None
    paper_url = info.get("paper_url") if info else None
    paper_doc_type = info.get("doc_type") if info else None

    # Server-side reading progress (fallback when localStorage is empty)
    all_progress = paper_svc.get_all_progress()
    server_progress = all_progress.get(name, 0)

    # Server-side video resume position + watched flag (for doc_type == "video")
    vp = paper_svc.get_all_video_progress().get(name) or {}
    video_position = vp.get("position", 0) or 0
    video_watched = bool(vp.get("watched", False))

    paper_name_encoded = quote(name, safe="")

    return templates.TemplateResponse(request=request, name="viewer.html", context={
        "paper_name": name,
        "paper_name_encoded": paper_name_encoded,
        "paper_title": paper_title,
        "paper_title_ko": paper_title_ko,
        "paper_authors": paper_authors,
        "paper_year": paper_year,
        "paper_venue": paper_venue,
        "paper_doi": paper_doi,
        "paper_url": paper_url,
        "paper_doc_type": paper_doc_type,
        "has_pdf": has_pdf,
        "has_md_ko": has_md_ko,
        "has_md_en": has_md_en,
        "has_md_ko_explained": has_md_ko_explained,
        "has_md_en_explained": has_md_en_explained,
        "has_md_ko_audio": has_md_ko_audio,
        "has_md_ko_audio_brief": has_md_ko_audio_brief,
        "has_audio_mp3": has_audio_mp3,
        "has_video": has_video,
        "video_poster_url": video_poster_url,
        "video_duration_hms": video_duration_hms,
        "video_position": video_position,
        "video_watched": video_watched,
        "location": location,
        "default_view": default_view,
        "server_progress": server_progress,
        # content-viewer parameterization (paper defaults — Phase 2b):
        "api_base": f"/api/papers/{paper_name_encoded}",
        "viewer_kind": "paper",
        "storage_scope": paper_name_encoded,
        "storage_scope_raw": name,
        # book chapter fields not applicable to paper viewer:
        "book_name": None, "book_title": None,
        "chapter_title": None, "chapter_index": None, "chapters_total": None,
        "prev_url": None, "next_url": None,
    })


@router.get("/books/{book}/chapters/{chapter}", response_class=HTMLResponse)
async def chapter_viewer_page(book: str, chapter: str, request: Request,
                              user: str | None = Depends(get_current_user_page)):
    if not user:
        return RedirectResponse("/login", status_code=302)

    book = unquote(book)
    chapter = unquote(chapter)
    # NOTE: /books and /books/{book} don't exist until Phase 2c, so error
    # redirects land on /papers (exists) in 2b. TODO 2c: switch to /books/{book}.
    detail = book_svc.get_book(book)
    if not detail:
        return RedirectResponse("/papers", status_code=302)
    chapters = detail["chapters"]
    idx = next((i for i, c in enumerate(chapters) if c["chapter_id"] == chapter), None)
    if idx is None:
        return RedirectResponse("/papers", status_code=302)

    info = book_svc.get_chapter_info(book, chapter)
    if not info:
        return RedirectResponse("/papers", status_code=302)
    fmt = info["formats"]

    book_id = detail["book_id"]
    ch = chapters[idx]
    book_enc = quote(book, safe="")
    chap_enc = quote(chapter, safe="")
    has_md_ko = fmt.get("md_ko", False)
    has_md_en = fmt.get("md_en", False)
    has_pdf = fmt.get("pdf", False)
    default_view = "md" if (has_md_ko or has_md_en) else ("pdf" if has_pdf else "md")

    def _chap_url(i):
        if i < 0 or i >= len(chapters):
            return None
        return f"/books/{book_enc}/chapters/{quote(chapters[i]['chapter_id'], safe='')}"

    scope = f"book_{book_id}-ch_{chapter}"
    context = {
        "request": request,
        "paper_name": chapter, "paper_name_encoded": chap_enc,
        "paper_title": ch.get("title") or chapter, "paper_title_ko": "",
        "paper_authors": [], "paper_year": None, "paper_venue": None,
        "paper_doi": None, "paper_url": None, "paper_doc_type": None,
        "has_pdf": has_pdf, "has_md_ko": has_md_ko, "has_md_en": has_md_en,
        "has_md_ko_explained": fmt.get("md_ko_explained", False),
        "has_md_en_explained": fmt.get("md_en_explained", False),
        "has_md_ko_audio": fmt.get("md_ko_audio", False),
        "has_md_ko_audio_brief": fmt.get("md_ko_audio_brief", False),
        "has_audio_mp3": fmt.get("audio_mp3", False),
        "has_video": False, "video_poster_url": "", "video_duration_hms": None,
        "video_position": 0, "video_watched": False,
        "location": detail["location"], "default_view": default_view,
        "server_progress": ch.get("progress", 0),
        "api_base": f"/api/books/{book_enc}/chapters/{chap_enc}",
        "viewer_kind": "book_chapter",
        "storage_scope": scope, "storage_scope_raw": scope,
        "book_name": book, "book_title": detail.get("title") or book,
        "chapter_title": ch.get("title") or chapter,
        "chapter_index": idx + 1, "chapters_total": len(chapters),
        "prev_url": _chap_url(idx - 1), "next_url": _chap_url(idx + 1),
    }
    return templates.TemplateResponse(request=request, name="viewer.html", context=context)
