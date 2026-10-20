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

export const diagramLabelFont = '16px system-ui, sans-serif'
let labelContext: CanvasRenderingContext2D | null | undefined

function labelWidth(text: string): number {
  // The browser measures the same font used by preview and SVG/PNG export.
  // Non-browser rendering has a conservative fallback, without a DOM dependency.
  if (labelContext === undefined) {
    labelContext = typeof document !== 'undefined' && typeof CanvasRenderingContext2D !== 'undefined'
      ? document.createElement('canvas').getContext('2d') : null
  }
  if (labelContext) {
    labelContext.font = diagramLabelFont
    return labelContext.measureText(text).width
  }
  return Array.from(text).reduce((width, char) => width + (char.codePointAt(0)! > 0xffff ? 32 : 16), 0)
}

type TextSegmenter = new (locale: string, options: { granularity: 'word' | 'grapheme' }) => {
  segment(text: string): Iterable<{ segment: string; index: number }>
}

function textSegments(text: string, granularity: 'word' | 'grapheme') {
  // ES2020 builds can use newer WebView/ICU segmentation without requiring it.
  const Segmenter = (Intl as unknown as { Segmenter?: TextSegmenter }).Segmenter
  if (Segmenter) return Array.from(new Segmenter('zh', { granularity }).segment(text), part => part.segment)
  if (granularity === 'word') return text.match(/[A-Za-z0-9]+(?:[.:/%–-][A-Za-z0-9]+)*|[^\S\n]+|[\s\S]/gu) || []
  // Conservative fallback: preserve combining marks and emoji ZWJ sequences.
  // CJK boundaries remain character-based without an ICU dictionary.
  const result: string[] = []
  for (const char of text) {
    const previous = result[result.length - 1]
    // GB11 joins across ZWJ only from Extended_Pictographic Extend* ZWJ to
    // another pictograph. A ZWJ following Latin text must not absorb its next A.
    const emojiJoin = /^\p{Extended_Pictographic}$/u.test(char)
      && /\p{Extended_Pictographic}[\p{Grapheme_Extend}\p{Emoji_Modifier}]*\u200D$/u.test(previous || '')
    if (previous && (/^[\p{Mark}\uFE0E\uFE0F\u{1F3FB}-\u{1F3FF}\u200D]$/u.test(char) || emojiJoin
      || (/^[\u{1F1E6}-\u{1F1FF}]$/u.test(previous) && /^[\u{1F1E6}-\u{1F1FF}]$/u.test(char)))) {
      result[result.length - 1] += char
    } else result.push(char)
  }
  return result
}

// Closing punctuation stays with preceding text; opening brackets/quotes stay
// with following text. These are break constraints, never text substitutions.
const noLineStart = /^[\p{Pe}\p{Pf}、。，．？！：；％‰…·・,.:;!?%]/u
const noLineEnd = /[\p{Ps}\p{Pi}]$/u

