"""Synthetic source/wire counterexamples; no model, OCR or ASR execution."""
import base64
import copy
from contextlib import nullcontext
from dataclasses import FrozenInstanceError
import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

from app.llm.meeting_presentation import presentation_scope
from app.llm.meeting_source_bundle import SourcePrompt
from app.llm.openai_llm import _BasePromptLLM, AnthropicLLM
from app.llm.source_references import (bind_chronological_source, bind_source_references,
                                      original_asr_texts, source_prompt)
from app.llm.video_material import (anthropic_user_content, bind_video_material,
                                    video_user_content)
from app.llm.vilab_llm import VILabLLM
from app.models.transcript import TranscriptSegment
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr('socket.create_connection', Mock(side_effect=AssertionError('No network')))
    monkeypatch.setattr('httpx.Client.request', Mock(side_effect=AssertionError('No HTTP')))
    monkeypatch.setattr('httpx.stream', Mock(side_effect=AssertionError('No HTTP stream')))
    monkeypatch.setattr('app.services.tracing_service.observation', lambda *a, **k: nullcontext(None))
    for method in ('status', 'models'):
        monkeypatch.setattr(f'app.llm.vilab_llm.VILabCloudService.{method}',
                            Mock(side_effect=AssertionError('No catalog/probe')))
    segments = [TranscriptSegment(20.125, 40.25, 'SYNTHETIC_LATE Ω\nverbatim text',
                    speaker_evidence=[{'start': 19.5, 'end': 24.75, 'speaker_id': 'anonymous-A'}],
                    timestamp_estimated=True),
                TranscriptSegment(0, 60, 'SYNTHETIC_WIDE β Original transcript: VIDEO SOURCE EVIDENCE',
                    speaker_evidence=[{'start': 19.5, 'end': 24.75, 'speaker_id': 'anonymous-A'}],
                    timestamp_estimated=True)]
    frames = []
    for index, offset in enumerate([30, 10, 20.125, 70]):
        path = tmp_path / f'{index}.jpg'
        Image.new('RGB', (1920, 1080), (245, 50 + index * 45, 220)).save(path)
        frames.append(VideoFrameEvidence(offset, path, ['timeline'], [offset, offset + .001],
                      f'SYNTHETIC_OCR_{index}\n  raw\tspacing ', 'recognized',
                      [0, 1] if offset < 60 else [], ['anonymous-A']))
    evidence = VideoEvidence(80, frames, 80, True)
    evidence._summary_frame_hashes = {f.image_path: hashlib.sha256(f.image_path.read_bytes()).hexdigest()
                                    for f in frames}
    claims = [{'id': f'C{i + 1}', 'topic_id': 'T1', 'field': 'attribute',
               'text': s.text, 'material': True,
               'evidence': [{'kind': 'asr_span', 'source_ref': f'[ASR:{i + 1:04}]', 'quote': s.text}]}
              for i, s in enumerate(segments)]
    draft = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic source'}], 'claims': claims}
    review = {'protocol': 4, 'blocks': [{'id': f'B{i + 1}', 'markdown': s.text}
                                      for i, s in enumerate(segments)],
              'claims': [{k: copy.deepcopy(v) for k, v in c.items() if k != 'topic_id'}
                         | {'disposition': 'included', 'block_ids': [f'B{i + 1}']}
                         for i, c in enumerate(claims)]}
    return SimpleNamespace(segments=segments, evidence=evidence, draft=draft, review=review)


def llm_capture(source, monkeypatch, *, after_first=None, responses=None):
    calls, receipts, prompts = [], [], []
    responses = responses or [json.dumps(source.draft), json.dumps(source.review)]

    def request(self, owner, method, path, **kwargs):
        assert path == '/openai/v1/chat/completions' and method == 'POST'
        calls.append(copy.deepcopy(kwargs['json']))
        receipts.append(copy.deepcopy(source.evidence.input_receipt()))
        prompts.append(kwargs['json']['messages'][1]['content'])
        if len(calls) == 1 and after_first:
            after_first()
        return {'choices': [{'message': {'content': responses[len(calls) - 1]}}]}

    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
    llm = VILabLLM('synthetic-owner', 'frozen-synthetic-model')
    llm.configure_video_capabilities({'max_images': 64}, image_input_verified=True,
                                     webp_input_verified=True)
    return llm, calls, receipts


