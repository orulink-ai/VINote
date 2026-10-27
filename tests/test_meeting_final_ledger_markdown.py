"""Markdown-aware raw HTML guard through the production draft3/review4 host."""
import json

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_presentation import presentation_scope
from app.llm.openai_llm import _BasePromptLLM
from app.llm.source_references import capture_working_draft
from app.models.transcript import TranscriptSegment


SOURCE = 'Use std::vector<int> as a proposal; the type is not a confirmed decision.'


def host(blocks, presentation):
    material = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic type proposal'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'attribute', 'text': SOURCE, 'material': True,
         'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': SOURCE}]}]}
    review = {'protocol': 4, 'blocks': [{'id': f'B{i}', 'markdown': text} for i, text in enumerate(blocks)],
        'claims': [{'id': 'C1', 'field': 'attribute', 'text': SOURCE, 'material': True,
                    'disposition': 'included', 'block_ids': ['B0'],
                    'evidence': material['claims'][0]['evidence']}]}
    raw3, raw4 = json.dumps(material, indent=2), json.dumps(review, indent=2)

    class Automatic(_BasePromptLLM):
        def __init__(self): self.calls = []

        def _complete(self, **prompts):
            self.calls.append(prompts)
            assert len(self.calls) <= 2, 'No repair call or replay'
            assert SOURCE in prompts['user_prompt']
            return raw3 if len(self.calls) == 1 else raw4

    return Automatic(), raw3, raw4


@pytest.mark.parametrize('presentation', ['text', 'html'])
@pytest.mark.parametrize('blocks', [
    ['Use `std::vector<int>` as a proposal.'],
    ['Use ``std::vector<int> and `quoted` `` as a proposal.'],
    ['Use `std::vector<int>\nand <Widget>` as a proposal.'],
    ['```cpp\nstd::vector<int> candidate;\n```'],
    ['~~~~cpp\nstd::vector<int> candidate;\n~~~~'],
    ['# Type proposal', '    std::vector<int> candidate;'],
    ['# Type proposal', '```cpp', 'std::vector<int> candidate;', '```'],
    ['```html\n<script>literal example only</script>\n```'],
    ['Entity literal &lt;Widget&gt; remains visible.'],
    [r'Use \<Widget> as the literal type.'],
    ['```cpp\nstd::vector<int> candidate;\n````'],
    ['```cpp\nstd::vector<int> candidate;'],
    ['See <https://example.org/types> for the proposal.'],
])
def test_actual_host_preserves_code_literals_and_raw_review(blocks, presentation):
    automatic, raw3, raw4 = host(blocks, presentation)
    observed = []
    with presentation_scope('detailed', presentation) as state, capture_working_draft(observed.append):
        result = automatic.summarize('Synthetic proposal', [TranscriptSegment(0, 5, SOURCE)], style='meeting')
        assert state.raw_review == raw4
    assert result == '\n\n'.join(blocks).strip()
    assert len(automatic.calls) == 2 and observed == [raw3]


@pytest.mark.parametrize('presentation', ['text', 'html'])
@pytest.mark.parametrize('blocks', [
    ['Use <span>this type</span> as a proposal.'],
    ['<div>raw HTML block</div>'],
    ['<script>alert(1)</script>'],
    ['<!-- raw HTML comment -->'],
    ['Use `std::vector<int>`.', '<iframe src="https://invalid.test"></iframe>'],
    ['```cpp\nstd::vector<int> candidate;\n```', 'Then <b>raw HTML</b>.'],
    ['```cpp', 'std::vector<int> candidate;', '```', '<img src="https://invalid.test/x">'],
    ['An unmatched ` does not protect <span>HTML</span>.'],
    ['```{title="`"}\n<img src="https://invalid.test/x">\n```'],
    ['<div', 'data-mode="raw">HTML across blocks</div>'],
])
def test_actual_host_still_rejects_genuine_html_and_misleading_code_delimiters(blocks, presentation):
    automatic, _, raw4 = host(blocks, presentation)
    with presentation_scope('detailed', presentation) as state:
        with pytest.raises(FinalLedgerError) as error:
            automatic.summarize('Synthetic proposal', [TranscriptSegment(0, 5, SOURCE)], style='meeting')
        assert error.value.code == 'invalid_block_content'
        assert state.raw_review == raw4 and state.figures == [] and state.visual_review is None
    assert len(automatic.calls) == 2


@pytest.mark.parametrize('guarded', ['[ASR:0001]', '[FRAME:0001]', '![image](https://invalid.test/x)',
                                   '[[Screenshot:00:01]]'])
@pytest.mark.parametrize('wrapper', ['`{}`', '```text\n{}\n```', '    {}'])
def test_code_regions_do_not_escape_source_id_or_image_guards(guarded, wrapper):
    automatic, _, raw4 = host([wrapper.format(guarded)], 'text')
    with presentation_scope('detailed', 'text') as state:
        with pytest.raises(FinalLedgerError) as error:
            automatic.summarize('Synthetic proposal', [TranscriptSegment(0, 5, SOURCE)], style='meeting')
        assert error.value.code == 'invalid_block_content' and state.raw_review == raw4
    assert len(automatic.calls) == 2
