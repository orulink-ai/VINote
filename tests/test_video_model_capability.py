import json
import hashlib
import multiprocessing
import os
import threading
import time
from contextlib import contextmanager
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
        assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
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


def _hold_process_lock(path, ready, release):
    from app.services.video_model_capability import _capability_lock
    with _capability_lock(path):
        ready.set()
        if not release.wait(30):
            raise RuntimeError('Synthetic lock holder timed out')


@contextmanager
def process_lock(path):
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_hold_process_lock, args=(path, ready, release))
    process.start()
    try:
        assert ready.wait(15), 'Synthetic child did not acquire the OS lock'
        yield
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
        assert process.exitcode == 0


def terminal_receipt(root, supported=True):
    identity = hashlib.sha256(json.dumps(['owner', 'https://models.example', 'chosen'], ensure_ascii=False).encode()).hexdigest()
    path = root / f'{identity}.json'
    record = dict(protocol=2, identity=identity, state='completed', supported=supported,
                  finish_reason='stop', checked_at=time.time())
    path.write_text(json.dumps(record))
    return path, record


@pytest.mark.parametrize('supported', [True, False])
def test_valid_terminal_receipt_is_read_while_another_process_holds_os_lock(tmp_path, supported):
    cloud = service()
    path, _ = terminal_receipt(tmp_path, supported)
    before = path.read_bytes()
    with process_lock(path.with_suffix('.lock')):
        assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud) is supported
    cloud.request.assert_not_called()
    assert path.read_bytes() == before and not list(tmp_path.glob('*.tmp'))


def test_nonterminal_and_invalid_receipts_still_block_under_another_process_claim(tmp_path):
    cloud = service()
    path, record = terminal_receipt(tmp_path)
    invalid = [
        {**record, 'state': 'pending'}, {**record, 'state': 'unknown'},
        {**record, 'identity': 'other-owner-origin-or-model'},
        {**record, 'protocol': 1}, {**record, 'protocol': 2.0},
        {**record, 'finish_reason': 'length'}, {**record, 'supported': 1},
        {**record, 'checked_at': time.time() - 8 * 86400},
        {**record, 'checked_at': time.time() + 86400},
        {**record, 'checked_at': True}, {**record, 'checked_at': 'now'},
        {**record, 'checked_at': float('nan')}, ['not-an-object'],
    ]
    with process_lock(path.with_suffix('.lock')):
        for value in [*(json.dumps(value) for value in invalid), '{broken', 'x' * 4097]:
            path.write_text(value)
            before = path.read_bytes()
            with pytest.raises(ValueError, match='正在进行'):
                verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
            assert path.read_bytes() == before
        path.unlink()
        with pytest.raises(ValueError, match='正在进行'):
            verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
        assert not path.exists()
    cloud.request.assert_not_called()


@pytest.mark.parametrize('damage', ['pending', 'unknown', 'expired', 'wrong_identity', 'protocol', 'supported', 'finish', 'corrupt'])
def test_invalid_existing_receipt_never_reprobes_even_when_lock_is_available(tmp_path, damage):
    cloud = service()
    path, record = terminal_receipt(tmp_path)
    if damage in {'pending', 'unknown'}: record['state'] = damage
    if damage == 'expired': record['checked_at'] -= 8 * 86400
    if damage == 'wrong_identity': record['identity'] = 'wrong'
    if damage == 'protocol': record['protocol'] = 1
    if damage == 'supported': record['supported'] = 'true'
    if damage == 'finish': record['finish_reason'] = 'tool_calls'
    path.write_text('{bad' if damage == 'corrupt' else json.dumps(record))
    before = path.read_bytes()
    with pytest.raises(ValueError, match='确认'):
        verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    cloud.request.assert_not_called()
    assert path.read_bytes() == before


def test_paid_probe_rechecks_receipt_after_acquiring_claim(tmp_path, monkeypatch):
    from app.services import video_model_capability as module
    cloud = service()
    original_lock = module._capability_lock
    observed = []

    @contextmanager
    def completed_in_gap(lock):
        with original_lock(lock):
            path, _ = terminal_receipt(tmp_path)
            observed.append(path.read_bytes())
            yield

    monkeypatch.setattr(module, '_capability_lock', completed_in_gap)
    assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    cloud.request.assert_not_called()
    assert next(tmp_path.glob('*.json')).read_bytes() == observed[0]


def test_new_paid_probe_has_one_durable_reservation_inside_os_claim(tmp_path):
    from app.services.video_model_capability import _capability_lock
    cloud = service()
    response = cloud.request.return_value

    def probe(*args, **kwargs):
        path = next(tmp_path.glob('*.json'))
        assert json.loads(path.read_text())['state'] == 'pending'
        with pytest.raises(ValueError, match='正在进行'):
            with _capability_lock(path.with_suffix('.lock')):
                pytest.fail('Paid probe must still own its OS claim')
        return response

    cloud.request.side_effect = probe
    assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    assert cloud.request.call_count == 1


def test_cached_read_does_not_wait_for_unrelated_inprocess_probe(tmp_path):
    from app.services import video_model_capability as module
    cloud = service()
    path, _ = terminal_receipt(tmp_path)
    completed = threading.Event()
    failures = []

    def read():
        try:
            assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
        except BaseException as error:
            failures.append(error)
        finally:
            completed.set()

    with module._LOCK:
        worker = threading.Thread(target=read)
        worker.start()
        fast = completed.wait(3)
    worker.join(5)
    assert fast and not failures and not worker.is_alive()
    cloud.request.assert_not_called()


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'directory'])
def test_invalid_receipt_paths_cannot_bypass_a_process_claim_or_reprobe(tmp_path, kind):
    cloud = service()
    path, _ = terminal_receipt(tmp_path)
    original = path.read_bytes()
    target = tmp_path / 'retained-evidence'
    target.write_bytes(original)
    path.unlink()
    if kind == 'directory':
        path.mkdir()
    elif kind == 'hardlink':
        os.link(target, path)
    else:
        try:
            path.symlink_to(target)
        except OSError:
            pytest.skip('Host does not allow synthetic symlinks')
    with process_lock(path.with_suffix('.lock')):
        with pytest.raises(ValueError, match='正在进行'):
            verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    with pytest.raises(ValueError, match='确认'):
        verify_image_input('owner', 'chosen', root=tmp_path, cloud=cloud)
    cloud.request.assert_not_called()
    assert target.read_bytes() == original
