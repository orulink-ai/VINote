"""
FastAPI application factory.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db


def create_app() -> FastAPI:
    from app.routers import auth, mcp, model_profiles, note, note_library, preferences, share, stt_profiles, teams

    app = FastAPI(
        title="VINote",
        description="Video-to-markdown note generation API.",
        version="0.2.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["health"])
    def healthz():
        return {"status": "ok"}

    @app.on_event("startup")
    def startup():
        from app.services.tracing_service import validate_configuration
        validate_configuration()
        init_db()

    @app.on_event("shutdown")
    def shutdown_tracing():
        from app.services.tracing_service import shutdown
        shutdown()

    from app.routers import vilab
    app.include_router(vilab.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(note.router, prefix="/api")
    app.include_router(note_library.router, prefix="/api")
    app.include_router(share.private_router, prefix="/api")
    app.include_router(preferences.router, prefix="/api")
    app.include_router(model_profiles.router, prefix="/api")
    app.include_router(stt_profiles.router, prefix="/api")
    app.include_router(teams.router, prefix="/api")
    app.include_router(mcp.router)
    app.include_router(share.public_router)
    return app
