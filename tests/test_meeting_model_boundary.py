from copy import deepcopy

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services.task_model_source import ensure_source, SNAPSHOT_FILE
from app.services.vilab_cloud_service import VILabCloudService

CAPABILITIES = {
    'useCases': ['meeting'], 'protocols': ['asr-recording'], 'audioDelivery': 'public',
    'audioFormats': ['wav'], 'maxAudioSeconds': 7200, 'maxAudioBytes': 512 * 1024 * 1024,
    'speakerDiarization': True, 'utteranceTimestamps': True,
    'recordedAudio': {'protocol': 1, 'supported': True, 'strategy': 'single_request',
                      'policySource': 'provider_model'},
}

@pytest.fixture
def catalog(monkeypatch):
    config = dict(mode='cloud', server_url=settings.vilab_server_url,
                  asr_model='speech', llm_model='summary')
    models = [dict(id='speech', modelType='asr', runtimeStatus='available', capabilities=deepcopy(CAPABILITIES)),
              dict(id='summary', modelType='llm', runtimeStatus='available')]
    monkeypatch.setattr(VILabCloudService, 'connection_snapshot', lambda *a: dict(config))
    monkeypatch.setattr(VILabCloudService, 'models', lambda *a: models)
    return config, models

@pytest.mark.parametrize('intent', [{'style': 'meeting'}, {'workflow': 'meeting', 'style': 'detailed'}])
def test_realtime_selection_rejected_before_snapshot(tmp_path, catalog, intent):
    catalog[1][0]['capabilities']['useCases'] = ['realtime']
    with pytest.raises(HTTPException, match='会议'):
        ensure_source(tmp_path, 'owner', intent, allow_capture=True)
    assert not (tmp_path / SNAPSHOT_FILE).exists()

def test_default_realtime_is_not_a_meeting_default(tmp_path, catalog, monkeypatch):
    catalog[0]['asr_model'] = ''
    catalog[1][0]['capabilities']['useCases'] = ['realtime']
    monkeypatch.setattr(VILabCloudService, 'request', lambda *a, **kw: dict(asr_model='speech', llm_model='summary'))
    with pytest.raises(HTTPException, match='会议'):
        ensure_source(tmp_path, 'owner', {'style': 'meeting'}, allow_capture=True)
    assert not (tmp_path / SNAPSHOT_FILE).exists()

def test_local_meeting_rejected_before_resolving_profiles(tmp_path, catalog, monkeypatch):
    from app.services.llm_service import LLMService
    catalog[0]['mode'] = 'local'
    def forbidden(*a, **kw):
        pytest.fail('local provider must not be resolved')
    monkeypatch.setattr(LLMService, 'resolve_config', forbidden)
    with pytest.raises(HTTPException, match='公网'):
        ensure_source(tmp_path, 'owner', {'style': 'meeting'}, allow_capture=True)

def test_valid_meeting_and_summary_only(tmp_path, catalog):
    source = ensure_source(tmp_path, 'owner', {'style': 'meeting'}, allow_capture=True)
    assert source['asr_model'] == 'speech'
    before = (tmp_path / SNAPSHOT_FILE).read_bytes()
    catalog[1][0]['capabilities'] = {}
    with pytest.raises(HTTPException):
        ensure_source(tmp_path, 'owner', {'style': 'meeting'})
    assert (tmp_path / SNAPSHOT_FILE).read_bytes() == before
    assert ensure_source(tmp_path, 'owner', {'style': 'meeting', 'needs_stt': False}) == source

def test_nonmeeting_keeps_realtime_selection(tmp_path, catalog):
    catalog[1][0]['capabilities'] = {}
    assert ensure_source(tmp_path, 'owner', {'style': 'detailed'}, allow_capture=True)['asr_model'] == 'speech'

