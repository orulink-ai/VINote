/** A bounded data parser, never a Mermaid/SVG/HTML interpreter. */
export type FlowPoint = { x: number; y: number }
export type FlowNode = { id: string; label: string; shape: 'box' | 'decision' | 'round'; x: number; y: number; width: number; height: number }
export type FlowEdge = { from: string; to: string; label: string; points: FlowPoint[]; labelAt: FlowPoint }
export type FlowGraph = { direction: 'TD' | 'LR'; nodes: FlowNode[]; edges: FlowEdge[]; width: number; height: number }
export type FlowResult = { ok: true; graph: FlowGraph } | { ok: false; reason: string }
type ParsedNode = Pick<FlowNode, 'id' | 'label' | 'shape'> & { defined: boolean }
type ParsedEdge = Pick<FlowEdge, 'from' | 'to' | 'label'>

function fail(reason: string): never { throw new Error(reason) }
function labelText(value: string, limit = 60) {
  const label = value.trim()
  if (!label || Array.from(label).length > limit) fail(`标签须为 1–${limit} 个字符，未截断原图`)
  if (/[<>\u0000-\u001f\u007f]/.test(label) || /(?:https?|data|javascript|file):/i.test(label)) fail('图中不支持 HTML、链接或外部资源')
  return label
}

export function flowLabelLines(value: string): string[] {
  const chars = Array.from(value), lines: string[] = []
  for (let offset = 0; offset < chars.length; offset += 14) lines.push(chars.slice(offset, offset + 14).join(''))
  return lines
}

