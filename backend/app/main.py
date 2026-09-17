from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_engine import router as engine_router
from app.api.routes_references import router as references_router
from app.api.routes_trends import router as trends_router
from app.composition import get_container
from app.core import logging as elog
from app.core.config import get_settings


def create_app(include_images: bool = True) -> FastAPI:
    elog.setup()
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
        c = get_container()
        ont = c.ontology
        elog.note(f"ontology {ont.version}  {len(ont.nodes)} nodes  {len(ont.edges)} edges")
        p = c.provider_status()
        # Every provider, present or absent, named once at startup. A run that
        # behaves unexpectedly is usually a provider that is not what you assumed.
        w = p["concept_writer"]
        elog.note(f"writer     {w.get('name', '-')} enabled={w['enabled']} "
                  f"configured={w.get('configured', False)}"
                  + (f" MISSING={w['missing']}" if w.get("missing") else ""))
        elog.note(f"llm        {p['llm']['name']}   embeddings {p['embeddings']['name']}   "
                  f"image {p['image']['name']}")
        t = p["trend_discovery"]
        elog.note(f"trends     {t['name']} live={t['live']}   "
                  f"references {p['reference_analyzer']['curated']} curated")
        elog.note(f"cognition  enabled={settings.creative_cognition_enabled} "
                  f"budget={settings.creative_cognition_budget}   "
                  f"k={settings.default_k}  seed={settings.engine_seed}")
        if not settings.creative_cognition_enabled:
            elog.note("           (set CREATIVE_COGNITION_ENABLED=true to expand candidates)")
        elog.note("ready")

    return app


app = create_app()
