import { expect, it } from 'vitest'
import { diagramTextLines } from './summaryVisualLayout'

const graphemes = new Intl.Segmenter('zh', { granularity: 'grapheme' })
const measure = (text: string) => Array.from(graphemes.segment(text), part =>
  part.segment === 'i' ? 4 : part.segment === 'W' ? 17 : part.segment.codePointAt(0)! > 0xffff ? 32 : 16,
).reduce((sum, value) => sum + value, 0)

function withoutSegmenter(test: () => void) {
  const descriptor = Object.getOwnPropertyDescriptor(Intl, 'Segmenter')!
  Object.defineProperty(Intl, 'Segmenter', { configurable: true, value: undefined })
  try { test() } finally { Object.defineProperty(Intl, 'Segmenter', descriptor) }
}

it.each(['A\u200D'.repeat(32) + 'A', '甲\u200D'.repeat(32) + '甲', '👩\u200DA\u200D'.repeat(12), 'A\u200D👩\u200D'.repeat(12)])
  ('bounds non-emoji ZWJ chains in both Segmenter modes without replacing code points: %s', label => {
    const normal = diagramTextLines(label, 236, measure)
    withoutSegmenter(() => {
      const fallback = diagramTextLines(label, 236, measure)
      for (const lines of [normal, fallback]) {
        expect(lines.length).toBeGreaterThan(1)
        expect(lines.join('')).toBe(label)
        expect(lines.every(line => measure(line) <= 236)).toBe(true)
        expect(lines.join('')).not.toContain('\uFFFD')
      }
      // Also exercise the no-canvas conservative width used by SSR.
      const conservative = (text: string) => Array.from(text).reduce((sum, char) => sum + (char.codePointAt(0)! > 0xffff ? 32 : 16), 0)
      const ssr = diagramTextLines(label, 236, conservative)
      expect(ssr.join('')).toBe(label)
      expect(ssr.every(line => conservative(line) <= 236)).toBe(true)
    })
  })

it('prefers actual Chinese word boundaries without guessing or changing entity text', () => {
  const label = '已通知传感器厂家复核。'
  const lines = diagramTextLines(label, 64, measure)
  expect(lines.join('')).toBe(label)
  expect(lines.some(line => line.includes('传感器'))).toBe(true)
  expect(lines.every(line => measure(line) <= 64)).toBe(true)
  const names = '负责人Mira Chen、赵青禾复核样本。'
  expect(diagramTextLines(names, 160, measure).join('')).toBe(names)
})

for (const fallback of [false, true]) {
  it(`keeps fitting comma-separated terms intact without a name dictionary (fallback=${fallback})`, () => {
    const run = () => {
      const terms = ['设备批次', 'Mira Chen', '陈青禾', '李澄川', '原始记录']
      const label = terms.join('、') + '，等待核验。'
      const lines = diagramTextLines(label, 176, measure)
      expect(lines.join('')).toBe(label)
      expect(lines.every(line => measure(line) <= 176)).toBe(true)
      for (const term of terms) expect(lines.some(line => line.includes(term))).toBe(true)
    }
    if (fallback) withoutSegmenter(run); else run()
  })

  it.each(['，', '、', '。', '；', '：', '？', '！', '）', '】', '」', '』', '”', '…'])
    (`keeps closing punctuation %s off automatic line starts (fallback=${fallback})`, punctuation => {
      const run = () => {
        const label = `设备校准记录必须由管理员复核${punctuation}保留原值。`
        const lines = diagramTextLines(label, 224, measure)
        expect(lines.join('')).toBe(label)
        expect(lines.every(line => measure(line) <= 224)).toBe(true)
        expect(lines.slice(1).every(line => !/^[\p{Pe}\p{Pf}、。，；：？！…]/u.test(line.trimStart()))).toBe(true)
      }
      if (fallback) withoutSegmenter(run); else run()
    })

  it(`keeps opening punctuation with following text and preserves whitespace (fallback=${fallback})`, () => {
    const run = () => {
      for (const label of ['记录交由（合成值班员）复核。', '复核「原始样本」后保留。', '  检查  【完整条件】\t结束  ']) {
        const lines = diagramTextLines(label, 96, measure)
        expect(lines.join('')).toBe(label)
        expect(lines.every(line => measure(line) <= 96)).toBe(true)
        expect(lines.slice(0, -1).every(line => !/[\p{Ps}\p{Pi}]$/u.test(line.trimEnd()))).toBe(true)
        expect(lines.slice(1).every(line => !/^[\p{Pe}\p{Pf}、。，]/u.test(line.trimStart()))).toBe(true)
      }
    }
    if (fallback) withoutSegmenter(run); else run()
  })

  it(`keeps fitting technical tokens and splits an overlong word within measured bounds (fallback=${fallback})`, () => {
    const run = () => {
      const tokens = ['08:30', 'AB2468', '12.5%', 'X7', '07:00–09:30']
      const label = `复核${tokens.join(' / ')} 完成`
      const lines = diagramTextLines(label, 192, measure)
      expect(lines.join('')).toBe(label)
      for (const token of tokens) expect(lines.some(line => line.includes(token))).toBe(true)
      const long = 'W'.repeat(90) + 'i'.repeat(10)
      const split = diagramTextLines(long, 112, measure)
      expect(split.join('')).toBe(long)
      expect(split.length).toBeGreaterThan(2)
      expect(split.every(line => measure(line) <= 112)).toBe(true)
    }
    if (fallback) withoutSegmenter(run); else run()
  })

  it(`does not split combining marks, ZWJ emoji or flag pairs (fallback=${fallback})`, () => {
    const run = () => {
      const label = '说明e\u0301👩🏽‍🔬🇨🇦结果，核验完成。'
      const lines = diagramTextLines(label, 64, measure)
      expect(lines.join('')).toBe(label)
      for (const cluster of ['e\u0301', '👩🏽‍🔬', '🇨🇦']) expect(lines.some(line => line.includes(cluster))).toBe(true)
      expect(lines.every(line => measure(line) <= 64)).toBe(true)
    }
    if (fallback) withoutSegmenter(run); else run()
  })
}

it('preserves authored blank lines and does not repair punctuation across an explicit newline', () => {
  const text = '合成记录\n\n，原样段落\n'
  expect(diagramTextLines(text, 320, measure).join('\n')).toBe(text)
  expect(diagramTextLines('', 320, measure)).toEqual([''])
})

it('keeps complete mixed-script labels bounded over many widths', () => {
  for (const label of ['设备记录（原值），复核「结果」；保留完整条件。', 'Mira Chen / Ροή e\u0301 08:30–09:30，参数12.5%。', '校准👩🏽‍🔬🧭结果，完整保存。']) {
    for (let width = 96; width <= 256; width += 8) {
      const lines = diagramTextLines(label, width, measure)
      expect(lines.join('')).toBe(label)
      expect(lines.every(line => measure(line) <= width)).toBe(true)
      expect(lines.slice(1).every(line => !/^[\p{Pe}\p{Pf}、。，；：？！]/u.test(line.trimStart()))).toBe(true)
    }
  }
})
