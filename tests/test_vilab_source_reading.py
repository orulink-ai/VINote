"""Offline real-adapter source-read boundaries; never dispatch to a provider."""
import copy
import hashlib
import json
import threading
from contextlib import nullcontext
from contextvars import ContextVar
from types import SimpleNamespace

import pytest
from PIL import Image

from app.llm.meeting_presentation import presentation_scope
from app.llm.meeting_source_reads import PartitionedDraft, combine_source_reads
from app.llm.source_references import capture_working_draft
from app.llm.vilab_llm import VILabLLM
from app.models.transcript import TranscriptSegment
from app.services.meeting_draft_artifact import save_source_reads, save_working_draft
from app.services.task_artifact_service import TaskArtifactService
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence
from app.services.vilab_cloud_service import _task_source, SummaryResultUnconfirmed


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr('httpx.Client.request', lambda *a, **k: pytest.fail('No network'))
    monkeypatch.setattr('httpx.stream', lambda *a, **k: pytest.fail('No network'))
    monkeypatch.setattr('app.services.tracing_service.observation', lambda *a, **k: nullcontext(None))
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.models', lambda *a: [
        {'id': 'frozen-model', 'modelType': 'llm', 'providerId': 'aliyun-token-plan-openai',
         'providerModel': 'deepseek-v4.1-flash'}])
    token = _task_source.set(('owner', {'mode': 'cloud', 'owner': 'owner',
        'server_url': 'https://example.invalid', 'llm_model': 'frozen-model'}))
    segments = [TranscriptSegment(i * 10, i * 10 + 9, f'Synthetic fact {i}.') for i in range(3)]
    frames = []
    for i in range(3):
        path = tmp_path / f'{i}.jpg'
        Image.new('RGB', (64, 64), (20, i * 60, 40)).save(path)
        frames.append(VideoFrameEvidence(i * 10 + 5, path, ['timeline'], [i * 10 + 5],
                      f'OCR {i}', 'recognized', [i], []))
    evidence = VideoEvidence(30, frames, 30, True)
    evidence._summary_frame_hashes = {f.image_path: hashlib.sha256(f.image_path.read_bytes()).hexdigest()
                                    for f in frames}
    artifacts = TaskArtifactService(tmp_path / 'output')
    folder = artifacts.create_task_dir('source-reads')
    yield SimpleNamespace(segments=segments, evidence=evidence, artifacts=artifacts, folder=folder)
    _task_source.reset(token)


def raw_draft(ref, text):
    return json.dumps({'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'attribute', 'text': text, 'material': True,
         'evidence': [{'kind': 'asr_span', 'source_ref': ref, 'quote': text}]}]})


def configured(case):
    llm = VILabLLM('owner', 'frozen-model')
    llm.configure_video_capabilities({'max_images': 8}, image_input_verified=True)
    llm.configure_source_reading(groups=3)
    llm.attach_source_reads_observer(lambda data: save_source_reads(case.artifacts, case.folder, data))
    return llm


def run(case, llm):
    with presentation_scope('detailed', 'text'), capture_working_draft(
            lambda text: save_working_draft(case.artifacts, case.folder, text)):
        return llm.summarize('Synthetic title', case.segments, style='meeting', video_evidence=case.evidence)


