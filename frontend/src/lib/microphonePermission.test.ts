import { describe, expect, it, vi } from 'vitest'
import { checkMicrophoneReadiness, mapMicrophoneError } from './microphonePermission'

describe('microphonePermission', () => {
  it('reports unsupported when getUserMedia is unavailable', async () => {
    await expect(checkMicrophoneReadiness({ mediaDevices: undefined })).resolves.toEqual({
      ok: false,
      reason: 'unsupported',
    })
  })

  it('reports denied when browser permissions are denied', async () => {
    const permissions = {
      query: vi.fn().mockResolvedValue({ state: 'denied' }),
    } as unknown as Permissions
    const mediaDevices = {
      getUserMedia: vi.fn(),
    } as unknown as MediaDevices

    await expect(checkMicrophoneReadiness({ permissions, mediaDevices })).resolves.toEqual({
      ok: false,
      reason: 'denied',
    })
  })

  it('reports missing audio input after permission is granted', async () => {
    const permissions = {
      query: vi.fn().mockResolvedValue({ state: 'granted' }),
    } as unknown as Permissions
    const mediaDevices = {
      getUserMedia: vi.fn(),
      enumerateDevices: vi.fn().mockResolvedValue([{ kind: 'videoinput' }]),
    } as unknown as MediaDevices

    await expect(checkMicrophoneReadiness({ permissions, mediaDevices })).resolves.toEqual({
      ok: false,
      reason: 'no-device',
    })
  })

  it('maps common getUserMedia failures to stable reasons', () => {
    expect(mapMicrophoneError(new DOMException('', 'NotAllowedError'))).toBe('denied')
    expect(mapMicrophoneError(new DOMException('', 'NotFoundError'))).toBe('no-device')
    expect(mapMicrophoneError(new DOMException('', 'NotReadableError'))).toBe('unavailable')
    expect(mapMicrophoneError(new Error('Device is busy or unavailable'))).toBe('unavailable')
  })
})
