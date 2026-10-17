"""Live ASR transport diagnostic; credentials remain in process memory.

This verifies public provider calls, not native UI or complete meeting generation.
"""
import argparse
import getpass
import json
import struct
import subprocess
import threading
import time
import wave
from pathlib import Path

import httpx
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect


def report(**fields):
    print(json.dumps(fields, ensure_ascii=False), flush=True)


def open_stream(ws_url, headers, direct, close_timeout):
    options = {'proxy': None} if direct else {}
    for attempt in range(1, 4):
        try:
            return connect(ws_url, additional_headers=headers, open_timeout=15,
                           close_timeout=close_timeout, **options)
        except InvalidStatus:
            raise
        except (OSError, TimeoutError) as exc:
            report(stage='websocket_transport', attempt=attempt, error_class=type(exc).__name__)
            if attempt == 3:
                raise
            time.sleep(attempt)


def stream_probe(ws_url, headers, model, wav, direct=False):
    with wave.open(str(wav), 'rb') as audio:
        duration = audio.getnframes() / audio.getframerate()
    started = time.monotonic()
    stop = threading.Event()
    sender_errors = []
    partials, max_audio_ms, final_chars = 0, 0, None
    try:
        with open_stream(ws_url, headers, direct, 3) as ws:
            ws.send(json.dumps({'type': 'session.start', 'model': model,
                                'audio': {'encoding': 'pcm_s16le', 'sampleRate': 16000, 'channels': 1}}))
            while True:
                event = json.loads(ws.recv(timeout=30))
                kind = event.get('type')
                report(stage='stream_start', event=kind, code=event.get('code'))
                if kind == 'session.started':
                    break
                if kind == 'error':
                    return

            def send_audio():
                try:
                    with wave.open(str(wav), 'rb') as audio:
                        send_started = time.monotonic()
                        sent_seconds = 0
                        seq = 0
                        while not stop.is_set():
                            frame = audio.readframes(3200)
                            if not frame:
                                break
                            flags = (1 if seq == 0 else 0) | (2 if audio.tell() == audio.getnframes() else 0)
                            ws.send(struct.pack('<4sBBBBQI', b'VLA2', 2, 1, flags, 0, seq, len(frame)) + frame)
                            seq += 1
                            sent_seconds += len(frame) / 32000
                            stop.wait(max(0, send_started + sent_seconds - time.monotonic()))
                except Exception as exc:
                    sender_errors.append(type(exc).__name__)
                    stop.set()

            sender = threading.Thread(target=send_audio, daemon=True)
            sender.start()
            first_partial, last_report = None, 0
            while time.monotonic() - started < duration + 120:
                try:
                    event = json.loads(ws.recv(timeout=1))
                except TimeoutError:
                    continue
                kind = event.get('type')
                elapsed = round(time.monotonic() - started, 1)
                if kind == 'asr.ready':
                    report(stage='stream_provider', provider=event.get('providerId'),
                           model=event.get('model'), streaming_mode=event.get('streamingMode'))
                elif kind == 'asr.partial':
                    partials += 1
                    max_audio_ms = max(max_audio_ms, event.get('audioMs') or 0)
                    if first_partial is None:
                        first_partial = elapsed
                    if partials == 1 or elapsed - last_report >= 20:
                        report(stage='stream_partial', audio_ms=max_audio_ms, elapsed_seconds=elapsed,
                               text_characters=len(event.get('text') or ''))
                        last_report = elapsed
                elif kind == 'asr.final':
                    final_chars = len(event.get('text') or '')
                    report(stage='stream_asr_final', text_characters=final_chars, elapsed_seconds=elapsed)
                    break
                elif kind in ('error', 'session.completed', 'session.cancelled'):
                    report(stage='stream_result', event=kind, code=event.get('code'), seconds=duration,
                           elapsed_seconds=elapsed, partial_events=partials, max_audio_ms=max_audio_ms,
                           first_partial_seconds=first_partial, final_characters=final_chars,
                           model=model, sender_errors=sender_errors)
                    break
            stop.set()
            sender.join(timeout=3)
    except Exception as exc:
        stop.set()
        report(stage='stream_result', error_class=type(exc).__name__, seconds=duration,
               elapsed_seconds=round(time.monotonic() - started, 1), model=model,
               close_code=(exc.rcvd.code if exc.rcvd else 1006) if isinstance(exc, ConnectionClosed) else None,
               partial_events=partials, max_audio_ms=max_audio_ms, final_characters=final_chars,
               sender_errors=sender_errors)


