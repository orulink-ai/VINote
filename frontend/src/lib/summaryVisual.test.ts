import { webcrypto } from 'node:crypto'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { makeVisualFixture, visualSavedBody, visualTask } from '../../test-fixtures/summaryVisual'
import { parseSummaryVisual, validateSummaryVisual, visualFramePath } from './summaryVisual'

beforeEach(() => vi.stubGlobal('crypto', webcrypto))
afterEach(() => vi.unstubAllGlobals())

it.each(['comic', 'infographic'] as const)('validates exact saved UTF-8 body for %s', async presentation => {
  const visual = await makeVisualFixture(presentation)
  expect(await validateSummaryVisual(visual, visualTask, presentation, visualSavedBody)).toMatchObject({ ok: true })
  expect(await validateSummaryVisual(visual, visualTask, presentation, visualSavedBody + '\n')).toMatchObject({ ok: false })
})

it('keeps technical comparison and URL labels as plain grounded text', async () => {
  const visual = await makeVisualFixture()
  expect(parseSummaryVisual(visual, visualTask, 'comic').ok).toBe(true)
  expect(visual.scenes[0].grounded_label).toContain('<')
  expect(visual.scenes[0].grounded_label).toContain('http://')
})

it.each([
  ['different task', (v: any) => { v.task_id = '22222222-2222-4222-8222-222222222222' }],
  ['unsupported protocol', (v: any) => { v.visual_protocol = 2 }],
  ['remote resource field', (v: any) => { v.frames[0].url = 'https://remote.invalid/a.jpg' }],
  ['model SVG', (v: any) => { v.svg = '<svg onload="run()" />' }],
  ['missing frame', (v: any) => { v.scenes[0].frame_id = 'missing' }],
  ['missing block', (v: any) => { v.scenes[0].block_ids = ['missing'] }],
  ['ungrounded label', (v: any) => { v.scenes[0].grounded_label = 'Invented decision' }],
  ['missing included claim', (v: any) => { v.blocks[1].claim_ids = [] }],
  ['invalid index', (v: any) => { v.frames[0].screenshot_index = 8 }],
  ['non-finite timestamp', (v: any) => { v.frames[0].timestamp_seconds = Infinity }],
  ['duplicate scene', (v: any) => { v.scenes.push(v.scenes[0]) }],
  ['oversize scenes', (v: any) => { v.scenes = Array(9).fill(v.scenes[0]) }],
  ['oversize body block', (v: any) => { v.blocks[0].text = 'x'.repeat(6001) }],
  ['oversize payload', (v: any) => { v.blocks = Array.from({ length: 64 }, (_, i) => ({ id: `B${i}`, text: 'x'.repeat(6000), claim_ids: [] })) }],
])('rejects %s without truncating or manufacturing content', async (_, mutate) => {
  const visual = await makeVisualFixture(); mutate(visual)
  expect(parseSummaryVisual(visual, visualTask, 'comic').ok).toBe(false)
})

it('rejects a self-consistent block echo that is absent from the saved body', async () => {
  const visual = await makeVisualFixture()
  visual.blocks[0].text = 'A substituted block'
  expect(await validateSummaryVisual(visual, visualTask, 'comic', visualSavedBody)).toMatchObject({ ok: false })
})

it('requires edge-specific grounding and existing nodes; does not turn cards into relationships', async () => {
  const visual = await makeVisualFixture('infographic')
  visual.diagram!.edges[0].block_ids = ['B2']
  expect(parseSummaryVisual(visual, visualTask, 'infographic').ok).toBe(false)
  const valid = await makeVisualFixture('infographic')
  valid.diagram!.edges[0].to = 'absent'
  expect(parseSummaryVisual(valid, visualTask, 'infographic').ok).toBe(false)
  const cards = await makeVisualFixture('infographic'); cards.diagram!.kind = 'cards'
  expect(parseSummaryVisual(cards, visualTask, 'infographic').ok).toBe(false)
  cards.diagram!.edges = []
  expect(parseSummaryVisual(cards, visualTask, 'infographic').ok).toBe(true)
})

it('constructs only the current task fixed asset path', () => {
  expect(visualFramePath(visualTask, 7)).toBe(`/api/task/${visualTask}/artifacts/screenshots/summary-source-7.jpg`)
  expect(() => visualFramePath('../../private', 0)).toThrow()
  expect(() => visualFramePath(visualTask, 8)).toThrow()
})
