import json

import pytest

from app.services.summary_failure import SummaryResultUnconfirmed, safe_summary_failure_context
from app.services.task_failure import failure_details
from app.services.task_artifact_service import TaskArtifactService


@pytest.mark.parametrize("reason", ["http524", "timeout", "connection"])
def test_safe_transport_category_survives_failure_and_status(tmp_path, reason):
    error = SummaryResultUnconfirmed(reason)
    expected = {"diagnostic_protocol": "summary_transport/1", "category": reason}
    error.summary_failure_context["body"] = "SYNTHETIC_SECRET"
    details = failure_details(error)
    assert details["summary_failure_context"] == expected
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir("task")
    artifacts.update_status(folder, "summarizing")
    artifacts.update_status(folder, "failed", str(error), **details)
    artifacts.update_status(folder, "failed", "outer", retryable=True)
    status = artifacts.get_status("task")
    assert status["summary_failure_context"] == expected
    assert status["retryable"] is False
    assert "SYNTHETIC_SECRET" not in json.dumps(status)


@pytest.mark.parametrize("category", ["SYNTHETIC_SECRET", None, [], 524])
def test_unknown_transport_category_rejected(category):
    assert safe_summary_failure_context({"diagnostic_protocol": "summary_transport/1",
                                         "category": category}) is None
