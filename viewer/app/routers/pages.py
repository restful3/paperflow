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

    has_html = info["formats"]["html"] if info else False
    has_pdf = info["formats"]["pdf"] if info else False
    location = info["location"] if info else "outputs"

    # Default view priority: html > pdf
    if has_html:
        default_view = "html"
    elif has_pdf:
        default_view = "pdf"
    else:
        default_view = "html"

    return templates.TemplateResponse("viewer.html", {
        "request": request,
        "paper_name": name,
        "paper_name_encoded": quote(name, safe=""),
        "has_html": has_html,
        "has_pdf": has_pdf,
        "location": location,
        "default_view": default_view,
    })
