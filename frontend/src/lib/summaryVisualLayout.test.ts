import { expect, it } from 'vitest'
import { diagramLayout, visualTextLines } from './summaryVisualLayout'

it('wraps wide Unicode without truncating an original label', () => {
  const label = '合成方案🧭需由负责人核验，保留完整条件与 12.5% 比例。'
  expect(visualTextLines(label, 16).join('')).toBe(label)
  expect(visualTextLines(label, 16).length).toBeGreaterThan(2)
})

it('keeps a cyclic relationship complete and all nodes inside finite export bounds', () => {
  const nodes = Array.from({ length: 12 }, (_, i) => ({ id: `n${i}`, label: `合成对象 ${i} 的完整说明` }))
  const edges = nodes.map((node, i) => ({ from: node.id, to: nodes[(i + 1) % nodes.length].id, label: '需共同核验' }))
  const graph = diagramLayout(nodes, edges, true)
  expect(graph.nodes).toHaveLength(12)
  expect(graph.edges).toHaveLength(12)
  for (const node of graph.nodes) {
    expect(node.x).toBeGreaterThanOrEqual(0)
    expect(node.x + node.width).toBeLessThanOrEqual(graph.width)
    expect(node.y + node.height).toBeLessThanOrEqual(graph.height)
  }
  expect(JSON.stringify(graph)).not.toMatch(/NaN|Infinity/)
})

it('flow levels express only supplied links and preserve independent nodes', () => {
  const graph = diagramLayout([{ id: 'b', label: '乙' }, { id: 'a', label: '甲' }, { id: 'c', label: '独立对象' }], [{ from: 'a', to: 'b', label: '依赖' }], true)
  expect(graph.nodes.find(n => n.id === 'a')!.y).toBeLessThan(graph.nodes.find(n => n.id === 'b')!.y)
  expect(graph.nodes).toHaveLength(3)
  expect(graph.edges).toHaveLength(1)
})
