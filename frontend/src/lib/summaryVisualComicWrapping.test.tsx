import { webcrypto } from 'node:crypto'
import { afterEach, expect, it, vi } from 'vitest'
import { makeVisualFixture } from '../../test-fixtures/summaryVisual'
import { comicTextLines } from '@/lib/summaryVisualLayout'
import { buildSummaryVisualSvg } from '@/lib/summaryVisualExport'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

const measure = (text: string) => Array.from(text).reduce((sum, char) => sum + (char.codePointAt(0)! > 0xffff ? 32 : char.codePointAt(0)! > 255 ? 16 : 8), 0)
const labels = [
  '设备校准（保持原值），核验结果；保留条件。',
  '模块QX-2048-REV3.2、u8FluxMiniCtrl与GPIO-15待复核。',
  '时间07:30–09:00，速率12.5%仍待确认。',
  'W'.repeat(90) + 'i'.repeat(10),
  'e\u0301👩🏽‍🔬🇨🇦原始样本，必须保留。',
  'A\u200D'.repeat(32) + 'A',
]

function expectFaithfulLines(text: string, lines: string[], width: number, widthOf = measure) {
  expect(lines.join('')).toBe(text)
  for (const line of lines) expect(widthOf(line)).toBeLessThanOrEqual(width)
  for (const line of lines.slice(1)) expect(line.trimStart()).not.toMatch(/^[\p{Pe}\p{Pf}、。，．？！：；％‰…·・,.:;!?%]/u)
  for (const line of lines.slice(0, -1)) expect(line.trimEnd()).not.toMatch(/[\p{Ps}\p{Pi}]$/u)
  let position = 0
  const boundaries = lines.slice(0, -1).map(line => (position += line.length))
  for (const token of text.matchAll(/[A-Za-z0-9]+(?:[.:/%–-][A-Za-z0-9]+)*/gu)) {
    if (widthOf(token[0]) <= width) expect(boundaries.some(end => end > token.index! && end < token.index! + token[0].length)).toBe(false)
  }
}

it.each([false, true])('preserves exact caption positions and fitting identifiers (fallback=%s)', fallback => {
  if (fallback) vi.stubGlobal('Intl', { ...Intl, Segmenter: undefined })
  for (const label of labels) for (const width of [160, 236, 476]) {
    expectFaithfulLines(label, comicTextLines(label, width, measure), width)
  }
})

it('checks both occurrences of the same fitting identifier by position', () => {
  const label = '甲'.repeat(12) + ' QX-2048-REV3.2，' + '乙'.repeat(12) + ' QX-2048-REV3.2。'
  expectFaithfulLines(label, comicTextLines(label, 236, measure), 236)
})

it.each([0, -1, NaN, Infinity])('rejects an invalid caption width %s', width => {
  expect(() => comicTextLines('合成说明', width, measure)).toThrow('text_layout_budget')
})

it.each(['bad\0control', 'bad\nline', 'bad\rline', 'bad\x7fcontrol'])('rejects control characters without rewriting %j', label => {
  expect(() => comicTextLines(label, 476, measure)).toThrow('text_layout_budget')
})

it.each([false, true])('rejects an irreducible quote plus fitting identifier (fallback=%s)', fallback => {
  if (fallback) vi.stubGlobal('Intl', { ...Intl, Segmenter: undefined })
  const token = 'W'.repeat(8), width = measure(token) + 1
  expect(measure(token)).toBeLessThan(width)
  expect(() => comicTextLines(`“${token}”`, width, measure)).toThrow('text_layout_budget')
})

it('does not emit an oversized indivisible grapheme', () => {
  expect(() => comicTextLines('👩🏽‍🔬', 1, measure)).toThrow('text_layout_budget')
})

