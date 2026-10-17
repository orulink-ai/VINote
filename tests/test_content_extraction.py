"""Extraction requests exercise both routers and cloud ASGI; no external I/O."""
import hashlib
import io
import socket
from zipfile import ZipFile

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import db
from app.config import settings
from app.models.auth import AuthenticatedUser
from app.routers import content_extraction as route
from app.services import document_source_service as source
from app.services import text_extraction_service as extraction
from app.services.generation_auth_service import get_generation_user
from tests.test_cloud_content_runtime import runtime, headers


@pytest.fixture(autouse=True)
def no_models_or_tasks(monkeypatch, runtime):
    from app.services import cloud_content_worker as worker
    from app.services.vilab_cloud_service import VILabCloudService
    from app.services.source_request_service import SourceRequestService
    from app.services.task_artifact_service import TaskArtifactService
    from app.services.note_service import NoteService
    from app.services.transcription_service import TranscriptionService

    def forbidden(*args, **kwargs):
        pytest.fail('pure extraction must not touch models, generation or task receipts')
    for target, names in [(worker, ['prepare_models', 'freeze', 'run_job']),
                          (VILabCloudService, ['request']),
                          (SourceRequestService, ['reserve']),
                          (TaskArtifactService, ['create_task_dir']),
                          (TranscriptionService, ['transcribe']),
                          (NoteService, ['generate', 'generate_from_file', 'generate_from_transcript'])]:
        for name in names:
            if hasattr(target, name):
                monkeypatch.setattr(target, name, forbidden)


def docx(text):
    output = io.BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


def assert_payload(response, text, kind):
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    body = response.json()
    assert set(body) == {'extraction_protocol', 'title', 'text', 'source_sha256', 'source_type'}
    assert body['extraction_protocol'] == 1
    assert body['text'] == text
    assert body['source_type'] == kind
    assert body['source_sha256'] == hashlib.sha256(text.encode('utf-8')).hexdigest()


def test_cloud_bearer_required_and_cookie_cannot_extract(runtime):
    for path in ['/api/content-service/extract-url', '/api/content-service/extract-file']:
        for auth in [{}, {'Cookie': 'vinote_session=fixture'}, headers('expired')]:
            result = runtime.client.post(path, headers=auth, json={'url': 'https://example.com'})
            assert result.status_code == 401
    assert runtime.provider_calls == []


@pytest.mark.parametrize('name,data,text,kind', [
    ('plain.txt', '正文内容'.encode(), '正文内容', 'transcript'),
    ('note.md', b'# Saved text', '# Saved text', 'transcript'),
    ('sub.srt', b'1\n00:00:00,000 --> 00:00:01,000\nSaved speech\n', 'Saved speech', 'transcript'),
    ('sub.vtt', b'WEBVTT\n\n00:00.000 --> 00:01.000\nSaved speech\n', 'Saved speech', 'transcript'),
    ('source.json', b'{"segments":[{"text":"saved segment","start":0,"end":1}]}', 'saved segment', 'transcript'),
    ('word.docx', docx('Document paragraph'), 'Document paragraph', 'document'),
])
def test_cloud_extract_file_without_identity_mapping_or_task(runtime, name, data, text, kind):
    assert_payload(runtime.client.post('/api/content-service/extract-file', headers=headers(),
                   files={'file': (name, data)}), text, kind)
    assert runtime.provider_calls == []
    assert list(runtime.root.iterdir()) == []
    from app.services.cloud_content_identity import ContentIdentityDB
    with db.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(ContentIdentityDB)) == 0


def test_cloud_caps_add_only_text_protocol(runtime):
    body = runtime.client.get('/api/content-service/capabilities', headers=headers()).json()
    assert body['text_extraction_protocol'] == 1
    assert body['models_configured'] is True
    assert runtime.provider_calls == []


