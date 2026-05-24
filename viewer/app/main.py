import asyncio
import contextlib
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import api, pages


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
    application = FastAPI(
        title="PaperFlow Viewer",
        docs_url=None,
        redoc_url=None,
        lifespan=app_lifespan,
    )

    # Routers (always)
    application.include_router(api.router)
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
