import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import meeting_video_analysis_service as module


def test_sampling_is_bounded_and_inside_video():
    assert module.sample_timestamps(1) == [0.5]
    samples = module.sample_timestamps(7200)
    assert len(samples) == 24
    assert all(0 <= value < 7200 for value in samples)
    with pytest.raises(ValueError):
        module.sample_timestamps(float('nan'))


def test_visual_analysis_submits_frames_and_persists_timestamped_evidence(monkeypatch, tmp_path):
    cloud = Mock()
    cloud.status.return_value = {'mode': 'cloud'}
    cloud.models.return_value = [{'id': module.VISION_MODEL, 'runtimeStatus': 'available'}]
    cloud.request.return_value = {'choices': [{'message': {'content': '画面显示项目进度表。'}}]}
    monkeypatch.setattr(module, 'VILabCloudService', lambda: cloud)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=b'jpeg'))
    trace = Mock()
    monkeypatch.setattr(module, 'update_current', trace)
    result = module.MeetingVideoAnalysisService().analyze(
        video_path=tmp_path/'meeting.webm', duration=30, user_id='user', task_dir=tmp_path)
    assert '抽样' in result
    payload = cloud.request.call_args.kwargs['json']
    assert len([item for item in payload['messages'][0]['content'] if item['type'] == 'image_url']) == 2
    artifact = json.loads((tmp_path/'visual_observations.json').read_text(encoding='utf-8'))
    assert artifact['offsets_seconds'] == [7.5, 22.5]
    assert 'image/jpeg' not in str(trace.call_args_list)
    assert str(tmp_path) not in str(trace.call_args_list)


def test_video_analysis_fails_explicitly_when_model_unavailable(monkeypatch, tmp_path):
    cloud = Mock()
    cloud.status.return_value = {'mode': 'cloud'}
    cloud.models.return_value = []
    monkeypatch.setattr(module, 'VILabCloudService', lambda: cloud)
    with pytest.raises(ValueError, match='录制已保留'):
        module.MeetingVideoAnalysisService().analyze(
            video_path=tmp_path/'meeting.webm', duration=30, user_id='user', task_dir=tmp_path)
    cloud.request.assert_not_called()