def test_pdf_scan_reuses_existing_parser_without_ocr(runtime):
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    output = io.BytesIO()
    writer.write(output)
    response = runtime.client.post('/api/content-service/extract-file', headers=headers(), files={'file': ('scan.pdf', output.getvalue())})
    assert response.status_code == 422  # No text; never start OCR/ASR/LLM.


def test_json_parser_errors_never_return_uploaded_content(runtime):
    content = b'{"private_fixture_body": INVALID}'
    response = runtime.client.post('/api/content-service/extract-file', headers=headers(), files={'file': ('private-name.json', content)})
    assert response.status_code == 422
    assert 'private_fixture_body' not in response.text and 'private-name' not in response.text


def fake_web(monkeypatch, respond):
    real_client = httpx.Client
    calls = []
    monkeypatch.setattr(source.socket, 'getaddrinfo', lambda *args, **kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))])

    def handle(request):
        calls.append(request)
        assert request.headers.get('authorization') is None
        assert request.headers.get('cookie') is None
        return respond(request, len(calls))
    monkeypatch.setattr(source.httpx, 'Client', lambda **kwargs:
                        real_client(transport=httpx.MockTransport(handle), **kwargs))
    return calls


def test_cloud_url_reuses_safe_html_and_never_model_service(runtime, monkeypatch):
    text = 'Public article body. ' * 4
    calls = fake_web(monkeypatch, lambda req, count: httpx.Response(200,
        headers={'content-type': 'text/html'}, text=f'<title>Article</title><body><main>{text}</main><script>ignore()</script></body>'))
    result = runtime.client.post('/api/content-service/extract-url', headers=headers(), json={'url': 'https://example.com/post'})
    assert_payload(result, text.strip(), 'webpage')
    assert result.json()['title'] == 'Article'
    assert len(calls) == 1 and calls[0].url.host == '8.8.8.8'
    assert calls[0].headers['host'] == 'example.com'
    assert runtime.provider_calls == [] and list(runtime.root.iterdir()) == []


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'ftp://example.com/a', 'https://user:password@example.com',
    'http://127.0.0.1/a', 'http://169.254.169.254/latest', 'http://[::1]/a',
    'https://example.com:8900/a', 'https://b23.tv/fixture', 'https://www.youtube.com/watch?v=fixture',
    'https://example.com/a.mp4', 'https://example.com/a.wav'])
def test_malicious_or_media_url_rejected_before_fetch(runtime, monkeypatch, url):
    def dns(host, *args, **kwargs):
        address = '127.0.0.1' if host not in ['169.254.169.254', '::1'] else host
        return [(socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]
    monkeypatch.setattr(source.socket, 'getaddrinfo', dns)
    monkeypatch.setattr(source.httpx, 'Client', lambda **kwargs: pytest.fail('unsafe target reached fetch'))
    response = runtime.client.post('/api/content-service/extract-url', headers=headers(), json={'url': url})
    assert response.status_code == 422
    assert 'password' not in response.text and '/etc/passwd' not in response.text


@pytest.mark.parametrize('target', ['http://127.0.0.1/private', 'https://b23.tv/fixture'])
def test_redirect_to_private_or_video_does_not_fetch_next_hop(runtime, monkeypatch, target):
    calls = fake_web(monkeypatch, lambda req, count: httpx.Response(302, headers={'location': target}))
    public_dns = source.socket.getaddrinfo
    monkeypatch.setattr(source.socket, 'getaddrinfo', lambda host, *args, **kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))]
                        if host == '127.0.0.1' else public_dns(host, *args, **kwargs))
    response = runtime.client.post('/api/content-service/extract-url', headers=headers(), json={'url': 'https://example.com/start'})
    assert response.status_code == 422 and len(calls) == 1


