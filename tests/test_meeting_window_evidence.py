"""Offline policy, literal-source and actual-adapter counterexamples."""
import copy
from contextlib import contextmanager
from contextvars import copy_context
import hashlib
import json
import threading

import pytest

from app.llm.meeting_fact_protocol import _evidence, prepare
from app.llm.meeting_final_claim_ledger import FinalLedgerError, validate_final_ledger
from app.llm.meeting_presentation import presentation_scope
from app.llm.meeting_source_reads import combine_source_reads
from app.llm.meeting_window_evidence import (bind_window_source, resolve_window_evidence,
    window_evidence_scope, window_evidence_enabled)
from app.llm.openai_llm import _BasePromptLLM
from app.llm.source_references import bind_chronological_source, bind_source_references, source_prompt
from app.models.transcript import TranscriptSegment
from test_vilab_source_reading import case, configured, run, raw_draft


ROW = {'kind': 'asr_window', 'source_ref': '[ASR:0001]'}


@contextmanager
def source_scope(text='Literal， repeated repeated.\n Ω', *, bind=True):
    segments = [TranscriptSegment(0, 10, text)]
    render = _BasePromptLLM()._build_segment_text
    with presentation_scope('detailed', 'text'), bind_source_references(segments), \
            bind_chronological_source(segments, render), window_evidence_scope(version=1):
        if bind:
            bind_window_source(source_prompt('prefix', render(segments), 'suffix'))
        yield segments


def material(row):
    return {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'attribute', 'text': 'Synthetic supported content.',
         'material': True, 'evidence': [copy.deepcopy(row)]}]}


def review(row):
    c = material(row)['claims'][0]
    c.pop('topic_id')
    c.update(disposition='included', block_ids=['B1'])
    return {'protocol': 4, 'claims': [c], 'blocks': [{'id': 'B1', 'markdown': c['text']}]}


def test_whole_window_uses_existing_exact_span_and_derived_hash_only():
    with source_scope() as segments:
        checked = []
        def exact(rows):
            checked.extend(rows)
            return _evidence(rows)
        derived = resolve_window_evidence(ROW, exact)
        assert checked == [{'kind': 'asr_span', 'source_ref': '[ASR:0001]',
            'quote': segments[0].text, 'start': 0, 'end': len(segments[0].text)}]
        assert derived == {**ROW, 'window_sha256': hashlib.sha256(segments[0].text.encode()).hexdigest(),
                           'verification': 'source_window_bound'}
        assert _evidence([derived]) == [derived]
        prepared = json.loads(prepare(material(ROW)))
        assert prepared['claims'][0]['evidence'] == [derived]
        assert 'quote' not in json.dumps(prepared)
        ledger = validate_final_ledger(review(ROW), prepared, depth='detailed')
        assert ledger.claims[0]['evidence'] == [derived]
        with pytest.raises(ValueError):
            _evidence([{**derived, 'window_sha256': '0' * 64}])
    assert ROW == {'kind': 'asr_window', 'source_ref': '[ASR:0001]'}


@pytest.mark.parametrize('mode', ['no_policy', 'no_binding', 'empty', 'missing', 'changed', 'extra'])
def test_absent_empty_changed_or_model_supplied_extra_fields_fail_closed(mode):
    if mode == 'no_policy':
        with pytest.raises(ValueError):
            _evidence([ROW])
        with pytest.raises(ValueError):
            prepare(material(ROW))
        return
    with source_scope('   ' if mode == 'empty' else 'Unchanged raw.', bind=mode != 'no_binding') as segments:
        row = copy.deepcopy(ROW)
        if mode == 'missing':
            row['source_ref'] = '[ASR:0099]'
        if mode == 'changed':
            segments[0].text += ' altered'
        if mode == 'extra':
            row['quote'] = 'Unchanged raw.'
        with pytest.raises(ValueError):
            prepare(material(row))


def test_copied_worker_scope_revoked_after_exit_and_wrong_form_rejected():
    with source_scope():
        context = copy_context()
        assert context.run(_evidence, [ROW])[0]['verification'] == 'source_window_bound'
        with presentation_scope('detailed', 'comic'), pytest.raises(ValueError):
            _evidence([ROW])
    assert window_evidence_enabled() is False
    with pytest.raises(ValueError):
        context.run(_evidence, [ROW])


