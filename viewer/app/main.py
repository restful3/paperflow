from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routers import api, pages


def create_app() -> FastAPI:
    application = FastAPI(title="PaperFlow Viewer", docs_url=None, redoc_url=None)

    # Routers
    application.include_router(api.router)
    application.include_router(pages.router)

    # Static files
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return application


app = create_app()
