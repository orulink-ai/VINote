"""Explicit one-off recovery through the normal confirmed child pipeline.

Run as a module from the repository root. Never rerun an operation ID: query
its existing receipt and child status instead. No credentials are printed.
"""
import argparse
import hashlib
import json
from uuid import UUID

from fastapi import BackgroundTasks

from app.llm.openai_llm import _BasePromptLLM
from app.services.meeting_summary_regeneration import SummaryConfirmation
from app.services.task_model_source import SNAPSHOT_FILE, validate_source
from app.services.vilab_cloud_service import VILabCloudService


def inject_saved_draft(llm, path, frozen_bytes, draft):
    if not isinstance(llm, _BasePromptLLM) or getattr(llm, 'source_reading_enabled', False):
        raise ValueError('unsupported summarizer')
    used = False

    def complete_stage(*, stage, **kwargs):
        nonlocal used
        if stage != 'LLM｜生成会议纪要' or used:
            raise ValueError('unexpected draft dispatch')
        if path.is_symlink() or path.read_bytes() != frozen_bytes:
            raise ValueError('draft changed')
        used = True
        return draft

    llm._complete_stage = complete_stage


def start_recovery(service, note, owner, parent, operation, *, on_accepted=None):
    from app.services.task_generation_context import _read_json
    context, folder, _, _, _ = service._context(owner, parent)
    path = folder / 'meeting_working_draft.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('draft unavailable')
    frozen = path.read_bytes()
    value = json.loads(frozen)
    if (value.get('version') != 1 or value.get('kind') != 'source_preservation_draft'
            or not isinstance(value.get('text'), str)):
        raise ValueError('unsupported draft')
    snapshot = validate_source(_read_json(folder / SNAPSHOT_FILE), owner)
    current = VILabCloudService().connection_snapshot(owner)
    if (snapshot['mode'] != 'cloud' or current.get('mode') != 'cloud'
            or snapshot['server_url'].rstrip('/') != current.get('server_url', '').rstrip('/')):
        raise ValueError('original model connection changed')
    presentation = _read_json(folder / 'summary_presentation.json')
    body = SummaryConfirmation(operation_id=operation, confirmed=True,
        context_revision=context['context_revision'], source_version=context['source']['version'],
        model_name=snapshot['llm_model'], content_depth=presentation['content_depth'],
        presentation=presentation['presentation'])
    # Existing IDs are query-only: never execute an old or ambiguous operation.
    from fastapi import HTTPException
    try:
        service.receipts.get(owner, str(operation))
    except HTTPException as error:
        if error.status_code != 404:
            raise
    else:
        raise ValueError('operation already exists; query receipt')
    create = note.llm_service.create_summarizer
    def create_recovery_summarizer(**kwargs):
        llm = create(**kwargs)
        if getattr(llm, 'model', None) != snapshot['llm_model']:
            raise ValueError('original model changed')
        inject_saved_draft(llm, path, frozen, value['text'])
        return llm
    note.llm_service.create_summarizer = create_recovery_summarizer
    try:
        background = BackgroundTasks()
        receipt = service.accept(owner, parent, body, background, note)
        if len(background.tasks) != 1:
            raise ValueError('operation already exists; query receipt')
        if on_accepted:
            on_accepted(receipt, hashlib.sha256(frozen).hexdigest())
        service.run_once(receipt.task_id, owner, note)
        return receipt
    finally:
        note.llm_service.create_summarizer = create


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--operation', required=True, type=UUID)
    parser.add_argument('--parent', default='69c55c6f-2c62-4b6b-b287-54e8caee0105',
                        choices=['69c55c6f-2c62-4b6b-b287-54e8caee0105'])
    args = parser.parse_args()
    from app.services.meeting_summary_regeneration import SummaryRegenerationService
    from app.services.note_service import NoteService
    service = SummaryRegenerationService()
    def accepted(receipt, digest):
        print(json.dumps({'operation_id': str(args.operation), 'task_id': receipt.task_id,
                          'draft_sha256': digest}), flush=True)
    receipt = start_recovery(service, NoteService(), args.owner, args.parent, args.operation,
                             on_accepted=accepted)
    status = service.artifacts.get_status(receipt.task_id)
    print(json.dumps({'task_id': receipt.task_id, 'status': status.get('status'),
                      'error_code': status.get('error_code')}), flush=True)


if __name__ == '__main__':
    main()
