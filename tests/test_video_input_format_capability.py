import base64
import hashlib
import io
import json
from unittest.mock import Mock

import pytest
from PIL import Image

from app.llm.vilab_llm import VILabLLM
from app.services.video_model_capability import verify_image_input, verify_optional_webp_input


def cloud():
    value = Mock()
    value.models.return_value = [{'id': 'chosen', 'modelType': 'llm', 'capabilities': {}}]
    value.status.return_value = {'server_url': 'https://models.example'}
    value.request.return_value = {'choices': [{'finish_reason': 'stop', 'message': {
        'role': 'assistant', 'content': 'LEFT: red circle. RIGHT: blue square.'}}]}
    return value


def test_webp_uses_independent_mime_bound_check_and_preserves_png_receipt(tmp_path):
    svc = cloud()
    assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=svc)
    identity = hashlib.sha256(json.dumps(['owner', 'https://models.example', 'chosen'], ensure_ascii=False).encode()).hexdigest()
    original = tmp_path / f'{identity}.json'
    before = original.read_bytes()
    assert verify_optional_webp_input('owner', 'chosen', image_input_verified=True, root=tmp_path, cloud=svc)
    assert verify_optional_webp_input('owner', 'chosen', image_input_verified=True, root=tmp_path, cloud=svc)
    assert svc.request.call_count == 2
    assert original.read_bytes() == before
    image_url = svc.request.call_args.kwargs['json']['messages'][0]['content'][1]['image_url']['url']
    assert image_url.startswith('data:image/webp;base64,')
    with Image.open(io.BytesIO(base64.b64decode(image_url.split(',')[1]))) as image:
        assert image.format == 'WEBP' and image.size == (420, 180)
    assert len(list(tmp_path.glob('*.json'))) == 2


def test_optional_pending_format_keeps_unknown_receipt_and_never_replays(tmp_path):
    svc = cloud()
    svc.request.side_effect = RuntimeError('synthetic transport unknown')
    assert not verify_optional_webp_input('owner', 'chosen', image_input_verified=True, root=tmp_path, cloud=svc)
    receipt = next(tmp_path.glob('*.json'))
    before = receipt.read_bytes()
    assert json.loads(before)['state'] == 'pending'
    assert not verify_optional_webp_input('owner', 'chosen', image_input_verified=True, root=tmp_path, cloud=svc)
    assert svc.request.call_count == 1 and receipt.read_bytes() == before


def test_optional_format_never_bypasses_required_image_capability(tmp_path):
    svc = cloud()
    assert not verify_optional_webp_input('owner', 'chosen', image_input_verified=False, root=tmp_path, cloud=svc)
    svc.models.assert_not_called()
    svc.request.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_general_vision_metadata_does_not_authorize_webp_without_format_check(tmp_path):
    svc = cloud()
    svc.models.return_value[0]['capabilities'] = {'vision': True}
    assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=svc)
    svc.request.assert_not_called()
    assert verify_image_input('owner', 'chosen', root=tmp_path, cloud=svc, image_format='webp')
    assert svc.request.call_count == 1


def test_unsupported_format_rejected_before_lookup(tmp_path):
    svc = cloud()
    with pytest.raises(ValueError, match='格式'):
        verify_image_input('owner', 'chosen', root=tmp_path, cloud=svc, image_format='svg')
    svc.models.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('verified,webp', [(False, False), (False, True), (True, False), (True, True)])
def test_catalog_cannot_forge_host_format_verification(verified, webp):
    llm = VILabLLM('owner', 'chosen')
    llm.configure_video_capabilities({'_vinote_webp_verified': True},
        image_input_verified=verified, webp_input_verified=webp)
    assert llm._video_capabilities.get('_vinote_webp_verified', False) is (verified and webp)
