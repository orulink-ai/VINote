"""Input rejection before any connection; synthetic audio and in-memory WS only."""
import json
import socket
import struct
import threading
from unittest.mock import Mock

import pytest

from app.services import asr_stream_service as service


def chunk(name, data):
    return name + struct.pack("<I", len(data)) + data + (b"\0" if len(data) % 2 else b"")


def wav(data_chunks, *, junk=False, rate=16000, channels=1, bits=16):
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * bits // 8,
                      channels * bits // 8, bits)
    body = b"WAVE" + chunk(b"fmt ", fmt)
    if junk:
        body += chunk(b"JUNK", b"abc")
    body += b"".join(chunk(b"data", data) for data in data_chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No network calls permitted")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.mark.parametrize("chunks,message", [
    ([b"1234567"], "完整采样点"),
    ([b"123456", b"abcdef"], "只能包含一个"),
    ([b"", b"abcdef"], "只能包含一个"),
    ([b"123456", b""], "只能包含一个"),
    ([], "缺少 data"),
])
def test_invalid_data_chunks_never_open_connection(tmp_path, monkeypatch, chunks, message):
    path = tmp_path / "synthetic.wav"
    path.write_bytes(wav(chunks))
    connect = Mock(side_effect=AssertionError("must reject before connection"))
    monkeypatch.setattr(service, "open_recognition", connect)
    with pytest.raises(ValueError, match=message):
        service.recognize_pcm("http://127.0.0.1:1", "synthetic", "frozen-model", path)
    connect.assert_not_called()


@pytest.mark.parametrize("format", [{"rate": 8000}, {"channels": 2}, {"bits": 24}])
def test_invalid_format_never_opens_connection(tmp_path, monkeypatch, format):
    path = tmp_path / "synthetic.wav"
    path.write_bytes(wav([b"123456"], **format))
    connect = Mock(side_effect=AssertionError("must reject before connection"))
    monkeypatch.setattr(service, "open_recognition", connect)
    with pytest.raises(ValueError, match="格式不匹配"):
        service.recognize_pcm("http://127.0.0.1:1", "synthetic", "frozen-model", path)
    connect.assert_not_called()


@pytest.mark.parametrize("samples,junk", [(3, False), (3, True), (3200, False), (3201, True)])
def test_complete_samples_preserve_exact_pcm_and_one_last(tmp_path, monkeypatch, samples, junk):
    pcm = b"\x31\x72" * samples
    path = tmp_path / "synthetic.wav"
    path.write_bytes(wav([pcm], junk=junk))
    sent = []
    last = threading.Event()

    class Socket:
        started = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def send(self, data):
            sent.append(data)
            if isinstance(data, bytes) and data[6] & 2:
                last.set()

        def recv(self, timeout):
            if not self.started:
                self.started = True
                return json.dumps({"type": "session.started"})
            assert last.wait(1), "synthetic sender must finish"
            return json.dumps({"type": "asr.final", "text": "synthetic final"})

    connect = Mock(return_value=Socket())
    monkeypatch.setattr(service, "open_recognition", connect)
    assert service.recognize_pcm("http://127.0.0.1:1", "synthetic", "frozen-model", path)["text"] == "synthetic final"
    connect.assert_called_once()
    assert json.loads(sent[0])["model"] == "frozen-model"
    frames = [frame for frame in sent if isinstance(frame, bytes)]
    assert b"".join(frame[20:] for frame in frames) == pcm
    assert sum(bool(frame[6] & 2) for frame in frames) == 1
    assert [struct.unpack_from("<Q", frame, 8)[0] for frame in frames] == list(range(len(frames)))
