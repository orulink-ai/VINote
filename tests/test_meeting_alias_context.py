"""Offline explicit-alias snapshot -> accepted summary -> actual two-call prompts."""
from contextlib import contextmanager
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.test_meeting_summary_regeneration import case, accept
from app.db_models import SourceRequestDB
from app.models.feishu_object_hotwords import FeishuObjectAliasDB, FeishuObjectDB
from app.services import feishu_object_hotwords as hotwords
from app.services.meeting_alias_context import capture_alias_context, alias_extras, alias_source_text


@pytest.fixture
def aliases(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'aliases.db'))
    FeishuObjectDB.__table__.create(engine)
    FeishuObjectAliasDB.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    binding = {'owner': 'alice', 'connection_id': 'connection-one',
               'sender_open_id': 'ou_sender_private', 'app_id': 'cli_test_app', 'tenant_key': 'tenant-private'}
    active = {'binding': copy.deepcopy(binding), 'enabled': True}
    service = hotwords.FeishuObjectHotwordsService(
        binding_provider=lambda owner: active['binding'], cli_enabled=lambda: active['enabled'],
        session_factory=sessions)
    monkeypatch.setattr(hotwords, 'service', service)
    service.record_objects('alice', binding, [
        {'id': 'ou_target_private', 'name': '林清', 'kind': 'contact'},
        {'id': 'oc_group_private', 'name': '研究小组', 'kind': 'group'},
        {'id': 'ou_unselected_private', 'name': '不应进入模型的通讯录对象', 'kind': 'contact'}])
    yield SimpleNamespace(**locals())
    engine.dispose()


def add(aliases):
    aliases.service.add_alias('alice', aliases.binding, '小林', 'ou_target_private')
    aliases.service.add_alias('alice', aliases.binding, '研究组', 'oc_group_private')


def test_only_explicit_aliases_join_real_targets_and_no_ids_enter_extras(aliases):
    add(aliases)
    frozen = capture_alias_context('alice')
    assert frozen['terms'] == [{'alias': '小林', 'name': '林清', 'kind': 'contact'},
                               {'alias': '研究组', 'name': '研究小组', 'kind': 'group'}]
    output = alias_extras('alice', '用户原有要求', frozen, source_text='小林加入研究组')
    assert output.startswith('用户原有要求\n\n') and '林清' in output
    for private in ('ou_target_private', 'oc_group_private', 'ou_unselected_private',
                    'connection-one', 'tenant-private', 'cli_test_app', 'ou_sender_private',
                    '不应进入模型的通讯录对象', frozen['binding_sha256']):
        assert private not in output
    assert '不得改写原ASR/OCR引文' in output and '发送授权' in output


def test_objects_without_explicit_aliases_do_not_add_context(aliases):
    frozen = capture_alias_context('alice')
    assert frozen == {'protocol': 1, 'owner': 'alice', 'binding_sha256': None, 'terms': []}
    assert alias_extras('alice', None, frozen) is None


@pytest.mark.parametrize('status', [401, 403, 409, 503])
def test_missing_or_unavailable_feishu_never_blocks_summary(aliases, monkeypatch, status):
    monkeypatch.setattr(aliases.service, 'current_binding', Mock(side_effect=HTTPException(status, 'private error')))
    frozen = capture_alias_context('alice')
    assert frozen['terms'] == [] and alias_extras('alice', 'unchanged', frozen) == 'unchanged'


def test_disabled_and_other_owner_cannot_disclose_aliases(aliases):
    add(aliases)
    assert capture_alias_context('bob')['terms'] == []
    aliases.active['enabled'] = False
    assert capture_alias_context('alice')['terms'] == []


@pytest.mark.parametrize('change', ['owner', 'connection', 'disabled', 'unavailable'])
def test_pre_request_connection_change_omits_optional_context_not_generation(aliases, monkeypatch, change):
    add(aliases)
    frozen = capture_alias_context('alice')
    if change == 'owner': aliases.active['binding']['owner'] = 'bob'
    elif change == 'connection': aliases.active['binding']['connection_id'] = 'connection-two'
    elif change == 'disabled': aliases.active['enabled'] = False
    else: monkeypatch.setattr(aliases.service, 'current_binding', Mock(side_effect=HTTPException(401)))
    assert alias_extras('alice', 'original extras', frozen, source_text='小林') == 'original extras'


def test_frozen_values_not_reloaded_after_alias_edit_and_legacy_not_upgraded(aliases, monkeypatch):
    add(aliases)
    frozen = capture_alias_context('alice')
    aliases.service.record_objects('alice', aliases.binding,
        [{'id': 'ou_target_private', 'name': '此后新名称', 'kind': 'contact'}])
    monkeypatch.setattr(aliases.service, 'snapshot', Mock(side_effect=AssertionError('do not read aliases again')))
    output = alias_extras('alice', None, frozen, source_text='小林')
    assert '林清' in output and '此后新名称' not in output
    assert alias_extras('alice', 'legacy', None) == 'legacy'
    assert alias_extras('bob', 'other owner', frozen) == 'other owner'
    assert alias_extras('alice', None, {**frozen, 'access_token': 'must not pass'}) is None


