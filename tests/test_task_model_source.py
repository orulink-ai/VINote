import importlib.util
import json
from pathlib import Path
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.config import settings
from app.models.note import LocalFileRequest
from app.models.audio import AudioDownloadResult
from app.models.model_profile import ResolvedLLMConfig
from app.routers import note
from app.services import task_model_source as sources
from app.services import vilab_cloud_service as cloud_module
from app.services.vilab_cloud_service import VILabCloudService
from app.services.task_artifact_service import TaskArtifactService
from app.services.note_service import NoteService


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setattr(settings, 'vilab_server_url', 'https://source.test')
    row = SimpleNamespace(mode='cloud', asr_model='original-asr', llm_model='original-llm')
    @contextmanager
    def session():
        yield SimpleNamespace(get=lambda cls, user: row)
    monkeypatch.setattr(cloud_module, 'session_scope', session)
    monkeypatch.setattr(VILabCloudService, 'models', lambda self,user: [
        {'id': 'original-asr', 'modelType': 'asr', 'runtimeStatus': 'available'},
        {'id': 'original-llm', 'modelType': 'llm', 'runtimeStatus': 'available'}])
    return row


@pytest.mark.parametrize('status', ['service_error', 'rate_limited'])
def test_expired_transient_health_allows_only_same_selected_model(monkeypatch, status):
    monkeypatch.setattr(cloud_module.time, 'time', lambda: 1000)
    models = [{'id':'selected', 'modelType':'asr', 'runtimeStatus':'not_available',
               'availability':{'status':status, 'retryAt':999999}}]
    VILabCloudService._validate_selection(models, 'selected', 'asr')
    with pytest.raises(HTTPException):
        VILabCloudService._validate_selection(models, 'other', 'asr')
    with pytest.raises(HTTPException):
        VILabCloudService._validate_selection(models, 'selected', 'llm')
    assert models[0]['runtimeStatus'] == 'not_available'


@pytest.mark.parametrize('status,retry_at,runtime', [
    ('service_error',1000001,'not_available'), ('service_error',None,'not_available'),
    ('service_error','999999','not_available'), ('rate_limited',True,'not_available'),
    ('service_error',float('nan'),'not_available'), ('rate_limited',float('inf'),'not_available'),
    ('service_error',0,'not_available'), ('service_error',999999,'disabled'),
    ('service_error',999999,'unknown'), ('auth_failed',999999,'available'),
    ('quota_exhausted',999999,'not_available'), ('permission_denied',999999,'not_available'),
    ('disabled',999999,'not_available'), ('unknown',999999,'available'),
])
def test_health_policy_fails_closed(monkeypatch, status, retry_at, runtime):
    monkeypatch.setattr(cloud_module.time, 'time', lambda:1000)
    with pytest.raises(HTTPException):
        VILabCloudService._validate_selection([{'id':'selected','modelType':'asr','runtimeStatus':runtime,
            'availability':{'status':status,'retryAt':retry_at}}], 'selected','asr')


def test_catalog_preserves_availability_without_fabricating_recovery(monkeypatch):
    health={'status':'service_error','retryAt':999999}
    monkeypatch.setattr(VILabCloudService, 'request', lambda *args,**kwargs:{'data':[
        {'id':'selected','modelType':'asr','runtimeStatus':'not_available','availability':health}]})
    models=VILabCloudService().models('owner')
    assert models[0]['availability']==health
    assert models[0]['runtimeStatus']=='not_available'


def test_snapshot_survives_preference_mode_and_default_changes(tmp_path, cloud):
    original=sources.ensure_source(tmp_path,'owner',{},allow_capture=True)
    before=(tmp_path/sources.SNAPSHOT_FILE).read_bytes()
    cloud.mode='local';cloud.asr_model='changed-asr';cloud.llm_model='changed-llm'
    restored=sources.ensure_source(tmp_path,'owner',{})
    with VILabCloudService().task_snapshot('owner',snapshot=restored):
        VILabCloudService().validate_ready('owner')
        assert VILabCloudService().status('owner')['mode']=='cloud'
        assert VILabCloudService().defaults('owner')['asr_model']=='original-asr'
        assert VILabCloudService().defaults('owner')['llm_model']=='original-llm'
    assert original==restored
    assert (tmp_path/sources.SNAPSHOT_FILE).read_bytes()==before


