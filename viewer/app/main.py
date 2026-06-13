import asyncio
import contextlib
import logging
import re as _re
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import api, pages, books


class _TokenRedactFilter(logging.Filter):
    """Mask ?token=/?ptoken= values in uvicorn access logs (HIGH#1)."""

    _RE = _re.compile(r"((?:p?token)=)[^&\s\"']+")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            # 문자열 arg 만 마스킹한다. uvicorn.access 의 상태코드(int, msg 의 %d)를
            # str 로 바꾸면 %d 포맷이 TypeError 로 깨진다.
            record.args = tuple(
                self._RE.sub(r"\1REDACTED", a) if isinstance(a, str) else a
                for a in record.args
            )
        record.msg = self._RE.sub(r"\1REDACTED", str(record.msg))
        return True


async def _periodic_mcp_cleanup():
    from .services import mcp_jobs as _mcp_jobs
    while True:
        try:
            await asyncio.sleep(3600)
            await _mcp_jobs.cleanup_expired_jobs()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


@contextlib.asynccontextmanager
async def app_lifespan(app: FastAPI):
    cleanup_task: asyncio.Task | None = None

    if settings.mcp_enabled:
        from .routers import mcp_router as _mcp_router
        from .services import mcp_jobs as _mcp_jobs

        async with _mcp_router.mcp_lifespan():
            # startup cleanup pass
            await _mcp_jobs.cleanup_expired_jobs()
            cleanup_task = asyncio.create_task(_periodic_mcp_cleanup())
            try:
                yield
            finally:
                if cleanup_task is not None:
                    cleanup_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await cleanup_task
                await _mcp_jobs.cancel_all_active_downloads(reason="shutdown")
    else:
        yield


def create_app() -> FastAPI:
    settings.validate_runtime()
    logging.getLogger("uvicorn.access").addFilter(_TokenRedactFilter())
    application = FastAPI(
        title="PaperFlow Viewer",
        docs_url=None,
        redoc_url=None,
        lifespan=app_lifespan,
    )

    # Routers (always)
    application.include_router(api.router)
    application.include_router(books.router)
    application.include_router(pages.router)

    # MCP (opt-in: only when MCP_API_KEY is set + base URL configured)
    if settings.mcp_enabled:
        from .routers import mcp_router as _mcp_router
        application.include_router(_mcp_router.mcp_zip_router)
        _mcp_router.mount_mcp(
            application,
            api_key=settings.MCP_API_KEY,
            allowed_origins=settings.mcp_allowed_origins_set,
        )

    # Static files
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return application


app = create_app()
