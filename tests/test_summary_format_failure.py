"""Completed malformed model output is distinct from source-validation failure."""
import json

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError, decode_final_review
from app.llm.meeting_final_review import prepare_final_draft
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_failure import failure_details, recovery_status
from app.services.summary_failure import safe_summary_failure_context
from test_meeting_invalid_draft_retry import Generator, run


SECRET = 'SYNTHETIC_PRIVATE_MEETING_TEXT'
MALFORMED = '{"protocol":3,"claims":[\n{"id":"C167","field","text":"' + SECRET + '"}]} '


def test_completed_malformed_draft_has_specific_message_code_and_safe_location_without_replay(tmp_path):
    generator = Generator([MALFORMED], eligible=False)
    saved = []
    with pytest.raises(FinalLedgerError) as caught:
        run(generator, saved)
    error = caught.value
    assert '模型返回格式不完整' in str(error)
    assert '事实或来源核对不完整' not in str(error)
    assert len(generator.calls) == 1 and saved == [MALFORMED]
    details = failure_details(error)
    assert details['error_code'] == 'summary_output_invalid'
    assert details['failed_stage'] == 'summarizing'
    assert details['retryable'] is False
    diagnostic = details['summary_failure_context']
    assert diagnostic['diagnostic_protocol'] == 'summary_format/1'
    assert diagnostic['category'] == 'syntax'
    assert diagnostic['output_stage'] == 'draft'
    assert diagnostic['line'] == 2 and diagnostic['column'] > 0 and diagnostic['offset'] > 0
    assert SECRET not in json.dumps(details) + str(error)
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir('format-failure')
    artifacts.update_status(folder, 'summarizing')
    artifacts.update_status(folder, 'failed', str(error), **details)
    artifacts.update_status(folder, 'failed', 'outer worker failed', retryable=True)
    status = recovery_status(artifacts.get_status('format-failure'))
    assert status['error_code'] == 'summary_output_invalid' and status['retryable'] is False
    assert status['failed_stage'] == 'summarizing'
    assert status['summary_failure_context'] == diagnostic
    assert '模型返回格式不完整' in status['message']


def test_valid_json_with_invalid_claims_keeps_distinct_source_validation_error():
    error = FinalLedgerError('invalid_final_evidence')
    assert '事实或来源核对不完整' in str(error)
    assert failure_details(error) == {}


@pytest.mark.parametrize('raw,category', [('{"a":1,"a":2}', 'duplicate_key'),
                                        ('{"a":NaN}', 'invalid_constant')])
def test_non_syntax_json_failures_do_not_invent_line_numbers(raw, category):
    with pytest.raises(FinalLedgerError) as caught:
        prepare_final_draft(raw)
    diagnostic = failure_details(caught.value)['summary_failure_context']
    assert diagnostic['category'] == category and diagnostic['output_stage'] == 'draft'
    assert 'line' not in diagnostic and 'column' not in diagnostic


def test_format_diagnostic_projection_rejects_arbitrary_values_and_never_copies_content():
    base = {'diagnostic_protocol': 'summary_format/1', 'category': 'syntax',
            'output_stage': 'draft', 'line': 2, 'column': 8, 'offset': 32}
    assert safe_summary_failure_context({**base, 'raw': SECRET, 'context': SECRET}) == base
    assert safe_summary_failure_context({**base, 'category': SECRET}) is None
    projected = safe_summary_failure_context({**base, 'line': True, 'column': SECRET,
                                              'offset': -1, 'output_stage': SECRET})
    assert projected == {'diagnostic_protocol': 'summary_format/1', 'category': 'syntax'}
