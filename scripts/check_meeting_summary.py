"""Recheck a live meeting report with the current real LLM, preserving its audio."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from app.config import settings
    from app.db import session_scope
    from app.db_models import NoteDB
    from app.services.auth_service import create_access_token, get_user_by_id
    from app.services.llm_service import LLMService
    from app.services.task_artifact_service import TaskArtifactService
    from app.services.vilab_cloud_service import VILabCloudService
    from main import app

    report = json.loads(args.report.read_text(encoding="utf-8"))
    with session_scope() as db:
        note = db.scalar(select(NoteDB).where(NoteDB.id == report["note_id"]))
        if note is None or note.task_id != report["task_id"]:
            parser.error("Report does not match a saved note")
        user_id, title = note.created_by, note.title
    transcript = TaskArtifactService().load_transcript(Path(report["artifact_dir"]))
    if not transcript:
        parser.error("Original real transcript is missing")
    started = time.monotonic()
    with VILabCloudService().task_snapshot(user_id):
        summarizer = LLMService().create_summarizer(
            user_id=user_id, model_profile_id=None, model_name=None,
            api_key=None, base_url=None,
        )
        markdown = summarizer.summarize(title, transcript.segments, style="meeting", output_language="zh-CN")
    args.output.write_text(markdown, encoding="utf-8")
    with TestClient(app) as client:
        client.cookies.set(settings.auth_cookie_name, create_access_token(get_user_by_id(user_id)))
        response = client.patch(f"/api/notes/{report['note_id']}", json={
            "title": title, "content": markdown, "status": "done",
        })
        response.raise_for_status()
        readback = client.get(f"/api/notes/{report['note_id']}")
        readback.raise_for_status()
        assert readback.json()["content"] == markdown
    print(json.dumps({"note_id": report["note_id"], "summary_seconds": round(time.monotonic() - started, 2),
                      "summary_file": str(args.output.resolve()), "reused_real_transcript": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
