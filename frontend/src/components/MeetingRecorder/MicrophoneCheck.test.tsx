import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const capture = vi.hoisted(() => ({ acquire: vi.fn() }))
vi.mock('@/lib/meetingCapture', () => ({ acquireMeetingMicrophone: capture.acquire }))
import { MicrophoneCheck } from './MicrophoneCheck'
describe('microphone check owns and releases its input', () => {
  const stop = vi.fn(), close = vi.fn().mockResolvedValue(undefined)
  beforeEach(() => {
    vi.clearAllMocks(); vi.useFakeTimers()
    capture.acquire.mockResolvedValue({ getTracks: () => [{ stop }] })
    vi.stubGlobal('AudioContext', class {
      state = 'running'
      resume = async () => {}
      close = close
      createMediaStreamSource = () => ({ connect: vi.fn() })
      createAnalyser = () => ({ fftSize: 512, getFloatTimeDomainData: (data: Float32Array) => data.fill(.1) })
    })
  })
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })
  it('measures actual input and releases after the bounded test', async () => {
    render(<MicrophoneCheck deviceId="headset" />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: '测试麦克风' })))
    act(() => vi.advanceTimersByTime(100))
    expect(Number(screen.getByRole('meter').getAttribute('aria-valuenow'))).toBeGreaterThan(0)
    act(() => vi.advanceTimersByTime(10000))
    expect(stop).toHaveBeenCalledTimes(1)
    expect(close).toHaveBeenCalledTimes(1)
    expect(screen.getByText(/测试完成/)).toBeInTheDocument()
  })
  it('releases a late permission result after the dialog is closed', async () => {
    let resolve!: (value: unknown) => void
    capture.acquire.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const view = render(<MicrophoneCheck deviceId="" />)
    fireEvent.click(screen.getByRole('button', { name: '测试麦克风' }))
    view.unmount()
    await act(async () => resolve({ getTracks: () => [{ stop }] }))
    expect(stop).toHaveBeenCalledTimes(1)
    expect(close).not.toHaveBeenCalled()
  })
  it('does not keep the old microphone when the selected device changes', async () => {
    const view = render(<MicrophoneCheck deviceId="first" />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: '测试麦克风' })))
    view.rerender(<MicrophoneCheck deviceId="second" />)
    expect(stop).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('meter')).toHaveAttribute('aria-valuenow', '0')
  })
  it('permission denial offers another test instead of pretending input is available', async () => {
    capture.acquire.mockRejectedValueOnce(new DOMException('Denied', 'NotAllowedError'))
    render(<MicrophoneCheck deviceId="" />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: '测试麦克风' })))
    expect(screen.getByText(/麦克风权限未开启/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '测试麦克风' })).toBeEnabled()
  })
})
