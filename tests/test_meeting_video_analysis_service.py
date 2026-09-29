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
    cloud.defaults.return_value = {'llm_model': 'deployed-vision-model'}
    cloud.models.return_value = [{'id': 'deployed-vision-model', 'modelType': 'llm', 'runtimeStatus': 'available'}]
    cloud.request.return_value = {'choices': [{'message': {'content': '画面显示项目进度表。'}}]}
    monkeypatch.setattr(module, 'VILabCloudService', lambda: cloud)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=b'jpeg'))
    trace = Mock()
    monkeypatch.setattr(module, 'update_current', trace)
    result = module.MeetingVideoAnalysisService().analyze(
        video_path=tmp_path/'meeting.webm', duration=30, user_id='user', task_dir=tmp_path)
    assert '抽样' in result
    payload = cloud.request.call_args.kwargs['json']
    assert payload['model'] == 'deployed-vision-model'
    assert len([item for item in payload['messages'][0]['content'] if item['type'] == 'image_url']) == 2
    artifact = json.loads((tmp_path/'visual_observations.json').read_text(encoding='utf-8'))
    assert artifact['offsets_seconds'] == [7.5, 22.5]
    assert 'image/jpeg' not in str(trace.call_args_list)
    assert str(tmp_path) not in str(trace.call_args_list)


def test_video_analysis_fails_explicitly_when_model_unavailable(monkeypatch, tmp_path):
    cloud = Mock()
    cloud.status.return_value = {'mode': 'cloud'}
    cloud.defaults.return_value = {'llm_model': 'gone'}
    cloud.models.return_value = []
    monkeypatch.setattr(module, 'VILabCloudService', lambda: cloud)
    with pytest.raises(ValueError, match='录制已保留'):
        module.MeetingVideoAnalysisService().analyze(
            video_path=tmp_path/'meeting.webm', duration=30, user_id='user', task_dir=tmp_path)
    cloud.request.assert_not_called()

@pytest.mark.parametrize('selected,support,expected', [
    ('chosen', None, 'chosen'),
    ('chosen', True, 'chosen'),
    ('chosen', False, 'other'),
    ('removed', None, 'other'),
])
def test_dynamic_selection_respects_catalog_and_task_choice(selected, support, expected):
    cloud = Mock()
    cloud.defaults.return_value = {'llm_model': selected}
    cloud.models.return_value = [
        {'id': 'chosen', 'modelType': 'llm', 'runtimeStatus': 'available',
         'capabilities': {} if support is None else {'vision': support}},
        {'id': 'other', 'modelType': 'llm', 'runtimeStatus': 'available',
         'capabilities': {'vision': {'status': 'supported'}}},
    ]
    assert module.resolve_video_model(cloud, 'user') == expected


def test_cache_is_invalidated_when_selected_model_changes(monkeypatch, tmp_path):
    cloud = Mock()
    cloud.status.return_value = {'mode': 'cloud'}
    cloud.defaults.return_value = {'llm_model': 'new-model'}
    cloud.models.return_value = [{'id': 'new-model', 'modelType': 'llm', 'runtimeStatus': 'available'}]
    cloud.request.return_value = {'choices': [{'message': {'content': 'new evidence'}}]}
    monkeypatch.setattr(module, 'VILabCloudService', lambda: cloud)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=b'jpeg'))
    cache = tmp_path / 'visual_observations.json'
    cache.write_text(json.dumps({'model': 'old-model', 'server': module.settings.vilab_server_url.rstrip('/'),
                                'offsets_seconds': [0.5], 'text': 'old evidence'}), encoding='utf-8')
    service = module.MeetingVideoAnalysisService()
    result = service.analyze(video_path=tmp_path/'video.mp4', duration=1, user_id='user', task_dir=tmp_path)
    assert 'new evidence' in result
    assert cloud.request.call_count == 1
    service.analyze(video_path=tmp_path/'video.mp4', duration=1, user_id='user', task_dir=tmp_path)
    assert cloud.request.call_count == 1
    assert json.loads(cache.read_text(encoding='utf-8'))['model'] == 'new-model'


def test_unknown_capability_failure_names_actual_selected_model(monkeypatch, tmp_path):
    from fastapi import HTTPException
    cloud = Mock()
    cloud.status.return_value = {'mode': 'cloud'}
    cloud.defaults.return_value = {'llm_model': 'server-selected'}
    cloud.models.return_value = [{'id': 'server-selected', 'modelType': 'llm', 'runtimeStatus': 'available'}]
    cloud.request.side_effect = HTTPException(502, 'upstream rejected images')
    monkeypatch.setattr(module, 'VILabCloudService', lambda: cloud)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=b'jpeg'))
    with pytest.raises(ValueError, match='server-selected'):
        module.MeetingVideoAnalysisService().analyze(video_path=tmp_path/'video.mp4', duration=1,
                                                   user_id='user', task_dir=tmp_path)
    assert not (tmp_path/'visual_observations.json').exists()
