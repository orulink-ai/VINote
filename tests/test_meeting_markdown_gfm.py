"""Actual draft3/review4-or-6 host and ReactMarkdown/GFM parity."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_presentation import presentation_scope
from app.llm.openai_llm import _BasePromptLLM
from app.models.transcript import TranscriptSegment
from app.services.summary_presentation_artifact import render_presentation
from tests.test_meeting_final_review import case, response, SOURCE


def automatic(c, value):
    raw3, raw4 = json.dumps(c.material), json.dumps(value)

    class Host(_BasePromptLLM):
        def __init__(self):
            self.calls = []
            self.configure_video_capabilities({'vision': True}, image_input_verified=True)

        def _complete(self, **prompts):
            self.calls.append(prompts)
            assert len(self.calls) <= 2, 'No automatic repair or replay'
            assert SOURCE in prompts['user_prompt']
            return raw3 if len(self.calls) == 1 else raw4

    return Host(), raw4


def summarize(llm, c):
    return llm.summarize('Synthetic', [TranscriptSegment(0, 10, SOURCE)],
                         style='meeting', video_evidence=c.evidence)


def graphic5_fixture(value):
    """Explicit new graphic response; preserve the tested Markdown exactly."""
    value = copy.deepcopy(value)
    value['protocol'] = 5
    value['blocks'] = [
        {'id': block['id'], 'parts': [{'id': f'PART_{index}', 'text': block['markdown']}]}
        for index, block in enumerate(value['blocks'])
    ]
    ref = {'part_id': 'PART_0', 'claim_ids': ['C1']}
    if value['visual']['diagram'] is None:
        value['visual'] = {'protocol': 2, 'scenes': [
            {'id': 'S1', 'frame_id': '[FRAME:0001]', 'label_ref': ref}], 'diagram': None}
    else:
        value['visual'] = {'protocol': 2, 'scenes': [], 'diagram': {
            'kind': 'cards', 'nodes': [{'id': 'N1', 'label_ref': ref}], 'edges': []}}
    return value


def graphic6_fixture(value):
    """Explicit new graphic response; preserve the tested Markdown exactly."""
    value = copy.deepcopy(value)
    value['protocol'] = 6
    value['blocks'] = [
        {'id': block['id'], 'parts': [block['markdown']]}
        for index, block in enumerate(value['blocks'])
    ]
    ref = {'block_id': value['blocks'][0]['id'], 'part_index': 0, 'claim_ids': ['C1']}
    if value['visual']['diagram'] is None:
        value['visual'] = {'protocol': 3, 'scenes': [
            {'id': 'S1', 'frame_id': '[FRAME:0001]', 'label_ref': ref}], 'diagram': None}
    else:
        value['visual'] = {'protocol': 3, 'scenes': [], 'diagram': {
            'kind': 'cards', 'nodes': [{'id': 'N1', 'label_ref': ref}], 'edges': []}}
    return value


def graphic7_fixture(value):
    value = graphic6_fixture(value); value['protocol'] = 7
    value['title_ref'] = {'block_id': value['blocks'][0]['id'], 'part_index': 0}
    for claim in value['claims']:
        block = claim.pop('block_ids')[0]; claim.pop('text')
        claim['part_ref'] = {'block_id': block, 'part_index': 0}
    covered = {c['part_ref']['block_id'] for c in value['claims']}
    for block in value['blocks']:
        if block['id'] not in covered:
            value['claims'].append({**copy.deepcopy(value['claims'][0]), 'id': 'NEW_' + block['id'],
                'part_ref': {'block_id': block['id'], 'part_index': 0}})
    return value


@pytest.fixture(scope='module')
def react_render():
    frontend = Path(__file__).resolve().parents[1] / 'frontend'
    node = shutil.which('node')
    if not node or not (frontend / 'node_modules/react-markdown/package.json').is_file():
        pytest.skip('ReactMarkdown/GFM parity requires the existing frontend dependencies and Node')

    def render(bodies):
        script = '''
import fs from 'node:fs';
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {renderToStaticMarkup} from 'react-dom/server';
const bodies = JSON.parse(fs.readFileSync(0, 'utf8'));
console.log(JSON.stringify(bodies.map(body => renderToStaticMarkup(
  React.createElement(ReactMarkdown, {skipHtml:true, remarkPlugins:[remarkGfm]}, body)))));
'''
        result = subprocess.run([node, '--input-type=module', '-e', script],
            input=json.dumps(bodies), cwd=frontend, text=True, encoding='utf-8',
            capture_output=True, check=True, timeout=20)
        return json.loads(result.stdout)

    return render


@pytest.mark.parametrize('presentation', ['text', 'html'])
@pytest.mark.parametrize('body', [
    '```cpp\nstd::vector<int> candidate;\n````',
    '```cpp\nstd::vector<int> candidate;',
    '```cpp example\nstd::vector<int> candidate;\n```',
    '- Proposal:\n\n  ```cpp\n  std::vector<int> candidate;\n  ```',
    r'Use \<Widget> as the literal type.',
    '| Type | Proposal |\n| --- | --- |\n| `std::vector<int>` | ~~old~~ new |',
    '- [x] Use `std::vector<int>` as a proposal.',
])
def test_valid_commonmark_gfm_survives_actual_host_and_renderer(case, presentation, body, react_render):
    value = response(case, presentation)
    value['blocks'][0]['markdown'] = body
    llm, raw4 = automatic(case, value)
    with presentation_scope('detailed', presentation) as state:
        markdown = summarize(llm, case)
        assert state.raw_review == raw4
        assert render_presentation(None, SimpleNamespace(presentation=presentation), markdown) == body
    html = react_render([markdown])[0]
    assert 'vector&lt;int&gt;' in html or '&lt;Widget&gt;' in html
    assert len(llm.calls) == 2


@pytest.mark.parametrize('presentation', ['text', 'html'])
@pytest.mark.parametrize('blocks, refs', [
    (['[proposal]: https://example.org "' + SOURCE + '"'], ['B1']),
    (['[proposal]: https://example.org "' + SOURCE + '"', SOURCE], ['B1']),
    (['#'], ['B1']),
    (['---'], ['B1']),
    (['```cpp', SOURCE, '```'], ['B1']),
    (['```cpp', SOURCE, '```'], ['B3']),
    ([SOURCE, '[proposal]: https://example.org'], ['B1', 'B2']),
])
def test_included_blocks_must_contribute_visible_text_in_joined_report(case, presentation, blocks, refs):
    value = response(case, presentation)
    value['blocks'] = [{'id': f'B{i+1}', 'markdown': text} for i, text in enumerate(blocks)]
    value['claims'][0]['block_ids'] = refs
    llm, raw4 = automatic(case, value)
    with presentation_scope('detailed', presentation) as state:
        with pytest.raises(FinalLedgerError) as error:
            summarize(llm, case)
        assert error.value.code == 'included_without_visible_block'
        assert state.raw_review == raw4 and state.figures == [] and state.visual_review is None
    assert len(llm.calls) == 2


def test_nonincluded_definitions_can_support_visible_included_links(case, react_render):
    value = response(case, 'text')
    value['blocks'] = [{'id':'R', 'markdown':'[proposal]: https://example.org "Source"'},
                       {'id':'B1', 'markdown':'A [visible proposal][proposal].'}]
    llm, _ = automatic(case, value)
    with presentation_scope('detailed', 'text'):
        markdown = summarize(llm, case)
    assert '<a href="https://example.org"' in react_render([markdown])[0]
    assert len(llm.calls) == 2


def test_cross_block_code_claim_can_reference_actual_content_not_just_delimiters(case, react_render):
    value = response(case, 'text')
    value['blocks'] = [{'id':'OPEN', 'markdown':'```cpp'}, {'id':'B1', 'markdown':SOURCE},
                       {'id':'CLOSE', 'markdown':'```'}]
    llm, _ = automatic(case, value)
    with presentation_scope('detailed', 'text'):
        markdown = summarize(llm, case)
    assert SOURCE in react_render([markdown])[0]
    assert len(llm.calls) == 2


def test_malformed_fence_cannot_hide_actual_html(case, react_render):
    body = '```{title="`"}\n<img src="https://invalid.test/x">\n```'
    # Actual export skips the raw HTML node; it is not an escaped code example.
    assert '&lt;img' not in react_render([body])[0]
    value = response(case, 'html')
    value['blocks'][0]['markdown'] = body
    llm, raw4 = automatic(case, value)
    with presentation_scope('detailed', 'html') as state:
        with pytest.raises(FinalLedgerError) as error:
            summarize(llm, case)
        assert error.value.code == 'invalid_block_content' and state.raw_review == raw4
    assert len(llm.calls) == 2


@pytest.mark.parametrize('depth', [25, 80])
def test_deep_uncited_container_cannot_hide_html_or_silently_skip_validation(case, depth):
    value = response(case, 'text')
    value['blocks'].append({'id':'EXTRA', 'markdown':'> ' * depth + '<img src="x">'})
    llm, raw4 = automatic(case, value)
    with presentation_scope('detailed', 'text') as state:
        with pytest.raises(FinalLedgerError) as error:
            summarize(llm, case)
        assert error.value.code == 'invalid_block_content' and state.raw_review == raw4
    assert len(llm.calls) == 2


@pytest.mark.parametrize('body', ['&#91;ASR:0001&#93;', '&#91;FRAME:0001&#93;',
                                '!&#91;image&#93;(https://invalid.test/x)'])
def test_decoded_text_does_not_escape_reserved_marker_guard(case, body):
    value = response(case, 'text')
    value['blocks'][0]['markdown'] = body
    llm, _ = automatic(case, value)
    with presentation_scope('detailed', 'text'):
        with pytest.raises(FinalLedgerError) as error:
            summarize(llm, case)
        assert error.value.code == 'invalid_block_content'


@pytest.mark.parametrize('closed', [True, False])
def test_illustrated_rejects_image_inside_cross_block_or_unclosed_code(case, closed, react_render):
    value = response(case, 'illustrated')
    value['blocks'][0]['markdown'] = '```cpp\n' + SOURCE
    if closed:
        value['blocks'].append({'id':'B2', 'markdown':'```'})
    llm, raw4 = automatic(case, value)
    with presentation_scope('detailed', 'illustrated') as state:
        with pytest.raises(FinalLedgerError) as error:
            summarize(llm, case)
        assert error.value.code == 'invalid_figure_placement'
        assert state.raw_review == raw4 and state.figures == []
    unsafe = '```cpp\n' + SOURCE + '\n\n![frame](/verified.jpg)' + ('\n\n```' if closed else '')
    assert '<img ' not in react_render([unsafe])[0]
    assert not (case.tmp_path / 'screenshots').exists() and len(llm.calls) == 2


@pytest.mark.parametrize('caption', ['Displayed type', r'C:\types\vector', 'Trailing slash\\',
                                    'A `quoted` type', 'Unmatched ` code', 'Parentheses (type)',
                                    '**strong** &amp; plain'])
def test_illustrated_real_render_emits_image_after_closed_code(case, react_render, caption):
    value = response(case, 'illustrated')
    value['blocks'][0]['markdown'] = '```cpp\n' + SOURCE + '\n```'
    value['figures'][0]['caption'] = caption
    llm, raw4 = automatic(case, value)
    with presentation_scope('detailed', 'illustrated') as state:
        body = summarize(llm, case)
        context = SimpleNamespace(task_id=str(uuid4()), task_dir=case.tmp_path,
            presentation='illustrated', video_evidence=case.evidence, presentation_figures=state.figures)
        rendered = render_presentation(None, context, body)
        assert state.raw_review == raw4
    html = react_render([rendered])[0]
    assert html.count('<img ') == 1 and html.index('</pre>') < html.index('<img ')
    assert (case.tmp_path / 'screenshots/summary-source-0.jpg').read_bytes() == case.path.read_bytes()
    assert len(llm.calls) == 2


@pytest.mark.parametrize('caption', ['Bad [bracket]', 'Bad ] bracket', 'Bad\nline',
                                    'Bad\rline', '<span>HTML</span>'])
def test_invalid_captions_are_rejected_before_projection_without_repair(case, caption):
    value = response(case, 'illustrated')
    value['figures'][0]['caption'] = caption
    llm, raw4 = automatic(case, value)
    with presentation_scope('detailed', 'illustrated') as state:
        with pytest.raises(FinalLedgerError) as error:
            summarize(llm, case)
        assert error.value.code == 'invalid_figure_caption'
        assert state.raw_review == raw4 and state.figures == []
    assert len(llm.calls) == 2


def test_multiple_figure_input_order_need_not_match_document_order(case, react_render):
    case.evidence.frames.append(copy.deepcopy(case.evidence.frames[0]))
    value = response(case, 'illustrated')
    value['blocks'].append({'id':'B2', 'markdown':'Another supported proposal.'})
    value['claims'][0]['block_ids'].append('B2')
    value['claims'][0]['evidence'].append({'kind':'frame_observation', 'source_ref':'[FRAME:0002]',
                                          'observation':'The other displayed proposal.'})
    value['figures'].insert(0, {'frame_ref':'[FRAME:0002]', 'claim_ids':['C1'],
                              'after_block_id':'B2', 'caption':'Second figure'})
    llm, _ = automatic(case, value)
    with presentation_scope('detailed', 'illustrated') as state:
        body = summarize(llm, case)
        context = SimpleNamespace(task_id=str(uuid4()), task_dir=case.tmp_path,
            presentation='illustrated', video_evidence=case.evidence, presentation_figures=state.figures)
        rendered = render_presentation(None, context, body)
    assert react_render([rendered])[0].count('<img ') == 2
    assert len(llm.calls) == 2


@pytest.mark.parametrize('presentation', ['text', 'html', 'illustrated', 'comic', 'infographic'])
@pytest.mark.parametrize('blocks, used', [
    (['[^unused]: ' + SOURCE], False),
    (['A condition[^used].', '[^used]: ' + SOURCE], True),
    (['[^unused]:', '    ' + SOURCE], False),
    ([SOURCE, '[^unused]: ' + SOURCE], False),
])
def test_footnotes_are_explicitly_unsupported_in_actual_host(case, presentation, blocks, used, react_render):
    # remark-gfm hides unused definitions; referenced ones become a separate
    # footnote section. Neither may stand in for a reviewed block/part.
    html = react_render(['\n\n'.join(blocks)])[0]
    if used:
        assert 'data-footnotes' in html and SOURCE in html
    elif blocks[0].startswith('[^unused]:'):
        assert html == ''
    else:
        assert 'data-footnotes' not in html and html.count(SOURCE) == 1
    value = response(case, presentation)
    value['blocks'] = [{'id':f'B{i+1}', 'markdown':text} for i, text in enumerate(blocks)]
    if presentation in {'comic', 'infographic'}:
        value = graphic7_fixture(value)
        assert [''.join(block['parts']) for block in value['blocks']] == blocks
    llm, raw_review = automatic(case, value)
    with presentation_scope('detailed', presentation) as state:
        with pytest.raises(FinalLedgerError) as error:
            summarize(llm, case)
        assert error.value.code == ('invalid_body_part_visibility' if presentation in {'comic', 'infographic'} else 'invalid_block_content')
        assert state.raw_review == raw_review and state.figures == [] and state.visual_review is None
        assert json.loads(raw_review)['protocol'] == (7 if presentation in {'comic', 'infographic'} else 4)
    assert len(llm.calls) == 2


@pytest.mark.parametrize('presentation', ['comic', 'infographic'])
@pytest.mark.parametrize('blocks', [
    ['[^unused]: ' + SOURCE],
    ['A condition[^used].', '[^used]: ' + SOURCE],
    ['[^unused]:', '    ' + SOURCE],
    [SOURCE, '[^unused]: ' + SOURCE],
])
def test_historical_raw4_graphic_finalizer_keeps_footnote_guard(case, presentation, blocks):
    # Historical direct validation does not represent a new expected6 model
    # operation. Keep its original raw4 response and exact rejection semantics.
    from app.llm.meeting_final_review import finalize_final_review
    from app.llm.source_references import bind_source_references
    from app.llm.video_material import bind_video_material
    value = response(case, presentation)
    value['blocks'] = [{'id': f'B{i+1}', 'markdown': text} for i, text in enumerate(blocks)]
    raw4 = json.dumps(value)
    with presentation_scope('detailed', presentation) as state, \
            bind_source_references([TranscriptSegment(0, 10, SOURCE)]), \
            bind_video_material(case.evidence, {'vision': True}):
        with pytest.raises(FinalLedgerError) as error:
            finalize_final_review(raw4, json.dumps(case.material))
        assert error.value.code == 'invalid_block_content'
        assert state.raw_review == raw4 and state.figures == [] and state.visual_review is None
        assert json.loads(state.raw_review)['protocol'] == 4


@pytest.mark.parametrize('presentation', ['comic', 'infographic'])
@pytest.mark.parametrize('blocks', [
    ['[^unused]: ' + SOURCE],
    ['A condition[^used].', '[^used]: ' + SOURCE],
    ['[^unused]:', '    ' + SOURCE],
    [SOURCE, '[^unused]: ' + SOURCE],
])
def test_historical_raw5_graphic_finalizer_keeps_footnote_guard(case, presentation, blocks):
    # Historical direct validation does not represent a new expected6 model
    # operation. Keep its original raw5 response and exact rejection semantics.
    from app.llm.meeting_final_review import finalize_final_review
    from app.llm.source_references import bind_source_references
    from app.llm.video_material import bind_video_material
    value = response(case, presentation)
    value['blocks'] = [{'id': f'B{i+1}', 'markdown': text} for i, text in enumerate(blocks)]
    value = graphic5_fixture(value)
    raw5 = json.dumps(value)
    with presentation_scope('detailed', presentation) as state, \
            bind_source_references([TranscriptSegment(0, 10, SOURCE)]), \
            bind_video_material(case.evidence, {'vision': True}):
        with pytest.raises(FinalLedgerError) as error:
            finalize_final_review(raw5, json.dumps(case.material))
        assert error.value.code == 'invalid_block_content'
        assert state.raw_review == raw5 and state.figures == [] and state.visual_review is None
        assert json.loads(state.raw_review)['protocol'] == 5


@pytest.mark.parametrize('presentation', ['text', 'html'])
@pytest.mark.parametrize('blocks, included', [
    ([r'\[^unused]: ' + SOURCE], 'B1'),
    ([r'[\^unused]: ' + SOURCE], 'B1'),
    (['`[^unused]: ' + SOURCE + '`'], 'B1'),
    (['```text\n[^unused]: ' + SOURCE + '\n```'], 'B1'),
    (['~~~text\n[^unused]: ' + SOURCE + '\n~~~'], 'B1'),
    (['```text', '[^unused]: ' + SOURCE, '```'], 'B2'),
    (['# Literal example', '    [^unused]: ' + SOURCE], 'B2'),
])
def test_escaped_and_code_footnote_literals_remain_visible_without_raw_repair(
        case, presentation, blocks, included, react_render):
    value = response(case, presentation)
    value['blocks'] = [{'id':f'B{i+1}', 'markdown':text} for i, text in enumerate(blocks)]
    value['claims'][0]['block_ids'] = [included]
    llm, raw4 = automatic(case, value)
    with presentation_scope('detailed', presentation) as state:
        markdown = summarize(llm, case)
        assert state.raw_review == raw4
        assert render_presentation(None, SimpleNamespace(presentation=presentation), markdown) == markdown
    html = react_render([markdown])[0]
    assert SOURCE in html and 'data-footnotes' not in html
    assert markdown == '\n\n'.join(blocks).strip() and len(llm.calls) == 2
