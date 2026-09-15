"""Frozen backend; user secrets stay in app data, tracing credentials are build-managed."""
import json
import os
from pathlib import Path
import secrets
import sys


def configure_langfuse(config):
    """Use only the bundled project; stale installation files cannot disable tracing."""
    keys = ('LANGFUSE_BASE_URL', 'LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY')
    if not all((config.get(key) or '').strip() for key in keys):
        raise RuntimeError('Bundled Langfuse configuration is incomplete; rebuild the package')
    for key in keys:
        os.environ[key] = config[key].strip()
    os.environ['LANGFUSE_ENABLED'] = 'true'
    os.environ['LANGFUSE_CAPTURE_CONTENT'] = 'true'
    os.environ['LANGFUSE_TRACING_ENVIRONMENT'] = config.get('LANGFUSE_TRACING_ENVIRONMENT') or 'production'


def watch_parent(parent_pid):
    """Also exit when an installer force-kills the desktop (Rust Drop cannot run)."""
    import threading
    def wait():
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x00100000, False, parent_pid)
            if handle:
                kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
                kernel.CloseHandle(handle)
        else:
            import time
            while os.getppid() == parent_pid:
                time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=wait, daemon=True, name='desktop-parent-watch').start()


def configure():
    state = Path(os.environ['VINOTE_DESKTOP_DATA']).resolve()
    state.mkdir(parents=True, exist_ok=True)
    os.chdir(state)
    bundle = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    config = json.loads((bundle / 'desktop-config.json').read_text(encoding='utf-8'))
    secret_file = state / 'desktop-secrets.json'
    if not secret_file.exists():
        from cryptography.fernet import Fernet
        with secret_file.open('x', encoding='utf-8') as handle:
            json.dump({'APP_JWT_SECRET': secrets.token_urlsafe(48),
                       'MODEL_PROFILE_ENCRYPTION_KEY': Fernet.generate_key().decode()}, handle)
        secret_file.chmod(0o600)
    os.environ.update(json.loads(secret_file.read_text(encoding='utf-8')))
    os.environ.update(config)
    os.environ['VINOTE_DESKTOP_RUNTIME'] = 'true'
    configure_langfuse(config)
    os.environ.setdefault("DIARIZATION_MODEL_DIR", str(bundle / "models" / "diarization"))
    os.environ.update({
        'HOST': '127.0.0.1', 'DATABASE_URL': f'sqlite:///{(state / "vinote.db").as_posix()}',
        'DATA_DIR': str(state / 'data'), 'OUTPUT_DIR': str(state / 'output'),
        'AUTH_COOKIE_SECURE': 'false', 'AUTH_COOKIE_SAMESITE': 'lax',
        'PATH': str(bundle / 'bin') + os.pathsep + os.environ.get('PATH', ''),
    })
    return bundle


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    bundle = configure()
    if '--langfuse-smoke-test' in sys.argv:
        from scripts.check_langfuse import run_check
        receipt = run_check()
        (Path(os.environ['VINOTE_DESKTOP_DATA']) / 'langfuse-smoke.json').write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8',
        )
        return
    if os.environ.get('VINOTE_DESKTOP_PARENT_PID'):
        watch_parent(int(os.environ['VINOTE_DESKTOP_PARENT_PID']))
    from app import create_app
    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException
    import uvicorn

    class SPA(StaticFiles):
        async def get_response(self, path, scope):
            try:
                return await super().get_response(path, scope)
            except HTTPException as exc:
                if exc.status_code != 404 or path.startswith('api/'):
                    raise
                return await super().get_response('index.html', scope)

    app = create_app()
    app.mount('/', SPA(directory=bundle / 'frontend', html=True), name='desktop')
    if '--smoke-test' in sys.argv:
        from app.db import init_db
        import subprocess
        init_db()
        for tool in ('ffmpeg', 'ffprobe'):
            subprocess.run([str(bundle / 'bin' / (tool + ('.exe' if os.name == 'nt' else ''))), '-version'], check=True, stdout=subprocess.DEVNULL)
        from app.services.speaker_diarization_service import SpeakerDiarizationService
        import numpy as np
        import sherpa_onnx

        segmentation, embedding = SpeakerDiarizationService.model_paths()
        for model in (segmentation, embedding):
            if not model.resolve().is_relative_to(bundle.resolve()):
                raise RuntimeError('Package smoke test must use bundled speaker models')
        SpeakerDiarizationService.require_ready()
        diarizer = sherpa_onnx.OfflineSpeakerDiarization(
            sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),
                    num_threads=2,
                ),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=2),
                clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.5),
            )
        )
        diarizer.process(np.zeros(16000, dtype=np.float32))
        import tempfile
        import wave
        from app.services.audio_preprocessing_service import prepare_meeting_audio
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory) / 'silence.wav'
            with wave.open(str(sample), 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(bytes(32000))
            prepare_meeting_audio(str(sample), Path(directory) / 'clean.f32')
        print('Desktop backend smoke test passed: database, routes, frontend, ffmpeg, ffprobe and bundled speaker inference.')
        return
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ['PORT']), log_level='info')


if __name__ == '__main__':
    main()