def test_accepted_snapshot_is_private_and_duplicate_operation_never_refreshes(case, aliases, monkeypatch):
    add(aliases)
    aliases.service.add_alias('alice', aliases.binding, 'Offline', 'ou_target_private')
    c = case
    parent_before = {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}
    receipt, _ = accept(c)
    with c.sessions() as db:
        saved = json.loads(db.get(SourceRequestDB, ('alice', str(c.body.operation_id))).receipt_json)
    assert saved['summary_alias_context']['terms'][0]['name'] == '林清'
    assert 'summary_alias_context' not in receipt.model_dump()
    child = c.artifacts.find_task_dir(receipt.task_id)
    assert '小林' not in (child / 'request.json').read_text(encoding='utf-8')
    monkeypatch.setattr(aliases.service, 'snapshot', Mock(side_effect=AssertionError('never recapture')))
    again, background = accept(c)
    assert again.task_id == receipt.task_id and not background.tasks
    c.service.run_once(receipt.task_id, 'alice', c.note)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert c.note.generate_from_transcript.call_count == 1
    assert '林清' in c.note.generate_from_transcript.call_args.kwargs['extras']
    assert not c.note.generate_from_file.called
    assert all(p.read_bytes() == raw for p, raw in parent_before.items())


@pytest.mark.parametrize('mode', ['changed_connection', 'legacy_receipt'])
def test_summary_runs_without_aliases_after_connection_change_or_for_legacy(case, aliases, monkeypatch, mode):
    add(aliases)
    c = case
    receipt, _ = accept(c)
    if mode == 'changed_connection':
        aliases.active['binding']['connection_id'] = 'connection-two'
    else:
        with c.sessions() as db:
            row = db.get(SourceRequestDB, ('alice', str(c.body.operation_id)))
            payload = json.loads(row.receipt_json)
            payload.pop('summary_alias_context')
            row.receipt_json = json.dumps(payload)
        monkeypatch.setattr(aliases.service, 'current_binding', Mock(side_effect=AssertionError('no legacy upgrade')))
    c.service.run_once(receipt.task_id, 'alice', c.note)
    c.note.generate_from_transcript.assert_called_once()
    assert 'extras' not in c.note.generate_from_transcript.call_args.kwargs


def test_actual_note_pipeline_both_prompts_use_same_immutable_context_and_original_quote(case, aliases):
    from app.llm.openai_llm import _BasePromptLLM
    from app.services.note_service import NoteService
    add(aliases)
    aliases.service.add_alias('alice', aliases.binding, 'Offline', 'ou_target_private')
    c = case
    source = c.transcript['full_text']
    proof = [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': source}]
    draft = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic topic'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'attribute', 'text': source,
         'material': True, 'evidence': proof}]}
    review = {'protocol': 4, 'blocks': [{'id': 'B1', 'markdown': source}], 'claims': [
        {'id': 'C1', 'field': 'attribute', 'text': source, 'material': True,
         'disposition': 'included', 'block_ids': ['B1'], 'evidence': proof}]}

    class Automatic(_BasePromptLLM):
        def __init__(self): self.calls = []
        def _complete(self, **prompts):
            self.calls.append(prompts)
            assert len(self.calls) <= 2 and source in prompts['user_prompt']
            # A concurrent Feishu change cannot replace input already used by call 1.
            aliases.active['binding']['connection_id'] = 'changed-after-first-send'
            return json.dumps(draft if len(self.calls) == 1 else review)

    automatic = Automatic()
    runner = object.__new__(NoteService)
    runner.artifact_service = c.artifacts
    runner.llm_service = SimpleNamespace(create_summarizer=Mock(return_value=automatic))
    runner.transcription_service = SimpleNamespace(transcribe=Mock(side_effect=AssertionError('no ASR')))
    body = c.body.model_copy(update={'content_depth': 'detailed', 'presentation': 'text'})
    receipt, _ = accept(c, body)
    before = (c.artifacts.find_task_dir(receipt.task_id) / 'transcript.json').read_bytes()
    c.service.run_once(receipt.task_id, 'alice', runner)
    assert c.artifacts.get_status(receipt.task_id)['status'] == 'success'
    assert len(automatic.calls) == 2
    marker = '用户明确确认的别称词义提示'
    def context(prompt):
        text = prompt['user_prompt']
        return text[text.index(marker):text.index('有歧义仍保留不确定。') + len('有歧义仍保留不确定。')]
    assert context(automatic.calls[0]) == context(automatic.calls[1])
    assert '林清' in context(automatic.calls[0])
    assert 'ou_target_private' not in str(automatic.calls)
    folder = c.artifacts.find_task_dir(receipt.task_id)
    assert (folder / 'transcript.json').read_bytes() == before
    assert json.loads((folder / 'meeting_fact_review.json').read_bytes())['raw_response'] == json.dumps(review)
    runner.transcription_service.transcribe.assert_not_called()


def test_literal_source_or_user_extras_match_only_no_canonical_fuzzy_or_cross_line_match(aliases):
    add(aliases)
    frozen = capture_alias_context('alice')
    assert alias_extras('alice', None, frozen, source_text='林清 lin xiaolin 小\n林') is None
    output = alias_extras('alice', None, frozen, source_text='小林提出要求')
    assert '林清' in output and '研究小组' not in output
    extras = alias_extras('alice', '请解释研究组这个别称', frozen)
    assert '研究小组' in extras and '林清' not in extras


def test_original_asr_and_existing_ocr_are_match_sources_not_speaker_labels(aliases):
    from app.models.transcript import TranscriptResult, TranscriptSegment
    add(aliases)
    frozen = capture_alias_context('alice')
    raw = {'full_text': '原始转写', 'segments': [{'start': 0, 'end': 1, 'text': '原始转写'}]}
    transcript = TranscriptResult('zh', '小林', [TranscriptSegment(0, 1, '小林', speaker_label='小林')],
                                  {'asr_evidence': raw})
    assert alias_extras('alice', None, frozen, source_text=alias_source_text(transcript)) is None
    visual = SimpleNamespace(frames=[SimpleNamespace(ocr_text='研究组文档')])
    before = copy.deepcopy(raw)
    output = alias_extras('alice', None, frozen, source_text=alias_source_text(transcript, visual))
    assert '研究小组' in output and '林清' not in output
    assert raw == before and visual.frames[0].ocr_text == '研究组文档'
