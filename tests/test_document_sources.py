from io import BytesIO
from zipfile import ZipFile
import pytest
import httpx
from app.services import document_source_service as source


def docx(text):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


def test_docx_extracts_paragraphs_not_instructions():
    assert source.document_text('中文.docx', docx('计划：先检查正文，再保存笔记。')) == '计划：先检查正文，再保存笔记。'


@pytest.mark.parametrize('name,data,message', [('a.docx', b'broken', '损坏'), ('a.doc', b'text', 'DOCX'), ('a.pdf', b'', '非空'), ('a.docx', docx(''), '未读取')])
def test_invalid_documents_explain_recovery(name, data, message):
    with pytest.raises(ValueError, match=message):
        source.document_text(name, data)


def test_scan_and_encrypted_pdf_need_manual_conversion():
    from pypdf import PdfWriter
    writer = PdfWriter(); writer.add_blank_page(width=200, height=200)
    output = BytesIO(); writer.write(output)
    with pytest.raises(ValueError, match='扫描'):
        source.document_text('a.pdf', output.getvalue())
    writer.encrypt('password'); output = BytesIO(); writer.write(output)
    with pytest.raises(ValueError, match='加密'):
        source.document_text('a.pdf', output.getvalue())


def test_private_dns_and_redirect_are_blocked(monkeypatch):
    monkeypatch.setattr(source.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(ValueError, match='内网'):
        source.public_url('https://example.com')
    with pytest.raises(ValueError, match='账号密码'):
        source.public_url('https://user:secret@example.com')


def test_article_reading_strips_navigation_and_scripts(monkeypatch):
    monkeypatch.setattr(source.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('8.8.8.8', 443))])
    transport = httpx.MockTransport(lambda req: httpx.Response(200, headers={'content-type': 'text/html'}, text='<title>资料</title><nav>不要总结菜单</nav><article><h1>实施计划</h1><p>' + '先提取正文，再生成总结，失败时保留来源并重试。' * 4 + '</p><script>run()</script></article>'))
    original = httpx.Client
    monkeypatch.setattr(source.httpx, 'Client', lambda **kw: original(transport=transport, **kw))
    title, text = source.webpage_text('https://example.com')
    assert title == '资料' and '实施计划' in text and 'run()' not in text and '菜单' not in text


def test_retry_uses_extracted_checkpoint(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from app.services import source_note_job
    folder = tmp_path
    (folder / 'document_text.json').write_text(json.dumps({'title': '计划', 'text': '已提取正文'}), encoding='utf-8')
    artifacts = SimpleNamespace(find_task_dir=lambda task: folder)
    calls = []
    service = SimpleNamespace(artifact_service=artifacts, generate_from_transcript=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(source_note_job, 'webpage_text', lambda url: pytest.fail('retry must not fetch source again'))
    source_note_job.run_source_job(service, 'task', {'url': 'https://example.com'}, 'owner')
    assert calls[0]['transcript'].metadata['source_kind'] == 'document'
    assert calls[0]['transcript'].segments[0].end == 0
