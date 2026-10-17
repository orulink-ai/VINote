export const VLA2_FIRST = 0x01
export const VLA2_LAST = 0x02

export function encodeVla2AudioFrame(payload: Uint8Array, sequence: number, last = false) {
  const packet = new Uint8Array(20 + payload.byteLength)
  const view = new DataView(packet.buffer)
  packet.set([0x56, 0x4c, 0x41, 0x32, 2, 1, (sequence === 0 ? VLA2_FIRST : 0) | (last ? VLA2_LAST : 0), 0])
  view.setUint32(8, sequence >>> 0, true)
  view.setUint32(12, Math.floor(sequence / 0x100000000), true)
  view.setUint32(16, payload.byteLength, true)
  packet.set(payload, 20)
  return packet.buffer
}

export function parseRealtimeEvent(value: string): Record<string, unknown> | null {
  try {
    const event = JSON.parse(value)
    return event && typeof event === 'object' && typeof event.type === 'string' ? event : null
  } catch {
    return null
  }
}
