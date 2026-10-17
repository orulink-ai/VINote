"""Uvicorn development reload bounded to backend sources, not media/build trees."""
import argparse
import sys
from pathlib import Path

import uvicorn
from uvicorn.supervisors.basereload import BaseReload
from watchfiles import PythonFilter, watch

ROOT = Path(__file__).resolve().parents[1]


def source_paths():
    return [ROOT / 'app', ROOT / 'main.py', ROOT / 'mcp_server.py']


class SourceReload(BaseReload):
    def __init__(self, config, target, sockets):
        super().__init__(config, target, sockets)
        self.reloader_name = 'VINoteSources'
        self.watcher = watch(
            *source_paths(), watch_filter=PythonFilter(),
            stop_event=self.should_exit, yield_on_timeout=True,
            force_polling=True, poll_delay_ms=1000,
        )

    def should_restart(self):
        self.pause()
        changes = next(self.watcher)
        return sorted({Path(path) for _, path in changes}) if changes else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8900)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    config = uvicorn.Config('main:app', host=args.host, port=args.port,
                           reload=True, reload_dirs=[str(ROOT / 'app')])
    server = uvicorn.Server(config)
    sock = config.bind_socket()
    SourceReload(config, target=server.run, sockets=[sock]).run()


if __name__ == '__main__':
    main()
