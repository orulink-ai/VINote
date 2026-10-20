import { expect, it, vi } from 'vitest'
import { diagramLayout, diagramTextLines, visualTextLines } from './summaryVisualLayout'

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

function sampledPath(path: string): Array<{ x: number; y: number }> {
  const tokens = path.match(/[MLHVC]|-?\d+(?:\.\d+)?/g)!
  const points: Array<{ x: number; y: number }> = []
  let cursor = { x: 0, y: 0 }, i = 0
  while (i < tokens.length) {
    const command = tokens[i++]
    if (command === 'M') { cursor = { x: Number(tokens[i++]), y: Number(tokens[i++]) }; points.push(cursor); continue }
    const start = cursor
    if (command === 'C') {
      const a = { x: Number(tokens[i++]), y: Number(tokens[i++]) }, b = { x: Number(tokens[i++]), y: Number(tokens[i++]) }
      cursor = { x: Number(tokens[i++]), y: Number(tokens[i++]) }
      for (let step = 1; step <= 100; step++) {
        const t = step / 100, u = 1 - t
        points.push({ x: u ** 3 * start.x + 3 * u ** 2 * t * a.x + 3 * u * t ** 2 * b.x + t ** 3 * cursor.x,
          y: u ** 3 * start.y + 3 * u ** 2 * t * a.y + 3 * u * t ** 2 * b.y + t ** 3 * cursor.y })
      }
    } else {
      if (command === 'L') cursor = { x: Number(tokens[i++]), y: Number(tokens[i++]) }
      else if (command === 'H') cursor = { x: Number(tokens[i++]), y: cursor.y }
      else if (command === 'V') cursor = { x: cursor.x, y: Number(tokens[i++]) }
      else throw new Error(`Unexpected path command ${command}`)
      const steps = Math.ceil(Math.hypot(cursor.x - start.x, cursor.y - start.y))
      for (let step = 1; step <= steps; step++) points.push({ x: start.x + (cursor.x - start.x) * step / steps, y: start.y + (cursor.y - start.y) * step / steps })
    }
  }
  return points
}

function expectClearRoutes(graph: ReturnType<typeof diagramLayout>) {
  expect(JSON.stringify(graph)).not.toMatch(/NaN|Infinity/)
  for (const [index, edge] of graph.edges.entries()) {
    for (const other of graph.edges.slice(index + 1)) {
      expect(Math.hypot(edge.labelX - other.labelX, edge.labelY - other.labelY), 'edge numbers overlap').toBeGreaterThanOrEqual(26)
    }
  }
  for (const edge of graph.edges) {
    const points = sampledPath(edge.path)
    for (const node of graph.nodes) {
      expect(points.some(p => p.x > node.x + 0.1 && p.x < node.x + node.width - 0.1 && p.y > node.y + 0.1 && p.y < node.y + node.height - 0.1), `${edge.from} -> ${edge.to} crosses ${node.id}`).toBe(false)
      expect(edge.labelX + 13 > node.x && edge.labelX - 13 < node.x + node.width && edge.labelY + 13 > node.y && edge.labelY - 13 < node.y + node.height, 'edge number overlaps a card').toBe(false)
    }
    const endpoints = [points[0], points.at(-1)!]
    for (const [index, id] of [edge.from, edge.to].entries()) {
      const node = graph.nodes.find(n => n.id === id)!, p = endpoints[index]
      expect(p.x >= node.x && p.x <= node.x + node.width && p.y >= node.y && p.y <= node.y + node.height).toBe(true)
      expect(p.x === node.x || p.x === node.x + node.width || p.y === node.y || p.y === node.y + node.height).toBe(true)
    }
    const bounded = [...points, { x: edge.labelX - 13, y: edge.labelY - 13 }, { x: edge.labelX + 13, y: edge.labelY + 13 }]
    expect(bounded.every(p => p.x >= 0 && p.x <= graph.width && p.y >= 0 && p.y <= graph.height)).toBe(true)
  }
}