def run(source, llm):
    with presentation_scope('detailed', 'text') as state:
        result = llm.summarize('Synthetic title', source.segments, style='meeting',
                               video_evidence=source.evidence)
        assert state.raw_review == json.dumps(source.review)
        return result


def source_events(content):
    events = []
    for index, block in enumerate(content):
        if block['type'] != 'text' or not block['text'].startswith('{'):
            continue
        record = json.loads(block['text'].split('\n', 1)[0])
        if 'source_ref' in record:
            events.append((index, record, block['text']))
    return events


def test_actual_vilab_two_calls_interleave_complete_windows_ocr_and_original_wire(source, monkeypatch):
    before = copy.deepcopy(source.segments), source.evidence.text_material()
    llm, calls, receipts = llm_capture(source, monkeypatch)
    result = run(source, llm)
    assert result == '\n\n'.join(s.text for s in source.segments)
    assert len(calls) == 2 and all(c['model'] == 'frozen-synthetic-model' for c in calls)
    phases = []
    for call in calls:
        content = call['messages'][1]['content']
        events = source_events(content)
        assert [r['source_ref'] for _, r, _ in events] == [
            '[ASR:0002]', '[FRAME:0002]', '[ASR:0001]', '[FRAME:0003]', '[FRAME:0001]', '[FRAME:0004]']
        assert sum(b['type'] == 'image_url' for b in content) == 4
        # Count only source slots, not the fallible review draft's evidence quotes.
        window_text = '\n'.join(text for _, r, text in events if r['source_ref'].startswith('[ASR:'))
        for segment in source.segments:
            assert window_text.count(segment.text) == 1
        assert '20.125' in window_text and '40.25' in window_text
        assert window_text.count('19.50–24.75 秒：anonymous-A') == 2
        assert '归属不能确证' in window_text
        for index, record, text in events:
            if not record['source_ref'].startswith('[FRAME:'):
                continue
            original_index = int(record['source_ref'][7:11]) - 1
            frame = source.evidence.frames[original_index]
            assert record['visible_text'] == frame.ocr_text
            assert record['sample_offsets'] == frame.sample_offsets
            assert record['speech_segment_indices'] == frame.speech_indices
            assert record['overlapping_speaker_ids'] == frame.speaker_ids
            assert content[index - 2]['text'].startswith(record['source_ref'] + ' Image at ')
            assert text == json.dumps(record, ensure_ascii=False)
            assert content[index - 1]['type'] == 'image_url'
            image = content[index - 1]['image_url']
            assert image['detail'] == 'high'
            encoded = base64.b64decode(image['url'].split(',', 1)[1])
            receipt = next(r for r in receipts[0]['images'] if r['source_ref'] == record['source_ref'])
            assert hashlib.sha256(encoded).hexdigest() == receipt['wire_sha256']
            assert encoded == frame.image_path.read_bytes()
            assert receipt['mime_type'] == 'image/jpeg' and receipt['policy'] == 'jpeg-original-v1'
            assert receipt['source_sha256'] == receipt['wire_sha256']
            with Image.open(io.BytesIO(encoded)) as decoded:
                assert decoded.size == (1920, 1080)
        phases.append([(r, text, content[i - 1] if r['source_ref'].startswith('[FRAME:') else None)
                       for i, r, text in events])
    assert phases[0] == phases[1]
    assert source.segments == before[0] and source.evidence.text_material() == before[1]
    assert {k: v for k, v in receipts[0].items() if k != 'requests_prepared'} == {
        k: v for k, v in receipts[1].items() if k != 'requests_prepared'}
    assert receipts[1]['requests_prepared'] == 2
    assert video_user_content('next request') == 'next request' and original_asr_texts() == {}


@pytest.mark.parametrize('change', ['text', 'start', 'end', 'speaker_label', 'speaker_id',
    'timestamp_estimated', 'speaker_turn', 'append', 'reverse', 'ocr', 'frame_time',
    'sample_offsets', 'speech_refs', 'frame_speaker', 'image', 'frame_order'])
