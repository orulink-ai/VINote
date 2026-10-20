import { webcrypto } from 'node:crypto'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { makeVisualFixture, visualSavedBody, visualTitle } from '../../test-fixtures/summaryVisual'
import { buildSummaryVisualSvg, readVisualJpeg } from './summaryVisualExport'
import { buildSummaryHtml } from './summaryPresentation'
import { apiFetch } from './api'
vi.mock('./api', () => ({ apiFetch: vi.fn() }))
beforeEach(() => vi.stubGlobal('crypto', webcrypto))
afterEach(() => { vi.resetAllMocks(); vi.unstubAllGlobals() })

it('creates standalone SVG from verified text with embedded owned JPEGs only', async () => {
  const visual = await makeVisualFixture()
  const readImage = vi.fn().mockResolvedValue('data:image/jpeg;base64,YWJj')
  const svg = await buildSummaryVisualSvg(visual, visualSavedBody, '<script>literal title</script>', readImage)
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
  expect(doc.querySelector('parsererror,script,foreignObject,a')).toBeNull()
  expect(doc.querySelector('title')!.textContent).toBe('<script>literal title</script>')
  expect(doc.querySelectorAll('image')).toHaveLength(2)
  expect([...doc.querySelectorAll('image')].every(image => image.getAttribute('href') === 'data:image/jpeg;base64,YWJj')).toBe(true)
  expect(doc.documentElement.textContent).toContain('http://sensor.example.invalid')
  expect(readImage).toHaveBeenCalledTimes(2)
})

it('includes exact model-supplied relationships and no external resources', async () => {
  const visual = await makeVisualFixture('infographic'), readImage = vi.fn()
  const svg = await buildSummaryVisualSvg(visual, visualSavedBody, visualTitle, readImage)
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
  expect(doc.querySelector('parsererror,image,a,foreignObject')).toBeNull()
  for (const edge of visual.diagram!.edges) expect(doc.documentElement.textContent).toContain(edge.grounded_label)
  expect(doc.querySelectorAll('[marker-end]')).toHaveLength(3)
  expect(readImage).not.toHaveBeenCalled()
})

it('exports punctuation-aware labels and distinct shared-node return routes without rewriting a plan', async () => {
  const visual = await makeVisualFixture('infographic')
  const labels = ['设备校准记录必须由管理员复核，保留原值。', '缓冲区', '离线校准', '结果复核']
  const pairs = [[0, 1], [1, 2], [2, 3], [3, 1]]
  const relationLabels = pairs.map((_, i) => `合成关系${i + 1}`)
  const body = [...labels, ...relationLabels].join('\n')
  visual.blocks = [{ id: 'B1', text: body, claim_ids: ['C1'] }]
  visual.body_sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(body))), byte => byte.toString(16).padStart(2, '0')).join('')
  visual.diagram = { kind: 'relationship', nodes: labels.map((grounded_label, i) => ({ id: `N${i}`, block_ids: ['B1'], grounded_label })),
    edges: pairs.map(([a, b], i) => ({ id: `E${i}`, from: `N${a}`, to: `N${b}`, block_ids: ['B1'], grounded_label: relationLabels[i] })) }
  const before = JSON.stringify(visual), readImage = vi.fn()
  const svg = await buildSummaryVisualSvg(visual, body, visualTitle, readImage)
  const root = new DOMParser().parseFromString(svg, 'image/svg+xml').documentElement
  const diagram = root.querySelector('svg')!
  const groups = [...diagram.querySelectorAll('g')].filter(g => g.querySelector(':scope > rect'))
  expect(groups.map(g => g.querySelectorAll('text')[1].textContent)).toEqual(labels)
  for (const group of groups) {
    const lines = [...group.querySelectorAll('tspan')]
    expect(lines.slice(1).every(line => !/^[\p{Pe}\p{Pf}、。，]/u.test(line.textContent!.trimStart()))).toBe(true)
    for (const line of lines) expect(Array.from(line.textContent!).length * 16).toBeLessThanOrEqual(236)
  }
  // The returned fourth relationship must not reuse the incoming third edge's
  // vertical stem, including when routes have different whole-path shapes.
  const paths = [...diagram.querySelectorAll('path[marker-end]')].map(path => {
    const values = path.getAttribute('d')!.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
    const points = Array.from({ length: values.length / 2 }, (_, i) => [values[2 * i], values[2 * i + 1]])
    return points.slice(1).map((end, i) => [points[i], end])
  })
  expect(paths).toHaveLength(4)
  for (const [a, b] of paths[2]) for (const [c, d] of paths[3]) {
    if (a[0] !== b[0] || c[0] !== d[0] || a[0] !== c[0] || (b[1] - a[1]) * (d[1] - c[1]) >= 0) continue
    expect(Math.min(Math.max(a[1], b[1]), Math.max(c[1], d[1])) - Math.max(Math.min(a[1], b[1]), Math.min(c[1], d[1]))).toBeLessThanOrEqual(0)
  }
  for (const label of relationLabels) expect(root.textContent).toContain(label)
  expect(root.querySelector('image,a,script,foreignObject')).toBeNull()
  expect(JSON.stringify(visual)).toBe(before)
  expect(readImage).not.toHaveBeenCalled()
})