def test_cross_account_invalid_and_changed_origin_never_recapture(tmp_path,cloud,monkeypatch):
    sources.ensure_source(tmp_path,'owner',{},allow_capture=True)
    with pytest.raises(HTTPException):sources.ensure_source(tmp_path,'other',{},allow_capture=True)
    monkeypatch.setattr(settings,'vilab_server_url','https://different.test')
    with pytest.raises(HTTPException):sources.ensure_source(tmp_path,'owner',{},allow_capture=True)
    (tmp_path/sources.SNAPSHOT_FILE).write_text('{broken')
    with pytest.raises(HTTPException):sources.ensure_source(tmp_path,'owner',{},allow_capture=True)


def test_old_missing_snapshot_requires_explicit_confirmation(tmp_path, cloud):
    with pytest.raises(HTTPException) as error:sources.ensure_source(tmp_path,'owner',{})
    assert error.value.status_code==409
    confirmation={'confirmed':True,'mode':'cloud','server_url':'https://source.test',
                  'asr_model':'original-asr','llm_model':'original-llm'}
    cloud.asr_model='other';cloud.llm_model='other'
    value=sources.ensure_source(tmp_path,'owner',{},confirmation=confirmation)
    assert value['asr_model']=='original-asr'
    with pytest.raises(HTTPException):sources.ensure_source(tmp_path,'owner',{},confirmation=confirmation)


def test_confirmation_cannot_bypass_auth_failure_or_origin(tmp_path,cloud,monkeypatch):
    confirmation={'confirmed':True,'mode':'cloud','server_url':'https://source.test',
                  'asr_model':'original-asr','llm_model':'original-llm'}
    monkeypatch.setattr(VILabCloudService,'models',lambda *args:[
        {'id':'original-asr','modelType':'asr','runtimeStatus':'not_available',
         'availability':{'status':'auth_failed','retryAt':1}},
        {'id':'original-llm','modelType':'llm','runtimeStatus':'available'}])
    with pytest.raises(HTTPException):sources.ensure_source(tmp_path,'owner',{},confirmation=confirmation)
    assert not (tmp_path/sources.SNAPSHOT_FILE).exists()
    confirmation['server_url']='https://arbitrary.test'
    with pytest.raises(HTTPException):sources.ensure_source(tmp_path,'owner',{},confirmation=confirmation)


def test_cloud_preflight_uses_frozen_models_before_preparation(tmp_path,cloud,monkeypatch):
    artifacts=TaskArtifactService(tmp_path/'output')
    folder=artifacts.create_task_dir('task')
    sources.ensure_source(folder,'owner',{},allow_capture=True)
    artifacts.update_status(folder,'failed','network')
    cloud.mode='local'; cloud.asr_model='new';cloud.llm_model='new'
    service=object.__new__(NoteService)
    service.artifact_service=artifacts
    audio=tmp_path/'original.wav';audio.write_bytes(b'original')
    meta=AudioDownloadResult(file_path=str(audio),title='recording',duration=10,video_id='task',platform='local')
    monkeypatch.setattr(service,'_build_local_audio_meta',lambda **kwargs:meta)
    monkeypatch.setattr(service,'_run_pipeline',lambda **kwargs:VILabCloudService().status('owner'))
    actual=service.generate_from_file(file_path=str(audio),task_id='task',user_id='owner')
    assert actual['asr_model']=='original-asr' and actual['mode']=='cloud'


def test_local_profile_change_fails_but_credentials_are_not_persisted(cloud):
    config=ResolvedLLMConfig(provider='openai-compatible',base_url='https://local.test',model_name='original',api_key='private')
    expected=sources.config_fingerprint(config)
    config.api_key='rotated'
    assert sources.config_fingerprint(config)==expected
    with VILabCloudService().task_snapshot('owner',snapshot={'mode':'local','local_llm_fingerprint':expected}):
        sources.verify_local_config('owner','llm',config)
        config.model_name='changed'
        with pytest.raises(HTTPException):sources.verify_local_config('owner','llm',config)


