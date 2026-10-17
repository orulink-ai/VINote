"""Real native inference heartbeat; optionally one selected-Aliyun ASR attempt.

Reports only timings/counts/close codes. Never prints text, credentials or raw errors.
"""
import argparse
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--seconds', type=float, required=True)
    parser.add_argument('--with-asr', action='store_true')
    parser.add_argument('--in-process-baseline', action='store_true', help='Short diagnostic only; deliberately exercise the old GIL boundary')
    parser.add_argument('--origin', default='https://api.orulink.ai')
    parser.add_argument('--user-id')
    args = parser.parse_args()
    from app.config import settings
    from app.models.transcript import TranscriptResult, TranscriptSegment
    from app.services.speaker_diarization_service import SpeakerDiarizationService
    if args.seconds <= 0 or args.seconds > 340:
        parser.error('Use a short sample or at most 340 seconds')
    if args.in_process_baseline and (args.seconds > 10 or args.with_asr):
        parser.error('Baseline is limited to <=10 seconds without ASR')
    settings.vilab_server_url = args.origin
    mode = 'parallel_asr' if args.with_asr else 'speaker_only'
    if args.in_process_baseline:
        from app.services import speaker_worker
        import queue
        def baseline(pcm, segmentation, embedding, count, threshold, progress=None):
            request = {'folder':str(pcm.parent), 'segmentation':str(segmentation.resolve()),
                       'embedding':str(embedding.resolve()), 'speaker_count':count, 'threshold':threshold}
            speaker_worker._infer(request, queue.Queue(maxsize=8), __import__('os').getppid())
            result_file = pcm.parent/'speaker-result.json'
            return speaker_worker.validate_result(json.loads(result_file.read_text()), pcm.stat().st_size/64000)
        speaker_worker.run_speaker_worker = baseline
        mode = 'in_process_baseline'
    transcriber = None
    last_progress = [0.0]
    if args.with_asr:
        from sqlalchemy import select
        from app.db import session_scope
        from app.db_models import CloudAccountDB
        from app.services.vilab_cloud_service import VILabCloudService
        from app.transcribers.vilab_transcriber import VILabTranscriber
        owner = args.user_id
        if owner is None:
            with session_scope() as db:
                owners = list(db.scalars(select(CloudAccountDB.user_id)))
            if len(owners) != 1:
                parser.error('Specify --user-id when multiple device accounts exist')
            owner = owners[0]
        service = VILabCloudService()
        model = service.status(owner)['asr_model']
        if 'aliyun' not in model.lower():
            parser.error('Selected model is not Aliyun; no model will be changed')
        transcriber = VILabTranscriber(service.status(owner)['server_url'], '', model, cloud_user_id=owner)
        def asr_progress(received, total, confirmed):
            if time.monotonic() - last_progress[0] >= 20 or received == total:
                print(json.dumps({'event': 'asr_progress', 'received_seconds': received,
                                  'total_seconds': total, 'confirmed_seconds': confirmed}), flush=True)
                last_progress[0] = time.monotonic()
        transcriber.progress_callback = asr_progress
        from app.services import asr_stream_service
        original_open = asr_stream_service.open_recognition
        class ObservedSocket:
            def __init__(self, socket):
                self.socket = socket
                self.sent_seconds = 0.0
                self.last_sent = None
                self.max_gap = 0.0
                self.last_report = 0.0
            def __enter__(self):
                self.socket.__enter__()
                return self
            def __exit__(self, *values):
                try:
                    return self.socket.__exit__(*values)
                finally:
                    print(json.dumps({'event':'socket_end', 'sent_seconds':round(self.sent_seconds,3),
                                      'max_send_gap_seconds':round(self.max_gap,3)}),flush=True)
            def send(self, data):
                self.socket.send(data)
                if isinstance(data, bytes):
                    now = time.monotonic()
                    self.sent_seconds += (len(data)-20)/32000
                    if self.last_sent is not None:
                        self.max_gap = max(self.max_gap, now-self.last_sent)
                    self.last_sent = now
                    if now-self.last_report >= 20 or data[6] & 2:
                        print(json.dumps({'event':'frames_sent', 'sent_seconds':round(self.sent_seconds,3),
                                          'max_send_gap_seconds':round(self.max_gap,3)}),flush=True)
                        self.last_report = now
            def __getattr__(self, name):
                return getattr(self.socket, name)
        asr_stream_service.open_recognition = lambda url,bearer: ObservedSocket(original_open(url,bearer))

    beats = []
    stopped = threading.Event()
    def heartbeat():
        while not stopped.wait(0.05):
            beats.append(time.monotonic())
    thread = threading.Thread(target=heartbeat, daemon=True)
    started = time.monotonic()
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='speaker-heartbeat-', dir=settings.data_dir) as directory:
            source = Path(directory)/'sample.wav'
            result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(args.source), '-t', str(args.seconds),
                                     '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(source)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            if result.returncode:
                raise RuntimeError('Audio preparation failed')
            def recognize(path, **kwargs):
                if transcriber:
                    return transcriber._transcribe_normalized(path)  # Exactly one attempt, no LLM.
                return TranscriptResult(None, 'diagnostic', [TranscriptSegment(0,args.seconds,'diagnostic')])
            def progress(status, message, **fields):
                print(json.dumps({'event': 'speaker_progress', 'elapsed_seconds': round(time.monotonic()-started,3),
                                  'stage': fields.get('stage'), 'fraction': fields.get('speaker_detection_progress')}), flush=True)
            result = SpeakerDiarizationService().transcribe(audio_path=str(source), transcribe=recognize,
                                                            update_status=progress)
            print(json.dumps({'status': 'success', 'mode': mode, 'speaker_turns': result.metadata['speaker_turn_count'],
                              'asr_covered_seconds': (max((s['end'] for s in result.metadata['asr_evidence']['segments']),default=0)
                                                      if transcriber else None)}), flush=True)
    except Exception as error:
        cause = error
        close_code = None
        while cause is not None:
            close_code = close_code or getattr(getattr(cause,'rcvd',None),'code',None)
            cause = cause.__cause__
        print(json.dumps({'status': 'failed', 'mode': mode, 'failure_type': type(error).__name__,
                          'close_code': close_code}), flush=True)
        return 1
    finally:
        stopped.set()
        thread.join(timeout=2)
        timeline = [started, *beats, time.monotonic()]
        print(json.dumps({'event':'heartbeat', 'mode':mode, 'elapsed_seconds':round(timeline[-1]-started,3),
                          'beats':len(beats), 'max_gap_seconds':round(max(b-a for a,b in zip(timeline,timeline[1:])),3),
                          'remaining_worker_children':len(multiprocessing.active_children())}),flush=True)
    return 0


if __name__ == '__main__':
    multiprocessing.freeze_support()
    try:
        code = main()
    except Exception as error:
        print(json.dumps({'status':'failed', 'phase':'setup', 'failure_type':type(error).__name__,
                          'http_status':getattr(error,'status_code',None)}),flush=True)
        code = 1
    raise SystemExit(code)