@pytest.mark.parametrize('meeting', [True, False])
def test_dispatch_rechecks_policy_and_preserves_nonmeeting_stream(monkeypatch, meeting):
    from unittest.mock import Mock
    from app.services.adaptive_asr_policy import RecordingModelPolicy
    from app.services.meeting_model_boundary import meeting_execution
    from app.transcribers.vilab_transcriber import VILabTranscriber
    adapter = VILabTranscriber(settings.vilab_server_url, 'synthetic', 'speech')
    capabilities = deepcopy(CAPABILITIES)
    capabilities['useCases'] = ['realtime']
    monkeypatch.setattr(adapter, '_recognition_bearer', lambda: 'synthetic')
    monkeypatch.setattr(adapter, '_recorded_audio_policy', lambda _: RecordingModelPolicy.from_capabilities(capabilities))
    stream = Mock(return_value='nonmeeting transcript')
    upload = Mock(side_effect=AssertionError('must not upload'))
    monkeypatch.setattr(adapter, '_transcribe_stream', stream)
    monkeypatch.setattr(adapter, '_transcribe_recording', upload)
    token = meeting_execution.set(meeting)
    try:
        if meeting:
            with pytest.raises(HTTPException, match='会议'):
                adapter._transcribe_normalized('never-open.wav')
            stream.assert_not_called()
        else:
            assert adapter._transcribe_normalized('never-open.wav') == 'nonmeeting transcript'
        upload.assert_not_called()
    finally:
        meeting_execution.reset(token)

def test_pipeline_rejects_local_before_media_or_provider_access(catalog):
    from app.services.note_service import NoteService
    from unittest.mock import patch
    service = object.__new__(NoteService)
    with patch.object(VILabCloudService, 'status', return_value={'mode': 'local'}):
        with pytest.raises(HTTPException, match='公网'):
            service._run_pipeline(style='meeting', user_id='owner')

def test_missing_default_is_actionable(tmp_path, catalog, monkeypatch):
    catalog[0]['asr_model'] = ''
    monkeypatch.setattr(VILabCloudService, 'request', lambda *a, **kw: dict(asr_model='', llm_model='summary'))
    with pytest.raises(HTTPException, match='服务管理员'):
        ensure_source(tmp_path, 'owner', {'style': 'meeting'}, allow_capture=True)
    assert not (tmp_path / SNAPSHOT_FILE).exists()

def test_summary_only_uses_frozen_llm_without_defaults_or_asr(catalog, monkeypatch):
    from app.services.meeting_model_boundary import meeting_pipeline
    from app.services.vilab_cloud_service import _task_source
    source = {**catalog[0], 'asr_model': 'retired-asr', 'needs_stt': False}
    catalog[1][:] = [catalog[1][1]]
    monkeypatch.setattr(VILabCloudService, 'status', lambda *a: dict(source))
    def forbidden(*a, **kw):
        pytest.fail('summary-only must not resolve defaults')
    monkeypatch.setattr(VILabCloudService, 'defaults', forbidden)
    @meeting_pipeline
    def execute(self, **kwargs):
        assert _task_source.get()[1]['llm_model'] == 'summary'
        return 'done'
    assert execute(None, style='meeting', user_id='owner', preloaded_transcript=object()) == 'done'

def test_legacy_settings_migration_is_readonly_and_requires_explicit_models(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from app.routers import vilab
    from app.services import vilab_cloud_service
    row = SimpleNamespace(mode='local', asr_model='old-asr', llm_model='old-llm')
    @contextmanager
    def session():
        yield SimpleNamespace(get=lambda *a: row)
    monkeypatch.setattr(vilab_cloud_service, 'session_scope', session)
    monkeypatch.setattr(VILabCloudService, 'models', lambda *a: [
        dict(id='summary', modelType='llm', runtimeStatus='available')])
    projected = vilab.config(SimpleNamespace(user_id='owner'))
    assert projected['mode'] == 'cloud'
    assert projected['asr_model'] == projected['llm_model'] == ''
    assert row.mode == 'local' and row.asr_model == 'old-asr'
    vilab.select_models(vilab.Selection(mode='cloud', llm_model='summary'), SimpleNamespace(user_id='owner'))
    assert row.mode == 'cloud' and row.asr_model == '' and row.llm_model == 'summary'

def test_defaults_read_under_captured_snapshot(tmp_path, catalog, monkeypatch):
    from app.services.vilab_cloud_service import _task_source
    catalog[0]['asr_model'] = ''
    def defaults(self, owner, method, path):
        assert path == '/v1/default-models'
        assert _task_source.get()[1]['server_url'] == settings.vilab_server_url
        assert _task_source.get()[1]['llm_model'] == 'summary'
        return {'asr_model': 'speech', 'llm_model': 'different-default'}
    monkeypatch.setattr(VILabCloudService, 'request', defaults)
    source = ensure_source(tmp_path, 'owner', {'style': 'meeting'}, allow_capture=True)
    assert source['llm_model'] == 'summary' and source['asr_model'] == 'speech'