export function parseSimpleFlowchart(source: string): FlowResult {
  try {
    if (source.length > 12000) fail('流程图源码超过 12000 字符，未截断原图')
    if (/<|%%|(?:https?|data|javascript|file):|\b(?:click|style|classDef|linkStyle|subgraph|class|image|icon)\b/i.test(source)) fail('不支持 HTML、交互指令、样式配置或外部资源')
    const statements = source.trim().split(/[\n;]/).map(line => line.trim()).filter(Boolean)
    const header = /^(?:flowchart|graph)\s+(TD|TB|LR)$/.exec(statements.shift() || '')
    if (!header) fail('仅支持 flowchart TD/TB/LR 的简单有向图')
    const direction: 'TD' | 'LR' = header![1] === 'LR' ? 'LR' : 'TD'
    const nodes = new Map<string, ParsedNode>(), edges: ParsedEdge[] = []

    function node(input: string): { id: string; rest: string } {
      const match = /^([A-Za-z_][A-Za-z0-9_]{0,39})/.exec(input.trim())
      if (!match) fail('节点标识须为最多 40 位字母、数字或下划线')
      const id = match![1]
      let rest = input.trim().slice(id.length).trim(), label = id
      let shape: ParsedNode['shape'] = 'box', defined = false
      const opening = rest[0], closing = ({ '[': ']', '{': '}', '(': ')' } as Record<string, string>)[opening]
      if (closing) {
        defined = true; shape = opening === '{' ? 'decision' : opening === '(' ? 'round' : 'box'
        rest = rest.slice(1).trim()
        if (rest.startsWith('"')) {
          const quoted = /^"(?:[^"\\]|\\.)*"/.exec(rest)
          if (!quoted) fail('节点文字的引号或转义不完整')
          try { label = JSON.parse(quoted![0]) as string } catch { fail('节点文字转义不受支持') }
          rest = rest.slice(quoted![0].length).trim()
          if (!rest.startsWith(closing)) fail('不支持嵌套节点形状或额外属性')
          rest = rest.slice(1).trim()
        } else {
          const end = rest.indexOf(closing)
          if (end < 0) fail('节点形状未闭合')
          label = rest.slice(0, end); rest = rest.slice(end + 1).trim()
        }
        label = labelText(label)
        if (/[\[\]{}()]/.test(label)) fail('标签中的嵌套形状字符暂不支持')
      }
      const previous = nodes.get(id)
      if (previous?.defined && defined && (previous.label !== label || previous.shape !== shape)) fail('同一节点出现不同定义，无法确认原图')
      if (!previous || defined) nodes.set(id, { id, label, shape, defined })
      if (nodes.size > 20) fail('流程图超过 20 个节点，未截断原图')
      return { id, rest }
    }

    for (const statement of statements) {
      let current = node(statement)
      while (current.rest) {
        let rest = current.rest, label = ''
        if (rest.startsWith('-->')) {
          rest = rest.slice(3).trim()
          if (rest.startsWith('|')) {
            const end = rest.indexOf('|', 1)
            if (end < 0) fail('关系标签未闭合')
            label = labelText(rest.slice(1, end), 40); rest = rest.slice(end + 1).trim()
          }
        } else {
          const labeled = /^--\s+(.+?)\s+-->\s*/.exec(rest)
          if (!labeled) fail('仅支持 -->、-->|关系| 或 -- 关系 -->；未执行其他语法')
          label = labelText(labeled![1], 40); rest = rest.slice(labeled![0].length)
        }
        const next = node(rest)
        edges.push({ from: current.id, to: next.id, label })
        if (edges.length > 40) fail('流程图超过 40 条边，未截断原图')
        current = next
      }
    }
    if (!nodes.size) fail('没有可显示的流程节点')
    const incoming = new Map([...nodes.keys()].map(id => [id, 0]))
    const levels = new Map([...nodes.keys()].map(id => [id, 0]))
    for (const edge of edges) incoming.set(edge.to, incoming.get(edge.to)! + 1)
    const queue = [...nodes.keys()].filter(id => incoming.get(id) === 0)
    let visited = 0
    while (queue.length) {
      const id = queue.shift()!; visited++
      for (const edge of edges.filter(edge => edge.from === id)) {
        levels.set(edge.to, Math.max(levels.get(edge.to)!, levels.get(id)! + 1))
        incoming.set(edge.to, incoming.get(edge.to)! - 1)
        if (incoming.get(edge.to) === 0) queue.push(edge.to)
      }
    }
    if (visited !== nodes.size) fail('环路暂不支持显示，请查看完整源码与文字依据')
    const rows: ParsedNode[][] = []
    for (const item of nodes.values()) (rows[levels.get(item.id)!] ||= []).push(item)
    const maxCount = Math.max(...rows.map(row => row.length)), margin = 24, nodeWidth = 220, nodeHeight = Math.max(64, ...Array.from(nodes.values()).map(item => flowLabelLines(item.label).length * 18 + 32))
    const horizontal = 296, vertical = nodeHeight + 80
    const positioned: FlowNode[] = rows.flatMap((row, level) => row.map((item, index) => ({
      id: item.id, label: item.label, shape: item.shape, width: nodeWidth, height: nodeHeight,
      x: margin + (direction === 'TD' ? index + (maxCount - row.length) / 2 : level) * horizontal,
      y: margin + (direction === 'TD' ? level : index + (maxCount - row.length) / 2) * vertical,
    })))
    const bodyWidth = Math.max(...positioned.map(item => item.x + item.width)) + margin
    const bodyHeight = Math.max(...positioned.map(item => item.y + item.height)) + margin
    let lanes = 0
    const routed: FlowEdge[] = edges.map(edge => {
      const from = positioned.find(item => item.id === edge.from)!, to = positioned.find(item => item.id === edge.to)!
      const start = direction === 'TD' ? { x: from.x + nodeWidth / 2, y: from.y + nodeHeight } : { x: from.x + nodeWidth, y: from.y + nodeHeight / 2 }
      const end = direction === 'TD' ? { x: to.x + nodeWidth / 2, y: to.y } : { x: to.x, y: to.y + nodeHeight / 2 }
      let points = [start, end]
      if (levels.get(edge.to)! - levels.get(edge.from)! > 1) {
        const lane = (direction === 'TD' ? bodyWidth : bodyHeight) + 24 + lanes++ * 18
        points = direction === 'TD'
          ? [start, { x: start.x, y: start.y + 24 }, { x: lane, y: start.y + 24 }, { x: lane, y: end.y - 24 }, { x: end.x, y: end.y - 24 }, end]
          : [start, { x: start.x + 24, y: start.y }, { x: start.x + 24, y: lane }, { x: end.x - 24, y: lane }, { x: end.x - 24, y: end.y }, end]
      }
      const middle = Math.floor((points.length - 1) / 2)
      const a = points[middle], b = points[middle + 1]
      return { ...edge, points, labelAt: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } }
    })
    return { ok: true, graph: { direction, nodes: positioned, edges: routed,
      width: bodyWidth + (direction === 'TD' && lanes ? 144 + lanes * 18 : 0),
      height: bodyHeight + (direction === 'LR' && lanes ? 48 + lanes * 18 : 0) } }
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? error.message : '此流程图暂不支持显示' }
  }
}
