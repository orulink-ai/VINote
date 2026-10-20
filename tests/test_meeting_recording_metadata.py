"""Recording display time comes from capture fields, never the generated note."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.meeting_recording_metadata import recording_started_at


def capture():
    return {'request': {'workflow': 'meeting', 'title': 'Wrong summary time 2099-01-01',
        'extras': '录制开始时间：2026-01-03T02:04:05.123Z。录制结束时间：2026-01-03T03:00:00Z。'},
        'trace': {'source': 'desktop_recording', 'session_id': 'rec-123-abc',
            'input': {'source': 'desktop_recording', 'workflow': 'meeting',
                'recording_id': 'rec-123-abc', 'filename': 'meeting-recording-2026-01-03-02-04-05.webm'}}}


def test_recording_time_preserves_exact_capture_time_independent_of_title():
    assert recording_started_at(capture()) == datetime(2026, 1, 3, 2, 4, 5, 123000, timezone.utc)


@pytest.mark.parametrize('change', [
    lambda d: d.pop('trace'),
    lambda d: d['request'].update(workflow='note_organization'),
    lambda d: d['trace'].update(source='local_file'),
    lambda d: d['trace']['input'].update(source='upload'),
    lambda d: d['trace']['input'].update(recording_id='rec-456-def'),
    lambda d: d['trace']['input'].update(filename='meeting-recording-2099-01-01-00-00-00.webm'),
    lambda d: d['trace']['input'].update(filename='../meeting-recording-2026-01-03-02-04-05.webm'),
    lambda d: d['request'].update(extras='2026-01-03 02:04:05'),
    lambda d: d['request'].update(extras='录制开始时间：2026-01-03T02:04:05。录制结束时间：2026-01-03T03:00:00。'),
    lambda d: d['request'].update(extras='录制开始时间：2026-01-03T02:04:05Z。录制结束时间：2026-01-02T03:00:00Z。'),
])
def test_missing_or_inconsistent_capture_fields_do_not_invent_time(change):
    value = deepcopy(capture())
    change(value)
    assert recording_started_at(value) is None


@pytest.mark.parametrize('value', [None, [], '2026-01-03', {'request': None, 'trace': {}}])
def test_invalid_historical_metadata_is_unknown(value):
    assert recording_started_at(value) is None