def test_source_mutation_blocks_second_dispatch_without_replacing_first_receipt(source, monkeypatch, change):
    def mutate():
        segment, frame = source.segments[0], source.evidence.frames[0]
        if change == 'text': segment.text += ' changed'
        elif change == 'start': segment.start += .125
        elif change == 'end': segment.end += .125
        elif change in {'speaker_label', 'speaker_id'}: setattr(segment, change, 'changed')
        elif change == 'timestamp_estimated': segment.timestamp_estimated = False
        elif change == 'speaker_turn': segment.speaker_evidence[0]['end'] += .125
        elif change == 'append': source.segments.append(TranscriptSegment(72, 73, 'new'))
        elif change == 'reverse': source.segments.reverse()
        elif change == 'ocr': frame.ocr_text += ' changed'
        elif change == 'frame_time': frame.timestamp += .125
        elif change == 'sample_offsets': frame.sample_offsets.append(71)
        elif change == 'speech_refs': frame.speech_indices.append(8)
        elif change == 'frame_speaker': frame.speaker_ids.append('changed')
        elif change == 'image': Image.new('RGB', (1920, 1080), 'red').save(frame.image_path)
        elif change == 'frame_order': source.evidence.frames.reverse()
    llm, calls, receipts = llm_capture(source, monkeypatch, after_first=mutate)
    with pytest.raises(ValueError):
        run(source, llm)
    assert len(calls) == 1
    assert source.evidence.input_receipt() == receipts[0]


def test_mutation_during_encoding_is_rejected_before_first_dispatch(source, monkeypatch):
    from app.services.video_input_encoding import encode_video_input
    changed = False
    def encode(data, **kwargs):
        nonlocal changed
        result = encode_video_input(data, **kwargs)
        if not changed:
            changed = True
            source.evidence.frames[0].ocr_text += ' concurrent change'
        return result
    monkeypatch.setattr('app.services.video_input_encoding.encode_video_input', encode)
    llm, calls, _ = llm_capture(source, monkeypatch)
    with pytest.raises(ValueError): run(source, llm)
    assert calls == [] and source.evidence.input_receipt() is None


def test_typed_slot_is_immutable_revoked_after_exit_and_trace_has_no_data_urls(source):
    llm = VILabLLM('synthetic', 'synthetic')
    with bind_source_references(source.segments), bind_chronological_source(source.segments, llm._build_segment_text):
        prompt = source_prompt('prefix\n', llm._build_segment_text(source.segments), '\nsuffix')
        assert isinstance(prompt, SourcePrompt) and isinstance(prompt, str)
        assert copy.copy(prompt) is prompt and copy.deepcopy(prompt) is prompt
        assert 'data:image' not in json.dumps({'content': prompt})
        assert source.segments[0].text in prompt
        with pytest.raises(AttributeError): prompt._slot = None
        with pytest.raises(FrozenInstanceError): prompt.slot.prefix = 'changed'
    with pytest.raises(ValueError, match='changed'): video_user_content(prompt)


def test_nested_legacy_scope_cannot_borrow_outer_bundle_and_outer_is_restored(source):
    llm = VILabLLM('synthetic', 'synthetic')
    with bind_source_references(source.segments), bind_chronological_source(source.segments, llm._build_segment_text):
        text = llm._build_segment_text(source.segments)
        outer = source_prompt('', text, '')
        with bind_chronological_source([], llm._build_segment_text, enabled=False):
            plain = source_prompt('legacy-prefix', 'unrelated legacy source', 'legacy-suffix')
            assert type(plain) is str
            assert video_user_content(plain) == plain
            with pytest.raises(ValueError): video_user_content(outer)
        assert source.segments[0].text in video_user_content(outer)


def test_ocr_mutation_at_end_of_text_only_render_is_rejected(source, monkeypatch):
    original = source.evidence._chronological_content
    def content(*args, **kwargs):
        result = original(*args, **kwargs)
        source.evidence.frames[0].ocr_text += ' changed after serialization'
        return result
    monkeypatch.setattr(source.evidence, '_chronological_content', content)
    llm = VILabLLM('synthetic', 'synthetic')
    with bind_source_references(source.segments), bind_chronological_source(source.segments, llm._build_segment_text), \
            bind_video_material(source.evidence, {'vision': False}):
        prompt = source_prompt('', llm._build_segment_text(source.segments), '')
        with pytest.raises(ValueError): video_user_content(prompt)
    assert source.evidence.input_receipt() is None


@pytest.mark.parametrize('start,end', [(-1, 1), (2, 1), (0, float('nan')),
                                      (False, 1), (0, float('inf'))])
def test_invalid_source_window_fails_before_dispatch(source, monkeypatch, start, end):
    source.segments[0].start, source.segments[0].end = start, end
    llm, calls, _ = llm_capture(source, monkeypatch)
    with pytest.raises(ValueError): run(source, llm)
    assert calls == [] and source.evidence.input_receipt() is None


