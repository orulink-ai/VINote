import time
from types import SimpleNamespace

import pytest

from app.models.audio import AudioDownloadResult
from app.services.note_service import NoteService


@pytest.mark.parametrize('video_duration,expected', [(300.25, 300.25), (None, 120), (float('nan'), 120)])
def test_result_uses_actual_video_duration_not_last_recognized_word(tmp_path, video_duration, expected):
    original = AudioDownloadResult('', '2026-10-19 15:41 | Source', 120, 'fixture', 'transcript')
    context = SimpleNamespace(step_timings={}, task_start_time=time.time(), audio_meta=original,
        video_evidence=SimpleNamespace(duration=video_duration) if video_duration is not None else None,
        style='meeting', summary_mode='default', task_dir=tmp_path)
    result = NoteService._build_result(None, context, None, '# Supported topic')
    assert result.audio_meta.duration == expected
    assert result.audio_meta.title == '2026-10-19 15:41 | Supported topic'
    assert original.duration == 120
    assert original.title == '2026-10-19 15:41 | Source'
