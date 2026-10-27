import type { SummaryVisual } from '../src/lib/summaryVisual'

// Entirely synthetic; not based on either retained meeting or any model output.
export const visualTask = '11111111-1111-4111-8111-111111111111'
export const visualTitle = '星港观测站联调 · 合成验收示例'
export const fixtureBlocks = [
  { id: 'B1', text: '## 星港观测站联调（合成示例）', claim_ids: [] },
  { id: 'B2', text: '采集端先完成离线校准。缓存延迟 < 120ms，http://sensor.example.invalid 仅为技术说明。', claim_ids: ['C1', 'C2'] },
  { id: 'B3', text: '离线校准通过后，传感器数据进入缓冲队列。缓冲队列保留异常样本，供控制台复核。', claim_ids: ['C3', 'C4'] },
  { id: 'B4', text: '控制台复核异常样本后，由值班员确认。控制台复核结果返回采集端。', claim_ids: ['C5', 'C6'] },
]
export const visualSavedBody = fixtureBlocks.map(block => block.text).join('\n\n')
export async function makeVisualFixture(presentation: 'comic' | 'infographic' = 'comic'): Promise<SummaryVisual> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(visualSavedBody))
  const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
  return {
    visual_protocol: 1, task_id: visualTask, presentation, body_sha256: hash,
    blocks: structuredClone(fixtureBlocks),
    frames: presentation === 'comic' ? [
      { id: '[FRAME:0001]', screenshot_index: 0, timestamp_seconds: 64.2, grounded_label: '采集端先完成离线校准' },
      { id: '[FRAME:0002]', screenshot_index: 1, timestamp_seconds: 132.5, grounded_label: '缓冲队列保留异常样本' },
    ] : [],
    scenes: presentation === 'comic' ? [
      { id: 'S1', block_ids: ['B2'], frame_id: '[FRAME:0001]', grounded_label: '缓存延迟 < 120ms，http://sensor.example.invalid 仅为技术说明。' },
      { id: 'S2', block_ids: ['B3'], frame_id: '[FRAME:0002]', grounded_label: '缓冲队列保留异常样本，供控制台复核。' },
    ] : [],
    diagram: presentation === 'infographic' ? { kind: 'flow', nodes: [
      { id: 'N1', block_ids: ['B2'], grounded_label: '采集端' },
      { id: 'N2', block_ids: ['B3'], grounded_label: '缓冲队列' },
      { id: 'N3', block_ids: ['B4'], grounded_label: '控制台复核' },
      { id: 'N4', block_ids: ['B4'], grounded_label: '值班员确认' },
    ], edges: [
      { id: 'E1', from: 'N1', to: 'N2', block_ids: ['B3'], grounded_label: '离线校准通过后，传感器数据进入缓冲队列' },
      { id: 'E2', from: 'N2', to: 'N3', block_ids: ['B3'], grounded_label: '缓冲队列保留异常样本，供控制台复核' },
      { id: 'E3', from: 'N3', to: 'N4', block_ids: ['B4'], grounded_label: '控制台复核异常样本后，由值班员确认' },
    ] } : null,
  }
}