def handshake_probe(ws_url, headers, model, direct):
    try:
        with open_stream(ws_url, headers, direct, 2) as ws:
            report(stage='websocket_handshake', result='accepted')
            ws.send(json.dumps({'type': 'session.start', 'model': model,
                                'audio': {'encoding': 'pcm_s16le', 'sampleRate': 16000, 'channels': 1}}))
            for _ in range(6):
                event = json.loads(ws.recv(timeout=20))
                report(stage='websocket_start', event=event.get('type'), code=event.get('code'))
                if event.get('type') in ('session.started', 'error', 'session.error'):
                    break
            ws.send(json.dumps({'type': 'session.cancel', 'reason': 'diagnostic_handshake_only'}))
    except InvalidStatus as exc:
        report(stage='websocket_handshake', http_status=exc.response.status_code)
    except Exception as exc:
        report(stage='websocket_handshake', error_class=type(exc).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--seconds', nargs='+', type=int, default=[12, 30, 60, 120])
    parser.add_argument('--origin', default='https://api.orulink.ai')
    parser.add_argument('--model')
    parser.add_argument('--stream-seconds', type=int, default=0)
    parser.add_argument('--skip-http', action='store_true')
    parser.add_argument('--direct', action='store_true', help='Ignore environment/OS proxy configuration for this probe only')
    parser.add_argument('--vinote-origin', help='Also verify sign-in and model access through this VINote backend')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'config/desktop-public.json').read_text(encoding='utf-8'))
    email = input('Account email: ').strip()
    password = getpass.getpass('Account password: ')
    report(stage='network', mode='ignore_system_proxy' if args.direct else 'system_proxy_defaults')
    with httpx.Client(timeout=30, trust_env=not args.direct) as client:
        try:
            response = None
            for attempt in range(1, 4):
                try:
                    response = client.post(config['VINOTE_SUPABASE_URL'] + '/auth/v1/token?grant_type=password',
                                           headers={'apikey': config['VINOTE_SUPABASE_PUBLISHABLE_KEY']},
                                           json={'email': email, 'password': password})
                    break
                except httpx.TransportError as exc:
                    report(stage='account_transport', attempt=attempt, error_class=type(exc).__name__)
                    if attempt < 3:
                        time.sleep(attempt)
            if args.vinote_origin and response is not None and response.status_code == 200:
                with httpx.Client(timeout=30, trust_env=False) as local:
                    login = local.post(args.vinote_origin + '/api/auth/sign-in',
                                       json={'email': email, 'password': password})
                    report(stage='vinote_login', http_status=login.status_code)
                    if login.status_code == 200:
                        config_result = local.get(args.vinote_origin + '/api/vilab/config')
                        report(stage='vinote_config', http_status=config_result.status_code,
                               mode=config_result.json().get('mode') if config_result.status_code == 200 else None)
                        catalog = local.get(args.vinote_origin + '/api/vilab/models')
                        report(stage='vinote_models', http_status=catalog.status_code)
        finally:
            password = None
        if response is None:
            return
        report(stage='account_login', http_status=response.status_code)
        if response.status_code != 200:
            return
        payload = response.json()
        token = payload['access_token']
        payload = None
        response = None
        headers = {'Authorization': 'Bearer ' + token}
        for attempt in range(1, 4):
            try:
                response = client.get(args.origin + '/v1/models', headers=headers)
                break
            except httpx.TransportError as exc:
                report(stage='catalog_transport', attempt=attempt, error_class=type(exc).__name__)
                if attempt == 3:
                    return
                time.sleep(attempt)
        report(stage='model_catalog', http_status=response.status_code)
        if response.status_code != 200:
            return
        models = [m for m in response.json().get('data', []) if m.get('modelType') == 'asr']
        for model in models:
            report(stage='model', model=model.get('id'), runtime=model.get('runtimeStatus'),
                   capabilities=model.get('capabilities'))
        selected = args.model or next((m['id'] for m in models if ':aliyun:' in m['id']), None)
        if not selected:
            report(stage='selection', result='aliyun_model_not_found')
            return
        report(stage='selection', model=selected)
        ws_url = args.origin.replace('https://', 'wss://').replace('http://', 'ws://') + '/v1/asr/transcriptions'
        if not args.stream_seconds:
            handshake_probe(ws_url, headers, selected, args.direct)
        if not args.source:
            return
        folder = root / 'data/asr-transport-probe'
        folder.mkdir(parents=True, exist_ok=True)
        if args.stream_seconds:
            wav = folder / f'stream-{args.stream_seconds}s.wav'
            subprocess.run(['ffmpeg', '-nostdin', '-y', '-loglevel', 'error', '-i', str(args.source),
                            '-t', str(args.stream_seconds), '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)],
                           check=True, capture_output=True, timeout=120)
            stream_probe(ws_url, headers, selected, wav, direct=args.direct)
        for seconds in ([] if args.skip_http else args.seconds):
            wav = folder / f'probe-{seconds}s.wav'
            subprocess.run(['ffmpeg', '-nostdin', '-y', '-loglevel', 'error', '-i', str(args.source),
                            '-t', str(seconds), '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)],
                           check=True, capture_output=True, timeout=120)
            with wave.open(str(wav), 'rb') as media:
                duration = media.getnframes() / media.getframerate()
            started = time.monotonic()
            report(stage='http_begin', seconds=duration, model=selected)
            try:
                with wav.open('rb') as media:
                    result = client.post(args.origin + '/v1/asr/transcriptions', headers=headers,
                                         data={'model': selected}, files={'file': (wav.name, media, 'audio/wav')},
                                         timeout=httpx.Timeout(max(90, duration * 1.5 + 60), connect=10))
                fields = {'stage': 'http_result', 'seconds': duration, 'http_status': result.status_code,
                          'elapsed_seconds': round(time.monotonic() - started, 1), 'model': selected}
                if result.status_code == 200:
                    fields['text_characters'] = len(result.json().get('text') or '')
                    fields['segments'] = len(result.json().get('segments') or [])
                else:
                    # Never echo arbitrary upstream messages or bodies.
                    try:
                        error = result.json().get('error')
                        fields['error_code'] = error.get('code') if isinstance(error, dict) else None
                    except ValueError:
                        fields['response_kind'] = result.headers.get('content-type')
                report(**fields)
            except Exception as exc:
                report(stage='http_result', seconds=duration, error_class=type(exc).__name__,
                       elapsed_seconds=round(time.monotonic() - started, 1), model=selected)


if __name__ == '__main__':
    main()
