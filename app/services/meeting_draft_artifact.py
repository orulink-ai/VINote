"""Private diagnostic draft; never a completed result or execution checkpoint."""
import json
import os
from pathlib import Path
import uuid


def _linked(path: Path) -> bool:
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def save_working_draft(artifacts, folder: Path, text: str) -> None:
    folder = Path(folder)
    root = artifacts.output_dir.resolve()
    if _linked(folder) or not folder.is_dir() or folder.resolve().parent != root:
        raise ValueError('Invalid working draft directory')
    target = folder / 'meeting_working_draft.json'
    if _linked(target) or (target.exists() and (not target.is_file() or target.stat().st_nlink != 1)):
        raise ValueError('Invalid working draft target')
    payload = json.dumps({'version': 1, 'kind': 'source_preservation_draft', 'text': text}, ensure_ascii=False)
    temporary = folder / f'.working-draft-{uuid.uuid4().hex}.tmp'
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if _linked(folder) or folder.resolve().parent != root or _linked(target):
            raise ValueError('Working draft location changed')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
