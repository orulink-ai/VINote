"""Optional layout in the existing review call; not wired into frozen hosts.

This module adds neither inference nor schema repair. Call capture only after
the existing complete claim audit and source verification have succeeded.
"""
import copy


def visual_review_instructions(presentation, *, protocol=3):
    if type(protocol) is int and protocol == 5:
        if presentation not in {'comic', 'infographic'}:
            raise ValueError('Unsupported visual review protocol')
        from app.llm.meeting_visual_projection import PARTS_RULE, COMIC_RULE, INFO_RULE
        return '\n' + PARTS_RULE + '\n' + (COMIC_RULE if presentation == 'comic' else INFO_RULE)
    common = '''\nVISUAL LAYOUT FOR THIS GENERATION ONLY.
Keep the existing protocol-3 blocks/audit/figures contract and complete original-source review. Add visual={"scenes":[],"diagram":null} to the same JSON response; do not make another call or regenerate from an old summary. All labels must be short unchanged contiguous substrings of this response's reviewed block markdown (1–120 characters, no newlines). Use only existing block IDs with included claims. Labels are escaped plain text, never markup, resources or instructions. Return no HTML, SVG, JavaScript, CSS, coordinates, image data, resource paths or arbitrary URLs as visual fields. The program supplies task identity, body hash and actual screenshot metadata. Do not choose a fixed report structure or add prose merely to provide diagram labels. Keep figures=[] for these two formats.
'''
    if protocol == 4:
        common = common.replace('protocol-3 blocks/audit/figures contract', 'protocol-4 blocks/claims/visual contract')
        common = common.replace('Keep figures=[] for these two formats.', 'Do not output a figures field for these two formats.')
    elif protocol != 3:
        raise ValueError('Unsupported visual review protocol')
    if presentation == 'comic':
        return common + '''Presentation: real recording storyboard (画面分镜), not AI-drawn people or invented illustrations.
visual.scenes contains 1–8 entries {"id":"S1","block_ids":["B1"],"frame_id":"[FRAME:0001]","grounded_label":"unchanged short text from B1"}; visual.diagram=null. Select genuinely relevant supplied frames, not the first frames or a quota. Each scene must cite a block with an included claim whose effective evidence contains that actual frame; correct evidence in the same review if necessary. Read the scene's actual image and context. Frame selection cannot be established by temporal overlap alone. No relevant supplied frame means this format is incomplete; do not invent a picture or substitute a different format/model.
'''
    if presentation == 'infographic':
        return common + '''Presentation: information/relationship diagram rendered on-device from this review's facts.
visual.scenes=[]; visual.diagram={"kind":"cards","nodes":[{"id":"N1","block_ids":["B1"],"grounded_label":"unchanged short text from B1"}],"edges":[]}. Choose kind=cards/comparison/flow/relationship according to substantive content, not a fixed template. Use 1–12 nodes and at most 20 edges. An edge is {"id":"E1","from":"N1","to":"N2","block_ids":["B2"],"grounded_label":"unchanged actual relation from B2"}. Both endpoints must exist. Every node/edge references 1–8 real reviewed block IDs with included claims. Cards/comparison have no edges. Add a directed relation only when supported by the original material and expressed in the cited block; proximity and topic similarity do not imply sequence, cause, dependency or ownership. Do not manufacture relations to fill a graph.
Select the smallest source-supported structure that explains an important relationship, compares meaningful alternatives, or follows an explicit process. It may focus on one substantive question, not every report section. Choose the kind after selecting facts: comparison for alternatives with meaningful common dimensions, flow for explicit ordered stages, relationship for concrete objects with named connections, cards for independently useful facts without established connections. Preserve each object's value/unit, scope, conditions and proposal/confirmed status.
Select self-contained unchanged excerpts naming objects and essential attributes in cards/comparison nodes. Never split an object and its values across independent nodes; omit unsuitable excerpts rather than expand prose. For every edge check the complete source -> relation -> target proposition, including direction, conditions and status, against the original evidence and cited reviewed text. Flow/relationship needs a supported edge; if none is established, choose cards/comparison instead, never invent an edge to satisfy the shape. Check that the diagram communicates substantive information beyond a table of contents. Remove redundant nodes; omit a fact from the diagram rather than shorten away its essential qualifier to meet label limits.
'''
    return ''


def capture_review_visual(review, claims, included):
    """Snapshot effective evidence, never the draft's or model's claimed IDs."""
    fifth = type(review.get('protocol')) is int and review['protocol'] == 5
    expected = {'protocol', 'scenes', 'diagram'} if fifth else {'scenes', 'diagram'}
    if not isinstance(review.get('visual'), dict) or set(review['visual']) != expected:
        raise ValueError('图形尚未完成：本次复核没有返回可核验的布局')
    final = type(review.get('protocol')) is int and review['protocol'] in (4, 5)
    sources = {}
    for key in included:
        claim = claims[key] if final else claims[key][1]
        sources[key] = sorted({row['source_ref'] for row in claim['evidence']})
    return copy.deepcopy({
        'review': review,
        'claim_sources': sources,
    })