it('routes a return edge to its target without entering the unrelated first card', () => {
  const nodes = ['input', 'controller', 'actuator', 'sensor'].map(id => ({ id, label: `Synthetic ${id}` }))
  const edges = [{ from: 'input', to: 'controller', label: 'input link' }, { from: 'controller', to: 'actuator', label: 'output link' }, { from: 'sensor', to: 'controller', label: 'return link' }]
  const graph = diagramLayout(nodes, edges, false)
  expect(graph.edges.map(({ from, to, label }) => ({ from, to, label }))).toEqual(edges)
  expectClearRoutes(graph)
})

it('routes long acyclic links across centered rows with different card counts', () => {
  const nodes = Array.from({ length: 8 }, (_, i) => ({ id: `stage${i}`, label: 'Variable label '.repeat(i + 1) }))
  const edges = [[0, 1], [0, 2], [0, 3], [0, 4], [1, 5], [2, 6], [5, 7], [0, 7]]
    .map(([from, to]) => ({ from: nodes[from].id, to: nodes[to].id, label: 'explicit dependency' }))
  expectClearRoutes(diagramLayout(nodes, edges, true))
})

it('wraps measured wide Latin, mixed CJK and emoji without changing the label', () => {
  const measure = (text: string) => Array.from(text).reduce((width, char) => width + (char === 'i' ? 4 : char === 'W' ? 17 : 16), 0)
  for (const label of ['WWWWWWWWWWWWWWWW', 'iiiiiiiiiiiiiiiiiiiiiiiiiiiiii', '合成航班12:00–14:30 航站楼T3 票价1234元起🧭']) {
    const lines = diagramTextLines(label, 236, measure)
    expect(lines.join('')).toBe(label)
    expect(lines.every(line => measure(line) <= 236)).toBe(true)
  }
  expect(diagramTextLines('WWWWWWWWWWWWWWWW', 236, measure)).toHaveLength(2)
  expect(diagramTextLines('iiiiiiiiiiiiiiiiiiiiiiiiiiiiii', 236, measure)).toHaveLength(1)
  expect(diagramTextLines('甲\n\n乙\n', 236, measure).join('\n')).toBe('甲\n\n乙\n')
  const tokens = ['12:00', 'CZ3551', '2215', 'T3']
  const label = `合成起飞${tokens[0]}航班${tokens[1]}票价${tokens[2]}航站楼${tokens[3]}`
  const wrapped = diagramTextLines(label, 112, measure)
  expect(wrapped.join('')).toBe(label)
  for (const token of tokens) expect(wrapped.some(line => line.includes(token))).toBe(true)
})

it('grows card height for wrapped complete labels without clipping text or changing order', () => {
  const nodes = ['WW'.repeat(45), '合成条件与限制'.repeat(12), '短标签'].map((label, i) => ({ id: `n${i}`, label }))
  const graph = diagramLayout(nodes, [], false)
  expect(graph.nodes.map(({ id, label }) => ({ id, label }))).toEqual(nodes)
  for (const node of graph.nodes) {
    expect(node.lines.join('')).toBe(node.label)
    expect(54 + (node.lines.length - 1) * 22 + 18).toBeLessThanOrEqual(node.height)
  }
})

it('uses browser font measurement rather than character counts when canvas is available', async () => {
  const context = { font: '', measureText: vi.fn((text: string) => ({ width: text.length * 17 })) }
  vi.stubGlobal('CanvasRenderingContext2D', function () {})
  const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
  try {
    vi.resetModules()
    const { diagramLayout: measuredLayout } = await import('./summaryVisualLayout')
    const label = 'W'.repeat(14)
    const graph = measuredLayout([{ id: 'wide', label }], [], false)
    expect(context.font).toBe('16px system-ui, sans-serif')
    expect(context.measureText).toHaveBeenCalled()
    expect(graph.nodes[0].lines).toEqual(['W'.repeat(13), 'W'])
    expect(graph.nodes[0].lines.join('')).toBe(label)
  } finally { getContext.mockRestore(); vi.unstubAllGlobals() }
})

it.each([false, true])('avoids intervening cards for forward, backward, multi-row and self links (flow=%s)', flow => {
  const nodes = Array.from({ length: 12 }, (_, i) => ({ id: `item${i}`, label: `Synthetic item ${i}` }))
  const edges = nodes.flatMap(a => nodes.map(b => ({ from: a.id, to: b.id, label: `${a.id} relates to ${b.id}` })))
  const graph = diagramLayout(nodes, edges, flow)
  expect(graph.edges.map(({ from, to, label }) => ({ from, to, label }))).toEqual(edges)
  expectClearRoutes(graph)
})

