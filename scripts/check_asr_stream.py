"""Authenticated live ASR probe using an existing encrypted VINote session.

No password/token is written to arguments, files, or output. Not a UI test.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.db import session_scope
from app.db_models import UserDB
from app.services.vilab_cloud_service import VILabCloudService
from app.transcribers.vilab_transcriber import VILabTranscriber


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--one-attempt", action="store_true")
    parser.add_argument("--origin", default="https://api.orulink.ai")
    args = parser.parse_args()
    from app.config import settings
    settings.vilab_server_url = args.origin
    with session_scope() as db:
        user = db.scalar(select(UserDB).where(UserDB.email == args.email.strip().lower()))
        if not user:
            raise RuntimeError("当前设备没有此账号")
        owner = user.id
    service = VILabCloudService()
    model = args.model or service.defaults(owner)["asr_model"]
    transcriber = VILabTranscriber(service.status(owner)["server_url"], "", model, cloud_user_id=owner)
    import time
    last_report = [0.0]
    def progress(received, total, confirmed):
        if time.monotonic() - last_report[0] >= 20 or received == total:
            print(json.dumps({"stage": "recognizing", "received_seconds": round(received, 2),
                              "total_seconds": total, "saved_seconds": confirmed}), flush=True)
            last_report[0] = time.monotonic()
    transcriber.progress_callback = progress
    try:
        result = transcriber._transcribe_normalized(str(args.source)) if args.one_attempt else transcriber.transcribe(str(args.source))
        print(json.dumps({"status": "success", "model": model, "characters": len(result.full_text),
                          "covered_end": result.segments[-1].end if result.segments else 0,
                          "metadata": result.metadata}, ensure_ascii=False), flush=True)
    except Exception as error:
        print(json.dumps({"status": "failed", "model": model, "error_class": type(error).__name__,
                          "message": "转写未完成，未输出原文或凭证",
                          "cause_class": type(error.__cause__).__name__ if error.__cause__ else None,
                          "close_code": getattr(getattr(error.__cause__, "rcvd", None), "code", None)}, ensure_ascii=False), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
