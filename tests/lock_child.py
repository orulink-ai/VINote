"""Actual subprocess lock/crash probe; only reads/writes the supplied temp folder."""
import importlib.util
import json
import os
from pathlib import Path
import sys

module_path, folder, action = sys.argv[1:]
spec = importlib.util.spec_from_file_location('lock_candidate', module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    with module.checkpoint_lock(Path(folder)):
        print('LOCKED', flush=True)
        if action == 'hold':
            sys.stdin.buffer.read(1)
        elif action in ('crash-final', 'crash-inflight'):
            checkpoint = {'completed': [{'start': 0, 'end': 1, 'text': 'confirmed final',
                                         'language': None, 'segments': []}]}
            if action == 'crash-inflight':
                checkpoint['completed'] = []
                checkpoint['inflight'] = {'start_frame': 0, 'end_frame': 16000}
            target = Path(folder) / 'recognition.json'
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(checkpoint), encoding='utf-8')
            temporary.replace(target)
            os._exit(29)
except ValueError:
    print('BUSY', flush=True)
    sys.exit(17)
