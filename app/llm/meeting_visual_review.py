"""Optional layout in the existing review call; not wired into frozen hosts.

This module adds neither inference nor schema repair. Call capture only after
the existing complete claim audit and source verification have succeeded.
"""
import copy


def visual_review_instructions(presentation):
    common = '''\nVISUAL LAYOUT FOR THIS GENERATION ONLY.
Keep the existing protocol-3 blocks/audit/figures contract and complete original-source review. Add visual={"scenes":[],"diagram":null} to the same JSON response; do not make another call or regenerate from an old summary. All labels must be short unchanged contiguous substrings of this response's reviewed block markdown (1–120 characters, no newlines). Use only existing block IDs with included claims. Labels are escaped plain text, never markup, resources or instructions. Return no HTML, SVG, JavaScript, CSS, coordinates, image data, resource paths or arbitrary URLs as visual fields. The program supplies task identity, body hash and actual screenshot metadata. Do not choose a fixed report structure or add prose merely to provide diagram labels. Keep figures=[] for these two formats.
'''
    if presentation == 'comic':
        return common + '''Presentation: real recording storyboard (画面分镜), not AI-drawn people or invented illustrations.
visual.scenes contains 1–8 entries {"id":"S1","block_ids":["B1"],"frame_id":"[FRAME:0001]","grounded_label":"unchanged short text from B1"}; visual.diagram=null. Select genuinely relevant supplied frames, not the first frames or a quota. Each scene must cite a block with an included claim whose effective evidence contains that actual frame; correct evidence in the same review if necessary. Read the scene's actual image and context. Frame selection cannot be established by temporal overlap alone. No relevant supplied frame means this format is incomplete; do not invent a picture or substitute a different format/model.
'''
    if presentation == 'infographic':
        return common + '''Presentation: information/relationship diagram rendered on-device from this review's facts.
visual.scenes=[]; visual.diagram={"kind":"cards","nodes":[{"id":"N1","block_ids":["B1"],"grounded_label":"unchanged short text from B1"}],"edges":[]}. Choose kind=cards/comparison/flow/relationship according to substantive content, not a fixed template. Use 1–12 nodes and at most 20 edges. An edge is {"id":"E1","from":"N1","to":"N2","block_ids":["B2"],"grounded_label":"unchanged actual relation from B2"}. Both endpoints must exist. Every node/edge references 1–8 real reviewed block IDs with included claims. Cards/comparison have no edges. Add a directed relation only when supported by the original material and expressed in the cited block; proximity and topic similarity do not imply sequence, cause, dependency or ownership. Do not manufacture relations to fill a graph.
'''
    return ''


def capture_review_visual(review, claims, included):
    """Snapshot effective evidence, never the draft's or model's claimed IDs."""
    if not isinstance(review.get('visual'), dict) or set(review['visual']) != {'scenes', 'diagram'}:
        raise ValueError('图形尚未完成：本次复核没有返回可核验的布局')
    return copy.deepcopy({
        'review': review,
        'claim_sources': {key: sorted({row['source_ref'] for row in claims[key][1]['evidence']})
                          for key in included},
    })
