"""Title metadata is an exact included part, never a second model prose slot."""
import copy
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_single_copy_projection7 import core_review7, reviewed_title7, metadata_title7
from app.models.audio import AudioDownloadResult
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.note_service import NoteService, PipelineContext
from app.services.task_artifact_service import TaskArtifactService
from test_meeting_single_copy_projection7 import example, RAW
from test_summary_visual_protocol7 import stored, read, case


def context_for(value, title, directory, presentation='infographic'):
    return PipelineContext(task_id='offline-title-test', task_dir=directory,
        audio_meta=AudioDownloadResult('original.webm', title, 10, 'synthetic', 'local'),
        style='meeting', summary_mode='default', extras=None, output_language='en', model_profile_id=None,
        stt_profile_id=None, model_name='frozen', api_key=None, base_url=None, user_id='offline',
        source_video_url=None, task_start_time=time.time(), step_timings={}, content_depth='concise',
        presentation=presentation, presentation_visual={'review': value, 'claim_sources': {}})


def transcript():
    return TranscriptResult('en', RAW, [TranscriptSegment(0, 10, RAW)])


@pytest.mark.parametrize('source,expected_prefix', [
    ('2026-10-19 15:41 | 待生成纪要', '2026-10-19 15:41 | '),
    ('2026-10-19 15:41｜Existing meeting name', '2026-10-19 15:41 | '),
    ('时间未知｜待生成纪要', ''), ('Time unknown｜Notes pending', ''), ('Existing user source title', ''), ('', ''),
])
def test_actual_build_result_uses_validated_title_part_and_existing_prefix_policy(tmp_path, source, expected_prefix):
    value = example(); before = copy.deepcopy(value)
    context = context_for(value, source, tmp_path)
    result = object.__new__(NoteService)._build_result(context, transcript(), RAW)
    assert result.audio_meta.title == expected_prefix + RAW
    assert context.audio_meta.title == source and result.markdown == RAW
    assert value == before
    rows = []; artifacts = object.__new__(TaskArtifactService)
    artifacts.write_json = lambda path, data: rows.append(data)
    artifacts.save_result(tmp_path, result)
    assert rows[0]['title'] == expected_prefix + RAW


@pytest.mark.parametrize('index', [True, False, -1, 0.0, '0', None, [], {}, 100])
def test_title_reference_requires_exact_existing_integer_path(index):
    value = example(); value['title_ref']['part_index'] = index
    with pytest.raises(FinalLedgerError) as error: core_review7(value, presentation='infographic')
    assert error.value.code == 'invalid_title_reference'


@pytest.mark.parametrize('bad', ['missing', 'free_title', 'wrong_block', 'extra_claim_ids', 'substring', 'excluded'])
def test_title_cannot_be_missing_free_text_substring_or_nonincluded_part(bad):
    value = example()
    if bad == 'missing': value.pop('title_ref')
    if bad == 'free_title': value['title'] = 'Invented topic'
    if bad == 'wrong_block': value['title_ref']['block_id'] = 'unknown'
    if bad == 'extra_claim_ids': value['title_ref']['claim_ids'] = ['C1']
    if bad == 'substring': value['title_ref'].update(start=0, end=3)
    if bad == 'excluded':
        value['claims'][0].update(disposition='omitted_for_depth', text='candidate', reason='selection', evidence=[])
        value['claims'][0].pop('part_ref'); value['claims'].pop()
    with pytest.raises(FinalLedgerError): core_review7(value, presentation='infographic')


@pytest.mark.parametrize('size', [1, 120, 121])
def test_title_counts_unicode_codepoints_and_never_truncates(size):
    value = example(); text = '😀' * size; value['blocks'][0]['parts'] = [text]
    if size <= 120: assert reviewed_title7(value, presentation='infographic') == text
    else:
        with pytest.raises(FinalLedgerError) as error: reviewed_title7(value, presentation='infographic')
        assert error.value.code == 'invalid_title_reference'
    assert value['blocks'][0]['parts'] == [text]


def test_whole_original_part_is_never_trimmed_or_concatenated():
    value = example(); value['blocks'][0]['parts'] = ['First.', ' Exact continuation.']
    value['claims'][1]['part_ref']['part_index'] = 1
    value['title_ref']['part_index'] = 1
    assert reviewed_title7(value, presentation='infographic') == ' Exact continuation.'
    assert metadata_title7(value, presentation='infographic', source_title='unknown') == ' Exact continuation.'


def test_build_result_cannot_use_title_from_a_different_body(tmp_path):
    context = context_for(example(), 'source', tmp_path)
    with pytest.raises(FinalLedgerError) as error:
        object.__new__(NoteService)._build_result(context, transcript(), RAW + ' Extra statement.')
    assert error.value.code == 'changed_final_body'


@pytest.mark.parametrize('mutation', ['result_title', 'missing_result_title', 'audio_title', 'missing_audio', 'title_path', 'title_extra'])
def test_saved_title_is_bound_to_raw_reference_and_source_prefix_without_writes(case, monkeypatch, mutation):
    c = case; value, raw, body, _ = stored(c, monkeypatch)
    result = json.loads((c.folder / 'result.json').read_bytes())
    if mutation == 'result_title': result['title'] = 'Host invented title'; c.write('result.json', result)
    if mutation == 'missing_result_title': result.pop('title'); c.write('result.json', result)
    if mutation == 'audio_title': c.write('audio_meta.json', {'title': '2030-01-01 10:00 | Changed prefix'})
    if mutation == 'missing_audio': (c.folder / 'audio_meta.json').unlink()
    if mutation in {'title_path', 'title_extra'}:
        if mutation == 'title_path': value['title_ref']['part_index'] = False
        else: value['title_ref']['text'] = 'not a second text slot'
        c.write('meeting_fact_review.json', {'protocol': 1, 'raw_response': json.dumps(value)})
        side = json.loads((c.folder / 'summary_visual.json').read_bytes())
        import hashlib
        side['review_sha256'] = hashlib.sha256((c.folder / 'meeting_fact_review.json').read_bytes()).hexdigest()
        c.write('summary_visual.json', side)
    before = {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}
    assert read(c) is None
    assert {p: p.read_bytes() for p in c.folder.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('version', [4, 5, 6])
@pytest.mark.parametrize('source', ['2026-10-19 15:41 | 待生成纪要', 'Legitimate existing source title'])
def test_actual_build_result_keeps_old_protocol_title_behavior_exactly(tmp_path, version, source):
    value = {'protocol': version}; context = context_for(value, source, tmp_path)
    result = object.__new__(NoteService)._build_result(context, transcript(), '# Topic\n\n' + RAW)
    expected = '2026-10-19 15:41 | Topic' if source.startswith('2026-') else 'Topic'
    assert result.audio_meta.title == expected
    plain = object.__new__(NoteService)._build_result(context, transcript(), RAW)
    assert plain.audio_meta.title == source


def test_title_binding_does_not_treat_source_raw_info_as_a_small_receipt(case, monkeypatch):
    c = case; stored(c, monkeypatch)
    meta = json.loads((c.folder / 'audio_meta.json').read_bytes())
    meta['raw_info'] = {'existing_metadata': 'x' * 32768}
    c.write('audio_meta.json', meta)
    assert read(c) is not None