it('exports all eight source-bound scenes in order with exact labels and embedded frames', async () => {
  vi.stubGlobal('crypto', webcrypto)
  vi.stubGlobal('CanvasRenderingContext2D', undefined)
  const visual = await makeVisualFixture()
  const captions = [
    '待'.repeat(22) + 'QX-2048-REV3.2，保留原型号。',
    '核'.repeat(25) + '，保持原条件。',
    '型号u8FluxMiniCtrl须核验，GPIO-15保留。',
    '第四项07:30–09:00，仍待确认。',
    '第五项保持原文及原始画面。',
    '第六项用于跨列顺序核验。',
    '第七项保留标签<script>literal</script>，不能执行。',
    '第八项是全文末尾，不可截断。',
  ]
  const body = captions.join('\n\n')
  visual.blocks = captions.map((text, i) => ({ id: `B${i + 1}`, text, claim_ids: [`C${i + 1}`] }))
  visual.body_sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(body))), b => b.toString(16).padStart(2, '0')).join('')
  visual.frames = captions.map((grounded_label, i) => ({ id: `[FRAME:${String(i + 1).padStart(4, '0')}]`, screenshot_index: i, timestamp_seconds: (i + 1) * 60, grounded_label }))
  visual.scenes = captions.map((grounded_label, i) => ({ id: `S${i + 1}`, block_ids: [`B${i + 1}`], frame_id: visual.frames[i].id, grounded_label }))
  const original = JSON.stringify(visual)
  const imageData = captions.map((_, i) => `data:image/jpeg;base64,${btoa(`synthetic-frame-${i}`)}`)
  const read = vi.fn(async (path: string) => imageData[Number(path.match(/summary-source-([0-7])\.jpg$/)![1])])
  const svg = await buildSummaryVisualSvg(visual, body, '合成分镜', read)
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
  const texts = [...doc.querySelectorAll('text[font-size="16"]')]
  expect(texts.map(text => text.textContent)).toEqual(captions)
  for (const [i, text] of texts.entries()) {
    expectFaithfulLines(captions[i], [...text.querySelectorAll('tspan')].map(line => line.textContent!), 476, text => Array.from(text).reduce((n, c) => n + (c.codePointAt(0)! > 0xffff ? 32 : 16), 0))
  }
  expect([...doc.querySelectorAll('image')].map(image => image.getAttribute('href'))).toEqual(imageData)
  expect(read.mock.calls.map(([path]) => path)).toEqual(captions.map((_, i) => `/api/task/${visual.task_id}/artifacts/screenshots/summary-source-${i}.jpg`))
  expect([...doc.querySelectorAll('image')].map(image => image.getAttribute('x'))).toEqual(['44', '576', '44', '576', '44', '576', '44', '576'])
  expect(doc.documentElement.getAttribute('width')).toBe('1104')
  expect(doc.querySelector('script,a,foreignObject,parsererror')).toBeNull()
  expect(JSON.stringify(visual)).toBe(original)
})

it.each([false, true])('reflows the fitting-identifier regression at 476px (fallback=%s)', fallback => {
  if (fallback) vi.stubGlobal('Intl', { ...Intl, Segmenter: undefined })
  const label = '本次评审确认下一阶段继续保留控制模块的型号QX-2048-REV3.2，后续继续核验。'
  const widthOf = (text: string) => Array.from(text).reduce((n, c) => n + (c.codePointAt(0)! > 255 ? 16 : 9.2), 0)
  const lines = comicTextLines(label, 476, widthOf)
  expect(lines).toEqual(['本次评审确认下一阶段继续保留控制模块的型号', 'QX-2048-REV3.2，后续继续核验。'])
  expectFaithfulLines(label, lines, 476, widthOf)
})

it.each([false, true])('exports the exact fitting-identifier regression through the real SVG builder (fallback=%s)', async fallback => {
  vi.stubGlobal('crypto', webcrypto)
  if (fallback) vi.stubGlobal('Intl', { ...Intl, Segmenter: undefined })
  // Model a font where the token fits alone but its following comma cannot fit
  // after the full Chinese prefix. Real Edge font coverage is separate evidence.
  const widthOf = (text: string) => Array.from(text).reduce((n, c) => n + (c.codePointAt(0)! > 255 ? 16 : 9.2), 0)
  vi.stubGlobal('CanvasRenderingContext2D', class {})
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ font: '', measureText: (text: string) => ({ width: widthOf(text) }) } as CanvasRenderingContext2D)
  // A fresh module instance ensures its cached measurement context is this font.
  vi.resetModules()
  const { buildSummaryVisualSvg: build } = await import('@/lib/summaryVisualExport')
  const visual = await makeVisualFixture()
  const label = '本次评审确认下一阶段继续保留控制模块的型号QX-2048-REV3.2，后续继续核验。'
  visual.blocks = [{ id: 'B1', text: label, claim_ids: ['C1'] }]
  visual.body_sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(label))), b => b.toString(16).padStart(2, '0')).join('')
  visual.frames = [{ ...visual.frames[0], grounded_label: label }]
  visual.scenes = [{ ...visual.scenes[0], block_ids: ['B1'], grounded_label: label }]
  const original = JSON.stringify(visual), read = vi.fn(async () => 'data:image/jpeg;base64,YWJj')
  const svg = await build(visual, label, '合成型号说明', read)
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
  const lines = [...doc.querySelectorAll('text[font-size="16"] tspan')].map(t => t.textContent!)
  expect(lines).toEqual(['本次评审确认下一阶段继续保留控制模块的型号', 'QX-2048-REV3.2，后续继续核验。'])
  expectFaithfulLines(label, lines, 476, widthOf)
  expect(doc.querySelectorAll('image')).toHaveLength(1)
  expect(read).toHaveBeenCalledTimes(1)
  expect(JSON.stringify(visual)).toBe(original)
})
