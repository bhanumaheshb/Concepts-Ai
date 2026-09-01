from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_engine import router as engine_router
from app.api.routes_references import router as references_router
from app.api.routes_trends import router as trends_router
from app.composition import get_container
from app.core.config import get_settings


def create_app(include_images: bool = True) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Creative Spatial Intelligence Engine", version="0.1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins + ["http://127.0.0.1:3000"],
        allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(engine_router)
    app.include_router(references_router)
    app.include_router(trends_router)
    if include_images:
        # separately mounted: the engine works identically without it
        from app.api.routes_images import router as images_router
        app.include_router(images_router)

    @app.on_event("startup")
    def _warm() -> None:
        get_container()

    return app


app = create_app()
