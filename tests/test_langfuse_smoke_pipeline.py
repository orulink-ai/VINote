import socket
from scripts.check_langfuse import generate_synthetic_note
from app.services.task_artifact_service import TaskArtifactService


def test_build_probe_runs_real_note_pipeline_without_meeting_policy_or_model_network(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Synthetic build check must not call a real model')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    state = generate_synthetic_note('synthetic-build-probe', str(tmp_path))
    assert state['status'] == 'success'
    assert TaskArtifactService(tmp_path).get_result('synthetic-build-probe')['markdown'] == '# Synthetic note'
