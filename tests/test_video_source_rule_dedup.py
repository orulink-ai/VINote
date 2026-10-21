"""SourcePrompt-only packet rule placement; no provider, OCR or ASR calls."""
import base64
import hashlib
import json

from PIL import Image
import pytest

from app.llm.source_references import bind_chronological_source, bind_source_references, source_prompt
from app.models.transcript import TranscriptSegment
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence


# Frozen prior packet wording: relocation must not paraphrase its meaning.
RULE = (
    'References indicate temporal overlap only, not that the speech describes this image '
    'or that screen names identify the speaker. Read this image independently; '
    'bind each number, time role, state and assignee to its own visible object. '
    'Do not join different events or infer a conflict from unrelated values.')


@pytest.fixture
def materials(tmp_path):
    segments = [TranscriptSegment(0, 30, 'RAW_FIRST\n  unchanged'),
                TranscriptSegment(30, 60, 'RAW_SECOND Ω')]
    frames = []
    for i, timestamp in enumerate([40.25, 5.5, 30]):
        path = tmp_path / f'{i}.jpg'
        Image.new('RGB', (320, 180), (20 + i * 40, 80, 210)).save(path)
        frames.append(VideoFrameEvidence(timestamp, path, ['timeline'], [timestamp, timestamp + .1],
            f'RAW_OCR_{i}\n  unchanged\tΩ', 'recognized', [1] if timestamp >= 30 else [0], ['anonymous']))
    evidence = VideoEvidence(60, frames, 60, True)
    evidence._summary_frame_hashes = {f.image_path: hashlib.sha256(f.image_path.read_bytes()).hexdigest()
                                    for f in frames}
    return segments, evidence


def render(segments):
    return '\n'.join(segment.text for segment in segments)


def packet_description(index, frame):
    references = ', '.join(f'[ASR:{i + 1:04d}]' for i in frame.speech_indices) or 'none'
    return (f'[FRAME:{index + 1:04d}] Image at recording offset {frame.timestamp:.3f} seconds. '
            f'Observed sample offsets: {frame.sample_offsets}. '
            f'Overlapping original ASR windows: {references}. ')


@pytest.mark.parametrize('webp', [False, True])
def test_typed_images_relocate_rule_once_preserving_packets_and_two_stages(materials, webp):
    segments, evidence = materials
    caps = {'vision': True, '_vinote_webp_verified': webp}
    original_material = evidence.text_material()
    source_hashes = {f.image_path: hashlib.sha256(f.image_path.read_bytes()).hexdigest()
                     for f in evidence.frames}
    stages = []
    with bind_source_references(segments), bind_chronological_source(segments, render):
        for phase in ['draft', 'review']:
            prompt = source_prompt(phase + '\n', render(segments), '\nend')
            content = evidence.user_content(prompt, capabilities=caps)
            text = '\n'.join(b['text'] for b in content if b['type'] == 'text')
            assert len(RULE) == 304 and text.count(RULE) == 1
            assert RULE in content[0]['text']
            assert content[0]['text'].endswith('\n' + RULE)
            for segment in segments:
                assert text.count(segment.text) == 1
            packets = []
            for pos, block in enumerate(content):
                if block['type'] != 'text' or not block['text'].startswith('{'):
                    continue
                record = json.loads(block['text'].split('\n', 1)[0])
                if not record['source_ref'].startswith('[FRAME:'):
                    continue
                i = int(record['source_ref'][7:11]) - 1
                frame = evidence.frames[i]
                assert record == evidence._frame_records()[i]
                assert block['text'] == json.dumps(record, ensure_ascii=False) + '\n' + packet_description(i, frame)
                assert content[pos + 1]['type'] == 'image_url'
                image = content[pos + 1]['image_url']
                assert image['detail'] == 'high'
                wire = base64.b64decode(image['url'].split(',', 1)[1])
                assert hashlib.sha256(wire).hexdigest() == evidence.input_receipt()['images'][i]['wire_sha256']
                packets.append((record, block['text'], image))
            assert [r['source_ref'] for r, _, _ in packets] == ['[FRAME:0002]', '[FRAME:0003]', '[FRAME:0001]']
            stages.append(packets)
    assert stages[0] == stages[1]
    assert evidence.input_receipt()['requests_prepared'] == 2
    assert evidence.text_material() == original_material
    assert source_hashes == {f.image_path: hashlib.sha256(f.image_path.read_bytes()).hexdigest()
                             for f in evidence.frames}


@pytest.mark.parametrize('webp', [False, True])
def test_plain_image_serialization_is_byte_identical_to_prior_packet_shape(materials, webp):
    _, evidence = materials
    content = evidence.user_content('PLAIN', capabilities={'vision': True, '_vinote_webp_verified': webp})
    expected = [{'type': 'text', 'text': 'PLAIN\n\n' + evidence.text_material()}]
    for i, frame in enumerate(evidence.frames):
        encoded = evidence._input_cache[(hashlib.sha256(frame.image_path.read_bytes()).hexdigest(), False)]
        expected.extend([
            {'type': 'text', 'text': packet_description(i, frame) + RULE},
            {'type': 'image_url', 'image_url': {'detail': 'high', 'url': f'data:{encoded.mime_type};base64,'
                + base64.b64encode(encoded.data).decode('ascii')}},
        ])
    assert json.dumps(content, ensure_ascii=False).encode() == json.dumps(expected, ensure_ascii=False).encode()
    assert sum(b.get('text', '').count(RULE) for b in content) == len(evidence.frames)


def test_typed_text_only_has_no_image_rule_or_supplied_image_claim(materials):
    segments, evidence = materials
    with bind_source_references(segments), bind_chronological_source(segments, render):
        content = evidence.user_content(source_prompt('prefix', render(segments), 'suffix'),
                                        capabilities={'vision': False})
    assert isinstance(content, str) and RULE not in content
    assert 'No images were supplied to this model' in content
    for frame in evidence.frames:
        assert json.dumps(frame.ocr_text, ensure_ascii=False) in content
    assert evidence.input_receipt()['mode'] == 'ocr_only'


def test_plain_text_only_serialization_is_unchanged(materials):
    _, evidence = materials
    expected = 'PLAIN\n\n' + evidence.text_material() + (
        '\nOnly extracted text was supplied. No images were supplied to this model; '
        'do not claim to have read images, diagrams, gestures or unseen screen operations.')
    assert evidence.user_content('PLAIN', capabilities={'vision': False}) == expected
