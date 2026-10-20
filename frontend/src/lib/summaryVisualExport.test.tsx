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
