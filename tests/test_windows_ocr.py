"""Offline boundaries; synthetic images and fake subprocesses only."""
import copy
import hashlib
import io
import json
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from app.services import windows_ocr as ocr


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "screen '$(); 中文.png"
    Image.new('RGB', (96, 64), 'white').save(path)
    return ocr.OCRInput(path, hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(ocr, '_is_windows', lambda: True)
    monkeypatch.setattr(ocr, '_local_drive', lambda path: True)
    monkeypatch.setattr(ocr, '_powershell_executable', lambda: 'trusted-system-powershell.exe')
    monkeypatch.setattr(ocr.subprocess, 'Popen', lambda *a, **kw: pytest.fail('unexpected process'))


def capability():
    return {'status':'available', 'failure':None, 'engine':'Windows.Media.Ocr.OcrEngine',
        'languages':['zh-Hans-CN'], 'requested_language':'zh-Hans-CN', 'actual_language':'zh-Hans-CN',
        'os_version':'10.0.1.0', 'os_build':'1.2', 'engine_file_version':None,
        'powershell_version':'5.1', 'execution_policy':'RemoteSigned', 'max_image_dimension':10000}


def response(payload):
    return {'protocol':1, 'status':'completed', 'failure':None, 'capability':capability(),
        'items':[{'index':i, 'status':'recognized', 'sha256':s['sha256'], 'size':s['size'],
            'width':s['width'], 'height':s['height'], 'text':' 原文\n中文 123 ', 'text_angle':None,
            'elapsed_ms':1, 'lines':[{'text':'中文 123','words':[{'text':'中文','x':2,'y':3,'width':10,'height':8}]}]}
            for i,s in enumerate(payload['items'])]}


def fake_engine(monkeypatch, mutate=None):
    calls = []
    def invoke(payload, deadline, limit):
        calls.append(copy.deepcopy(payload))
        raw = response(payload)
        if mutate:
            mutate(raw, payload)
        return raw
    monkeypatch.setattr(ocr, '_invoke', invoke)
    return calls


def test_completed_preserves_original_text_coordinates_and_inputs(monkeypatch, image):
    before = image.path.read_bytes()
    calls = fake_engine(monkeypatch)
    value = ocr.recognize_batch([image])
    assert value.status == 'completed' and value.failure is None
    assert value.inputs_verified_after is True
    assert value.items[0].text == ' 原文\n中文 123 '
    assert value.items[0].lines[0].words[0] == ocr.OCRWord('中文', 2, 3, 10, 8)
    assert value.capability.languages == ('zh-Hans-CN',)
    assert value.capability.engine_file_version is None
    assert not hasattr(value.items[0], 'confidence')
    assert not hasattr(value.capability, 'model_version')
    assert len(calls) == 1 and calls[0]['items'][0]['path'] == str(image.path)
    assert image.path.read_bytes() == before


def test_describe_uses_same_transport_without_images(monkeypatch):
    calls = fake_engine(monkeypatch)
    result = ocr.describe_capability()
    assert result.status == 'available'
    assert calls[0]['mode'] == 'describe' and calls[0]['items'] == []


def test_empty_recognition_is_distinct_from_unavailable(monkeypatch, image):
    def empty(raw, _):
        raw['items'][0].update(status='no_text_detected', text='', lines=[])
    fake_engine(monkeypatch, empty)
    result = ocr.recognize_batch([image])
    assert result.status == 'completed'
    assert result.items[0].status == 'no_text_detected' and result.items[0].text == ''


@pytest.mark.parametrize('code', [ocr.OCRFailure.LANGUAGE_UNAVAILABLE, ocr.OCRFailure.POLICY_BLOCKED, ocr.OCRFailure.ENGINE_UNAVAILABLE])
def test_native_capability_failure_is_typed_no_empty_success(monkeypatch, image, code):
    def unavailable(raw, _):
        raw.update(status='failed', failure=code.value, items=[])
        raw['capability'].update(status='unavailable',failure=code.value,actual_language=None)
    fake_engine(monkeypatch, unavailable)
    result = ocr.recognize_batch([image])
    assert result.failure == code and result.items[0].text is None
    assert result.capability.status == 'unavailable'


@pytest.mark.parametrize('value', [[], [None], [ocr.OCRInput('relative.png','f'*64)], [ocr.OCRInput('https://example.org/a','f'*64)], [ocr.OCRInput('\\\\host\\share\\a.png','f'*64)], [ocr.OCRInput('C:\\a.png:stream','f'*64)]])
def test_invalid_or_remote_inputs_never_spawn(value):
    assert ocr.recognize_batch(value).status == 'failed'


def test_non_windows_never_spawns(monkeypatch, image):
    monkeypatch.setattr(ocr, '_is_windows', lambda: False)
    assert ocr.recognize_batch([image]).failure == ocr.OCRFailure.UNSUPPORTED_OS


def test_mapped_network_drive_never_spawns(monkeypatch, image):
    monkeypatch.setattr(ocr, '_local_drive', lambda _: False)
    assert ocr.recognize_batch([image]).failure == ocr.OCRFailure.UNSAFE_PATH


def test_hash_mismatch_and_invalid_hash_never_spawn(image):
    assert ocr.recognize_batch([replace(image,expected_sha256='0'*64)]).failure == ocr.OCRFailure.HASH_MISMATCH
    assert ocr.recognize_batch([replace(image,expected_sha256='not-a-hash')]).failure == ocr.OCRFailure.INVALID_REQUEST


def test_missing_image_never_spawns(image):
    image.path.unlink()
    assert ocr.recognize_batch([image]).failure == ocr.OCRFailure.IMAGE_UNAVAILABLE


def test_symlink_ancestor_rejected(monkeypatch, image):
    original = Path.lstat
    class Reparse:
        st_mode = 0o40755
        st_file_attributes = 0x400
    monkeypatch.setattr(Path, 'lstat', lambda p, *a, **kw: Reparse() if p == image.path.parent else original(p,*a,**kw))
    assert ocr.recognize_batch([image]).failure == ocr.OCRFailure.UNSAFE_PATH


@pytest.mark.parametrize('limits', [ocr.OCRLimits(max_images=1),ocr.OCRLimits(max_image_bytes=1),ocr.OCRLimits(max_dimension=32),ocr.OCRLimits(max_pixels=100),ocr.OCRLimits(max_total_image_bytes=1)])
def test_image_budgets_fail_before_process(image, limits):
    inputs = [image, image] if limits.max_images == 1 else [image]
    assert ocr.recognize_batch(inputs,limits=limits).status == 'failed'


@pytest.mark.parametrize('change', [dict(max_images=65),dict(max_output_bytes=2**30),dict(max_text_chars=16001),dict(batch_timeout=float('nan')),dict(image_timeout=31),dict(batch_timeout=True),dict(max_words=0),dict(image_timeout=20,batch_timeout=10)])
def test_caller_cannot_disable_limits(image, change):
    assert ocr.recognize_batch([image],limits=replace(ocr.OCRLimits(),**change)).failure == ocr.OCRFailure.INVALID_REQUEST


def test_language_is_data_not_script(image):
    assert ocr.recognize_batch([image],language="zh'; Get-Content secret").failure == ocr.OCRFailure.INVALID_REQUEST


def test_duplicate_image_not_dispatched_twice(image):
    assert ocr.recognize_batch([image,image]).failure == ocr.OCRFailure.INVALID_REQUEST


def test_invalid_image_bytes_never_spawn(image):
    image.path.write_bytes(b'not an image')
    invalid = replace(image,expected_sha256=hashlib.sha256(image.path.read_bytes()).hexdigest())
    assert ocr.recognize_batch([invalid]).failure == ocr.OCRFailure.INVALID_IMAGE


@pytest.mark.parametrize('kind', ['GIF','animated PNG'])
def test_unsupported_or_multiframe_images_rejected(image, kind):
    first = Image.new('RGB',(10,10),'white')
    if kind == 'GIF':
        first.save(image.path,format='GIF')
    else:
        first.save(image.path,format='PNG',save_all=True,append_images=[Image.new('RGB',(10,10),'red')])
    item = replace(image,expected_sha256=hashlib.sha256(image.path.read_bytes()).hexdigest())
    assert ocr.recognize_batch([item]).failure == ocr.OCRFailure.INVALID_IMAGE


def test_changed_source_discards_previously_recognized_text(monkeypatch, image):
    def change(raw, _):
        Image.new('RGB',(96,64),'black').save(image.path)
    fake_engine(monkeypatch,change)
    result = ocr.recognize_batch([image])
    assert result.failure == ocr.OCRFailure.IMAGE_CHANGED
    assert result.items[0].text is None and result.items[0].lines == ()


def test_same_bytes_replaced_file_identity_is_not_accepted(monkeypatch, image):
    def change(raw, _):
        content = image.path.read_bytes()
        other = image.path.with_name('replacement.png')
        other.write_bytes(content)
        other.replace(image.path)
    fake_engine(monkeypatch,change)
    assert ocr.recognize_batch([image]).failure == ocr.OCRFailure.IMAGE_CHANGED


@pytest.mark.parametrize('mutate', [
    lambda r: r['items'][0].update(text='x'*16001),
    lambda r: r['items'][0].update(width=97),
    lambda r: r['items'][0].update(sha256='0'*64),
    lambda r: r['items'][0].update(index=True),
    lambda r: r['items'][0].update(status='no_text_detected'),
    lambda r: r['items'][0]['lines'][0]['words'][0].update(x=float('inf')),
    lambda r: r['items'][0]['lines'][0]['words'][0].update(width=1000),
    lambda r: r['items'][0]['lines'][0]['words'][0].update(confidence=.99),
    lambda r: r['items'][0]['lines'][0].update(text='x'*48001),
    lambda r: r['items'][0]['lines'][0].update(text='x'*16001),
    lambda r: r['items'][0]['lines'][0]['words'][0].update(text='x'*16001),
    lambda r: r['items'][0].update(elapsed_ms=10001.1),
    lambda r: r['items'].append(r['items'][0]),
    lambda r: r['capability'].update(actual_language='en-US'),
    lambda r: r['capability'].update(engine='some-remote-ocr'),
    lambda r: r['capability'].update(model_version='invented'),
    lambda r: r.update(protocol=True),
    lambda r: r.update(extra='unknown'),
    lambda r: r.update(status=[]),
    lambda r: r['items'][0].update(status={}),
    lambda r: r['capability'].update(status=[]),
    lambda r: r['items'][0].update(lines=[]),
])
def test_untrusted_reply_is_never_partial_success(monkeypatch, image, mutate):
    fake_engine(monkeypatch,lambda raw,_:mutate(raw))
    result = ocr.recognize_batch([image])
    assert result.status == 'failed' and all(x.text is None for x in result.items)


@pytest.mark.parametrize('code', [ocr.OCRFailure.IMAGE_TIMEOUT,ocr.OCRFailure.BATCH_TIMEOUT,ocr.OCRFailure.OUTPUT_LIMIT,ocr.OCRFailure.TEXT_LIMIT])
def test_batch_failure_never_replays_or_returns_partial_text(monkeypatch, image, code):
    def fail(raw, _):
        raw.update(status='failed',failure=code.value,items=[])
    calls = fake_engine(monkeypatch,fail)
    result = ocr.recognize_batch([image])
    assert result.failure == code and len(calls) == 1
    assert result.items[0].text is None


def test_nonblocking_single_batch_admission(image):
    assert ocr._worker.acquire(False)
    try:
        assert ocr.recognize_batch([image]).failure == ocr.OCRFailure.BUSY
    finally:
        ocr._worker.release()


class FakeProcess:
    def __init__(self, data=b'{}', stderr=b'', hanging=False):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(data)
        self.stderr = io.BytesIO(stderr)
        self.returncode = None if hanging else 0
        self.killed = False
    def poll(self):
        return self.returncode
    def wait(self, timeout=None):
        if self.returncode is None:
            time.sleep(min(timeout or .001,.003))
            raise subprocess.TimeoutExpired('fixed-script',timeout)
        return self.returncode
    def kill(self):
        self.killed = True
        self.returncode = -9


def test_process_fixed_script_stdin_json_hidden_no_policy_override(monkeypatch, image):
    seen = []
    class Input(io.BytesIO):
        def close(self):
            self.captured=self.getvalue()
            super().close()
    process = FakeProcess()
    process.stdin=Input()
    def popen(command, **kwargs):
        seen.append((command,kwargs))
        return process
    monkeypatch.setattr(ocr.subprocess,'Popen',popen)
    monkeypatch.setenv('CLOUD_SECRET_TOKEN','must-not-inherit')
    payload={'path':str(image.path)}
    assert ocr._invoke(payload,time.monotonic()+2,1024)=={}
    command,kwargs=seen[0]
    assert command[-1] is ocr._POWERSHELL_SCRIPT
    assert str(image.path) not in ' '.join(command)
    assert json.loads(process.stdin.captured)==payload
    assert kwargs['shell'] is False and kwargs['creationflags'] & 0x08000000
    assert 'CLOUD_SECRET_TOKEN' not in kwargs['env']
    assert '-ExecutionPolicy' not in command and '-EncodedCommand' not in command
    assert 'Invoke-Expression' not in ocr._POWERSHELL_SCRIPT
    assert 'Restricted' in ocr._POWERSHELL_SCRIPT and 'AllSigned' in ocr._POWERSHELL_SCRIPT


@pytest.mark.parametrize('data,stderr,expected', [
    (b'x'*8192,b'',ocr.OCRFailure.OUTPUT_LIMIT),
    (b'{}',b'x'*8192,ocr.OCRFailure.OUTPUT_LIMIT),
    (b'{}',b'failure details must not escape',ocr.OCRFailure.ENGINE_FAILED),
    (b'{"key":1,"key":2}',b'',ocr.OCRFailure.INVALID_RESPONSE),
    (b'{"x":NaN}',b'',ocr.OCRFailure.INVALID_RESPONSE),
    (b'not JSON',b'',ocr.OCRFailure.INVALID_RESPONSE),
    (b'\xff',b'',ocr.OCRFailure.INVALID_RESPONSE),
])
def test_bounded_process_transport(monkeypatch,data,stderr,expected):
    process=FakeProcess(data,stderr)
    monkeypatch.setattr(ocr.subprocess,'Popen',lambda *a,**kw:process)
    with pytest.raises(ocr._Rejected) as error:
        ocr._invoke({},time.monotonic()+2,1024)
    assert error.value.code==expected
    assert 'failure details' not in str(error.value)


def test_process_deadline_kills_and_reaps(monkeypatch):
    process=FakeProcess(hanging=True)
    monkeypatch.setattr(ocr.subprocess,'Popen',lambda *a,**kw:process)
    with pytest.raises(ocr._Rejected) as error:
        ocr._invoke({},time.monotonic()+.05,1024)
    assert error.value.code==ocr.OCRFailure.BATCH_TIMEOUT and process.killed


def test_total_deadline_includes_preflight_no_process_after_expiry(monkeypatch,image):
    original = ocr._snapshot
    def slow(*args):
        result = original(*args)
        time.sleep(.06)
        return result
    monkeypatch.setattr(ocr,'_snapshot',slow)
    result=ocr.recognize_batch([image],limits=ocr.OCRLimits(batch_timeout=.05,image_timeout=.05))
    assert result.failure==ocr.OCRFailure.BATCH_TIMEOUT and not result.inputs_verified_after


def test_total_deadline_includes_postflight_discards_text(monkeypatch,image):
    original = ocr._snapshot
    count = 0
    def slow(*args):
        nonlocal count
        count += 1
        result = original(*args)
        if count == 2:
            time.sleep(.06)
        return result
    monkeypatch.setattr(ocr,'_snapshot',slow)
    fake_engine(monkeypatch)
    result=ocr.recognize_batch([image],limits=ocr.OCRLimits(batch_timeout=.05,image_timeout=.05))
    assert result.failure==ocr.OCRFailure.BATCH_TIMEOUT and result.items[0].text is None


def test_describe_never_hides_failure_after_capability_probe(monkeypatch):
    def fail(raw,_):
        raw.update(status='failed',failure='output_limit',items=[])
    fake_engine(monkeypatch,fail)
    result=ocr.describe_capability(limits=ocr.OCRLimits(max_output_bytes=1))
    assert result.status=='failed' and result.failure==ocr.OCRFailure.OUTPUT_LIMIT


def test_total_text_layers_and_word_count_are_bounded(monkeypatch,image):
    def many(raw,_):
        raw['items'][0]['lines'][0]['words'] *= 2
    fake_engine(monkeypatch,many)
    result=ocr.recognize_batch([image],limits=ocr.OCRLimits(max_words=1))
    assert result.failure==ocr.OCRFailure.OUTPUT_LIMIT and result.items[0].text is None


def test_one_batch_process_has_both_items(monkeypatch,image,tmp_path):
    second=tmp_path/'second.png'
    Image.new('RGB',(80,50),'black').save(second)
    other=ocr.OCRInput(second,hashlib.sha256(second.read_bytes()).hexdigest())
    calls=fake_engine(monkeypatch)
    result=ocr.recognize_batch([image,other])
    assert result.status=='completed' and len(result.items)==2 and len(calls)==1
    assert len(calls[0]['items'])==2


def test_release_slot_after_failure_then_success(monkeypatch,image):
    def fail(*a):
        raise ocr._Rejected(ocr.OCRFailure.ENGINE_FAILED)
    monkeypatch.setattr(ocr,'_invoke',fail)
    assert ocr.recognize_batch([image]).failure==ocr.OCRFailure.ENGINE_FAILED
    fake_engine(monkeypatch)
    assert ocr.recognize_batch([image]).status=='completed'
