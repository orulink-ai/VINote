"""Private diagnostic draft; never a completed result or execution checkpoint."""
import json
import os
from pathlib import Path
import uuid


def _linked(path: Path) -> bool:
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def _save_private(artifacts, folder: Path, name: str, value: dict) -> None:
    folder = Path(folder)
    root = artifacts.output_dir.resolve()
    if _linked(folder) or not folder.is_dir() or folder.resolve().parent != root:
        raise ValueError('Invalid working draft directory')
    target = folder / name
    if _linked(target) or (target.exists() and (not target.is_file() or target.stat().st_nlink != 1)):
        raise ValueError('Invalid working draft target')
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
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


def save_working_draft(artifacts, folder: Path, text: str) -> None:
    from app.llm.meeting_source_reads import PartitionedDraft
    if isinstance(text, PartitionedDraft):
        value = {'version': 2, 'kind': 'partitioned_source_preservation_draft',
                 'text': str(text), 'provenance': {
                     'kind': text.provenance_kind, 'raw_reads': list(text.raw_reads),
                     'raw_sha256': list(text.raw_sha256),
                     'allowed_refs': [sorted(refs) for refs in text.allowed_refs],
                     'id_maps': [{'topics': dict(row.topics), 'claims': dict(row.claims)}
                                 for row in text.id_maps]}}
    else:
        value = {'version': 1, 'kind': 'source_preservation_draft', 'text': text}
    _save_private(artifacts, folder, 'meeting_working_draft.json', value)


def save_source_reads(artifacts, folder: Path, diagnostic: dict) -> None:
    """Private observations only, never a lease, checkpoint or retry authority."""
    _save_private(artifacts, folder, 'meeting_source_reads.json', diagnostic)
