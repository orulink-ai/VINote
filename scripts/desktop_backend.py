"""Frozen desktop backend. Secrets and notes live in the user's app data, never the bundle."""
import json
import os
from pathlib import Path
import secrets
import sys
import logging


def configure_langfuse(state):
    """Use a per-install atomic credential set, following ViTalk desktop."""
    os.environ.setdefault('LANGFUSE_TRACING_ENVIRONMENT', 'production')
    path = state / 'langfuse.env'
    if not path.exists():
        return
    from dotenv import dotenv_values
    keys = ('LANGFUSE_BASE_URL', 'LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY')
    try:
        values = dotenv_values(path)
        for key in keys:
            os.environ[key] = (values.get(key) or '').strip()
        complete = all(os.environ[key] for key in keys)
        enabled = (values.get('LANGFUSE_ENABLED') or 'true').strip().lower() in ('true', '1', 'yes', 'on')
        os.environ['LANGFUSE_ENABLED'] = 'true' if complete and enabled else 'false'
        os.environ['LANGFUSE_CAPTURE_CONTENT'] = values.get('LANGFUSE_CAPTURE_CONTENT') or 'false'
        if not complete:
            logging.warning('Langfuse configuration incomplete; tracing disabled')
    except Exception:
        os.environ['LANGFUSE_ENABLED'] = 'false'
        logging.warning('Langfuse configuration unreadable; tracing disabled')


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
    configure_langfuse(state)
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
        print('Desktop backend smoke test passed: database, routes, frontend, ffmpeg and ffprobe.')
        return
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ['PORT']), log_level='info')


if __name__ == '__main__':
    main()
