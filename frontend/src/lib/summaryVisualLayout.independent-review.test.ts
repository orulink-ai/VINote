import { expect, it } from 'vitest'
import { diagramLayout, type DiagramLink } from './summaryVisualLayout'

const nodes = [{ id: 'A', label: 'Acquisition' }, { id: 'B', label: 'Controller' }]
const cases: Array<[string, DiagramLink[]]> = [
  ['opposite directions', [{ from: 'A', to: 'B', label: 'command' }, { from: 'B', to: 'A', label: 'acknowledgement' }]],
  ['parallel relationships', [{ from: 'A', to: 'B', label: 'telemetry' }, { from: 'A', to: 'B', label: 'control' }]],
  ['multiple self links', [{ from: 'A', to: 'A', label: 'validation' }, { from: 'A', to: 'A', label: 'retention' }]],
]

it.each(cases)('keeps numbered references separately legible for %s', (_name, links) => {
  for (const flow of [false, true]) {
    const graph = diagramLayout(nodes, links, flow)
    expect(graph.edges.map(edge => edge.label)).toEqual(links.map(link => link.label))
    const [first, second] = graph.edges
    // DiagramGraphic renders an opaque circle of radius 13 for each reference.
    // A later circle at the same center completely hides the earlier number.
    expect(Math.hypot(first.labelX - second.labelX, first.labelY - second.labelY)).toBeGreaterThanOrEqual(26)
  }
})
