from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response

from ..auth import create_token, set_auth_cookie, clear_auth_cookie
from ..config import settings
from ..dependencies import get_current_user_api
from ..services import papers as paper_svc

router = APIRouter(prefix="/api", tags=["api"])


# ── Auth ────────────────────────────────────────────────────────────────────

@router.post("/login")
async def login(payload: dict):
    uid = payload.get("username", "")
    pwd = payload.get("password", "")
    if uid == settings.LOGIN_ID and pwd == settings.LOGIN_PASSWORD:
        token = create_token(uid)
        resp = JSONResponse({"ok": True})
        set_auth_cookie(resp, token)
        return resp
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    clear_auth_cookie(resp)
    return resp


# ── Papers ──────────────────────────────────────────────────────────────────

@router.get("/papers")
async def list_papers(tab: str = "unread", _user: str = Depends(get_current_user_api)):
    return paper_svc.list_papers(tab)


@router.get("/papers/{name:path}/info")
async def paper_info(name: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    info = paper_svc.get_paper_info(name)
    if not info:
        raise HTTPException(status_code=404, detail="Paper not found")
    return info


@router.post("/papers/{name:path}/archive")
async def archive_paper(name: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    ok, msg = paper_svc.archive_paper(name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/papers/{name:path}/restore")
async def restore_paper(name: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    ok, msg = paper_svc.restore_paper(name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.delete("/papers/{name:path}")
async def delete_paper(name: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    ok, msg = paper_svc.delete_paper(name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


# ── File serving ────────────────────────────────────────────────────────────

@router.get("/papers/{name:path}/html")
async def serve_html(name: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    path = paper_svc.get_html_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="HTML file not found")
    return FileResponse(path, media_type="text/html")


@router.get("/papers/{name:path}/pdf")
async def serve_pdf(name: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    path = paper_svc.get_pdf_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="PDF file not found")
    return FileResponse(path, media_type="application/pdf")


# ── Upload ──────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...), _user: str = Depends(get_current_user_api)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:  # 200 MB limit
        raise HTTPException(status_code=400, detail="File too large (max 200 MB)")
    ok, msg = paper_svc.save_upload(file.filename, data)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


# ── Stats / Logs ────────────────────────────────────────────────────────────

@router.get("/stats")
async def stats(_user: str = Depends(get_current_user_api)):
    return paper_svc.get_stats()


@router.get("/logs/latest")
async def latest_log(_user: str = Depends(get_current_user_api)):
    log = paper_svc.get_latest_log()
    if not log:
        return {"filename": None, "content": "No logs found.", "total_lines": 0}
    return log
