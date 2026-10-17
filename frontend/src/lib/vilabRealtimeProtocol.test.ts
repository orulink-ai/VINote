import { describe, expect, it } from 'vitest'
import { encodeVla2AudioFrame, parseRealtimeEvent } from './vilabRealtimeProtocol'

describe('VLA2 protocol', () => {
  it('encodes sequence, flags and payload length', () => {
    const bytes = new Uint8Array(encodeVla2AudioFrame(new Uint8Array([1, 2, 3]), 0, true))
    const view = new DataView(bytes.buffer)
    expect(new TextDecoder().decode(bytes.slice(0, 4))).toBe('VLA2')
    expect(bytes[4]).toBe(2)
    expect(bytes[6]).toBe(3)
    expect(view.getUint32(8, true)).toBe(0)
    expect(view.getUint32(16, true)).toBe(3)
    expect(Array.from(bytes.slice(20))).toEqual([1, 2, 3])
  })

  it('ignores malformed events', () => {
    expect(parseRealtimeEvent('{')).toBeNull()
    expect(parseRealtimeEvent('{"type":"asr.final","text":"好"}')?.text).toBe('好')
  })
})