def test_retry_without_snapshot_does_not_schedule_or_mutate_source(tmp_path,cloud,monkeypatch):
    artifacts=TaskArtifactService(tmp_path/'output')
    folder=artifacts.create_task_dir('old')
    artifacts.update_status(folder,'failed','network')
    (folder/'recording_owner').write_text('owner')
    audio=folder/'source.wav';audio.write_bytes(b'original')
    artifacts.record_source_media(folder,audio,media_kind='audio')
    req=LocalFileRequest(file_path=str(audio),model_profile_id='vilab-cloud',stt_profile_id='vilab-cloud')
    artifacts.write_json(folder/'request.json',{'request':req.model_dump(),'trace':None})
    before=(folder/'request.json').read_bytes()
    monkeypatch.setattr(note,'_note_service',SimpleNamespace(artifact_service=artifacts))
    tasks=BackgroundTasks()
    with pytest.raises(HTTPException) as error:note.retry_media_task('old',tasks,SimpleNamespace(user_id='owner'),None)
    assert error.value.status_code==409 and not tasks.tasks
    assert (folder/'request.json').read_bytes()==before and audio.read_bytes()==b'original'
    confirmation={'confirmed':True,'mode':'cloud','server_url':'https://source.test',
                  'asr_model':'original-asr','llm_model':'original-llm'}
    try:
        assert note.retry_media_task('old',tasks,SimpleNamespace(user_id='owner'),confirmation)['task_id']=='old'
        assert len(tasks.tasks)==1
        cloud.asr_model='different'
        assert sources.ensure_source(folder,'owner',{})['asr_model']=='original-asr'
    finally:
        note._ACTIVE_FILE_TASKS.discard('old')


@pytest.mark.parametrize('entry', ['upload', 'direct_file'])
def test_fresh_router_persists_source_before_request_and_reaches_generator(tmp_path, cloud, monkeypatch, entry):
    import io
    import wave
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    artifacts = TaskArtifactService(tmp_path/'output')
    service = object.__new__(NoteService)
    service.artifact_service = artifacts
    service.transcription_service = SimpleNamespace(get_audio_duration=lambda path: 1)
    reached = []
    monkeypatch.setattr(service, '_run_pipeline', lambda **kwargs: reached.append(VILabCloudService().status('owner')))
    monkeypatch.setattr(note, '_note_service', service)
    persist = note._persist_file_request
    def persist_then_change_settings(folder, req, user_id, trace):
        persist(folder, req, user_id, trace)
        assert (folder/sources.SNAPSHOT_FILE).exists()
        assert (folder/'request.json').exists()
        cloud.mode = 'local'
        cloud.asr_model = cloud.llm_model = 'changed-after-submit'
    monkeypatch.setattr(note, '_persist_file_request', persist_then_change_settings)
    app = FastAPI()
    app.include_router(note.router, prefix='/api')
    app.dependency_overrides[note.get_optional_current_user] = lambda: SimpleNamespace(user_id='owner')
    content = io.BytesIO()
    with wave.open(content, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b'\0' * 32000)
    with TestClient(app) as client:
        if entry == 'upload':
            response = client.post('/api/generate_from_upload', data={'source_type':'audio','workflow':'meeting'},
                                   files={'file':('original.wav',content.getvalue(),'audio/wav')})
        else:
            original = tmp_path/'original.wav'
            original.write_bytes(content.getvalue())
            response = client.post('/api/generate_from_file', json={'file_path':str(original)})
    assert response.status_code == 200, response.text
    task_id = response.json()['task_id']
    folder = artifacts.find_task_dir(task_id)
    assert len(reached) == 1
    assert reached[0]['asr_model'] == 'original-asr' and reached[0]['llm_model'] == 'original-llm'
    assert reached[0]['mode'] == 'cloud'
    assert json.loads((folder/'request.json').read_text())['request']['file_path']
