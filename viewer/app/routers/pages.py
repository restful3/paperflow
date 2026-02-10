from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..dependencies import get_current_user_page
from ..services import papers as paper_svc

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
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/papers", response_class=HTMLResponse)
async def papers_page(request: Request, user: str | None = Depends(get_current_user_page)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("papers.html", {"request": request, "username": user})


@router.get("/viewer/{paper_name:path}", response_class=HTMLResponse)
async def viewer_page(paper_name: str, request: Request, user: str | None = Depends(get_current_user_page)):
    if not user:
        return RedirectResponse("/login", status_code=302)

    name = unquote(paper_name)
    info = paper_svc.get_paper_info(name)

    has_pdf = info["formats"]["pdf"] if info else False
    has_md_ko = info["formats"]["md_ko"] if info else False
    has_md_en = info["formats"]["md_en"] if info else False
    has_md_ko_explained = info["formats"].get("md_ko_explained", False) if info else False
    has_md_en_explained = info["formats"].get("md_en_explained", False) if info else False
    location = info["location"] if info else "outputs"

    # Default view priority: md > pdf
    if has_md_ko or has_md_en:
        default_view = "md"
    elif has_pdf:
        default_view = "pdf"
    else:
        default_view = "md"

    paper_title = info.get("title") if info else None
    paper_title_ko = info.get("title_ko") if info else None

    # Server-side reading progress (fallback when localStorage is empty)
    all_progress = paper_svc.get_all_progress()
    server_progress = all_progress.get(name, 0)

    return templates.TemplateResponse("viewer.html", {
        "request": request,
        "paper_name": name,
        "paper_name_encoded": quote(name, safe=""),
        "paper_title": paper_title,
        "paper_title_ko": paper_title_ko,
        "has_pdf": has_pdf,
        "has_md_ko": has_md_ko,
        "has_md_en": has_md_en,
        "has_md_ko_explained": has_md_ko_explained,
        "has_md_en_explained": has_md_en_explained,
        "location": location,
        "default_view": default_view,
        "server_progress": server_progress,
    })
