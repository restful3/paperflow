import json
import os
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
async def list_papers(
    tab: str = "unread",
    sort: str = "name",
    order: str = "asc",
    _user: str = Depends(get_current_user_api),
):
    papers = paper_svc.list_papers(tab)
    if sort == "title":
        papers.sort(
            key=lambda p: (p.get("title") or p["name"]).lower(),
            reverse=(order == "desc"),
        )
    elif sort == "size":
        papers.sort(key=lambda p: p["size_mb"], reverse=(order == "desc"))
    elif sort == "name":
        papers.sort(key=lambda p: p["name"].lower(), reverse=(order == "desc"))
    return papers


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


# ── Chat (Chatbot) ──────────────────────────────────────────────────────────
# IMPORTANT: Must be declared BEFORE delete_paper to prevent {name:path} from
# greedily matching /chat/history as part of the paper name

from sse_starlette.sse import EventSourceResponse
from ..services import chat as chat_svc
from ..services import rag as rag_svc
from ..models.chat import ChatRequest, ChatMessage
from datetime import datetime


@router.post("/papers/{name:path}/chat")
async def chat_with_paper(
    name: str,
    request: ChatRequest,
    _user: str = Depends(get_current_user_api)
):
    """Stream chat response using Server-Sent Events (SSE).

    Flow:
    1. Load chat history
    2. Add user message
    3. Get/create markdown chunks
    4. Search relevant chunks
    5. Build RAG context
    6. Stream LLM response
    7. Save assistant message
    8. Complete

    Args:
        name: Paper name (URL-encoded)
        request: ChatRequest with message and paper_name
        _user: Authenticated user (from JWT)

    Returns:
        EventSourceResponse with SSE stream

    Events:
        - data: {"type": "token", "content": "word"}
        - data: {"type": "sources", "sources": [...]}
        - data: {"type": "done"}
        - data: {"type": "error", "error": "..."}
    """
    name = unquote(name)

    async def event_generator():
        try:
            # 1. Load chat history
            history = chat_svc.load_chat_history(name)

            # 2. Add user message
            user_msg = ChatMessage(
                role="user",
                content=request.message,
                timestamp=datetime.now()
            )
            history.messages.append(user_msg)

            # 3. Get chunks (cached or generate)
            try:
                chunks = chat_svc.get_or_create_chunks(name)
            except ValueError as e:
                yield {
                    "event": "message",
                    "data": json.dumps({"type": "error", "error": str(e)})
                }
                return

            # 4. Search relevant chunks
            relevant_chunks = rag_svc.search_chunks(
                request.message,
                chunks,
                top_k=5
            )

            # 5. Build RAG context
            context = rag_svc.build_rag_context(
                query=request.message,
                chunks=relevant_chunks,
                history=history.messages[:-1],  # Exclude current message
                max_chunks=5,
                max_history=2
            )

            # 6. Stream LLM response
            assistant_content = ""
            async for event in rag_svc.generate_response_stream(
                context=context,
                query=request.message,
                model=os.getenv("TRANSLATION_MODEL", "gemini-claude-sonnet-4-5"),
                base_url=os.getenv("OPENAI_BASE_URL", ""),
                api_key=os.getenv("OPENAI_API_KEY", "")
            ):
                if event["type"] == "token":
                    assistant_content += event["content"]
                yield {"event": "message", "data": json.dumps(event)}

                if event["type"] == "error":
                    # Don't save on error
                    return

            # 7. Send sources
            sources = [
                {
                    "index": chunk.index,
                    "heading": chunk.heading,
                    "content": chunk.content[:200]  # Excerpt only
                }
                for chunk in relevant_chunks
            ]
            yield {
                "event": "message",
                "data": json.dumps({"type": "sources", "sources": sources})
            }

            # 8. Save assistant message
            assistant_msg = ChatMessage(
                role="assistant",
                content=assistant_content,
                timestamp=datetime.now(),
                sources=sources
            )
            history.messages.append(assistant_msg)
            chat_svc.save_chat_history(history)

            # 9. Done
            yield {"event": "message", "data": json.dumps({"type": "done"})}

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }

    return EventSourceResponse(event_generator())


@router.get("/papers/{name:path}/chat/history")
async def get_chat_history(
    name: str,
    _user: str = Depends(get_current_user_api)
):
    """Get full chat history for a paper.

    Args:
        name: Paper name (URL-encoded)
        _user: Authenticated user

    Returns:
        ChatHistory object as JSON

    Raises:
        HTTPException: 404 if paper not found
    """
    name = unquote(name)
    try:
        history = chat_svc.load_chat_history(name)
        # Convert to dict for JSON serialization
        try:
            return history.model_dump()
        except AttributeError:
            return history.dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/papers/{name:path}/chat/history")
async def clear_chat_history_endpoint(
    name: str,
    _user: str = Depends(get_current_user_api)
):
    """Clear all chat history for a paper.

    Args:
        name: Paper name (URL-encoded)
        _user: Authenticated user

    Returns:
        Success message

    Raises:
        HTTPException: 404 if paper not found
    """
    name = unquote(name)
    ok = chat_svc.clear_chat_history(name)
    if not ok:
        raise HTTPException(status_code=404, detail="Paper not found or no chat history")
    return {"ok": True, "message": f"Chat history cleared for '{name}'"}


@router.delete("/papers/{name:path}")
async def delete_paper(name: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    ok, msg = paper_svc.delete_paper(name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


# ── File serving ────────────────────────────────────────────────────────────

@router.get("/papers/{name:path}/pdf")
async def serve_pdf(name: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    path = paper_svc.get_pdf_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="PDF file not found")
    return FileResponse(path, media_type="application/pdf")


@router.get("/papers/{name:path}/md-ko")
async def serve_md_ko(name: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    path = paper_svc.get_md_ko_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="Korean markdown file not found")
    return FileResponse(path, media_type="text/markdown; charset=utf-8")


@router.get("/papers/{name:path}/md-en")
async def serve_md_en(name: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    path = paper_svc.get_md_en_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="English markdown file not found")
    return FileResponse(path, media_type="text/markdown; charset=utf-8")


@router.get("/papers/{name:path}/assets/{filename}")
async def serve_asset(name: str, filename: str, _user: str = Depends(get_current_user_api)):
    name = unquote(name)
    filename = unquote(filename)
    path = paper_svc.get_asset_path(name, filename)
    if not path:
        raise HTTPException(status_code=404, detail="Asset not found")
    # Guess media type from extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    media_types = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "svg": "image/svg+xml"}
    return FileResponse(path, media_type=media_types.get(ext, "application/octet-stream"))


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


@router.get("/processing/status")
async def processing_status(_user: str = Depends(get_current_user_api)):
    return paper_svc.get_processing_status()


@router.delete("/processing/queue/{filename}")
async def delete_queued_file(filename: str, _user: str = Depends(get_current_user_api)):
    filename = unquote(filename)
    ok, msg = paper_svc.delete_queued_file(filename)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


