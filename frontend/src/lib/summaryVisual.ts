/** Wire contract shared with the backend summary-visual/1 sidecar. */
export type VisualBlock = { id: string; text: string; claim_ids: string[] }
export type VisualFrame = { id: string; screenshot_index: number; timestamp_seconds: number; grounded_label: string }
export type VisualScene = { id: string; block_ids: string[]; frame_id: string; grounded_label: string }
export type VisualNode = { id: string; block_ids: string[]; grounded_label: string }
export type VisualEdge = VisualNode & { from: string; to: string }
export type SummaryVisual = {
  visual_protocol: 1; task_id: string; presentation: 'comic' | 'infographic'; body_sha256: string
  blocks: VisualBlock[]; frames: VisualFrame[]; scenes: VisualScene[]
  diagram: null | { kind: 'cards' | 'comparison' | 'flow' | 'relationship'; nodes: VisualNode[]; edges: VisualEdge[] }
}
export type VisualValidation = { ok: true; value: SummaryVisual } | { ok: false; reason: string }
const taskPattern = /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/
const idPattern = /^[A-Za-z0-9_[\]:.-]{1,64}$/
function fail(reason = '图形数据无法核验，正文仍保留。'): never { throw new Error(reason) }
function record(value: unknown, keys: string[]): asserts value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !keys.includes(key)) || keys.some(key => !(key in value))) fail()
}
function rows(value: unknown, max: number, min = 0): asserts value is unknown[] {
  if (!Array.isArray(value) || value.length < min || value.length > max) fail('图形内容超出支持范围，未截断原图。')
}
function text(value: unknown, max: number): asserts value is string {
  if (typeof value !== 'string' || !value.trim() || Array.from(value).length > max) fail()
}
function id(value: unknown): asserts value is string { if (typeof value !== 'string' || !idPattern.test(value)) fail() }
function label(value: unknown): asserts value is string {
  text(value, 120)
  // A technical URL or comparison is harmless text. Labels never become href,
  // markup, styles or resource paths, so do not reject legitimate meeting facts.
  if (/[\u0000-\u001f\u007f]/.test(value)) fail('图形标签含不可显示字符，正文仍保留。')
}
function unique(values: string[]) { if (new Set(values).size !== values.length) fail() }

