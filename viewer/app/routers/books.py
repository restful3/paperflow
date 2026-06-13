from urllib.parse import unquote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..dependencies import get_current_user_api
from ..services import books as book_svc

router = APIRouter(prefix="/api/books", tags=["books"])

_MD_KINDS = {
    "md-ko": "md_ko",
    "md-en": "md_en",
    "md-ko-explained": "md_ko_explained",
    "md-en-explained": "md_en_explained",
    "md-ko-audio": "md_ko_audio",
    "md-ko-audio-brief": "md_ko_audio_brief",
}
_IMG_MEDIA = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png",
              "gif": "image/gif", "svg": "image/svg+xml", "webp": "image/webp"}
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB per chapter (mirrors papers upload)


class MarkdownUpdateRequest(BaseModel):
    content: str


@router.get("")
async def list_books(tab: str = "books", _user: str = Depends(get_current_user_api)):
    return book_svc.list_books(tab=tab)


@router.post("/upload")
async def upload_book(
    title: str = Form(...),
    author: str = Form(""),
    year: str = Form(""),
    files: list[UploadFile] = File(...),
    _user: str = Depends(get_current_user_api),
):
    if not title.strip():
        raise HTTPException(status_code=400, detail="Book title is required")
    if not files:
        raise HTTPException(status_code=400, detail="At least one chapter PDF is required")
    payload: list[tuple[str, bytes]] = []
    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"Only PDF files are accepted: {f.filename}")
        data = await f.read()
        if len(data) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail=f"File too large (max 200 MB): {f.filename}")
        payload.append((f.filename, data))
    yr = None
    if year.strip():
        try:
            yr = int(year.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Year must be a number")
    ok, msg, slug = book_svc.save_book_upload(title, author, yr, payload)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg, "slug": slug, "chapters": len(payload)}


@router.get("/{book}/info")
async def book_info(book: str, _user: str = Depends(get_current_user_api)):
    info = book_svc.get_book(unquote(book))
    if not info:
        raise HTTPException(status_code=404, detail="Book not found")
    return info


@router.get("/{book}/cover")
async def book_cover(book: str, _user: str = Depends(get_current_user_api)):
    path = book_svc.get_book_cover_path(unquote(book))
    if not path:
        raise HTTPException(status_code=404, detail="Cover not found")
    ext = path.suffix.lstrip(".").lower()
    return FileResponse(path, media_type=_IMG_MEDIA.get(ext, "application/octet-stream"))


@router.post("/{book}/archive")
async def archive_book(book: str, _user: str = Depends(get_current_user_api)):
    ok, msg = book_svc.archive_book(unquote(book))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/{book}/restore")
async def restore_book(book: str, _user: str = Depends(get_current_user_api)):
    ok, msg = book_svc.restore_book(unquote(book))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.delete("/{book}")
async def delete_book(book: str, _user: str = Depends(get_current_user_api)):
    ok, msg = book_svc.delete_book(unquote(book))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.get("/{book}/chapters/{chapter}/info")
async def chapter_info(book: str, chapter: str, _user: str = Depends(get_current_user_api)):
    info = book_svc.get_chapter_info(unquote(book), unquote(chapter))
    if not info:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return info


@router.get("/{book}/chapters/{chapter}/pdf")
async def chapter_pdf(book: str, chapter: str, _user: str = Depends(get_current_user_api)):
    path = book_svc.get_chapter_content_path(unquote(book), unquote(chapter), "pdf")
    if not path:
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(path, media_type="application/pdf")


@router.get("/{book}/chapters/{chapter}/assets/{filename:path}")
async def chapter_asset(book: str, chapter: str, filename: str,
                        _user: str = Depends(get_current_user_api)):
    path = book_svc.get_chapter_asset_path(unquote(book), unquote(chapter), unquote(filename))
    if not path:
        raise HTTPException(status_code=404, detail="Asset not found")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return FileResponse(path, media_type=_IMG_MEDIA.get(ext, "application/octet-stream"))


@router.put("/{book}/chapters/{chapter}/markdown/{md_type}")
async def chapter_markdown_save(book: str, chapter: str, md_type: str,
                                payload: MarkdownUpdateRequest,
                                _user: str = Depends(get_current_user_api)):
    if md_type not in ("ko", "en"):
        raise HTTPException(status_code=400, detail="md_type must be 'ko' or 'en'")
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    ok, msg = book_svc.save_chapter_markdown(unquote(book), unquote(chapter), md_type, payload.content)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/{book}/chapters/{chapter}/progress")
async def chapter_progress(book: str, chapter: str, payload: dict,
                           _user: str = Depends(get_current_user_api)):
    progress = payload.get("progress")
    if not isinstance(progress, (int, float)):
        raise HTTPException(status_code=400, detail="'progress' required")
    info = book_svc.get_book(unquote(book))
    if not info:
        raise HTTPException(status_code=404, detail="Book not found")
    book_svc.save_chapter_progress(info["book_id"], unquote(chapter), int(progress))
    return {"ok": True}


@router.get("/{book}/chapters/{chapter}/{md_kind}")
async def chapter_md(book: str, chapter: str, md_kind: str,
                     _user: str = Depends(get_current_user_api)):
    kind = _MD_KINDS.get(md_kind)
    if kind is None:
        raise HTTPException(status_code=404, detail="Unknown markdown kind")
    path = book_svc.get_chapter_content_path(unquote(book), unquote(chapter), kind)
    if not path:
        raise HTTPException(status_code=404, detail="Markdown not found")
    return FileResponse(path, media_type="text/markdown; charset=utf-8")