def test_three_parallel_reads_one_full_review_real_guard_and_v2_artifact(case, monkeypatch):
    llm = configured(case)
    barrier, calls = threading.Barrier(3), []
    marker = ContextVar('test_source_read_context', default=None)
    marker.set('copied execution context')

    def request(self, owner, method, path, **kwargs):
        assert owner == 'owner' and method == 'POST' and path == '/openai/v1/chat/completions'
        assert marker.get() == 'copied execution context'
        payload = kwargs['json']
        assert payload['model'] == 'frozen-model' and payload['stream'] is True
        assert payload['response_format'] == {'type': 'json_object'}
        content = payload['messages'][1]['content']
        image_count = sum(b['type'] == 'image_url' for b in content)
        calls.append((image_count, copy.deepcopy(payload)))
        if image_count == 1:
            assert 'SOURCE READ SCOPE:' in payload['messages'][0]['content']
            # Serialize the diagnostic assertion with its writer: Windows
            # readers do not share delete access with atomic os.replace.
            with llm._source_reads_lock:
                assert (json.loads((case.folder / 'meeting_source_reads.json').read_text())['reads']
                        [next(i for i in range(3) if f'[ASR:{i + 1:04d}]' in json.dumps(content))]['state']
                        == 'dispatched')
            ref = next(f'[ASR:{i + 1:04d}]' for i in range(3) if f'[ASR:{i + 1:04d}]' in json.dumps(content))
            index = int(ref[5:9]) - 1
            barrier.wait(timeout=5)
            raw = raw_draft(ref, case.segments[index].text)
        else:
            assert image_count == 3 and len(calls) == 4
            assert 'SOURCE READ SCOPE:' not in payload['messages'][0]['content']
            artifact = json.loads((case.folder / 'meeting_working_draft.json').read_text())
            material = json.loads(artifact['text'])
            assert artifact['version'] == 2
            assert artifact['provenance']['raw_reads'] == [
                raw_draft(f'[ASR:{i + 1:04d}]', s.text) for i, s in enumerate(case.segments)]
            raw = json.dumps({'protocol': 4,
                'blocks': [{'id': f'B{i}', 'markdown': c['text']} for i, c in enumerate(material['claims'])],
                'claims': [{k: v for k, v in c.items() if k != 'topic_id'} | {
                    'disposition': 'included', 'block_ids': [f'B{i}']}
                    for i, c in enumerate(material['claims'])]})
        return {'choices': [{'message': {'content': raw}}]}

    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
    assert run(case, llm) == '\n\n'.join(s.text for s in case.segments)
    assert len(calls) == 4 and sorted(n for n, _ in calls) == [1, 1, 1, 3]
    data = llm.source_reads_diagnostic()
    assert data['state'] == 'combined' and all(r['state'] == 'complete' for r in data['reads'])
    assert 'data:image' not in json.dumps(data)
    with pytest.raises(ValueError, match='fresh instance'):
        llm.configure_source_reading(groups=3)
    with pytest.raises(ValueError, match='already claimed'):
        run(case, llm)
    with pytest.raises(ValueError, match='already claimed'):
        llm._complete_review(system_prompt='x', user_prompt='x')
    assert len(calls) == 4


@pytest.mark.parametrize('mode', ['unknown', 'malformed', 'observer', 'mutation'])
def test_failure_preserves_raw_and_never_reviews_or_replays(case, monkeypatch, mode):
    llm = configured(case)
    calls = []
    if mode == 'observer':
        llm.attach_source_reads_observer(lambda data: (_ for _ in ()).throw(OSError('not logged')))
    if mode == 'mutation':
        original = llm._notify_source_reads
        def mutate():
            original()
            case.evidence.frames[0].ocr_text += 'changed'
        llm._notify_source_reads = mutate

    def request(self, owner, method, path, **kwargs):
        calls.append(kwargs['json'])
        if mode == 'unknown':
            raise SummaryResultUnconfirmed('connection')
        return {'choices': [{'message': {'content': '{ incomplete JSON'}}]}

    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
    with pytest.raises((ValueError, RuntimeError, OSError, SummaryResultUnconfirmed)) as caught:
        run(case, llm)
    if mode == 'unknown':
        assert isinstance(caught.value, SummaryResultUnconfirmed)
    assert len(calls) <= 3
    assert not (case.folder / 'result.json').exists()
    assert not (case.folder / 'meeting_working_draft.json').exists()
    if mode in {'observer', 'mutation'}:
        assert calls == []
    if mode == 'malformed':
        assert all(row['raw_response'] == '{ incomplete JSON' for row in llm.source_reads_diagnostic()['reads'])
    with pytest.raises(ValueError):
        run(case, llm)


def test_optin_rejects_other_forms_before_post_and_v1_remains_exact(case, monkeypatch):
    llm = configured(case)
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', lambda *a, **k: pytest.fail('No post'))
    with presentation_scope('detailed', 'html'), pytest.raises(ValueError, match='detailed text'):
        llm.summarize('title', case.segments, style='meeting', video_evidence=case.evidence)
    save_working_draft(case.artifacts, case.folder, 'Old raw draft')
    assert json.loads((case.folder / 'meeting_working_draft.json').read_text()) == {
        'version': 1, 'kind': 'source_preservation_draft', 'text': 'Old raw draft'}


def test_v2_preserves_namespace_mapping_without_rewriting_raw(case):
    raws = [raw_draft(f'[ASR:{i + 1:04d}]', s.text) for i, s in enumerate(case.segments)]
    draft = combine_source_reads(raws, [{f'[ASR:{i + 1:04d}]'} for i in range(3)])
    assert isinstance(draft, PartitionedDraft)
    save_working_draft(case.artifacts, case.folder, draft)
    data = json.loads((case.folder / 'meeting_working_draft.json').read_text())
    assert data['version'] == 2 and data['provenance']['raw_reads'] == raws
    assert [m['claims']['C1'] for m in data['provenance']['id_maps']] == ['R1_C1', 'R2_C1', 'R3_C1']


