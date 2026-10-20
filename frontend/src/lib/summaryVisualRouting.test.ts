import { expect, it } from 'vitest'
import { diagramLayout, type DiagramLink } from './summaryVisualLayout'

type Point = { x: number; y: number }
function points(path: string): Point[] {
  const values = path.match(/-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/gi)!.map(Number)
  return Array.from({ length: values.length / 2 }, (_, i) => ({ x: values[2 * i], y: values[2 * i + 1] }))
}

function reverseLength(paths: string[]) {
  const segments = paths.map(path => { const p = points(path); return p.slice(1).map((end, i) => [p[i], end]) })
  let length = 0
  for (let a = 0; a < segments.length; a++) for (let b = a + 1; b < segments.length; b++) {
    for (const [p, q] of segments[a]) for (const [r, s] of segments[b]) {
      const vertical = p.x === q.x && r.x === s.x && Math.abs(p.x - r.x) < 1e-7
      const horizontal = p.y === q.y && r.y === s.y && Math.abs(p.y - r.y) < 1e-7
      if (!vertical && !horizontal) continue
      const [start, end, otherStart, otherEnd] = vertical ? [p.y, q.y, r.y, s.y] : [p.x, q.x, r.x, s.x]
      if ((end - start) * (otherEnd - otherStart) >= 0) continue
      length += Math.max(0, Math.min(Math.max(start, end), Math.max(otherStart, otherEnd)) - Math.max(Math.min(start, end), Math.min(otherStart, otherEnd)))
    }
  }
  return length
}

function expectSeparated(graph: ReturnType<typeof diagramLayout>, links: DiagramLink[]) {
  expect(graph.edges.map(({ from, to, label }) => ({ from, to, label }))).toEqual(links)
  expect(graph.edges.map(edge => edge.number)).toEqual(links.map((_, i) => i + 1))
  expect(reverseLength(graph.edges.map(edge => edge.path))).toBe(0)
  for (const [i, edge] of graph.edges.entries()) {
    const route = points(edge.path)
    for (const [endIndex, id] of [[0, edge.from], [route.length - 1, edge.to]] as const) {
      const p = route[endIndex], box = graph.nodes.find(node => node.id === id)!
      expect(p.x >= box.x && p.x <= box.x + box.width && p.y >= box.y && p.y <= box.y + box.height).toBe(true)
      expect(p.x === box.x || p.x === box.x + box.width || p.y === box.y || p.y === box.y + box.height).toBe(true)
    }
    for (const [j, end] of route.slice(1).entries()) {
      const start = route[j]
      expect(start.x === end.x || start.y === end.y).toBe(true)
      for (const box of graph.nodes) {
        const enters = start.x === end.x
          ? start.x > box.x && start.x < box.x + box.width && Math.max(start.y, end.y) > box.y && Math.min(start.y, end.y) < box.y + box.height
          : start.y > box.y && start.y < box.y + box.height && Math.max(start.x, end.x) > box.x && Math.min(start.x, end.x) < box.x + box.width
        expect(enters, `${edge.from} -> ${edge.to} enters ${box.id}`).toBe(false)
      }
    }
    for (const p of [...route, { x: edge.labelX - 13, y: edge.labelY - 13 }, { x: edge.labelX + 13, y: edge.labelY + 13 }]) {
      expect(p.x >= 0 && p.x <= graph.width && p.y >= 0 && p.y <= graph.height).toBe(true)
    }
    for (const other of graph.edges.slice(i + 1)) expect(Math.hypot(edge.labelX - other.labelX, edge.labelY - other.labelY)).toBeGreaterThanOrEqual(26)
  }
}

it('separates a return to a shared node from a different incoming edge', () => {
  const nodes = ['sample', 'buffer', 'validation', 'feedback'].map(id => ({ id, label: id }))
  const links = [[0, 1], [1, 2], [2, 3], [3, 1]].map(([a, b], i) => ({ from: nodes[a].id, to: nodes[b].id, label: `Explicit relation ${i}` }))
  const before = JSON.stringify({ nodes, links })
  expectSeparated(diagramLayout(nodes, links, false), links)
  expect(JSON.stringify({ nodes, links })).toBe(before)
})

it('detects the positive-length return-stem ambiguity rather than just identical paths', () => {
  // Generic four-card topology: a different incoming edge and return edge share
  // one stem, despite having different complete paths and endpoint pairs.
  expect(reverseLength(['M 10 0 L 10 80 L 30 80', 'M 10 80 L 10 30 L 30 30'])).toBe(50)
})

it.each([false, true])('keeps shared-node, reverse, self and crowded reference detours separate (flow=%s)', flow => {
  const nodes = Array.from({ length: 12 }, (_, i) => ({ id: `part${i}`, label: i % 2 ? '合成记录需逐项校准，保留原值。' : `Synthetic part ${i}` }))
  for (let seed = 1; seed <= 16; seed++) {
    let state = seed
    const next = () => { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state >>> 16 }
    const links = Array.from({ length: 20 }, (_, i) => ({ from: nodes[next() % nodes.length].id, to: nodes[next() % nodes.length].id, label: `Relation ${i}` }))
    expectSeparated(diagramLayout(nodes, links, flow), links)
  }
})

it('keeps all directions clear even when many independent pairs share ports', () => {
  const nodes = Array.from({ length: 8 }, (_, i) => ({ id: `part${i}`, label: `Part ${i}` }))
  const links = nodes.flatMap(a => nodes.map(b => ({ from: a.id, to: b.id, label: `${a.id} / ${b.id}` })))
  for (const flow of [false, true]) expectSeparated(diagramLayout(nodes, links, flow), links)
})
