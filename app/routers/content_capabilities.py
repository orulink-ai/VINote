"""Authenticated device preflight; contains no model or provider operation."""
from fastapi import APIRouter, Depends, Response

from app.services.generation_auth_service import get_generation_user

router = APIRouter(tags=["content-capabilities"])


@router.get("/content-service/capabilities")
def capabilities(response: Response, user=Depends(get_generation_user)):
    from app.services.speaker_diarization_service import SpeakerDiarizationService
    response.headers["Cache-Control"] = "no-store"
    return {"content_service_protocol": 1, "generation": True, "sync": False,
            "text_extraction_protocol": 1,
            "bearer_required": False, "authentication_required": True,
            "video_url": True, "max_upload_bytes": 2 * 1024 * 1024 * 1024,
            "max_document_bytes": 20 * 1024 * 1024,
            "diarization_available": bool(SpeakerDiarizationService.readiness()["available"])}
