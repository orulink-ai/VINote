"""Coordinate refresh with the official CLI's ordinary local workspace lock.

CLI profiles share Windows keychain app/user entries even when config dirs
differ. Match gofrs/flock's byte-0/length-1 LockFileEx contract on Windows,
and flock on Unix. No credentials are read. Login/init are separate consent
operations; this lock serializes normal credential-bearing API invocations.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import time

from app.services.feishu_service import FeishuError


def lock_path(identity):
    app_id, open_id = identity.get("app_id"), identity.get("open_id")
    if (not isinstance(app_id, str) or not re.fullmatch(r"cli_[A-Za-z0-9_-]+", app_id)
            or not isinstance(open_id, str) or not re.fullmatch(r"ou_[A-Za-z0-9_-]+", open_id)):
        raise FeishuError("飞书凭据身份尚未核验", 409)
    root = Path(os.environ.get("LARKSUITE_CLI_CONFIG_DIR", Path.home() / ".lark-cli"))
    return root / "locks" / ("refresh_" + app_id + "_" + open_id + ".lock")


@contextmanager
def credential_lock(identity, private_directory, timeout=10):
    if not identity:
        yield
        return
    path = lock_path(identity)
    if path.parent.parent.resolve() == Path(private_directory).resolve():
        raise FeishuError("飞书刷新锁与当前配置冲突，尚未调用", 409)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise FeishuError("飞书刷新锁不可用，尚未调用", 409)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            import msvcrt

            class Overlapped(ctypes.Structure):
                _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                            ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                            ("hEvent", wintypes.HANDLE)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                         wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
            kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                           wintypes.DWORD, ctypes.POINTER(Overlapped)]
            native, position = msvcrt.get_osfhandle(handle.fileno()), Overlapped()

            def attempt():
                if kernel.LockFileEx(native, 3, 0, 1, 0, ctypes.byref(position)):
                    return True
                if ctypes.get_last_error() != 33:  # ERROR_LOCK_VIOLATION
                    raise FeishuError("飞书刷新互斥不可用，尚未调用", 503)
                return False

            def release():
                kernel.UnlockFileEx(native, 0, 1, 0, ctypes.byref(position))
        else:
            import fcntl

            def attempt():
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except BlockingIOError:
                    return False

            def release():
                fcntl.flock(handle, fcntl.LOCK_UN)

        deadline = time.monotonic() + timeout
        while not attempt():
            if time.monotonic() >= deadline:
                raise FeishuError("飞书授权正在由其他应用更新，请稍后再试；尚未提交", 409,
                                  code="credential_busy")
            time.sleep(0.1)
        try:
            yield
        finally:
            release()