def test_ordinary_adapter_payload_and_raw_response_remain_single_call(case, monkeypatch):
    llm, calls = VILabLLM('owner', 'frozen-model'), []
    def request(self, owner, method, path, **kwargs):
        calls.append(kwargs['json'])
        return {'choices': [{'message': {'content': '  Unchanged legacy result  '}}]}
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
    assert llm._complete(system_prompt='System', user_prompt='Plain input') == 'Unchanged legacy result'
    assert calls[0]['messages'][1]['content'] == 'Plain input'
    assert calls[0]['stream_options'] == {'include_usage': True}
    assert llm.source_reads_diagnostic() is None


def test_raw_complete_survives_observer_write_failure(case, monkeypatch):
    llm = configured(case)
    def observer(data):
        if any(row['state'] == 'complete' for row in data['reads']):
            raise OSError('private disk failure')
        save_source_reads(case.artifacts, case.folder, data)
    llm.attach_source_reads_observer(observer)
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request',
        lambda *a, **k: {'choices': [{'message': {'content': '  actual complete raw  '}}]})
    with pytest.raises((OSError, ValueError)):
        run(case, llm)
    completed = [row for row in llm.source_reads_diagnostic()['reads'] if 'raw_response' in row]
    assert completed and all(row['raw_response'] == '  actual complete raw  ' for row in completed)
    assert all(row['state'] == 'complete' for row in completed)


def test_unknown_read_blocks_other_reads_paused_before_final_post_slot(case, monkeypatch):
    llm = configured(case)
    first_paused, failure_recorded = threading.Event(), threading.Event()
    original = SummaryResultUnconfirmed('connection')
    calls = []
    send = llm._send_prepared

    def observer(data):
        save_source_reads(case.artifacts, case.folder, data)
        if data['state'] == 'failed':
            failure_recorded.set()
    llm.attach_source_reads_observer(observer)

    def paused_send(cloud, system, content, parameters, **kwargs):
        text = json.dumps(content)
        if '[ASR:0001]' in text:
            first_paused.set()
            assert failure_recorded.wait(timeout=5)
        elif '[ASR:0003]' in text:
            assert failure_recorded.wait(timeout=5)
        return send(cloud, system, content, parameters, **kwargs)

    def request(self, owner, method, path, **kwargs):
        calls.append(kwargs['json'])
        assert first_paused.wait(timeout=5)
        raise original

    monkeypatch.setattr(llm, '_send_prepared', paused_send)
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
    with pytest.raises(SummaryResultUnconfirmed) as caught:
        run(case, llm)
    assert caught.value is original
    assert len(calls) == llm._source_post_count == 1
    assert '[ASR:0002]' in json.dumps(calls[0])
    assert not (case.folder / 'meeting_working_draft.json').exists()
    assert not (case.folder / 'result.json').exists()


def test_note_finally_diagnostic_failure_keeps_original_unconfirmed_and_raw_review(case, monkeypatch):
    from unittest.mock import Mock
    from app.services.note_service import NoteService
    import app.services.meeting_draft_artifact as artifact_module
    from app.llm.meeting_presentation import presentation_state
    original = SummaryResultUnconfirmed('connection')
    class Broken:
        source_reading_enabled = True
        model = 'frozen-model'
        def attach_source_reads_observer(self, callback):
            self.observer = callback
        def source_reads_diagnostic(self):
            return {'state': 'failed', 'reads': []}
        def summarize(self, **kwargs):
            presentation_state().raw_review = 'actual complete raw review'
            raise original
    runner = object.__new__(NoteService)
    runner.artifact_service = case.artifacts
    runner.llm_service = SimpleNamespace(create_summarizer=Mock(return_value=Broken()))
    context = SimpleNamespace(user_id='owner', model_profile_id=None, model_name='frozen-model',
        api_key=None, base_url=None, extras=None, style='meeting', content_depth='detailed',
        presentation='text', summary_mode='default', output_language='en', task_dir=case.folder,
        task_id='source-reads', step_timings={}, audio_meta=SimpleNamespace(title='title'))
    monkeypatch.setattr(artifact_module, 'save_source_reads', Mock(side_effect=OSError('not logged')))
    with pytest.raises(SummaryResultUnconfirmed) as caught:
        runner._summarize_audio(context, SimpleNamespace(metadata={}, segments=case.segments))
    assert caught.value is original
    assert json.loads((case.folder / 'meeting_fact_review.json').read_text())['raw_response'] == 'actual complete raw review'
