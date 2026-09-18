"""Exercise console visibility and signal isolation without starting the app."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console behavior")
def test_backend_console_is_hidden_and_reload_signal_is_isolated():
    launcher = Path(__file__).resolve().parents[1] / "scripts/windows-backend-dev.py"
    probe = """
import ctypes
import os
import signal
import time

ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p
ctypes.windll.user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
window = ctypes.windll.kernel32.GetConsoleWindow()
assert window, 'Backend needs its own console for Uvicorn reload'
assert not ctypes.windll.user32.IsWindowVisible(window), 'Console must stay hidden'
received = []
signal.signal(signal.SIGINT, lambda *_: received.append(True))
# Broadcast to this console, as a reload control event can do on Windows.
# The launcher/test runner must remain alive in their separate console.
os.kill(0, signal.CTRL_C_EVENT)
for _ in range(20):
    if received:
        break
    time.sleep(0.05)
assert received, 'Reload signal must reach the backend console'
print('hidden-console-and-reload-ok', flush=True)
"""
    result = subprocess.run(
        [sys.executable, str(launcher), "-c", probe],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr
    assert "hidden-console-and-reload-ok" in result.stdout