/** Measured word wrapping with bounded emergency breaks; never rewrite a label. */
export function diagramTextLines(text: string, width: number, measure = labelWidth): string[] {
  return text.split('\n').flatMap(paragraph => {
    if (!paragraph) return ['']
    const graphemes = textSegments(paragraph, 'grapheme')
    const offsets = [0]
    graphemes.forEach(part => offsets.push(offsets[offsets.length - 1] + part.length))
    const words = new Set<number>()
    let offset = 0
    for (const part of textSegments(paragraph, 'word')) { offset += part.length; words.add(offset) }
    const keepTogether = (start: number, end: number) => {
      for (const boundary of words) if (boundary > start && boundary < end) words.delete(boundary)
    }
    // Dictionary boundaries vary across ICU versions. Keep a fitting list term
    // or short clause whole, without recognizing names or changing its text.
    for (const match of paragraph.matchAll(/[^、，,；;。！？!?]+/gu)) {
      if (measure(match[0]) <= width) keepTogether(match.index!, match.index! + match[0].length)
    }
    // ICU may split punctuation within a time/range/identifier. Keep the existing
    // technical-token boundary when it fits, without guessing entity meanings.
    for (const match of paragraph.matchAll(/[A-Za-z0-9]+(?:[.:/%–-][A-Za-z0-9]+)*/gu)) {
      keepTogether(match.index!, match.index! + match[0].length)
    }
    const legal = (end: number) => end === graphemes.length
      || (!noLineEnd.test(paragraph.slice(0, offsets[end]).trimEnd())
          && !noLineStart.test(paragraph.slice(offsets[end]).trimStart()))
    const lines: string[] = []
    let start = 0
    while (start < graphemes.length) {
      let fit = start
      while (fit < graphemes.length && measure(paragraph.slice(offsets[start], offsets[fit + 1])) <= width) fit++
      let end = fit
      if (fit < graphemes.length) {
        // Prefer whole words, then an allowed grapheme boundary. Backtracking
        // carries the preceding text with closing punctuation instead of spilling.
        while (end > start && !(words.has(offsets[end]) && legal(end))) end--
        if (end === start) { end = fit; while (end > start && !legal(end)) end-- }
      }
      // A long word still splits; a lone glyph wider than the entire box is the
      // same irreducible case as before, never a reason to lose its characters.
      if (end === start) end = Math.max(start + 1, fit)
      lines.push(paragraph.slice(offsets[start], offsets[end]))
      start = end
    }
    return lines
  })
}

type Point = { x: number; y: number }
type Box = DiagramLayout['nodes'][number]

function clearSegment(a: Point, b: Point, boxes: Box[]): boolean {
  return !boxes.some(box => a.y === b.y
    ? a.y > box.y && a.y < box.y + box.height && Math.max(a.x, b.x) > box.x && Math.min(a.x, b.x) < box.x + box.width
    : a.x > box.x && a.x < box.x + box.width && Math.max(a.y, b.y) > box.y && Math.min(a.y, b.y) < box.y + box.height)
}

function routeLink(a: Box, b: Box, boxes: Box[], slot: number, count: number): Point[] {
  const centerX = (box: Box) => box.x + box.width / 2
  const centerY = (box: Box) => box.y + box.height / 2
  const clearance = 28
  // Reverse and parallel links share a group but get different boundary ports.
  const offset = slot - (count - 1) / 2
  const portOffset = offset * Math.min(16, (a.width - 48) / Math.max(1, count - 1))
  if (a.id === b.id) {
    const x = a.x + a.width, top = centerY(a) - 24 - slot * 16, bottom = centerY(a) + 24 + slot * 16
    const lane = x + clearance + slot * 32
    return [{ x, y: top }, { x: lane, y: top }, { x: lane, y: bottom }, { x, y: bottom }]
  }
  if (a.y === b.y) {
    const right = b.x > a.x
    const start = { x: a.x + (right ? a.width : 0), y: centerY(a) + offset * 32 }
    const end = { x: b.x + (right ? 0 : b.width), y: centerY(b) + offset * 32 }
    if (clearSegment(start, end, boxes)) return [start, end]
    // A same-row skip link goes above the row, never through an intervening card.
    const y = a.y - clearance - slot * 32
    return [{ x: centerX(a) + portOffset, y: a.y }, { x: centerX(a) + portOffset, y }, { x: centerX(b) + portOffset, y }, { x: centerX(b) + portOffset, y: b.y }]
  }
  const down = b.y > a.y
  const start = { x: centerX(a) + portOffset, y: a.y + (down ? a.height : 0) }
  const end = { x: centerX(b) + portOffset, y: b.y + (down ? 0 : b.height) }
  const middle = (start.y + end.y) / 2 + offset * 32
  const direct = [start, { x: start.x, y: middle }, { x: end.x, y: middle }, end]
  if (direct.slice(1).every((p, i) => clearSegment(direct[i], p, boxes))) return direct
  // For multi-row links, exit through the free row gutters and use an outside
  // lane. Node positions and semantic endpoints are unchanged by routing.
  const lane = Math.min(...boxes.map(box => box.x)) - clearance - slot * 32
  const exitY = start.y + (down ? 1 : -1) * (clearance + slot * 32)
  const entryY = end.y - (down ? 1 : -1) * (clearance + slot * 32)
  return [start, { x: start.x, y: exitY }, { x: lane, y: exitY }, { x: lane, y: entryY }, { x: end.x, y: entryY }, end]
}

