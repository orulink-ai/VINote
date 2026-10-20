/** Renderer-owned geometry. Model data never supplies coordinates, styles or SVG. */
export type DiagramItem = { id: string; label: string }
export type DiagramLink = { from: string; to: string; label: string }
export type DiagramLayout = {
  width: number; height: number
  nodes: Array<DiagramItem & { x: number; y: number; width: number; height: number; lines: string[] }>
  edges: Array<DiagramLink & { path: string; number: number; labelX: number; labelY: number }>
}

/** Count wide characters as two units; never ellipsize or lose the saved label. */
export function visualTextLines(text: string, units = 32): string[] {
  const lines: string[] = []
  let line = '', used = 0
  for (const char of text) {
    const size = char.codePointAt(0)! > 255 ? 2 : 1
    if (char === '\n' || used + size > units) {
      lines.push(line); line = ''; used = 0
      if (char === '\n') continue
    }
    line += char; used += size
  }
  if (line || !lines.length) lines.push(line)
  return lines
}

export function diagramLayout(items: DiagramItem[], links: DiagramLink[], flow: boolean): DiagramLayout {
  const boxWidth = 272, gap = 56, margin = 56
  const boxHeight = Math.max(100, ...items.map(item => visualTextLines(item.label).length * 22 + 54))
  const incoming = new Map(items.map(item => [item.id, 0]))
  const rank = new Map(items.map(item => [item.id, 0]))
  links.forEach(link => incoming.set(link.to, (incoming.get(link.to) || 0) + 1))
  const queue = items.filter(item => incoming.get(item.id) === 0).map(item => item.id)
  let visited = 0
  while (queue.length) {
    const id = queue.shift()!; visited++
    for (const link of links.filter(link => link.from === id)) {
      rank.set(link.to, Math.max(rank.get(link.to) || 0, rank.get(id)! + 1))
      incoming.set(link.to, incoming.get(link.to)! - 1)
      if (incoming.get(link.to) === 0) queue.push(link.to)
    }
  }
  // Cycles are displayed as supplied relationships, never silently dropped or
  // interpreted as a temporal sequence. The textual edge index remains complete.
  const rows: DiagramItem[][] = []
  for (const [index, item] of items.entries()) {
    const level = flow && visited === items.length ? rank.get(item.id)! : Math.floor(index / 3)
    ;(rows[level] ||= []).push(item)
  }
  const columns = Math.min(3, Math.max(1, ...rows.filter(Boolean).map(row => row.length)))
  const width = columns * boxWidth + (columns - 1) * gap + margin * 2
  const nodes: DiagramLayout['nodes'] = []
  let y = margin
  for (const row of rows) {
    if (!row) continue
    for (let offset = 0; offset < row.length; offset += 3) {
      const slice = row.slice(offset, offset + 3)
      slice.forEach((item, index) => nodes.push({ ...item, width: boxWidth, height: boxHeight,
        x: (width - slice.length * boxWidth - (slice.length - 1) * gap) / 2 + index * (boxWidth + gap),
        y, lines: visualTextLines(item.label) }))
      y += boxHeight + 100
    }
  }
  const edges = links.map((link, index) => {
    const a = nodes.find(node => node.id === link.from)!, b = nodes.find(node => node.id === link.to)!
    if (a.id === b.id) {
      const x = a.x + a.width, y1 = a.y + 24, y2 = a.y + a.height - 24
      return { ...link, number: index + 1, path: `M ${x} ${y1} C ${x + 50} ${y1 - 16}, ${x + 50} ${y2 + 16}, ${x} ${y2}`,
        labelX: x + 34, labelY: (y1 + y2) / 2 }
    }
    if (a.y === b.y) {
      const rightward = b.x > a.x
      const x1 = a.x + (rightward ? a.width : 0), x2 = b.x + (rightward ? 0 : b.width)
      const center = a.y + a.height / 2
      const bend = center - 35 - (index % 3) * 18
      return { ...link, number: index + 1, path: `M ${x1} ${center} C ${x1 + (rightward ? 24 : -24)} ${bend}, ${x2 + (rightward ? -24 : 24)} ${bend}, ${x2} ${center}`,
        labelX: (x1 + x2) / 2, labelY: bend }
    }
    const down = b.y > a.y, x1 = a.x + a.width / 2, x2 = b.x + b.width / 2
    const y1 = a.y + (down ? a.height : 0), y2 = b.y + (down ? 0 : b.height)
    if (Math.abs(a.y - b.y) > boxHeight + 110 || !down) {
      const lane = 20 + (index % 3) * 12
      return { ...link, number: index + 1, path: `M ${a.x} ${a.y + a.height / 2} H ${lane} V ${b.y + b.height / 2} H ${b.x}`,
        labelX: lane + 8, labelY: (a.y + b.y + boxHeight) / 2 }
    }
    return { ...link, number: index + 1, path: `M ${x1} ${y1} C ${x1} ${y1 + 48}, ${x2} ${y2 - 48}, ${x2} ${y2}`,
      labelX: (x1 + x2) / 2, labelY: (y1 + y2) / 2 }
  })
  return { width, height: y - 100 + margin, nodes, edges }
}
