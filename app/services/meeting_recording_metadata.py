"""Read capture timestamps, never summary titles, duration or file mtimes."""
from datetime import datetime, timezone
import re


def recording_started_at(request_document):
    """Project the desktop capture's existing explicit timestamp contract.

    The caller must already authorize the canonical original and read a regular
    bounded request file. This display metadata grants no processing authority.
    Missing historical metadata remains unknown; nothing is rewritten.
    """
    if not isinstance(request_document, dict):
        return None
    request, trace = request_document.get('request'), request_document.get('trace')
    if not isinstance(request, dict) or not isinstance(trace, dict):
        return None
    capture = trace.get('input')
    if (request.get('workflow') != 'meeting' or trace.get('source') != 'desktop_recording'
            or not isinstance(capture, dict) or capture.get('source') != 'desktop_recording'
            or capture.get('workflow') != 'meeting'):
        return None
    recording_id = capture.get('recording_id')
    if (not isinstance(recording_id, str) or not re.fullmatch(r'rec-[0-9]+-[a-z0-9]+', recording_id)
            or trace.get('session_id') != recording_id):
        return None
    extras = request.get('extras')
    match = re.match(r'录制开始时间：([^。\r\n]{1,80})。录制结束时间：([^。\r\n]{1,80})。', extras) if isinstance(extras, str) else None
    if match is None:
        return None
    try:
        start, end = [datetime.fromisoformat(value.replace('Z', '+00:00')) for value in match.groups()]
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            return None
        utc_start = start.astimezone(timezone.utc)
        # Capture's filename provides a second explicit source field. A filename
        # alone is never used to infer the time of an imported recording.
        expected = 'meeting-recording-' + utc_start.strftime('%Y-%m-%d-%H-%M-%S')
        filename = capture.get('filename')
        if (not isinstance(filename, str) or not re.fullmatch(re.escape(expected) + r'\.(?:webm|wav|mp4|m4a|ogg)', filename)):
            return None
        return utc_start
    except (ValueError, OverflowError):
        return None