function reverseOverlap(route: Point[], occupied: Point[][]): boolean {
  return route.slice(1).some((end, i) => {
    const start = route[i], vertical = start.x === end.x
    return occupied.some(other => other.slice(1).some((q, j) => {
      const p = other[j]
      if (vertical ? p.x !== q.x || p.x !== start.x : p.y !== q.y || p.y !== start.y) return false
      const [a, b, c, d] = vertical ? [start.y, end.y, p.y, q.y] : [start.x, end.x, p.x, q.x]
      return (b - a) * (d - c) < 0 && Math.min(Math.max(a, b), Math.max(c, d)) > Math.max(Math.min(a, b), Math.min(c, d))
    }))
  })
}

function separateRoute(a: Box, b: Box, lane: number, index: number, count: number, occupied: Point[][]): Point[] {
  // All legs outside the endpoint cards use row gutters or a fresh outer lane.
  // Distinct ports/gutter levels also separate edges sharing a node, not just a
  // pair of endpoints. Trying new fractions avoids occupied collinear stems.
  const attempts = 8 * occupied.reduce((sum, route) => sum + route.length, 0) + 2
  for (let attempt = 0; attempt < attempts; attempt++) {
    const t = (attempt + 1) / (attempts + 1)
    const from = (index + .2 + .4 * t) / (count + 1), to = (index + .75 + .2 * t) / (count + 1)
    const down = b.y > a.y, sameRow = a.y === b.y
    const start = { x: a.x + 18 + (a.width - 36) * from, y: a.y + (!sameRow && down ? a.height : 0) }
    const end = { x: b.x + 18 + (b.width - 36) * to, y: b.y + (!sameRow && !down ? b.height : 0) }
    const exitY = start.y + (sameRow || !down ? -1 : 1) * (16 + 8 * from)
    const entryY = end.y + (sameRow || down ? -1 : 1) * (16 + 8 * to)
    const route = [start, { x: start.x, y: exitY }, { x: lane, y: exitY }, { x: lane, y: entryY }, { x: end.x, y: entryY }, end]
    if (!reverseOverlap(route, occupied)) return route
  }
  throw new Error('Unable to separate diagram relationship routes')
}