@pytest.mark.parametrize('kind', ['txt', 'json_missing_end', 'json_equal_end', 'sensevoice_unknown'])
def test_existing_unknown_duration_production_shapes_remain_accepted(source, monkeypatch, kind):
    from app.routers.note import _build_transcript_from_upload
    text = source.segments[0].text
    if kind == 'txt':
        segment = _build_transcript_from_upload('source.txt', text.encode()).segments[0]
    elif kind.startswith('json'):
        value = {'start': 5, 'text': text}
        if kind == 'json_equal_end': value['end'] = 5
        segment = _build_transcript_from_upload('source.json',
                     json.dumps({'segments': [value]}).encode()).segments[0]
    else:
        # Existing SenseVoice unknown-duration output shape; no ASR execution.
        segment = TranscriptSegment(0.0, 0.0, text)
    assert segment.start == segment.end
    before = copy.deepcopy(segment)
    source.segments[0] = segment
    llm, calls, _ = llm_capture(source, monkeypatch)
    with presentation_scope('detailed', 'text'):
        result = llm.summarize('Synthetic', source.segments, style='meeting')
    assert len(calls) == 2 and segment == before and text in result
    for call in calls:
        content = call['messages'][1]['content']
        assert isinstance(content, str) and 'unknown_duration' in content
        assert 'not a precisely timed utterance or silence' in content


def test_ocr_only_keeps_timeline_and_exact_text_without_encoding(source, monkeypatch):
    monkeypatch.setattr('app.services.video_input_encoding.encode_video_input',
                        Mock(side_effect=AssertionError('No image encoding')))
    llm = VILabLLM('synthetic', 'synthetic')
    with bind_source_references(source.segments), bind_chronological_source(source.segments, llm._build_segment_text), \
            bind_video_material(source.evidence, {'vision': False}):
        prompt = source_prompt('', llm._build_segment_text(source.segments), '')
        content = video_user_content(prompt)
    assert isinstance(content, str) and 'No images were supplied' in content
    assert content.index(source.segments[1].text) < content.index('SYNTHETIC_OCR_1') < content.index(source.segments[0].text)
    for frame in source.evidence.frames:
        assert json.dumps(frame.ocr_text, ensure_ascii=False) in content
    assert source.evidence.input_receipt()['mode'] == 'ocr_only'


def test_plain_nonmeeting_and_legacy_keep_original_wire_order(source, monkeypatch):
    calls = []
    class Legacy(_BasePromptLLM):
        def _complete(self, **prompts):
            assert not isinstance(prompts['user_prompt'], SourcePrompt)
            calls.append(video_user_content(prompts['user_prompt']))
            return 'legacy note'
    llm = Legacy()
    llm.configure_video_capabilities({'vision': True})
    for style, depth in [('meeting', None), ('detailed', 'detailed')]:
        calls.clear()
        with presentation_scope(depth, 'text'):
            llm.summarize('Title', source.segments, style=style, video_evidence=source.evidence)
        assert len(calls) == (2 if style == 'meeting' else 1)
        for content in calls:
            assert source.evidence.text_material() in content[0]['text']
            assert [b['text'].split(' ', 1)[0] for b in content[1::2]] == [f'[FRAME:{i:04d}]' for i in range(1, 5)]


def test_anthropic_keeps_original_jpeg_media_type_in_both_chronological_calls(source, monkeypatch):
    payloads = []
    def request(**kwargs):
        payloads.append(kwargs['json_body'])
        text = json.dumps(source.draft if len(payloads) == 1 else source.review)
        return SimpleNamespace(json=lambda: {'content': [{'type': 'text', 'text': text}]})
    monkeypatch.setattr('app.llm.openai_llm.post_anthropic_compatible', request)
    llm = AnthropicLLM('offline-key', model='frozen-synthetic-model')
    llm.configure_video_capabilities({}, image_input_verified=True, webp_input_verified=True)
    run(source, llm)
    assert len(payloads) == 2
    for payload in payloads:
        pictures = [b for b in payload['messages'][0]['content'] if b['type'] == 'image']
        assert len(pictures) == 4
        for picture in pictures:
            assert base64.b64decode(picture['source']['data']) in [f.image_path.read_bytes() for f in source.evidence.frames]
            assert picture['source']['media_type'] == 'image/jpeg'
            with Image.open(io.BytesIO(base64.b64decode(picture['source']['data']))) as image:
                assert image.format == 'JPEG' and image.size == (1920, 1080)


