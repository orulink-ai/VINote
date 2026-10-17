"""Owner-selected model diagnostics. No model invocation or credential output.

Run from VINote's normal local backend environment. Supply the known owner email
at the hidden prompt; never put a token, key or email into a command argument.
CloudAccountService alone handles normal encrypted-session refresh if necessary.
"""
import getpass
import json
import logging
from pathlib import Path
import re
import sys
import time
import warnings

ORIGIN = "https://api.orulink.ai"
PATHS = ("/v1/models", "/v1/default-models")


def safe_id(value, *, token="", email=""):
    if not isinstance(value, str) or not value or len(value) > 200:
        return None
    if (token and token in value) or (email and email.lower() in value.lower()):
        return "[omitted]"
    if (not re.fullmatch(r"[\w./:@+-]+", value)
            or re.fullmatch(r"[\w-]{20,}\.[\w-]{20,}\.[\w-]+", value)):
        return "[omitted]"
    return value


def metadata(raw, *, token="", email="", selected=None):
    """Only allowlisted model fields leave memory, never a raw response body."""
    names = lambda value: safe_id(value, token=token, email=email)
    rows = raw.get("models", raw.get("data", [])) if isinstance(raw, dict) else raw
    result = {"catalog_type": type(rows).__name__}
    if isinstance(raw, dict):
        result["llm_model"] = names(raw.get("llm_model"))
        result["llm_model_type"] = type(raw.get("llm_model")).__name__
        result["known_fields"] = [k for k in ("models", "data", "llm_model", "llmModel",
                                             "llm", "defaults", "defaultModels") if k in raw]
    if isinstance(rows, list):
        result["model_count"] = len(rows)
        result["models"] = [{key: names(model.get(key)) for key in ("id", "modelType", "runtimeStatus")}
                            for model in rows[:100] if isinstance(model, dict)]
        result["selected_model_status"] = [{key: names(model.get(key)) for key in ("id", "modelType", "runtimeStatus")}
            for model in rows if isinstance(model, dict) and selected and model.get("id") == selected]
    return result


def collect(client, token, email, selected=None):
    outputs = []
    for path in PATHS:
        output = {"path": path}
        try:
            deadline = time.monotonic() + 15
            with client.stream("GET", ORIGIN + path, headers={"Authorization": "Bearer " + token,
                    "Accept": "application/json", "Accept-Encoding": "identity"}) as response:
                output["http"] = response.status_code
                if response.status_code == 200:
                    if response.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
                        raise ValueError()
                    body = bytearray()
                    for chunk in response.iter_raw():
                        body.extend(chunk)
                        if len(body) > 524288 or time.monotonic() >= deadline:
                            raise ValueError()
                    output.update(metadata(json.loads(body), token=token, email=email, selected=selected))
        except Exception:
            # No repr, exception body, request headers, cookies or provider error.
            output["error"] = "metadata_unavailable"
        outputs.append(output)
    return outputs


def main():
    logging.disable(logging.CRITICAL)
    token = None
    try:
        warnings.simplefilter("error", getpass.GetPassWarning)
        email = getpass.getpass("Known VINote owner email (hidden): ").strip().lower()
        if not email or "@" not in email:
            raise ValueError()
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from sqlalchemy import func, select
        from app.db import session_scope
        from app.db_models import CloudAccountDB, UserDB, VILabPreferenceDB
        from app.services.cloud_account_service import CloudAccountService

        with session_scope() as db:
            ids = list(db.scalars(select(UserDB.id).where(func.lower(func.trim(UserDB.email)) == email)))
            if len(ids) != 1:
                raise ValueError()
            user_id = ids[0]
            linked = db.scalar(select(CloudAccountDB.user_id).where(
                CloudAccountDB.user_id == user_id, func.lower(func.trim(CloudAccountDB.email)) == email))
            if linked != user_id:
                raise ValueError()
            selected = db.scalar(select(VILabPreferenceDB.llm_model).where(
                VILabPreferenceDB.user_id == user_id, VILabPreferenceDB.mode == "cloud"))
        token = CloudAccountService().access_token(user_id)
        import httpx
        with httpx.Client(timeout=httpx.Timeout(10, connect=5), follow_redirects=False,
                          trust_env=False) as client:
            results = collect(client, token, email, selected)
        output = {"selected_cloud_llm": safe_id(selected, token=token, email=email), "requests": results}
        output["selected_model_status"] = next((r.get("selected_model_status", [])
            for r in results if r["path"] == "/v1/models"), [])
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({"error": "owner_or_session_metadata_unavailable"}))
        return 1
    finally:
        token = None


if __name__ == "__main__":
    raise SystemExit(main())
