"""Explicit live smoke: synthetic transcript + mock provider through the real pipeline."""
import argparse
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.config import settings
from app.llm.openai_llm import OpenAILLM
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.note_service import NoteService
from app.services.task_artifact_service import TaskArtifactService
from app.services.tracing_service import DesktopTraceContext, desktop_trace, get_client, shutdown


def run_check():
    client = get_client()
    if client is None:
        raise SystemExit('Langfuse is disabled or missing configuration')
    llm = OpenAILLM(api_key='synthetic-test-only', model='vinote-smoke-mock')
    service_llm = SimpleNamespace(
        resolve_config=lambda **kwargs: SimpleNamespace(model_name=llm.model),
        create_summarizer=lambda **kwargs: llm,
    )
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='# Synthetic note'))],
                                 usage={'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30})
    task_id = 'langfuse-smoke-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='vinote-langfuse-') as folder:
        artifacts = TaskArtifactService(Path(folder))
        service = NoteService(llm_service=service_llm, artifact_service=artifacts)
        with patch.object(llm.client.chat.completions, 'create', return_value=completion), patch(
            'app.services.vilab_cloud_service.VILabCloudService.status', return_value={'mode': 'local'}
        ):
            with desktop_trace(DesktopTraceContext(
                workflow='synthetic', source='build_validation', media_type='transcript',
                channel=settings.langfuse_environment,
                input={'synthetic': True, 'business': False, 'purpose': 'langfuse_connectivity'},
            )):
                service.generate_from_transcript(
                    TranscriptResult(language='en', full_text='Synthetic integration check.',
                                     segments=[TranscriptSegment(start=0, end=1, text='Synthetic integration check.')]),
                    task_id, title='Langfuse synthetic integration check',
                )
        trace_id = artifacts.get_status(task_id).get('langfuse_trace_id')
        if not trace_id:
            raise SystemExit('Pipeline did not produce a trace ID')
    client.flush()
    # Read back from Langfuse; an SDK flush alone is not evidence of ingestion.
    with httpx.Client(base_url=settings.langfuse_base_url,
                      auth=(settings.langfuse_public_key, settings.langfuse_secret_key), timeout=10) as http:
        for attempt in range(12):
            response = http.get('/api/public/traces/' + trace_id)
            if response.status_code == 200:
                trace = response.json()
                observations = trace.get('observations', [])
                if any(item.get('type') == 'GENERATION' for item in observations):
                    break
            elif response.status_code != 404:
                raise SystemExit(f'Langfuse readback failed: HTTP {response.status_code}')
            time.sleep(2)
        else:
            raise SystemExit('Trace not visible yet: ' + trace_id)
    assert trace['sessionId'] == task_id
    assert trace['name'] == '桌面端｜笔记整理'
    generations = [item for item in observations if item.get('type') == 'GENERATION']
    assert generations[0]['model'] == 'vinote-smoke-mock'
    assert generations[0]['usage']['total'] == 30
    assert generations[0]['parentObservationId']
    assert generations[0]['modelParameters']['temperature'] == 0.7
    assert trace['environment'] == settings.langfuse_environment
    receipt = {'task_id': task_id, 'trace_id': trace_id,
                      'observations': len(observations), 'mock_provider': True,
                      'environment': settings.langfuse_environment,
                      'release': settings.langfuse_release,
                      'trace_url': client.get_trace_url(trace_id=trace_id)}
    print(json.dumps(receipt, ensure_ascii=False))
    shutdown()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true', help='Send synthetic traces to configured Langfuse')
    args = parser.parse_args()
    if not args.send:
        parser.error('--send is required for the live check')
    run_check()


if __name__ == '__main__':
    main()
