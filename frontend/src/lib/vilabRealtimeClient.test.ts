import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiJson } from './api'
import { VILabRealtimeClient } from './vilabRealtimeClient'

vi.mock('./api', () => ({ apiJson: vi.fn() }))
vi.mock('./livePcmCapture', () => ({ startLivePcmCapture: vi.fn(async () => ({ stop: () => new Uint8Array() })) }))

class Socket extends EventTarget {
  static OPEN = 1
  static CLOSING = 2
  static instance: Socket
  readyState = 1
  binaryType = ''
  send = vi.fn()
  close = vi.fn(() => { this.readyState = 3 })
  constructor() { super(); Socket.instance = this }
  message(data: object) { this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(data) })) }
}
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks() })
describe('shared cloud realtime session', () => {
  async function start() {
    vi.stubGlobal('WebSocket', Socket)
    vi.mocked(apiJson).mockResolvedValue({ url: 'ws://test', language: 'zh-CN', model: 'asr-test' })
    const onStatus = vi.fn()
    const client = new VILabRealtimeClient({ onStatus, onSegments: vi.fn() })
    const pending = client.start({} as MediaStream, 'meeting-test')
    await vi.waitFor(() => expect(Socket.instance).toBeDefined())
    await Promise.resolve()
    Socket.instance.dispatchEvent(new Event('open'))
    return { client, pending, onStatus }
  }
  it('uses the backend-resolved model without a runtime profile override', async () => {
    const { client, pending } = await start()
    const request = JSON.parse(Socket.instance.send.mock.calls[0][0])
    expect(request.type).toBe('session.start')
    expect(request).not.toHaveProperty('profileId')
    expect(request.model).toBe('asr-test')
    Socket.instance.message({ type: 'session.started' })
    await pending
    await client.cancel()
  })
  it('rejects a server startup error instead of leaving start pending', async () => {
    const { pending, onStatus } = await start()
    const rejected = expect(pending).rejects.toThrow('upstream unavailable')
    Socket.instance.message({ type: 'error', message: 'upstream unavailable' })
    await rejected
    expect(onStatus).toHaveBeenCalledWith('failed', 'upstream unavailable')
  })
})