/** Structural validation is repeated on the device; no model coordinates/markup survive. */
export function parseSummaryVisual(input: unknown, taskId: string, presentation: 'comic' | 'infographic'): VisualValidation {
  try {
    if (new TextEncoder().encode(JSON.stringify(input)).length > 128 * 1024) fail('图形数据过大，未截断原图。')
    record(input, ['visual_protocol', 'task_id', 'presentation', 'body_sha256', 'blocks', 'frames', 'scenes', 'diagram'])
    if (!taskPattern.test(taskId) || input.visual_protocol !== 1 || input.task_id !== taskId || input.presentation !== presentation || typeof input.body_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(input.body_sha256)) fail('图形与当前纪要版本不一致，正文仍保留。')
    rows(input.blocks, 64, 1)
    const blocks = new Map<string, VisualBlock>()
    for (const block of input.blocks) {
      record(block, ['id', 'text', 'claim_ids']); id(block.id); text(block.text, 6000); rows(block.claim_ids, 64)
      block.claim_ids.forEach(id); unique(block.claim_ids as string[])
      if (blocks.has(block.id)) fail()
      blocks.set(block.id, block as VisualBlock)
    }
    function references(value: unknown): string[] {
      rows(value, 8, 1); value.forEach(id); unique(value as string[])
      if (!value.every(key => blocks.has(key as string)) || !value.some(key => blocks.get(key as string)!.claim_ids.length)) fail('图形引用的正文依据缺失，未补造关联。')
      return value as string[]
    }
    function grounded(value: unknown, refs: string[]) {
      label(value)
      if (!refs.some(key => blocks.get(key)!.text.includes(value))) fail('图形标签与正文依据不一致，未补造内容。')
    }
    rows(input.frames, 8); rows(input.scenes, 8)
    const frames = new Map<string, VisualFrame>(), indices = new Set<number>()
    for (const frame of input.frames) {
      record(frame, ['id', 'screenshot_index', 'timestamp_seconds', 'grounded_label']); id(frame.id); label(frame.grounded_label)
      if (frames.has(frame.id) || typeof frame.screenshot_index !== 'number' || !Number.isInteger(frame.screenshot_index) || frame.screenshot_index < 0 || frame.screenshot_index > 7 || indices.has(frame.screenshot_index) || typeof frame.timestamp_seconds !== 'number' || !Number.isFinite(frame.timestamp_seconds) || frame.timestamp_seconds < 0) fail()
      frames.set(frame.id, frame as VisualFrame); indices.add(frame.screenshot_index)
    }
    const sceneIds: string[] = [], frameBlocks = new Map<string, string[]>()
    for (const scene of input.scenes) {
      record(scene, ['id', 'block_ids', 'frame_id', 'grounded_label']); id(scene.id); id(scene.frame_id)
      const refs = references(scene.block_ids); grounded(scene.grounded_label, refs)
      if (!frames.has(scene.frame_id)) fail('分镜缺少对应原始画面，未用卡片替代。')
      frameBlocks.set(scene.frame_id, [...(frameBlocks.get(scene.frame_id) || []), ...refs]); sceneIds.push(scene.id)
    }
    unique(sceneIds)
    if (presentation === 'comic') {
      if (!input.scenes.length || !input.frames.length || input.diagram !== null || [...frames.keys()].some(key => !frameBlocks.has(key))) fail()
      for (const frame of frames.values()) grounded(frame.grounded_label, frameBlocks.get(frame.id)!)
    } else {
      if (input.scenes.length) fail()
      record(input.diagram, ['kind', 'nodes', 'edges'])
      if (!['cards', 'comparison', 'flow', 'relationship'].includes(input.diagram.kind as string)) fail()
      rows(input.diagram.nodes, 12, 1); rows(input.diagram.edges, 20)
      const nodes: string[] = [], edges: string[] = []
      for (const node of input.diagram.nodes) {
        record(node, ['id', 'block_ids', 'grounded_label']); id(node.id)
        grounded(node.grounded_label, references(node.block_ids)); nodes.push(node.id)
      }
      unique(nodes)
      for (const edge of input.diagram.edges) {
        record(edge, ['id', 'from', 'to', 'block_ids', 'grounded_label']); id(edge.id); id(edge.from); id(edge.to)
        if (!nodes.includes(edge.from) || !nodes.includes(edge.to)) fail('关系图节点缺失，未补造对象。')
        grounded(edge.grounded_label, references(edge.block_ids)); edges.push(edge.id)
      }
      unique(edges)
      if (['cards', 'comparison'].includes(input.diagram.kind as string) && input.diagram.edges.length) fail()
    }
    return { ok: true, value: input as SummaryVisual }
  } catch (error) { return { ok: false, reason: error instanceof Error ? error.message : '图形数据无法核验，正文仍保留。' } }
}

export async function validateSummaryVisual(input: unknown, taskId: string, presentation: 'comic' | 'infographic', savedBody: string): Promise<VisualValidation> {
  const parsed = parseSummaryVisual(input, taskId, presentation)
  if (!parsed.ok) return parsed
  try {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(savedBody))
    const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
    if (hash !== parsed.value.body_sha256 || parsed.value.blocks.some(block => !savedBody.includes(block.text))) return { ok: false, reason: '图形对应的已保存正文已变化，请查看当前正文。' }
    return parsed
  } catch { return { ok: false, reason: '无法核验图形的正文版本，正文仍保留。' } }
}

export function visualFramePath(taskId: string, index: number) {
  if (!taskPattern.test(taskId) || !Number.isInteger(index) || index < 0 || index > 7) throw new Error('截图引用无效')
  return `/api/task/${taskId}/artifacts/screenshots/summary-source-${index}.jpg`
}
export function visualTimestamp(seconds: number) {
  const total = Math.floor(seconds), h = Math.floor(total / 3600), m = Math.floor(total % 3600 / 60), s = total % 60
  return `${h ? `${h}:` : ''}${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
