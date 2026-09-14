"""Run speaker analysis on a file without opening or controlling the desktop."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.config import settings
    from app.models.transcript import TranscriptResult, TranscriptSegment
    from app.services.speaker_diarization_service import SpeakerDiarizationService

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--speakers", type=int)
    parser.add_argument("--with-vilab", action="store_true", help="Send speaking turns to configured ViLab STT")
    parser.add_argument("--user-id", help="Local VINote account for personal cloud authentication")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.with_vilab:
        from app.transcribers.vilab_transcriber import VILabTranscriber
        user_id = args.user_id
        if settings.cloud_auth_url and not user_id:
            from app.db import session_scope
            from app.db_models import CloudAccountDB
            from sqlalchemy import select
            with session_scope() as db:
                ids = list(db.scalars(select(CloudAccountDB.user_id)))
            if len(ids) != 1:
                parser.error("Pass --user-id when there is not exactly one linked local account")
            user_id = ids[0]
        from app.services.vilab_cloud_service import VILabCloudService
        defaults = VILabCloudService().request(user_id, "GET", "/v1/default-models", timeout=30)
        transcriber = VILabTranscriber(settings.vilab_server_url, settings.vilab_api_key,
                                      model=defaults["asr_model"], cloud_user_id=user_id)
        transcribe = transcriber.transcribe
    else:
        # Analysis-only mode deliberately returns no recognized speech.
        transcribe = lambda _: TranscriptResult(None, "[analysis only]", [TranscriptSegment(0, 0, "[analysis only]")])
    result = SpeakerDiarizationService().transcribe(
        audio_path=str(args.file), transcribe=transcribe, speaker_count=args.speakers,
        update_status=lambda _, message: print(message, flush=True),
    )
    payload = {"metadata": result.metadata, "recognized_text": args.with_vilab,
               "segments": [{"start": segment.start, "end": segment.end,
                             "speaker_id": segment.speaker_id, "text": segment.text} for segment in result.segments]}
    if args.output:
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"metadata": result.metadata, "segment_count": len(result.segments),
                      "characters": len(result.full_text), "recognized_text": args.with_vilab}))


if __name__ == "__main__":
    main()
