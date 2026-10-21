"""Packet reordering conserves inputs; no providers or media processing."""
import copy
import hashlib
import json

from app.llm.meeting_source_bundle import (
    SourceBundle, SourcePrompt, SourceSlot, SourceWindow, chronological_content,
)


def material():
    windows = (
        SourceWindow('[ASR:0001]', 10, 20, 'WHOLE ASR\n  Ω\tverbatim'),
        SourceWindow('[ASR:0002]', 0, 10, 'EARLY ASR'),
    )
    records = (
        {'source_ref': '[FRAME:0001]', 'offset_seconds': 10,
         'visible_text': '原OCR\n  Ω\t[]',
         'layout': {'line_spans': [[0, 3], [4, 9]], 'revision': 'opaque-A'},
         'sample_offsets': [10, 10.1]},
        {'source_ref': '[FRAME:0002]', 'offset_seconds': 5,
         'visible_text': '原OCR\n  Ω\t[]', 'layout': None, 'sample_offsets': [5]},
    )
    packets = tuple((
        {'type': 'text', 'text': r['source_ref'] + ' original description Ω'},
        {'type': 'image_url', 'image_url': {
            'url': 'data:image/jpeg;base64,' + wire, 'detail': 'high'}},
    ) for r, wire in zip(records, ('AAECAw==', '/wD/AA==')))
    prompt = SourcePrompt(SourceSlot(
        'PREFIX\n', SourceBundle(windows, 'FULL ORIGINAL', lambda: None), '\nSUFFIX'))
    return prompt, records, packets


def test_each_image_precedes_its_exact_record_without_crossing_asr_or_other_frames():
    prompt, records, packets = material()
    before = copy.deepcopy((records, packets))
    content = chronological_content(prompt, visual_header='VISUAL HEADER\n',
                                    records=records, packets=packets)
    # Chronology: ASR2, complete FRAME2 packet, ASR1, complete FRAME1 packet.
    assert len(content) == 10
    assert content[1]['text'].endswith('\nEARLY ASR')
    assert content[5]['text'].endswith('\nWHOLE ASR\n  Ω\tverbatim')
    for index, start in ((1, 2), (0, 6)):
        description, image = packets[index]
        assert content[start] is description
        assert content[start + 1] is image
        assert content[start + 2] == {
            'type': 'text', 'text': json.dumps(records[index], ensure_ascii=False)}
    assert (records, packets) == before
    assert str(prompt) == 'PREFIX\nFULL ORIGINAL\nSUFFIX'


def test_text_only_bytes_equal_pre_reordering_snapshot():
    prompt, records, _ = material()
    content = chronological_content(prompt, visual_header='VISUAL HEADER\n', records=records)
    assert isinstance(content, str)
    # Frozen from the previous serializer with these exact inputs.
    assert hashlib.sha256(content.encode('utf-8')).hexdigest() == (
        '6fcc1b284efde0695794a29046e28a5e846024291d011fb1f9977dc45864ec5d')