export function diagramLayout(items: DiagramItem[], links: DiagramLink[], flow: boolean): DiagramLayout {
  const groupKey = (link: DiagramLink) => JSON.stringify([link.from, link.to].sort())
  const groupCounts = new Map<string, number>()
  links.forEach(link => groupCounts.set(groupKey(link), (groupCounts.get(groupKey(link)) || 0) + 1))
  const extraLanes = Math.max(1, ...groupCounts.values()) - 1
  const extraSelfLanes = Math.max(1, ...items.map(item => groupCounts.get(groupKey({ from: item.id, to: item.id, label: '' })) || 0)) - 1
  const boxWidth = 272, gap = 56 + extraSelfLanes * 64, margin = 56
  const rowGap = 100 + extraLanes * 32
  const lines = new Map(items.map(item => [item.id, diagramTextLines(item.label, boxWidth - 36)]))
  const boxHeight = Math.max(100 + extraLanes * 32, ...Array.from(lines.values(), value => value.length * 22 + 54))
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
        y, lines: lines.get(item.id)! }))
      y += boxHeight + rowGap
    }
  }
  const groupSlots = new Map<string, number>()
  const routes: Point[][] = []
  links.forEach((link, index) => {
    const a = nodes.find(node => node.id === link.from)!, b = nodes.find(node => node.id === link.to)!
    const key = groupKey(link), slot = groupSlots.get(key) || 0
    groupSlots.set(key, slot + 1)
    let route = routeLink(a, b, nodes, slot, groupCounts.get(key)!)
      .filter((p, i, all) => !i || p.x !== all[i - 1].x || p.y !== all[i - 1].y)
    if (reverseOverlap(route, routes)) {
      const lane = Math.min(...nodes.map(node => node.x), ...routes.flat().map(p => p.x)) - 32
      route = separateRoute(a, b, lane, index, links.length, routes)
    }
    routes.push(route)
  })
  const labels: Point[] = []
  const clearLabel = (p: Point) => !nodes.some(box => p.x + 13 > box.x && p.x - 13 < box.x + box.width && p.y + 13 > box.y && p.y - 13 < box.y + box.height)
    && labels.every(other => Math.hypot(p.x - other.x, p.y - other.y) >= 30)
  const edges = links.map((link, index) => {
    let points = routes[index]
    const segments = points.slice(1).map((end, i) => ({ start: points[i], end, length: Math.hypot(end.x - points[i].x, end.y - points[i].y) }))
      .filter(segment => segment.length > 0).sort((a, b) => b.length - a.length)
    let label: Point | undefined
    for (const { start, end, length } of segments) {
      // Try the midpoint first, then separated positions along the same segment.
      for (let step = 0; step <= Math.floor(length / 32) && !label; step++) {
        for (const distance of step ? [step * 16, -step * 16] : [0]) {
          const t = 0.5 + distance / length
          if (t < 0 || t > 1) continue
          const candidate = { x: start.x + (end.x - start.x) * t, y: start.y + (end.y - start.y) * t }
          if (clearLabel(candidate)) { label = candidate; break }
        }
      }
      if (label) break
    }
    if (!label) {
      // Crowded short segments get a dedicated outside lane rather than hiding
      // a reference. Row gutters keep its entry/exit away from all other cards.
      const a = nodes.find(node => node.id === link.from)!, b = nodes.find(node => node.id === link.to)!
      const lane = Math.min(...nodes.map(node => node.x), ...routes.flat().map(p => p.x), ...labels.map(p => p.x - 13)) - 32
      points = separateRoute(a, b, lane, index, links.length, routes.filter((_, i) => i !== index))
      routes[index] = points
      label = { x: lane, y: (points[2].y + points[3].y) / 2 }
    }
    labels.push(label)
    return { ...link, number: index + 1, path: points.map((p, i) => `${i ? 'L' : 'M'} ${p.x} ${p.y}`).join(' '), labelX: label.x, labelY: label.y }
  })
  // Include every route and full reference circle in both screen/export bounds.
  const bounds = [...routes.flat(), ...labels.flatMap(p => [{ x: p.x - 13, y: p.y - 13 }, { x: p.x + 13, y: p.y + 13 }])]
  const shiftX = Math.max(0, 16 - Math.min(margin, ...bounds.map(p => p.x)))
  const shiftY = Math.max(0, 16 - Math.min(margin, ...bounds.map(p => p.y)))
  nodes.forEach(node => { node.x += shiftX; node.y += shiftY })
  edges.forEach((edge, index) => {
    edge.path = routes[index].map((p, i) => `${i ? 'L' : 'M'} ${p.x + shiftX} ${p.y + shiftY}`).join(' ')
    edge.labelX += shiftX; edge.labelY += shiftY
  })
  return { width: Math.max(width, ...bounds.map(p => p.x + 16)) + shiftX,
    height: Math.max(y - rowGap + margin, ...bounds.map(p => p.y + 16), 32) + shiftY, nodes, edges }
}
