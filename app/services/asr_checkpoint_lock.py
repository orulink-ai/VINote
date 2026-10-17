"""Nonblocking process lock; the OS releases ownership when its process exits.

Keep the backing file: unlinking it can split POSIX contenders across inodes.
This is a new lock namespace; legacy recognition.lock is never reclaimed here.
"""
from contextlib import contextmanager
import errno
import os


@contextmanager
def checkpoint_lock(folder):
    fd = os.open(folder / "recognition.process.lock", os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise ValueError("这份录音已有处理中或待核验的转写请求，未重复提交") from None
            raise
        locked = True
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        yield
    finally:
        try:
            if locked:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