def test_default_final_review_rejects_window_kind_without_upgrading_old_material():
    old = {'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': 'Original raw.'}
    segments = [TranscriptSegment(0, 10, 'Original raw.')]
    with bind_source_references(segments), pytest.raises(FinalLedgerError) as caught:
        validate_final_ledger(review(ROW), material(old), depth='detailed')
    assert caught.value.code == 'invalid_final_evidence'


def test_replaced_raw_asr_mapping_rejected_even_with_live_bundle():
    with source_scope():
        other = [TranscriptSegment(0, 10, 'Different raw.')]
        with bind_source_references(other), pytest.raises(ValueError, match='source changed'):
            _evidence([ROW])


def test_unrelated_typed_bundle_cannot_replace_active_source():
    from app.llm.meeting_source_bundle import SourceBundle, SourcePrompt, SourceSlot, SourceWindow
    fake = SourceBundle((SourceWindow('[ASR:0001]', 0, 10, 'Forged rendering'),),
                        'Forged rendering', lambda: None)
    with source_scope(bind=False), pytest.raises(ValueError, match='current source bundle'):
        bind_window_source(SourcePrompt(SourceSlot('', fake, '')))


def test_old_exact_spans_stay_strict_and_legacy_p2_cannot_adopt_window_kind():
    with source_scope('Raw， punctuation unchanged.'):
        old = {'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': 'Raw， punctuation unchanged.'}
        assert _evidence([old])[0]['verification'] == 'exact_asr_span'
        with pytest.raises(ValueError):
            _evidence([{**old, 'quote': 'Raw, punctuation unchanged.'}])
        with pytest.raises(FinalLedgerError, match='模型返回') as caught:
            validate_final_ledger(review({**old, 'quote': 'Raw, punctuation unchanged.'}),
                                  material(old), depth='detailed')
        assert caught.value.code == 'invalid_final_evidence'
        p2 = {'protocol': 2, 'topics': [{'id': 'T1'}], 'facts': [{'id': 'F1', 'topic_id': 'T1',
            'entity': None, 'claims': [{'id': 'C1', 'field': 'attribute', 'text': 'Raw', 'anchor': 'Raw',
                                      'material': True, 'evidence': [ROW]}]}]}
        with pytest.raises(ValueError):
            prepare(p2)


def test_combiner_keeps_raw_and_rejects_cross_read_ref_or_unscoped_new_kind():
    raw = json.dumps(material(ROW))
    raws, allowed = [raw] * 3, [{'[ASR:0001]'}] * 3
    with pytest.raises(ValueError):
        combine_source_reads(raws, allowed)
    with source_scope():
        combined = combine_source_reads(raws, allowed)
        assert combined.raw_reads == tuple(raws)
        assert all(c['evidence'] == [ROW] for c in json.loads(combined)['claims'])
        with pytest.raises(ValueError, match='outside'):
            combine_source_reads(raws, [set(), *allowed[1:]])


def test_actual_four_call_adapter_window_policy_binds_both_stages_without_quote_echo(case, monkeypatch):
    llm = configured(case)
    llm.configure_window_evidence(version=1)
    barrier, calls = threading.Barrier(3), []
    def request(self, owner, method, path, **kwargs):
        payload = kwargs['json']
        calls.append(copy.deepcopy(payload))
        assert 'EXPLICIT WINDOW EVIDENCE POLICY v1' in payload['messages'][0]['content']
        assert window_evidence_enabled()
        content = payload['messages'][1]['content']
        if sum(b['type'] == 'image_url' for b in content) == 1:
            ref = next(f'[ASR:{i + 1:04d}]' for i in range(3) if f'[ASR:{i + 1:04d}]' in json.dumps(content))
            i = int(ref[5:9]) - 1
            value = json.loads(raw_draft(ref, case.segments[i].text))
            value['claims'][0]['evidence'] = [{'kind': 'asr_window', 'source_ref': ref}]
            barrier.wait(timeout=5)
        else:
            saved = json.loads((case.folder/'meeting_working_draft.json').read_text())
            original = json.loads(saved['text'])
            assert all(set(c['evidence'][0]) == {'kind', 'source_ref'} for c in original['claims'])
            assert 'source_window_bound' in json.dumps(content)
            assert 'window_sha256' in json.dumps(content)
            value = {'protocol': 4,
                'blocks': [{'id': f'B{i}', 'markdown': c['text']} for i, c in enumerate(original['claims'])],
                'claims': [{k:v for k,v in c.items() if k!='topic_id'} | {
                    'disposition':'included','block_ids':[f'B{i}']} for i,c in enumerate(original['claims'])]}
        return {'choices': [{'message': {'content': json.dumps(value)}}]}
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
    assert run(case, llm) == '\n\n'.join(s.text for s in case.segments)
    assert len(calls) == 4 and llm.source_reads_diagnostic()['window_evidence_policy'] == 1
    assert window_evidence_enabled() is False
    with pytest.raises(ValueError):
        llm.configure_window_evidence(version=1)
    with pytest.raises(ValueError):
        _evidence([ROW])


