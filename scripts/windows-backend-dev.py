"""Keep Uvicorn reload's CTRL_C_EVENT in a hidden Windows console.

The desktop launcher owns this process tree and stops it on exit. Output still
goes to the caller's terminal; only the console used for signals is isolated.
"""

import subprocess
import sys


def main() -> int:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    with subprocess.Popen(
        [sys.executable, *sys.argv[1:]],
        stdin=subprocess.DEVNULL,
        stdout=sys.stdout,
        stderr=sys.stderr,
        startupinfo=startup,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    ) as child:
        try:
            return child.wait()
        except KeyboardInterrupt:
            # dev-desktop.mjs terminates this entire tree with taskkill /T.
            return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