const repeatedRelations = [
  { name: 'two opposite directions', count: 2, pair: (i: number) => i % 2 ? ['n1', 'n0'] : ['n0', 'n1'] },
  { name: 'twenty parallel relationships', count: 20, pair: () => ['n0', 'n1'] },
  { name: 'twenty self relationships', count: 20, pair: () => ['n0', 'n0'] },
  { name: 'same-row skip relationships in both directions', count: 8, pair: (i: number) => i % 2 ? ['n2', 'n0'] : ['n0', 'n2'] },
  { name: 'multi-row return relationships in both directions', count: 8, pair: (i: number) => i % 2 ? ['n11', 'n0'] : ['n0', 'n11'] },
]

for (const flow of [false, true]) {
  it.each(repeatedRelations)('keeps $name distinct, clear and bounded (flow=' + flow + ')', ({ count, pair }) => {
    const nodes = Array.from({ length: 12 }, (_, i) => ({ id: `n${i}`, label: i % 2 ? `完整条件 ${i}` : `Source ${i}` }))
    const edges = Array.from({ length: count }, (_, i) => {
      const [from, to] = pair(i)
      return { from, to, label: `Original relationship ${i}: 12.5% / 08:30` }
    })
    const graph = diagramLayout(nodes, edges, flow)
    expect(graph.edges.map(({ from, to, label }) => ({ from, to, label }))).toEqual(edges)
    expect(graph.edges.map(edge => edge.number)).toEqual(edges.map((_, i) => i + 1))
    expect(graph.nodes.map(({ id, label }) => ({ id, label })).sort((a, b) => a.id.localeCompare(b.id)))
      .toEqual([...nodes].sort((a, b) => a.id.localeCompare(b.id)))
    // Compare geometry regardless of traversal direction: reversing a path alone
    // must not count as separating two supplied relationships.
    const shapes = graph.edges.map(edge => {
      const points = edge.path.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
      const segments: string[] = []
      for (let i = 2; i < points.length; i += 2) {
        segments.push([`${points[i - 2]},${points[i - 1]}`, `${points[i]},${points[i + 1]}`].sort().join(':'))
      }
      return segments.sort().join(';')
    })
    expect(new Set(shapes).size).toBe(edges.length)
    expectClearRoutes(graph)
  })
}

it.each([false, true])('places mixed shared-node, reverse and self references without overlap (flow=%s)', flow => {
  const nodes = Array.from({ length: 12 }, (_, i) => ({ id: `n${i}`, label: `Item ${i}` }))
  // Fixed seeds exercise different routing/label orders, not one answer diagram.
  for (let seed = 1; seed <= 24; seed++) {
    let state = seed
    const next = () => { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state >>> 16 }
    const edges = Array.from({ length: 20 }, (_, i) => ({ from: nodes[next() % nodes.length].id,
      to: nodes[next() % nodes.length].id, label: `Relationship ${i}` }))
    const graph = diagramLayout(nodes, edges, flow)
    expect(graph.edges.map(({ from, to, label }) => ({ from, to, label }))).toEqual(edges)
    expectClearRoutes(graph)
  }
})

it('keeps a crowded short route and a self reference visible beside an isolated card', () => {
  const nodes = ['isolated', 'source', 'target'].map(id => ({ id, label: id }))
  const edges = [{ from: 'source', to: 'target', label: 'forward condition' },
    { from: 'source', to: 'source', label: 'self condition' }]
  const graph = diagramLayout(nodes, edges, false)
  expect(graph.edges.map(({ from, to, label }) => ({ from, to, label }))).toEqual(edges)
  expectClearRoutes(graph)
})

it('keeps empty and single short-node layouts finite without inventing relationships', () => {
  for (const items of [[], [{ id: 'only', label: '短' }]]) {
    const graph = diagramLayout(items, [], true)
    expect(graph.edges).toEqual([])
    expect(graph.nodes.map(({ id, label }) => ({ id, label }))).toEqual(items)
    expect(graph.width).toBeGreaterThan(0)
    expect(graph.height).toBeGreaterThan(0)
    expect(JSON.stringify(graph)).not.toMatch(/NaN|Infinity/)
  }
})
