"""Explicit live desktop upload smoke: real STT/LLM and Langfuse readback.

Uses the desktop's HTTP routes in process; does not exercise native capture/UI.
Credentials stay in memory and are never written to the report.
"""
import argparse
import json
import mimetypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--speakers", type=int, help="Known speaker count; omitted means automatic")
    parser.add_argument("--title", help="Test note title; defaults to the input filename")
    parser.add_argument("--extras", help="Explicit meeting context, such as actual start/end times")
    parser.add_argument("--no-diarize", action="store_true", help="Explicit content-only baseline without speaker attribution")
    parser.add_argument("--workflow", choices=("meeting", "note_organization"), default="meeting")
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
    meeting = args.workflow == "meeting"
    diarize = not args.no_diarize
    is_video = args.file.suffix.lower() in {'.mp4', '.webm', '.mov', '.mkv'} and (
        mimetypes.guess_type(args.file.name)[0] or '').startswith('video/')
    with TestClient(app) as client:
        client.cookies.set(settings.auth_cookie_name, create_access_token(user))
        capability = client.get("/api/meeting-capabilities")
        capability.raise_for_status()
        if diarize:
            assert capability.json()["diarization"]["available"], capability.json()
        with args.file.open("rb") as audio:
            response = client.post("/api/generate_from_upload", headers={
                "X-VINote-Client": "desktop", "X-VINote-Client-Version": "source-live-check",
            }, data={
                "source_type": "video" if is_video else "audio", "diarize": "true" if diarize else "false",
                **({"speaker_count": str(args.speakers)} if args.speakers else {}),
                "style": "meeting" if meeting else "detailed",
                "workflow": args.workflow, "trace_source": "local_file",
                "summary_mode": "default", "output_language": "zh-CN",
                "title": args.title or f"测试｜{args.file.stem}",
                **({"extras": args.extras} if args.extras else {}),
            }, files={"file": (args.file.name, audio, mimetypes.guess_type(args.file.name)[0] or "application/octet-stream")})
        response.raise_for_status()
        task_id = response.json()["task_id"]
        status = client.get(f"/api/task/{task_id}")
        status.raise_for_status()
        result = status.json()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report = {"task_id": task_id, "status": result,
                  "workflow": args.workflow, "diarize_requested": diarize,
                  "models": models, "elapsed_seconds": round(time.monotonic() - started, 2),
                  "validation_scope": "in-process desktop HTTP routes, real cloud STT and LLM; no native capture/UI"}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        assert result["status"] == "success", result
        trace_id = result.get("langfuse_trace_id")
        assert trace_id, result
        from app.services.tracing_service import get_client
        get_client().flush()
        expected_trace_name = "桌面端｜会议纪要" if meeting else "桌面端｜笔记整理"
        import httpx
        trace = None
        with httpx.Client(base_url=settings.langfuse_base_url,
                          auth=(settings.langfuse_public_key, settings.langfuse_secret_key), timeout=10) as http:
            for _ in range(20):
                response = http.get(f"/api/public/traces/{trace_id}")
                if response.status_code == 200:
                    trace = response.json()
                    if trace.get("name") == expected_trace_name and trace.get("output"):
                        break
                time.sleep(2)
        assert trace and trace.get("name") == expected_trace_name, trace
        assert trace.get("input") and trace.get("output"), trace
        observations = trace.get("observations") or []
        stt_calls = [item for item in observations if item.get("name", "").startswith("STT｜")]
        assert stt_calls and all(item.get("model") and item.get("input") is not None
                                 and item.get("output") is not None for item in stt_calls), stt_calls
        if diarize:
            names = {item.get("name") for item in observations}
            assert {"说话人检测", "说话人聚类"} <= names, names
            for call in stt_calls:
                stt_input = call.get("input") or {}
                assert stt_input.get("transcription_scope") == "complete_recording", stt_input
                assert stt_input.get("diarization_turn_count", 0) > 0, stt_input
        llm_calls = [item for item in observations if item.get("type") == "GENERATION"
                     and item.get("name", "").startswith("LLM｜")]
        assert llm_calls and all(item.get("model") and item.get("input") is not None
                                 and item.get("output") is not None for item in llm_calls), llm_calls
        generated = result["result"]
        saved = client.post("/api/notes", json={
            "title": generated["title"], "content": generated["markdown"],
            "task_id": task_id, "source_type": ("meeting_video" if is_video else "meeting_recording") if meeting else "audio",
            "status": "done", "scope": "personal",
        })
        saved.raise_for_status()
        note_id = saved.json()["id"]
        transcript = client.get(f"/api/notes/{note_id}/transcript")
        transcript.raise_for_status()
        media = client.get(f"/api/notes/{note_id}/media", headers={"Range": "bytes=0-1023"})
        media.raise_for_status()
        report.update(note_id=note_id, transcript=transcript.json(),
                      langfuse_trace_id=trace_id, langfuse_trace_name=trace["name"],
                      langfuse_observations=len(observations),
                      langfuse_stt_calls=len(stt_calls),
                      langfuse_llm_calls=len(llm_calls),
                      langfuse_trace_url=get_client().get_trace_url(trace_id=trace_id),
                      media_status=media.status_code, media_bytes=len(media.content),
                      artifact_dir=str(TaskArtifactService().find_task_dir(task_id)))
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: report[key] for key in (
            "task_id", "note_id", "elapsed_seconds", "artifact_dir", "media_status"
        )}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