it.each([false, true])('exports a Latin + ZWJ label within card width without replacement (fallback=%s)', async fallback => {
  const visual = await makeVisualFixture('infographic')
  const label = 'A\u200D'.repeat(32) + 'A'
  visual.blocks = [{ id: 'B1', text: label, claim_ids: ['C1'] }]
  visual.body_sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(label))), byte => byte.toString(16).padStart(2, '0')).join('')
  visual.diagram = { kind: 'cards', nodes: [{ id: 'N1', block_ids: ['B1'], grounded_label: label }], edges: [] }
  const before = JSON.stringify(visual), descriptor = Object.getOwnPropertyDescriptor(Intl, 'Segmenter')!
  if (fallback) Object.defineProperty(Intl, 'Segmenter', { configurable: true, value: undefined })
  try {
    const readImage = vi.fn()
    const svg = await buildSummaryVisualSvg(visual, label, visualTitle, readImage)
    const root = new DOMParser().parseFromString(svg, 'image/svg+xml').documentElement
    const group = [...root.querySelector('svg')!.querySelectorAll('g')].find(g => g.querySelector(':scope > rect'))!
    const text = group.querySelectorAll('text')[1], lines = [...text.querySelectorAll('tspan')]
    expect(lines.length).toBeGreaterThan(1)
    expect(text.textContent).toBe(label)
    expect(text.textContent).not.toContain('\uFFFD')
    // No canvas in jsdom: the production conservative measure counts each BMP
    // code point, including ZWJ, as 16px. No resulting line may exceed the box.
    expect(lines.every(line => Array.from(line.textContent!).length * 16 <= 236)).toBe(true)
    expect(JSON.stringify(visual)).toBe(before)
    expect(readImage).not.toHaveBeenCalled()
  } finally { Object.defineProperty(Intl, 'Segmenter', descriptor) }
})

it.each([
  ['wide Latin', 'W'.repeat(120)],
  ['mixed Unicode', '控制W🧭12.5% / 08:30；'.repeat(5)],
  ['technical URL', 'https://sensor.example.invalid/' + 'W'.repeat(80)],
])('wraps complete %s relationship legends to the actual export width', async (_name, label) => {
  const visual = await makeVisualFixture('infographic')
  visual.blocks[1].text = label
  visual.diagram = { kind: 'relationship', nodes: [
    { id: 'N1', block_ids: ['B2'], grounded_label: label },
    { id: 'N2', block_ids: ['B2'], grounded_label: label },
  ], edges: [{ id: 'E1', from: 'N1', to: 'N2', block_ids: ['B2'], grounded_label: label }] }
  const body = visual.blocks.map(block => block.text).join('\n\n')
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(body))
  visual.body_sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
  const before = JSON.stringify(visual), readImage = vi.fn()
  const svg = await buildSummaryVisualSvg(visual, body, visualTitle, readImage)
  const root = new DOMParser().parseFromString(svg, 'image/svg+xml').documentElement
  const group = [...root.children].find(element => element.tagName === 'g')!
  const legend = [...group.children].find(element => element.tagName === 'text' && element.getAttribute('font-size') === '16')!
  const available = Number(root.getAttribute('width')) - 64
  const lines = [...legend.querySelectorAll('tspan')]
  expect(lines.length).toBeGreaterThan(1)
  // jsdom has no canvas. The shared wrapping helper uses a conservative
  // 16px-per-BMP / 32px-per-supplementary-character fallback there.
  for (const line of lines) {
    const width = Array.from(line.textContent!).reduce((sum, char) => sum + (char.codePointAt(0)! > 0xffff ? 32 : 16), 0)
    expect(width).toBeLessThanOrEqual(available)
  }
  expect(legend.textContent).toBe(`1. ${label} → ${label} · ${label}`)
  expect(legend.getAttribute('font-weight')).toBe('400')
  expect(Number(legend.getAttribute('y')) + (lines.length - 1) * 22 + 16).toBeLessThanOrEqual(Number(root.getAttribute('height')) - 32)
  expect(JSON.stringify(visual)).toBe(before)
  expect(root.querySelector('a,image,script,foreignObject')).toBeNull()
  expect(readImage).not.toHaveBeenCalled()
})