def test_window_policy_independently_supports_whole_draft_and_review_two_calls(case, monkeypatch):
    from app.llm.vilab_llm import VILabLLM
    llm = VILabLLM('owner', 'frozen-model')
    llm.configure_video_capabilities({'max_images': 8}, image_input_verified=True)
    llm.configure_window_evidence(version=1)
    claims = []
    for i, segment in enumerate(case.segments):
        claim = json.loads(raw_draft(f'[ASR:{i + 1:04d}]', segment.text))['claims'][0]
        claim['id'] = f'C{i + 1}'
        claim['evidence'] = [{'kind': 'asr_window', 'source_ref': f'[ASR:{i + 1:04d}]'}]
        claims.append(claim)
    draft = json.dumps({'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic'}], 'claims': claims})
    final = json.dumps({'protocol': 4,
        'blocks': [{'id': f'B{i}', 'markdown': c['text']} for i, c in enumerate(claims)],
        'claims': [{k:v for k,v in c.items() if k != 'topic_id'} | {
            'disposition': 'included', 'block_ids': [f'B{i}']} for i,c in enumerate(claims)]})
    calls = []
    def request(self, owner, method, path, **kwargs):
        calls.append(copy.deepcopy(kwargs['json']))
        content = calls[-1]['messages'][1]['content']
        assert sum(b['type'] == 'image_url' for b in content) == 3
        assert all(f'[ASR:{i + 1:04d}]' in json.dumps(content) for i in range(3))
        assert 'EXPLICIT WINDOW EVIDENCE POLICY v1' in calls[-1]['messages'][0]['content']
        assert 'SOURCE READ SCOPE:' not in calls[-1]['messages'][0]['content']
        assert len(calls) <= 2
        return {'choices': [{'message': {'content': draft if len(calls) == 1 else final}}]}
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
    assert run(case, llm) == '\n\n'.join(s.text for s in case.segments)
    saved = json.loads((case.folder/'meeting_working_draft.json').read_text())
    assert saved == {'version': 1, 'kind': 'source_preservation_draft', 'text': draft}
    assert len(calls) == 2 and not llm.source_reading_enabled
    assert llm.source_reads_diagnostic() is None
    assert not (case.folder/'meeting_source_reads.json').exists()


def test_configured_policy_rejects_other_forms_before_any_post(case, monkeypatch):
    llm = configured(case)
    llm.configure_window_evidence(version=1)
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', lambda *a, **k: pytest.fail('No post'))
    with presentation_scope('concise', 'text'), pytest.raises(ValueError, match='detailed text'):
        llm.summarize('title', case.segments, style='meeting', video_evidence=case.evidence)


def test_cannot_enable_window_policy_after_an_ordinary_first_call(case, monkeypatch):
    from app.llm.vilab_llm import VILabLLM
    llm = VILabLLM('owner', 'frozen-model')
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request',
                        lambda *a, **k: {'choices': [{'message': {'content': 'Ordinary response'}}]})
    assert llm._complete(system_prompt='legacy', user_prompt='plain') == 'Ordinary response'
    with pytest.raises(ValueError, match='fresh frozen instance'):
        llm.configure_window_evidence(version=1)