@pytest.mark.parametrize('case', ['legacy', 'frozen', 'wrong_owner', 'active', 'blocked'])
def test_confirmation_route_is_owner_scoped_read_only(tmp_path, cloud, monkeypatch, case):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    artifacts = TaskArtifactService(tmp_path/'output')
    folder = artifacts.create_task_dir('recover')
    artifacts.update_status(folder, 'failed', 'network')
    (folder/'recording_owner').write_text('owner')
    audio = folder/'source.wav'
    audio.write_bytes(b'original')
    artifacts.record_source_media(folder, audio, media_kind='audio')
    req = LocalFileRequest(file_path=str(audio), title='Original recording')
    artifacts.write_json(folder/'request.json', {'request':req.model_dump(), 'trace':None})
    if case == 'frozen':
        sources.ensure_source(folder, 'owner', {}, allow_capture=True)
    if case == 'active':
        status = artifacts.get_status('recover')
        status['status'] = 'transcribing'
        artifacts.write_json(folder/'status.json', status)
    if case == 'blocked':
        monkeypatch.setattr(VILabCloudService, 'models', lambda *args: [
            {'id':'original-asr', 'modelType':'asr', 'runtimeStatus':'not_available',
             'availability':{'status':'auth_failed','retryAt':1}},
            {'id':'original-llm', 'modelType':'llm','runtimeStatus':'available'}])
    before = {p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
    monkeypatch.setattr(note, '_note_service', SimpleNamespace(artifact_service=artifacts))
    app = FastAPI()
    app.include_router(note.router, prefix='/api')
    app.dependency_overrides[note.get_current_user] = lambda: SimpleNamespace(user_id='other' if case=='wrong_owner' else 'owner')
    with TestClient(app) as client:
        response = client.get('/api/task/recover/model-confirmation')
    assert response.status_code == {'wrong_owner':404, 'active':409}.get(case, 200), response.text
    if case in {'legacy','blocked'}:
        value = response.json()
        assert value['selection']['asr_model'] == 'original-asr'
        assert value['selection']['llm_model'] == 'original-llm'
        assert value['source']['title'] == 'Original recording'
        assert value['can_confirm'] == (case=='legacy')
        assert 'file_path' not in response.text
    elif case == 'frozen':
        assert response.json()['requires_confirmation'] is False
    assert before == {p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}

def test_http_retry_confirmation_freezes_displayed_models_and_preserves_task(tmp_path, cloud, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    artifacts = TaskArtifactService(tmp_path/'output')
    folder = artifacts.create_task_dir('old-http')
    artifacts.update_status(folder, 'failed', 'network', retryable=True)
    (folder/'recording_owner').write_text('owner')
    audio = folder/'source.wav'
    audio.write_bytes(b'original')
    artifacts.record_source_media(folder, audio, media_kind='audio')
    req = LocalFileRequest(file_path=str(audio), title='Original')
    artifacts.write_json(folder/'request.json', {'request':req.model_dump(), 'trace':None})
    request_before = (folder/'request.json').read_bytes()
    monkeypatch.setattr(note, '_note_service', SimpleNamespace(artifact_service=artifacts))
    scheduled = []
    monkeypatch.setattr(note, '_run_task_from_file', lambda *args, **kwargs: scheduled.append((args,kwargs)))
    app = FastAPI()
    app.include_router(note.router, prefix='/api')
    app.dependency_overrides[note.get_current_user] = lambda: SimpleNamespace(user_id='owner')
    try:
        with TestClient(app) as client:
            assert client.post('/api/task/old-http/retry').status_code == 409
            context = client.get('/api/task/old-http/model-confirmation').json()
            cloud.asr_model = cloud.llm_model = 'changed-after-read'
            response = client.post('/api/task/old-http/retry', json={'confirmed':True, **context['selection']})
        assert response.status_code == 200, response.text
        assert response.json()['task_id'] == 'old-http'
        assert len(scheduled) == 1
        assert sources.ensure_source(folder, 'owner', {})['asr_model'] == 'original-asr'
        assert (folder/'request.json').read_bytes() == request_before
        assert audio.read_bytes() == b'original'
    finally:
        note._ACTIVE_FILE_TASKS.discard('old-http')