it.each([2, 20])('keeps the complete nested diagram inside the real SVG export with %s final-node self links', async count => {
  const visual = await makeVisualFixture('infographic')
  visual.diagram!.kind = 'relationship'
  visual.diagram!.nodes = visual.diagram!.nodes.slice(0, 3)
  visual.diagram!.edges = Array.from({ length: count }, (_, i) => ({ id: `SELF${i}`, from: 'N3', to: 'N3',
    block_ids: ['B4'], grounded_label: i % 2 ? '控制台复核结果返回采集端' : '控制台复核异常样本后，由值班员确认' }))
  const readImage = vi.fn()
  const source = await buildSummaryVisualSvg(visual, visualSavedBody, visualTitle, readImage)
  const doc = new DOMParser().parseFromString(source, 'image/svg+xml')
  expect(doc.querySelector('parsererror')).toBeNull()
  const root = doc.documentElement, diagram = root.querySelector('svg')!
  const outerWidth = Number(root.getAttribute('width')), outerHeight = Number(root.getAttribute('height'))
  const [x, y] = diagram.parentElement!.getAttribute('transform')!.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
  const inOuter = (px: number, py: number) => {
    expect(px + x).toBeGreaterThanOrEqual(0); expect(px + x).toBeLessThanOrEqual(outerWidth)
    expect(py + y).toBeGreaterThanOrEqual(0); expect(py + y).toBeLessThanOrEqual(outerHeight)
  }
  // Check the enclosing viewport as well as actual marks in outer coordinates:
  // valid inner geometry alone cannot detect clipping by the exported root.
  inOuter(0, 0)
  inOuter(Number(diagram.getAttribute('width')), Number(diagram.getAttribute('height')))
  const circles = [...diagram.querySelectorAll('circle')]
  expect(circles).toHaveLength(count)
  for (const circle of circles) {
    const cx = Number(circle.getAttribute('cx')), cy = Number(circle.getAttribute('cy')), r = Number(circle.getAttribute('r'))
    inOuter(cx - r, cy - r); inOuter(cx + r, cy + r)
  }
  for (const path of diagram.querySelectorAll('path[marker-end]')) {
    const coordinates = path.getAttribute('d')!.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
    for (let i = 0; i < coordinates.length; i += 2) inOuter(coordinates[i], coordinates[i + 1])
  }
  for (const edge of visual.diagram!.edges) expect(root.textContent).toContain(edge.grounded_label)
  expect(diagram.querySelectorAll('path[marker-end]')).toHaveLength(count)
  expect(readImage).not.toHaveBeenCalled()
})

it('fails before loading assets on a changed saved body and never silently omits missing screenshots', async () => {
  const visual = await makeVisualFixture(), readImage = vi.fn().mockRejectedValue(new Error('missing frame'))
  await expect(buildSummaryVisualSvg(visual, 'Another body', visualTitle, readImage)).rejects.toThrow('正文')
  expect(readImage).not.toHaveBeenCalled()
  await expect(buildSummaryVisualSvg(visual, visualSavedBody, visualTitle, readImage)).rejects.toThrow('missing frame')
  await expect(buildSummaryVisualSvg(visual, visualSavedBody, visualTitle, vi.fn().mockResolvedValue('data:image/svg+xml;base64,YWJj'))).rejects.toThrow('格式')
})

it('preserves a validated graphic and body in safe standalone HTML', async () => {
  const visual = await makeVisualFixture('infographic')
  const html = await buildSummaryHtml(visualSavedBody, visualTitle, visual.task_id, vi.fn(), visual)
  const doc = new DOMParser().parseFromString(html, 'text/html')
  expect(doc.querySelector('svg')).not.toBeNull()
  expect(doc.querySelector('script,iframe,foreignObject')).toBeNull()
  expect(doc.querySelector('main')!.textContent).toContain('值班员确认')
  expect(doc.querySelector('meta[http-equiv="Content-Security-Policy"]')).not.toBeNull()
})

it('does not fetch arbitrary URLs and rejects non-JPEG screenshot responses', async () => {
  await expect(readVisualJpeg('https://remote.invalid/source.jpg')).rejects.toThrow()
  expect(apiFetch).not.toHaveBeenCalled()
  vi.mocked(apiFetch).mockResolvedValue(new Response('<svg/>', { status: 200, headers: { 'content-type': 'image/svg+xml' } }))
  await expect(readVisualJpeg('/api/task/11111111-1111-4111-8111-111111111111/artifacts/screenshots/summary-source-0.jpg')).rejects.toThrow('不可用')
})
