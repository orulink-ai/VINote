import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.llm.openai_llm import _BasePromptLLM
from app.services.note_service import NoteService
from tests.test_meeting_summary_regeneration import case


def test_saved_draft_runs_only_final_review_and_normal_child_save(case, monkeypatch):
    from scripts.recover_meeting_review import start_recovery
    c = case
    from app.services.vilab_cloud_service import VILabCloudService
    monkeypatch.setattr(VILabCloudService, 'models', lambda self, owner: [
        {'id': 'old-model', 'modelType': 'llm', 'runtimeStatus': 'available'}])
    source = c.transcript['full_text']
    draft = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'relation', 'text': source, 'anchor': source,
         'material': True, 'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': source}]}]}
    c.artifacts.write_json(c.folder / 'meeting_working_draft.json',
                           {'version': 1, 'kind': 'source_preservation_draft', 'text': json.dumps(draft)})
    c.artifacts.write_json(c.folder / 'summary_presentation.json',
                           {'content_depth': 'detailed', 'presentation': 'text'})
    calls = []
    class Offline(_BasePromptLLM):
        model = 'old-model'
        def _complete(self, **prompts):
            calls.append(prompts)
            return json.dumps({'protocol': 4, 'blocks': [{'id': 'B1', 'markdown': '# Synthetic'},
                {'id': 'B2', 'markdown': source}], 'claims': [{'id': 'C1', 'field': 'relation',
                'text': source, 'material': True, 'disposition': 'included', 'block_ids': ['B2'],
                'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': source}]}]})
    runner = object.__new__(NoteService)
    runner.artifact_service = c.artifacts
    runner.llm_service = SimpleNamespace(create_summarizer=Mock(return_value=Offline()))
    runner.transcription_service = SimpleNamespace(transcribe=Mock(side_effect=AssertionError('ASR forbidden')))
    before = (c.folder / 'meeting_working_draft.json').read_bytes()
    receipt = start_recovery(c.service, runner, 'alice', c.parent, uuid4())
    child = c.artifacts.find_task_dir(receipt.task_id)
    assert c.artifacts.get_status(receipt.task_id)['status'] == 'success'
    assert json.loads((child / 'result.json').read_text(encoding='utf-8'))['markdown'] == '# Synthetic\n\n' + source
    assert (child / 'note.md').exists()
    assert len(calls) == 1 and source in calls[0]['user_prompt']
    assert (c.folder / 'meeting_working_draft.json').read_bytes() == before
    assert json.loads((child / 'model_source_snapshot.json').read_text())['llm_model'] == 'old-model'
    with pytest.raises(ValueError, match='operation already exists'):
        start_recovery(c.service, runner, 'alice', c.parent, receipt.operation_id)
    assert len(calls) == 1


def test_recovery_rejects_changed_draft_before_review(case):
    from scripts.recover_meeting_review import inject_saved_draft
    path = case.folder / 'meeting_working_draft.json'
    path.write_text('original', encoding='utf-8')
    llm = _BasePromptLLM()
    inject_saved_draft(llm, path, path.read_bytes(), 'old draft')
    path.write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='draft changed'):
        llm._complete_stage(stage='LLM｜生成会议纪要')