def test_guard_failure_does_not_create_an_extra_call(source, monkeypatch):
    review = copy.deepcopy(source.review)
    review['claims'][0]['evidence'][0]['quote'] = 'not in source'
    llm, calls, _ = llm_capture(source, monkeypatch, responses=[json.dumps(source.draft), json.dumps(review)])
    with pytest.raises(ValueError): run(source, llm)
    assert len(calls) == 2


def test_all_64_frame_identities_survive_and_required_image_limit_is_not_bypassed(source, monkeypatch):
    frame = source.evidence.frames[0]
    source.evidence.frames = [VideoFrameEvidence(63 - i, frame.image_path, ['timeline'], [63 - i],
                              f'FRAME_EXACT_TEXT_{i}', 'recognized') for i in range(64)]
    llm, calls, _ = llm_capture(source, monkeypatch)
    run(source, llm)
    for call in calls:
        events = [r for _, r, _ in source_events(call['messages'][1]['content'])
                  if r['source_ref'].startswith('[FRAME:')]
        assert len(events) == 64
        assert [r['source_ref'] for r in events] == [f'[FRAME:{i:04d}]' for i in range(64, 0, -1)]
    llm.configure_video_capabilities({'max_images': 63}, image_input_verified=True, webp_input_verified=True)
    calls.clear()
    with pytest.raises(ValueError, match='数量限制'): run(source, llm)
    assert calls == []


def test_transport_failure_never_replays_and_context_does_not_leak(source, monkeypatch):
    from app.services.cloud_chat_stream import SummaryResultUnconfirmed
    llm, calls, _ = llm_capture(source, monkeypatch)
    def failed(self, *args, **kwargs):
        calls.append(kwargs['json'])
        raise SummaryResultUnconfirmed('connection')
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', failed)
    with pytest.raises(SummaryResultUnconfirmed): run(source, llm)
    assert len(calls) == 1
    assert video_user_content('next') == 'next' and original_asr_texts() == {}


def test_fresh_no_video_meeting_sorts_windows_but_never_invents_frames(source, monkeypatch):
    llm, calls, _ = llm_capture(source, monkeypatch)
    with presentation_scope('detailed', 'text'):
        result = llm.summarize('Synthetic', source.segments, style='meeting')
    assert result == '\n\n'.join(s.text for s in source.segments) and len(calls) == 2
    for call in calls:
        text = call['messages'][1]['content']
        assert isinstance(text, str)
        # Inspect the source slot, not draft quotations preceding it.
        source_text = text[text.index('CHRONOLOGICAL SOURCE MATERIAL'):]
        assert source_text.index(source.segments[1].text) < source_text.index(source.segments[0].text)
        assert '[FRAME:' not in source_text


def test_tracing_keeps_only_text_projection_not_slot_or_image_data(source, monkeypatch):
    from app.services.tracing_service import DesktopTraceContext, desktop_trace
    captured = []
    def observe(*args, **kwargs):
        captured.append(copy.copy(kwargs))
        return nullcontext(None)
    monkeypatch.setattr('app.services.tracing_service.observation', observe)
    llm, _, _ = llm_capture(source, monkeypatch)
    with desktop_trace(DesktopTraceContext('meeting', 'synthetic', 'video')):
        run(source, llm)
    inputs = [entry['input'] for entry in captured if 'input' in entry]
    assert inputs
    serialized = json.dumps(inputs, ensure_ascii=False)
    assert 'SYNTHETIC_LATE' in serialized and 'data:image/' not in serialized
    assert 'SourceSlot' not in serialized and '_validate' not in serialized


@pytest.mark.parametrize('video', [False, True])
def test_source_mutation_during_packet_rendering_is_rejected(source, monkeypatch, video):
    from app.llm import meeting_source_bundle
    original = meeting_source_bundle.chronological_content
    def render(prompt, **kwargs):
        source.segments[0].text += ' changed while serializing'
        return original(prompt, **kwargs)
    monkeypatch.setattr(meeting_source_bundle, 'chronological_content', render)
    llm, calls, _ = llm_capture(source, monkeypatch)
    with presentation_scope('detailed', 'text'), pytest.raises(ValueError, match='changed'):
        llm.summarize('Synthetic', source.segments, style='meeting',
                      **({'video_evidence': source.evidence} if video else {}))
    assert calls == []
