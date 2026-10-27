"""Actual offline Pillow PNGs, complete semantics and hostile-input budgets."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
import json
import socket
import subprocess
import sys
from types import FunctionType
import unicodedata
from uuid import uuid4

from PIL import Image, ImageChops
import pytest

from app.services import summary_visual_png as png

_PYTHON_RUN = subprocess.run
_PYTHON_POPEN = subprocess.Popen


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Renderer must never use network, subprocess or provider')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)


def frame_bytes(width=320, height=180, fmt='JPEG'):
    image = Image.new('RGB', (width, height), '#2244cc')
    # Opposing corners prove the original was contained, rather than cropped.
    for box, color in [((0, 0, width // 3, height // 3), '#ff0000'),
                       ((2 * width // 3, 2 * height // 3, width, height), '#00ff00')]:
        image.paste(color, box)
    stream = BytesIO()
    image.save(stream, fmt)
    return stream.getvalue()


def wire(kind='comic', *, scenes=2, nodes=3, labels=None, edges=None):
    value = dict(visual_protocol=1, task_id=str(uuid4()), presentation='comic' if kind == 'comic' else 'infographic',
                 body_sha256='a' * 64, blocks=[], frames=[], scenes=[], diagram=None)

    def block(label, number):
        key = f'B{number}'
        value['blocks'].append(dict(id=key, text=label, claim_ids=[f'C{number}']))
        return [key]

    if kind == 'comic':
        for index in range(scenes):
            label = labels[index] if labels else f'画面 {index + 1}：保持设备 A 关闭，等待确认后再执行。'
            refs = block(label, index)
            value['frames'].append(dict(id=f'F{index}', screenshot_index=index,
                timestamp_seconds=[61.25, 0.125, 3671.5, 2, 3, 4, 5, 6][index], grounded_label=label))
            value['scenes'].append(dict(id=f'S{index}', block_ids=refs, frame_id=f'F{index}', grounded_label=label))
    else:
        rows = []
        for index in range(nodes):
            label = labels[index] if labels else f'设备 {index + 1}：保留条件与范围。'
            rows.append(dict(id=f'N{index}', block_ids=block(label, index), grounded_label=label))
        links = []
        for index, (start, end, label) in enumerate(edges or []):
            links.append(dict(id=f'E{index}', **{'from': f'N{start}', 'to': f'N{end}'},
                              block_ids=block(label, index + nodes), grounded_label=label))
        value['diagram'] = dict(kind=kind, nodes=rows, edges=links)
    return value


def pictures(value, fmt='JPEG'):
    return {row['id']: frame_bytes(fmt=fmt) for row in value['frames']}


def render(value, **kwargs):
    return png.render_summary_visual_png(value, pictures(value), title='会议纪要：已保存图形', **kwargs)


def visible_lines(result, ref):
    return ''.join(run.text for page in result.pages for run in page.text_runs if run.semantic_ref == ref)


def assert_real_pages(result):
    assert result.pages and len(result.fingerprint) == 64
    for page in result.pages:
        assert page.png_bytes.startswith(b'\x89PNG\r\n\x1a\n')
        assert sha256(page.png_bytes).hexdigest() == page.sha256
        with Image.open(BytesIO(page.png_bytes)) as image:
            assert image.format == 'PNG' and image.size == (page.width, page.height)
            image.load()
            assert ImageChops.difference(image.convert('RGB'), Image.new('RGB', image.size, 'white')).getbbox()
            for run in page.text_runs:
                assert 0 <= run.x <= page.width - run.width
                assert 0 <= run.y <= page.height - run.height
                if run.text.strip():
                    region = image.crop((run.x, run.y, run.x + run.width, run.y + run.height)).convert('RGB')
                    assert region.getextrema() != ((255, 255),) * 3, run
            for route in page.edge_routes:
                assert all(0 <= x < page.width and 0 <= y < page.height for x, y in (*route.points, *route.arrow))


@pytest.mark.parametrize('fmt', ['JPEG', 'PNG'])
def test_actual_scene_frames_full_captions_precise_times_and_input_order(tmp_path, fmt):
    value = wire(scenes=3, labels=['先核对输入，不代表已获同意。', '时间较早但仍按分镜顺序。', '最后条件必须完整保留。'])
    source = pictures(value, fmt)
    before = deepcopy(value), dict(source)
    result = png.render_summary_visual_png(value, source, title='画面分镜真实离线闭环')
    assert_real_pages(result)
    assert [item.id for item in result.semantic_order] == ['S0', 'S1', 'S2']
    assert [item.frame_id for item in result.semantic_order] == ['F0', 'F1', 'F2']
    assert [item.timestamp_seconds for item in result.semantic_order] == [61.25, 0.125, 3671.5]
    for index, scene in enumerate(value['scenes']):
        assert scene['grounded_label'] in visible_lines(result, f'scene:S{index}')
    all_text = ''.join(run.text for page in result.pages for run in page.text_runs)
    assert '00:01:01.25' in all_text and '00:00:00.125' in all_text and '01:01:11.5' in all_text
    # Both opposing original corner colors must survive in the actual PNG.
    with Image.open(BytesIO(result.pages[0].png_bytes)) as image:
        colors = image.getdata()
        assert any(r > 200 and g < 60 and b < 60 for r, g, b in colors)
        assert any(g > 180 and r < 80 and b < 80 for r, g, b in colors)
    assert value == before[0] and source == before[1]
    (tmp_path / f'comic-{fmt}.png').write_bytes(result.pages[0].png_bytes)


def test_scene_pagination_preserves_all_eight_scenes_without_duplication():
    value = wire(scenes=8, labels=['条件甲乙丙丁' * 20 for _ in range(8)])
    result = render(value, limits=replace(png.DEFAULT_LIMITS, page_height=1500))
    assert 2 <= len(result.pages) <= 16
    assert [ref for page in result.pages for ref in page.semantic_refs] == [f'scene:S{i}' for i in range(8)]
    for index in range(8):
        assert value['scenes'][index]['grounded_label'] in visible_lines(result, f'scene:S{index}')
    assert_real_pages(result)


@pytest.mark.parametrize('kind', ['cards', 'comparison'])
def test_all_cards_and_comparison_nodes_have_full_labels_and_real_pixels(kind):
    value = wire(kind, nodes=12, labels=[f'{i}：' + '完整中文条件不可省略' * 11 for i in range(12)])
    result = render(value, limits=replace(png.DEFAULT_LIMITS, page_height=1200))
    assert_real_pages(result)
    assert len(result.pages) > 1
    assert [item.id for item in result.semantic_order] == [f'N{i}' for i in range(12)]
    for index, node in enumerate(value['diagram']['nodes']):
        assert node['grounded_label'] in visible_lines(result, f'node:N{index}')
    assert not any(page.edge_routes for page in result.pages)


@pytest.mark.parametrize('kind', ['flow', 'relationship'])
def test_cycles_self_loops_parallel_and_reverse_edges_are_drawn_and_fully_explained(tmp_path, kind):
    edges = [(0, 1, '条件通过才允许继续'), (0, 1, '并行关系不可合并'), (1, 0, '反向反馈不是同一条边'),
             (0, 0, '设备自身复核'), (1, 2, '保留范围限制'), (2, 0, '形成闭环仍保持方向')]
    value = wire(kind, edges=edges)
    before = deepcopy(value)
    result = render(value)
    assert_real_pages(result)
    routes = [route for page in result.pages for route in page.edge_routes]
    assert [route.id for route in routes] == [f'E{i}' for i in range(len(edges))]
    assert len({route.points for route in routes}) == len(edges)
    assert routes[3].from_id == routes[3].to_id == 'N0'
    for index, route in enumerate(routes):
        assert (route.from_id, route.to_id) == (f'N{edges[index][0]}', f'N{edges[index][1]}')
        assert route.arrow[0] == route.points[-1]
        assert route.arrow[1][0] > route.arrow[0][0]  # Arrow points into the target's right boundary.
        assert edges[index][2] in visible_lines(result, f'edge:E{index}')
    assert [item.kind for item in result.semantic_order] == ['node'] * 3 + ['edge'] * 6
    assert value == before
    (tmp_path / f'{kind}.png').write_bytes(result.pages[0].png_bytes)


def test_maximum_graph_and_long_legends_paginate_without_dropping_any_edge(tmp_path):
    label = '原文条件范围尚待核验' * 10
    edges = [(i % 12, (i + 1) % 12, f'{i}：' + label) for i in range(20)]
    value = wire('relationship', nodes=12, labels=[f'{i}：' + label for i in range(12)], edges=edges)
    result = render(value)
    assert_real_pages(result)
    assert len(result.pages) >= 2
    assert len(result.semantic_order) == 32
    assert len([route for page in result.pages for route in page.edge_routes]) == 20
    for index, edge in enumerate(value['diagram']['edges']):
        text = visible_lines(result, f'edge:E{index}')
        assert edge['grounded_label'] in text
        assert value['diagram']['nodes'][index % 12]['grounded_label'] in text
    for index, page in enumerate(result.pages):
        (tmp_path / f'max-graph-{index}.png').write_bytes(page.png_bytes)
    # A full legend that fits a fresh page must not start at one page's foot
    # and continue without its number at the next page's head.
    for index in range(20):
        legend_pages = [page for page in result.pages if any(
            run.semantic_ref == f'edge:E{index}' and len(run.text) > 2 for run in page.text_runs)]
        assert len(legend_pages) == 1


def test_twenty_self_loops_have_distinct_ports_and_visible_numbered_arrows():
    value = wire('flow', nodes=1, edges=[(0, 0, f'复核关系 {i}') for i in range(20)])
    result = render(value)
    assert_real_pages(result)
    routes = [route for page in result.pages for route in page.edge_routes]
    assert len(routes) == 20 and len({route.points for route in routes}) == 20
    assert len({route.points[0] for route in routes}) == 20
    assert len({route.points[-1] for route in routes}) == 20


def test_maximum_chinese_nodes_and_twenty_self_loops_still_fit_default_graph_budget():
    value = wire('relationship', nodes=12, labels=['条件' * 60 for _ in range(12)],
                 edges=[(0, 0, f'自身复核条件 {i}') for i in range(20)])
    result = render(value)
    assert_real_pages(result)
    assert len(result.semantic_order) == 32
    assert sum(len(page.edge_routes) for page in result.pages) == 20
    for index in range(12):
        assert '条件' * 60 in visible_lines(result, f'node:N{index}')


def test_flow_uses_existing_edges_without_changing_source_node_or_semantic_order():
    value = wire('flow', nodes=3, edges=[(2, 1, '已有条件甲'), (1, 0, '已有条件乙')])
    before = deepcopy(value)
    result = render(value)
    assert value == before
    assert [item.id for item in result.semantic_order[:3]] == ['N0', 'N1', 'N2']
    positions = {ref: min(run.y for page in result.pages for run in page.text_runs if run.semantic_ref == ref)
                 for ref in ('node:N0', 'node:N1', 'node:N2')}
    assert positions['node:N2'] < positions['node:N1'] < positions['node:N0']
    assert_real_pages(result)


def test_source_title_line_breaks_and_numeric_conditions_are_never_ellipsized():
    value = wire('cards', nodes=1, labels=['只有 AM12345 在 06:30 前且金额 1000.50 元时才执行。'])
    title = ('完整标题' * 45) + '\n保留换行与最后条件'
    result = png.render_summary_visual_png(value, {}, title=title)
    runs = [run.text for page in result.pages for run in page.text_runs if run.font_size == 40]
    assert ''.join(runs) == title.replace('\n', '')
    assert value['diagram']['nodes'][0]['grounded_label'] in visible_lines(result, 'node:N0')
    assert_real_pages(result)


def test_explicit_title_newline_is_not_rebalanced_as_a_soft_wrap():
    result = png.render_summary_visual_png(wire('cards', nodes=1), {}, title='标题多行\n好')
    assert [run.text for page in result.pages for run in page.text_runs
            if run.font_size == 40] == ['标题多行', '好']


def test_fingerprints_bind_font_engine_source_title_frames_limits_and_page_bytes():
    value = wire(scenes=1)
    result = render(value)
    again = render(value)
    assert result == again
    identity = png.renderer_identity()
    assert result.renderer_identity == identity
    assert identity['font_sha256'] == png.FONT_SHA256
    assert sha256(png._FONT_PATH.read_bytes()).hexdigest() == png.FONT_SHA256
    assert identity['layout_engine'] == 'Pillow BASIC'
    assert png.render_summary_visual_png(value, pictures(value), title='另一个已保存标题').fingerprint != result.fingerprint
    changed = pictures(value)
    changed['F0'] = frame_bytes(fmt='PNG')
    assert png.render_summary_visual_png(value, changed, title='会议纪要：已保存图形').fingerprint != result.fingerprint
    assert render(value, limits=replace(png.DEFAULT_LIMITS, max_pages=15)).fingerprint != result.fingerprint
    copy = result.renderer_identity
    copy['font_sha256'] = 'bad'
    assert result.renderer_identity == identity
    with pytest.raises(FrozenInstanceError):
        result.pages[0].width = 10


@pytest.mark.parametrize('damage', ['missing', 'extra', 'path_key', 'url_bytes', 'corrupt', 'truncated', 'large', 'animated'])
def test_frame_bytes_are_exactly_bound_decoded_and_bounded(damage):
    value = wire(scenes=1)
    data = pictures(value)
    if damage == 'missing':
        data.clear()
    elif damage == 'extra':
        data['foreign-frame'] = data['F0']
    elif damage == 'path_key':
        data['/tmp/arbitrary.png'] = data.pop('F0')
    elif damage == 'url_bytes':
        data['F0'] = 'https://example.invalid/secret.png'
    elif damage == 'corrupt':
        data['F0'] = b'<svg onload="evil()">not a raster</svg>'
    elif damage == 'truncated':
        data['F0'] = data['F0'][:200]
    elif damage == 'large':
        data['F0'] = b'x' * (png.DEFAULT_LIMITS.max_frame_bytes + 1)
    else:
        stream = BytesIO()
        Image.new('RGB', (32, 24), 'red').save(stream, 'PNG', save_all=True,
            append_images=[Image.new('RGB', (32, 24), 'blue')])
        data['F0'] = stream.getvalue()
    with pytest.raises(png.SummaryVisualPngError):
        png.render_summary_visual_png(value, data, title='测试')


@pytest.mark.parametrize('limits,code', [
    (dict(max_pages=1, page_height=1500), 'page_budget'),
    (dict(max_page_bytes=100), 'png_byte_budget'),
    (dict(max_total_bytes=100), 'png_byte_budget'),
    (dict(max_page_pixels=100), 'pixel_budget'),
    (dict(max_total_pixels=100), 'pixel_budget'),
    (dict(max_frame_pixels=100), 'frame_pixel_budget'),
    (dict(max_frame_bytes=100), 'frame_byte_budget'),
    (dict(max_total_frame_bytes=100), 'frame_byte_budget'),
    (dict(max_pages=17), 'invalid_limits'),
    (dict(page_height=999999), 'invalid_limits'),
    (dict(max_pages=True), 'invalid_limits'),
])
def test_resource_limits_fail_without_partial_result(limits, code):
    with pytest.raises(png.SummaryVisualPngError) as error:
        render(wire(scenes=8), limits=replace(png.DEFAULT_LIMITS, **limits))
    assert error.value.code == code


@pytest.mark.parametrize('change', [
    lambda v: v.update(visual_protocol=True),
    lambda v: v.update(body_sha256='unknown'),
    lambda v: v.update(resource='/etc/passwd'),
    lambda v: v['scenes'][0].update(grounded_label='无原文依据'),
    lambda v: v['scenes'][0].update(frame_id='foreign'),
    lambda v: v['frames'][0].update(timestamp_seconds=float('nan')),
    lambda v: v['frames'][0].update(screenshot_index=True),
    lambda v: v['frames'][0].update(timestamp_seconds=10 ** 400),
])
def test_invalid_wire_cannot_become_a_complete_graphic(change):
    value = wire(scenes=1)
    change(value)
    with pytest.raises(png.SummaryVisualPngError):
        png.render_summary_visual_png(value, {'F0': frame_bytes()}, title='测试')


def test_literals_are_raster_text_not_markup_and_unknown_glyphs_fail_explicitly():
    label = '<svg onload="evil()"> http://example.test A < B'
    value = wire('cards', nodes=1, labels=[label])
    result = render(value)
    assert label in visible_lines(result, 'node:N0')
    assert_real_pages(result)
    bad = wire('cards', nodes=1, labels=['不存在的字形\U0010ffff'])
    with pytest.raises(png.SummaryVisualPngError) as error:
        render(bad)
    assert error.value.code == 'unsupported_glyph'


def test_combining_marks_and_ascii_identifiers_are_not_lost_at_wrap_boundaries():
    label = '名称 cafe\u0301，完整条件 ' + 'AB12345-06:30/' * 6
    value = wire('comparison', nodes=1, labels=[label])
    result = render(value)
    assert label in visible_lines(result, 'node:N0')
    assert not any(run.text and unicodedata.combining(run.text[0]) for page in result.pages for run in page.text_runs)
    assert_real_pages(result)


def test_last_listed_name_does_not_leave_a_single_character_final_line():
    label = '「22-25打黑客松」标注叶棕竣、阳晓冰、邵宇'
    value = wire('cards', nodes=1, labels=[label])
    result = render(value)
    runs = [run.text for page in result.pages for run in page.text_runs
            if run.semantic_ref == 'node:N0' and run.font_size == 30]
    assert ''.join(runs) == label and any('邵宇' in line for line in runs)
    assert not any(line == '宇' for line in runs)


def test_transparent_frame_is_composited_on_white_without_exposing_hidden_rgb():
    value = wire(scenes=1)
    source = Image.new('RGBA', (320, 180), (250, 0, 250, 0))
    stream = BytesIO()
    source.save(stream, 'PNG')
    result = png.render_summary_visual_png(value, {'F0': stream.getvalue()}, title='透明原图')
    with Image.open(BytesIO(result.pages[0].png_bytes)) as image:
        assert not any(r > 200 and b > 200 and g < 40 for r, g, b in image.getdata())
    assert_real_pages(result)


def test_renderer_only_reads_the_fixed_font_and_performs_no_file_writes(monkeypatch):
    value = wire('cards', nodes=1)
    original = Path.open
    reads = []

    def confined(path, mode='r', *args, **kwargs):
        assert path == png._FONT_PATH and mode == 'rb', (path, mode)
        reads.append(path)
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', confined)
    png._font_bytes.cache_clear()
    result = render(value)
    assert reads == [png._FONT_PATH]
    assert_real_pages(result)


def test_wrong_font_hash_never_falls_back_to_system_font(monkeypatch):
    png._font_bytes.cache_clear()
    original = Path.open

    def altered(path, mode='r', *args, **kwargs):
        return BytesIO(b'wrong font') if path == png._FONT_PATH else original(path, mode, *args, **kwargs)

    with monkeypatch.context() as current:
        current.setattr(Path, 'open', altered)
        with pytest.raises(png.SummaryVisualPngError) as error:
            png.renderer_identity()
        assert error.value.code == 'font_hash_mismatch'
    png._font_bytes.cache_clear()


def test_missing_font_fails_explicitly_even_when_system_fonts_exist(monkeypatch):
    png._font_bytes.cache_clear()
    original = Path.open

    def missing(path, mode='r', *args, **kwargs):
        if path == png._FONT_PATH:
            raise FileNotFoundError('fixed resource missing')
        return original(path, mode, *args, **kwargs)

    with monkeypatch.context() as current:
        current.setattr(Path, 'open', missing)
        with pytest.raises(png.SummaryVisualPngError) as error:
            render(wire('cards', nodes=1))
        assert error.value.code == 'font_unavailable'
    png._font_bytes.cache_clear()


def test_desktop_package_includes_fixed_font_and_license_without_app_submodule_dependency():
    root = Path(__file__).resolve().parents[1]
    build = (root / 'scripts/build-desktop.mjs').read_text(encoding='utf-8')
    assert "join(root, 'app/resources/fonts')" in build
    assert 'app/resources/fonts' in build and 'SIL OPEN FONT LICENSE' in (
        root / 'app/resources/fonts/OFL.txt').read_text(encoding='utf-8')
    assert 'VINote-app' not in str(png._FONT_PATH)


@pytest.mark.parametrize('name', png._IDENTITY_FUNCTION_NAMES)
def test_every_loaded_local_function_change_is_detected_without_version_bump(monkeypatch, name):
    before = png.renderer_identity()
    function = getattr(png, name)
    function = getattr(function, '__wrapped__', function)
    changed = function.__code__.replace(co_consts=(*function.__code__.co_consts, 'review-code-change'))
    monkeypatch.setattr(function, '__code__', changed)
    after = png.renderer_identity()
    assert after['renderer_version'] == before['renderer_version']
    assert after['implementation_sha256'] != before['implementation_sha256']
    assert after['fingerprint'] != before['fingerprint']


@pytest.mark.parametrize('name', ['line', 'text', 'ensure', 'seal', 'new_page', '__init__'])
def test_loaded_drawing_class_method_changes_identity(monkeypatch, name):
    before = png.renderer_identity()
    function = getattr(png._Document, name)
    monkeypatch.setattr(function, '__code__', function.__code__.replace(
        co_consts=(*function.__code__.co_consts, 'review-method-change')))
    assert png.renderer_identity()['implementation_sha256'] != before['implementation_sha256']


@pytest.mark.parametrize('name,value', [('_MARGIN', 49), ('_FOREGROUND', '#18181a'),
    ('_EDGE_COLORS', ('#000000',)), ('DEFAULT_LIMITS', replace(png.DEFAULT_LIMITS, max_pages=15))])
def test_live_immutable_output_constants_and_limits_change_identity(monkeypatch, name, value):
    before = png.renderer_identity()
    monkeypatch.setattr(png, name, value)
    assert png.renderer_identity()['implementation_sha256'] != before['implementation_sha256']


def test_property_defaults_and_immutable_closure_values_are_bound(monkeypatch):
    before = png.renderer_identity()
    with monkeypatch.context() as current:
        function = png._Document.bottom.fget
        current.setattr(function, '__code__', function.__code__.replace(
            co_consts=(*function.__code__.co_consts, 'property-change')))
        assert png.renderer_identity()['implementation_sha256'] != before['implementation_sha256']
    with monkeypatch.context() as current:
        current.setattr(png._Document.text, '__kwdefaults__', {**png._Document.text.__kwdefaults__, 'gap': 19})
        assert png.renderer_identity()['implementation_sha256'] != before['implementation_sha256']
    original = png._width

    def wrapped(delta):
        def width(text, font):
            return original(text, font) + delta
        return width

    with monkeypatch.context() as current:
        current.setattr(png, '_width', wrapped(1))
        first = png.renderer_identity()
        current.setattr(png, '_width', wrapped(2))
        assert png.renderer_identity()['implementation_sha256'] != first['implementation_sha256']


def test_loaded_code_identity_does_not_read_source_pyc_or_loader(monkeypatch, tmp_path):
    before = png.renderer_identity()

    class NoLoader:
        def get_code(self, *args):
            pytest.fail('Never reread source through a loader')

    def no_source(*args, **kwargs):
        pytest.fail('No source/pyc/font reread after font verification')

    monkeypatch.setattr(png, '__file__', str(tmp_path / 'missing.py'))
    monkeypatch.setattr(png, '__cached__', str(tmp_path / 'missing.pyc'))
    monkeypatch.setattr(png, '__loader__', NoLoader())
    monkeypatch.setattr(Path, 'open', no_source)
    assert png.renderer_identity() == before


def test_code_location_changes_do_not_change_implementation_identity(monkeypatch):
    before = png.renderer_identity()
    original = png._comic.__code__
    monkeypatch.setattr(png._comic, '__code__', original.replace(
        co_filename='PYZ/app/services/summary_visual_png.py', co_firstlineno=original.co_firstlineno + 99))
    assert png.renderer_identity() == before


def test_fresh_processes_and_hash_seeds_have_identical_loaded_identity(monkeypatch):
    code = 'import json; from app.services.summary_visual_png import renderer_identity; print(json.dumps(renderer_identity(),sort_keys=True))'
    outputs = []
    # Only these explicit local Python probes may spawn; no CLI/provider path.
    with monkeypatch.context() as current:
        current.setattr(subprocess, 'Popen', _PYTHON_POPEN)
        for seed in ('7', '91'):
            result = _PYTHON_RUN([sys.executable, '-B', '-c', code],
                cwd=Path(__file__).resolve().parents[1], env={**os.environ, 'PYTHONHASHSEED': seed},
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert result.returncode == 0, result.stderr
            outputs.append(json.loads(result.stdout))
    assert outputs[0] == outputs[1] == png.renderer_identity()


def test_identity_addition_keeps_prior_real_png_bytes_and_semantics():
    root = Path(__file__).resolve().parents[1]
    path = root / '.desktop-build/meeting-delivery-20261020/png-renderer-real-review/manifest.json'
    if not path.is_file():
        pytest.skip('Private original A/B fixtures are not repository test data')
    evidence = json.loads(path.read_text(encoding='utf-8'))
    for row in evidence['runs']:
        folder = Path(row['source_folder'])
        sidecar = json.loads((folder / 'summary_visual.json').read_text(encoding='utf-8'))
        frames = {frame['id']: (folder / 'screenshots' / f"summary-source-{frame['screenshot_index']}.jpg").read_bytes()
                  for frame in sidecar['visual']['frames']}
        result = png.render_summary_visual_png(sidecar['visual'], frames, title=row['title'])
        assert [page.sha256 for page in result.pages] == [page['sha256'] for page in row['pages']]
        assert json.loads(json.dumps([asdict(item) for item in result.semantic_order])) == row['semantic_order']
