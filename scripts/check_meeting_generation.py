"""Explicit live meeting upload smoke: real STT/LLM, saved personal test note.

Uses the desktop's HTTP routes in process; does not exercise native capture/UI.
Credentials stay in memory and are never written to the report.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--speakers", type=int, default=4)
    parser.add_argument("--user-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from app.config import settings
    from app.db import session_scope
    from app.db_models import CloudAccountDB
    from app.services.auth_service import create_access_token, get_user_by_id
    from app.services.vilab_cloud_service import VILabCloudService
    from app.services.task_artifact_service import TaskArtifactService
    from main import app

    user_id = args.user_id
    if not user_id:
        with session_scope() as db:
            ids = list(db.scalars(select(CloudAccountDB.user_id)))
        if len(ids) != 1:
            parser.error("Specify --user-id when there is not exactly one linked account")
        user_id = ids[0]
    user = get_user_by_id(user_id)
    if not user:
        parser.error("Local user not found")
    cloud = VILabCloudService()
    if cloud.status(user_id)["mode"] != "cloud":
        parser.error("Select cloud mode before this live ViLab test")
    defaults = cloud.defaults(user_id)
    models = {key: defaults[key] for key in ("asr_model", "llm_model")}
    print(json.dumps({"models": models}, ensure_ascii=False), flush=True)
    started = time.monotonic()
    with TestClient(app) as client:
        client.cookies.set(settings.auth_cookie_name, create_access_token(user))
        capability = client.get("/api/meeting-capabilities")
        capability.raise_for_status()
        assert capability.json()["diarization"]["available"], capability.json()
        with args.file.open("rb") as audio:
            response = client.post("/api/generate_from_upload", data={
                "source_type": "audio", "diarize": "true",
                "speaker_count": str(args.speakers), "style": "meeting",
                "summary_mode": "default", "output_language": "zh-CN",
                "title": "测试｜公开四人音频会议总结",
            }, files={"file": (args.file.name, audio, "audio/wav")})
        response.raise_for_status()
        task_id = response.json()["task_id"]
        status = client.get(f"/api/task/{task_id}")
        status.raise_for_status()
        result = status.json()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report = {"task_id": task_id, "status": result,
                  "models": models, "elapsed_seconds": round(time.monotonic() - started, 2),
                  "validation_scope": "in-process desktop HTTP routes, real cloud STT and LLM; no native capture/UI"}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        assert result["status"] == "success", result
        generated = result["result"]
        saved = client.post("/api/notes", json={
            "title": generated["title"], "content": generated["markdown"],
            "task_id": task_id, "source_type": "meeting_recording",
            "status": "done", "scope": "personal",
        })
        saved.raise_for_status()
        note_id = saved.json()["id"]
        transcript = client.get(f"/api/notes/{note_id}/transcript")
        transcript.raise_for_status()
        media = client.get(f"/api/notes/{note_id}/media", headers={"Range": "bytes=0-1023"})
        media.raise_for_status()
        report.update(note_id=note_id, transcript=transcript.json(),
                      media_status=media.status_code, media_bytes=len(media.content),
                      artifact_dir=str(TaskArtifactService().find_task_dir(task_id)))
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: report[key] for key in (
            "task_id", "note_id", "elapsed_seconds", "artifact_dir", "media_status"
        )}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
