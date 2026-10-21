"""
FastAPI application factory.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db


def create_app() -> FastAPI:
    if settings.content_cloud_runtime and not settings.workspace_cloud_runtime:
        raise ValueError("Cloud content requires the protected workspace cloud runtime")
    from app.routers import auth, feishu, mcp, mcp_connections, model_profiles, note, note_library, preferences, share, stt_profiles, teams, workspace, workspace_attachments

    app = FastAPI(
        title="VINote",
        description="Video-to-markdown note generation API.",
        version="0.3.3",
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
        if settings.workspace_cloud_runtime:
            from app.services.workspace_bootstrap import initialize_private_storage
            initialize_private_storage()
        from app.services import feishu_auto_runtime
        feishu_auto_runtime.start()

    @app.on_event("shutdown")
    def shutdown_tracing():
        from app.services import feishu_auto_runtime
        feishu_auto_runtime.stop()
        from app.services import feishu_cli
        feishu_cli.shutdown()
        from app.services.tracing_service import shutdown
        shutdown()

    from app.routers import vilab
    app.include_router(feishu.router, prefix="/api")
    if not settings.content_cloud_runtime:
        app.include_router(workspace.router, prefix="/api")
        app.include_router(workspace_attachments.router, prefix="/api")
    app.include_router(mcp_connections.router, prefix="/api")
    from app.routers import first_party_translation
    app.include_router(first_party_translation.router, prefix="/api")
    from app.routers import content_plugins
    app.include_router(content_plugins.router, prefix="/api")
    if not settings.workspace_cloud_runtime or settings.content_cloud_runtime:
        from app.routers.content_extraction import router as extraction_router
        app.include_router(extraction_router, prefix="/api")
    if settings.workspace_cloud_runtime:
        if settings.content_cloud_runtime:
            from app.routers.cloud_content import router as content_router
            from app.services.cloud_content_identity import ContentCredentialMiddleware
            app.include_router(content_router, prefix="/api")
            app.add_middleware(ContentCredentialMiddleware)
        # Shared content servers do not expose the device's upload/capture,
        # local account or public-share APIs. Originals stay on their device.
        return app
    from app.routers.content_capabilities import router as capabilities_router
    app.include_router(capabilities_router, prefix="/api")
    app.include_router(vilab.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    from app.routers import files
    app.include_router(files.router, prefix="/api")
    from app.routers import original_location
    app.include_router(original_location.router, prefix="/api")
    app.include_router(note.router, prefix="/api")
    from app.routers.meeting_summary_regeneration import create_summary_regeneration_router
    app.include_router(create_summary_regeneration_router(
        note_service=note._note_service,
        active=lambda task_id: task_id in note._ACTIVE_FILE_TASKS), prefix='/api')
    from app.routers.summary_visual import create_summary_visual_router
    app.include_router(create_summary_visual_router(
        artifacts=note._note_service.artifact_service), prefix='/api')
    from app.routers.meeting_version_context import create_meeting_version_router
    from app.services.task_fresh_asr import FreshASRService
    app.include_router(create_meeting_version_router(
        note_service=note._note_service,
        fresh_service=FreshASRService(),
        active=lambda task_id: task_id in note._ACTIVE_FILE_TASKS), prefix='/api')
    app.include_router(note_library.router, prefix="/api")
    from app.routers import feishu_auto_local
    app.include_router(feishu_auto_local.router, prefix="/api")
    app.include_router(feishu_auto_local.device_router, prefix="/api")
    if settings.desktop_runtime:
        from app.routers import feishu_object_hotwords, meeting_participants, meeting_source_link, feishu_meeting_wiki_recovery
        app.include_router(feishu_object_hotwords.router, prefix="/api")
        app.include_router(meeting_participants.router, prefix="/api")
        app.include_router(meeting_source_link.router, prefix="/api")
        app.include_router(feishu_meeting_wiki_recovery.router, prefix="/api")
    app.include_router(share.private_router, prefix="/api")
    app.include_router(preferences.router, prefix="/api")
    app.include_router(model_profiles.router, prefix="/api")
    app.include_router(stt_profiles.router, prefix="/api")
    app.include_router(teams.router, prefix="/api")
    app.include_router(mcp.router)
    app.include_router(share.public_router)
    return app