@pytest.mark.parametrize('addresses', [['224.0.0.1'], ['ff02::1'], ['fec0::1'], ['8.8.8.8', '127.0.0.1']])
def test_non_public_or_mixed_dns_answers_are_rejected_before_socket(runtime, monkeypatch, addresses):
    monkeypatch.setattr(source.socket, 'getaddrinfo', lambda *args, **kwargs:
        [(socket.AF_INET6 if ':' in ip else socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in addresses])
    monkeypatch.setattr(source.httpx, 'Client', lambda **kwargs: pytest.fail('non-public DNS reached fetch'))
    assert runtime.client.post('/api/content-service/extract-url', headers=headers(), json={'url': 'https://example.com'}).status_code == 422


def test_duplicate_files_and_oversized_url_body_are_rejected(runtime):
    response = runtime.client.post('/api/content-service/extract-file', headers=headers(),
        files=[('file', ('one.txt', b'one')), ('file', ('two.txt', b'two'))])
    assert response.status_code in {400, 422}
    response = runtime.client.post('/api/content-service/extract-url', headers={**headers(), 'content-type': 'application/json'},
        content=iter([b'{"url":"https://example.com/', b'a' * 32768, b'"}']))
    assert response.status_code == 413


@pytest.mark.parametrize('data', [b'', b'broken', b'{"full_text": ""}'])
def test_invalid_files_have_safe_errors(runtime, data):
    response = runtime.client.post('/api/content-service/extract-file', headers=headers(), files={'file': ('source.json', data)})
    assert response.status_code in {413, 422}


def test_no_model_url_options_or_media_upload(runtime):
    response = runtime.client.post('/api/content-service/extract-url', headers=headers(),
        json={'url': 'https://example.com', 'base_url': 'https://models.invalid'})
    assert response.status_code == 422
    assert runtime.client.post('/api/content-service/extract-file', headers=headers(),
        files={'file': ('audio.m4a', b'not text')}).status_code == 422
    assert runtime.client.post('/api/content-service/extract-file', headers=headers(),
        data={'model_url': 'https://models.invalid'}, files={'file': ('a.txt', b'body')}).status_code in {400, 422}


def test_limits_before_parse_and_without_content_length(runtime, monkeypatch):
    monkeypatch.setattr(extraction, 'MAX_BYTES', 32)
    assert runtime.client.post('/api/content-service/extract-file', headers=headers(),
        files={'file': ('text.txt', b'x' * 33)}).status_code == 413
    response = runtime.client.post('/api/content-service/extract-file', headers={**headers(), 'Content-Type': 'multipart/form-data; boundary=x'},
        content=iter([b'x' * 40000, b'x' * 40000]))
    assert response.status_code == 413
    assert runtime.client.post('/api/content-service/extract-url', headers={**headers(), 'Content-Length': '32769'}, content=b'{}').status_code == 413
    monkeypatch.setattr(extraction, 'MAX_TEXT', 10)
    assert runtime.client.post('/api/content-service/extract-file', headers=headers(), files={'file': ('text.txt', b'x' * 11)}).status_code == 422


def test_extraction_is_independent_of_generation_slot_and_has_no_mapping(runtime):
    from app.services import cloud_content_identity as identity
    assert identity._submission_slot.acquire(blocking=False)
    try:
        assert_payload(runtime.client.post('/api/content-service/extract-file', headers=headers(),
                       files={'file': ('text.txt', b'body')}), 'body', 'transcript')
    finally:
        identity._submission_slot.release()


def test_request_auth_outage_does_not_extract(runtime, monkeypatch):
    monkeypatch.setattr(extraction, 'extract_url', lambda url: pytest.fail('unauthenticated extraction'))
    assert runtime.client.post('/api/content-service/extract-url', headers=headers('outage'), json={'url': 'https://example.com'}).status_code == 502


def test_device_route_auth_and_shared_response_contract(monkeypatch):
    app = FastAPI()
    app.include_router(route.router, prefix='/api')
    client = TestClient(app)
    assert client.post('/api/content-service/extract-file', files={'file': ('a.txt', b'body')}).status_code == 401
    app.dependency_overrides[get_generation_user] = lambda: AuthenticatedUser(user_id='fixture-owner')
    assert_payload(client.post('/api/content-service/extract-file', files={'file': ('a.txt', b'body')}), 'body', 'transcript')
    client.close()
