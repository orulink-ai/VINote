import json
from unittest.mock import Mock, patch

import pytest

from app.services.video_model_capability import verify_image_input


def service(content='LEFT: red circle. RIGHT: blue square.'):
    cloud = Mock()
    cloud.models.return_value = [{'id': 'chosen', 'modelType': 'llm', 'capabilities': {}}]
    cloud.status.return_value = {'server_url': 'https://models.example'}
    cloud.request.return_value = {'choices': [{'finish_reason': 'stop',
        'message': {'role': 'assistant', 'content': content}}]}
    return cloud


def test_actual_check_cached_only_for_same_owner_model_and_origin(tmp_path):
    cloud = service()
    assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert cloud.request.call_count == 1
    assert cloud.request.call_args.kwargs['json']['model'] == 'chosen'
    assert verify_image_input('other', 'chosen', root=tmp_path, cloud=cloud)
    assert cloud.request.call_count == 2
    cloud.status.return_value = {'server_url': 'https://other.example'}
    assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert cloud.request.call_count == 3


def test_explicit_text_only_capability_never_probes(tmp_path):
    cloud = service()
    cloud.models.return_value[0]['capabilities'] = {'vision': False}
    assert not verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    cloud.request.assert_not_called()


def test_incorrect_visual_answer_fails_closed_and_is_not_repeated(tmp_path):
    cloud = service('LEFT: green triangle. RIGHT: yellow square.')
    assert not verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert not verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert cloud.request.call_count == 1


def test_unknown_network_outcome_not_replayed(tmp_path):
    cloud = service()
    cloud.request.side_effect = RuntimeError('unavailable')
    with pytest.raises(RuntimeError):
        verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    with pytest.raises(ValueError, match='确认'):
        verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert cloud.request.call_count == 1


def test_unknown_vision_metadata_enters_actual_check(tmp_path):
    cloud = service()
    cloud.models.return_value[0]['capabilities'] = {'vision': {'status': 'unknown'}}
    assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert cloud.request.call_count == 1


def test_existing_process_claim_prevents_any_provider_dispatch(tmp_path):
    from app.services.video_model_capability import _capability_lock
    cloud = service()
    verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    lock = next(tmp_path.glob('*.lock'))
    with _capability_lock(lock):
        with pytest.raises(ValueError, match='正在进行'):
            verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert cloud.request.call_count == 1


@pytest.mark.parametrize('kind', ['length', 'tool_calls', 'function_call', 'content_filter',
    'missing_finish', 'refusal', 'text_refusal', 'embedded_tool', 'embedded_function', 'empty',
    'missing_choices', 'error', 'non_text', 'overlong'])
def test_unconfirmed_probe_never_becomes_capability_success_or_replays(tmp_path, kind):
    cloud = service()
    payload = cloud.request.return_value
    choice = payload['choices'][0]
    message = choice['message']
    if kind in {'length', 'tool_calls', 'function_call', 'content_filter'}:
        choice['finish_reason'] = kind  # Even the correct visual text is not a normal final.
    elif kind == 'missing_finish': del choice['finish_reason']
    elif kind == 'refusal': message['refusal'] = 'synthetic refusal'
    elif kind == 'text_refusal': message['content'] = 'I cannot inspect the LEFT red circle or the RIGHT blue square.'
    elif kind == 'embedded_tool': message['tool_calls'] = [{'id': 'synthetic-call'}]
    elif kind == 'embedded_function': message['function_call'] = {'name': 'synthetic-function'}
    elif kind == 'empty': message['content'] = '   '
    elif kind == 'missing_choices': payload['choices'] = []
    elif kind == 'error': payload['error'] = {'message': 'synthetic provider error'}
    elif kind == 'non_text': message['content'] = [{'type': 'text', 'text': message['content']}]
    elif kind == 'overlong': message['content'] += 'x' * 2000
    with pytest.raises(ValueError, match='确认'):
        verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    receipt = next(tmp_path.glob('*.json'))
    before = receipt.read_bytes()
    assert json.loads(before)['state'] == 'pending'
    assert 'supported' not in json.loads(before)
    cloud.request.return_value = service().request.return_value
    with patch('app.services.video_model_capability.time.time', return_value=json.loads(before)['checked_at'] + 8 * 86400):
        with pytest.raises(ValueError, match='确认'):
            verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert cloud.request.call_count == 1 and receipt.read_bytes() == before


def test_completed_receipt_without_terminal_validation_is_not_trusted_or_reprobed(tmp_path):
    cloud = service()
    verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    receipt = next(tmp_path.glob('*.json'))
    saved = json.loads(receipt.read_text())
    saved['protocol'] = 1  # Historical receipts did not validate stop/refusal/tool calls.
    receipt.write_text(json.dumps(saved))
    before = receipt.read_bytes()
    with pytest.raises(ValueError, match='确认'):
        verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert cloud.request.call_count == 1 and receipt.read_bytes() == before
