"""CommonMark/GFM structural checks; never rewrite reviewed Markdown.

Table and strikethrough rules match the report renderer's GFM constructs.
Task checkboxes and bare-URL linkification do not change code/HTML boundaries;
no renderer, plugin discovery or dynamic extension import is needed here.
"""
import re

from markdown_it import MarkdownIt


_RESERVED = re.compile(r'\[(?:ASR|FRAME):|!\[|\[\[Screenshot:')
_MAX_NESTING = 64


def _reject_footnote_inline(state, silent):
    # This protocol excludes the unescaped [^ prefix, rather than partially
    # implementing GFM footnotes. Escape/backtick rules already consumed their
    # literals before this rule; link destinations/titles are not parsed text.
    if state.src.startswith('[^', state.pos):
        raise ValueError('unsupported_footnote')
    return False


def _reject_footnote_block(state, start_line, end_line, silent):
    # Run before reference definitions can be consumed without inline tokens.
    # The parser already handled fenced/indented code and container prefixes.
    pos = state.bMarks[start_line] + state.tShift[start_line]
    if state.src.startswith('[^', pos):
        raise ValueError('unsupported_footnote')
    return False


def _parse(text):
    # remark-gfm accepts ~single~ and ~~double~~ delimiters, while runs of
    # three or more are literal. Plain-part visibility must use the same rules.
    parser = MarkdownIt('commonmark', {
        'maxNesting': _MAX_NESTING, 'strikethrough_single_tilde': True,
    }).enable(['table', 'strikethrough'])
    parser.block.ruler.before('reference', 'reject_footnote', _reject_footnote_block)
    parser.inline.ruler.before('link', 'reject_footnote', _reject_footnote_inline)
    try:
        tokens = parser.parse(text)
    except RecursionError:
        raise ValueError('excessive_markdown_nesting') from None
    # The parser otherwise silently skips content at its nesting ceiling. An
    # incomplete parse cannot authorize HTML/resource or visibility checks.
    if any(token.level >= _MAX_NESTING - 1 for token in _walk(tokens)):
        raise ValueError('excessive_markdown_nesting')
    return tokens


def _walk(tokens):
    for token in tokens:
        yield token
        yield from _walk(token.children or [])


def inspect_report(blocks):
    """Return IDs with visible text in the *joined* report, not isolated blocks.

    Maps come from the parser: definitions and fence delimiters contribute no
    visible text. This checks visibility only, never semantic entailment.
    """
    parts = [row['markdown'] for row in blocks]
    parts[0] = parts[0].lstrip()
    parts[-1] = parts[-1].rstrip()
    parts = [part.replace('\r\n', '\n').replace('\r', '\n') for part in parts]
    text = '\n\n'.join(parts)
    tokens = _parse(text)
    for token in _walk(tokens):
        if token.type in {'html_inline', 'html_block', 'image'}:
            raise ValueError('raw_html_or_image')
        if token.type in {'text', 'code_inline', 'code_block', 'fence'} and _RESERVED.search(token.content):
            raise ValueError('reserved_report_marker')
    lines = text.split('\n')
    visible_lines = set()
    for token in tokens:
        if token.type == 'inline' and token.map:
            if any(child.type in {'text', 'code_inline'} and child.content.strip()
                   for child in _walk(token.children or [])):
                visible_lines.update(range(*token.map))
        elif token.type in {'fence', 'code_block'} and token.map:
            start = token.map[0] + (token.type == 'fence')
            visible_lines.update(start + index for index, line in enumerate(token.content.split('\n'))
                                 if line.strip())
    offsets, position = [], 0
    for line in lines:
        offsets.append((position, position + len(line)))
        position += len(line) + 1
    visible, position = set(), 0
    for row, part in zip(blocks, parts):
        end = position + len(part)
        if any(position < offsets[line][1] and offsets[line][0] < end
               for line in visible_lines):
            visible.add(row['id'])
        position = end + 2
    return visible


def figure_markdown(caption, timestamp, url):
    """Exact syntax shared by validation and the existing screenshot renderer."""
    label = f'{caption} · 原视频 {int(timestamp) // 60:02d}:{int(timestamp) % 60:02d}'
    return f'![{label}]({url})'


def figures_are_images(markdown, figures):
    """Check each exact insertion position by parsing a detached image projection.

    Only the existing renderer may emit the actual screenshot URLs. This probe
    has the same image syntax/alt suffix, and cannot move a figure or fix prose.
    """
    projected, expected = markdown, []
    for index, figure in enumerate(figures):
        target = f'/__vinote_figure_check_{index}.jpg'
        # Timestamp digits and the contained task URL add no Markdown syntax;
        # use the actual caption and the renderer's exact construction.
        image = figure_markdown(figure['caption'], 0, target)
        projected = projected.replace(figure['frame_ref'], image, 1)
        expected.append(target)
    actual = [token.attrGet('src') for token in _walk(_parse(projected)) if token.type == 'image']
    return sorted(actual) == sorted(expected)
