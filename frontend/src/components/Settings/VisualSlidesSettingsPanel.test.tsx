import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api'
import { I18nProvider } from '@/lib/i18n'
import { VisualSlidesSettingsPanel } from './VisualSlidesSettingsPanel'

const apiJsonMock = vi.fn()
let currentOwner: string | undefined = 'user-1'
let currentOrigin = 'http://127.0.0.1:8900'
let currentLanguage: 'zh-CN' | 'en' = 'zh-CN'
const authListeners = new Set<(state: { initialized: boolean; user: { id: string } | null }) => void>()

function emitOwnerChange(nextOwner: string | undefined) {
  currentOwner = nextOwner
  const snapshot = { initialized: true, user: nextOwner ? { id: nextOwner } : null }
  authListeners.forEach((listener) => listener(snapshot))
}

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    apiJson: (...args: unknown[]) => apiJsonMock(...args),
  }
})

vi.mock('@/lib/runtimeConfig', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/runtimeConfig')>()
  return {
    ...actual,
    resolveBackendOrigin: () => currentOrigin,
  }
})

vi.mock('@/stores/authStore', () => ({
  useAuthStore: Object.assign(
    (selector?: (state: { initialized: boolean; user: { id: string } | null }) => unknown) => {
      const state = { initialized: true, user: currentOwner ? { id: currentOwner } : null }
      return typeof selector === 'function' ? selector(state) : state
    },
    {
      getState: () => ({ initialized: true, user: currentOwner ? { id: currentOwner } : null }),
      subscribe: (listener: (state: { initialized: boolean; user: { id: string } | null }) => void) => {
        authListeners.add(listener)
        return () => {
          authListeners.delete(listener)
        }
      },
    },
  ),
}))

vi.mock('@/stores/languageStore', () => ({
  useLanguageStore: () => ({
    language: currentLanguage,
    setLanguage: vi.fn(),
    syncWithAccount: vi.fn(),
  }),
}))

function renderPanel() {
  return render(
    <I18nProvider>
      <VisualSlidesSettingsPanel />
    </I18nProvider>,
  )
}

describe('VisualSlidesSettingsPanel', () => {
  beforeEach(() => {
    currentOwner = 'user-1'
    currentOrigin = 'http://127.0.0.1:8900'
    currentLanguage = 'zh-CN'
    authListeners.clear()
    apiJsonMock.mockReset()
  })

  afterEach(cleanup)

  it('stays disabled while loading and while signed out without calling API', () => {
    currentOwner = undefined
    renderPanel()
    const toggle = screen.getByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })
    expect(toggle).toBeDisabled()
    expect(apiJsonMock).not.toHaveBeenCalled()

    cleanup()
    currentOwner = 'user-1'
    apiJsonMock.mockImplementationOnce(() => new Promise(() => {}))
    renderPanel()
    expect(screen.getByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })).toBeDisabled()
  })

  it('loads preference from /api/preferences and toggles auto-generation via PATCH', async () => {
    apiJsonMock
      .mockResolvedValueOnce({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: false,
      })
      .mockResolvedValueOnce({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: true,
      })

    renderPanel()
    const toggle = await screen.findByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })
    await waitFor(() => expect(toggle).not.toBeDisabled())
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(apiJsonMock).toHaveBeenCalledWith(
      '/api/preferences',
      expect.objectContaining({ cache: 'no-store' }),
    )

    await userEvent.click(toggle)

    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'true'))
    expect(apiJsonMock).toHaveBeenLastCalledWith(
      '/api/preferences',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ visual_slides_auto_generate: true }),
      }),
    )
    expect(screen.getByRole('status')).toHaveTextContent('已开启')
  })

  it('reverts toggle and shows alert on PATCH failure, and disables on runtime 409 kill switch', async () => {
    apiJsonMock
      .mockResolvedValueOnce({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: false,
      })
      .mockRejectedValueOnce(new Error('服务暂时不可用'))
      .mockRejectedValueOnce(new ApiError('视觉幻灯片功能已禁用', 409, '视觉幻灯片功能已禁用'))

    renderPanel()
    const toggle = await screen.findByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })
    await waitFor(() => expect(toggle).not.toBeDisabled())

    await userEvent.click(toggle)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('服务暂时不可用'))
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(toggle).not.toBeDisabled()

    await userEvent.click(toggle)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('视觉幻灯片功能已禁用'))
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(toggle).toBeDisabled()
    expect(screen.getByText(/服务端未启用/)).toBeVisible()
  })

  it('disables toggle when server feature flag is off and rejects non-object proxy HTML 200', async () => {
    apiJsonMock
      .mockResolvedValueOnce('<html>proxy error</html>')
      .mockResolvedValueOnce({
        language: 'zh-CN',
        visual_slides_enabled: false,
        visual_slides_auto_generate: false,
      })

    renderPanel()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('无法读取视觉幻灯片设置'))
    expect(screen.getByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: '重新读取' }))
    await waitFor(() => expect(screen.getByText(/服务端未启用/)).toBeVisible())
    expect(screen.getByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })).toBeDisabled()
  })

  it('shows retry control when initial load fails and recovers on click', async () => {
    apiJsonMock
      .mockRejectedValueOnce(new Error('读取失败'))
      .mockResolvedValueOnce({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: true,
      })

    renderPanel()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('读取失败'))
    const toggle = screen.getByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })
    expect(toggle).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: '重新读取' }))
    await waitFor(() => expect(toggle).not.toBeDisabled())
    expect(toggle).toHaveAttribute('aria-checked', 'true')
  })

  it('does not deadlock saving or trigger redundant GET when locale flips during in-flight PATCH', async () => {
    let resolvePatch!: (value: unknown) => void
    apiJsonMock
      .mockResolvedValueOnce({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: false,
      })
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolvePatch = resolve }),
      )

    const { rerender } = renderPanel()
    const toggle = await screen.findByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })
    await waitFor(() => expect(toggle).not.toBeDisabled())

    await userEvent.click(toggle)
    expect(apiJsonMock).toHaveBeenCalledTimes(2)

    // Locale changes while PATCH is still in flight
    currentLanguage = 'en'
    rerender(
      <I18nProvider>
        <VisualSlidesSettingsPanel />
      </I18nProvider>,
    )

    // Must NOT fire a redundant GET
    expect(apiJsonMock).toHaveBeenCalledTimes(2)

    await act(async () => {
      resolvePatch({
        language: 'en',
        visual_slides_enabled: true,
        visual_slides_auto_generate: true,
      })
    })

    const enToggle = await screen.findByRole('switch', { name: 'Auto-generate visual slides for meeting minutes' })
    await waitFor(() => expect(enToggle).not.toBeDisabled())
    expect(enToggle).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('status')).toHaveTextContent('Enabled')
  })

  it('blocks rapid double-toggle synchronously so only one PATCH is dispatched', async () => {
    let resolvePatch!: (value: unknown) => void
    apiJsonMock
      .mockResolvedValueOnce({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: false,
      })
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolvePatch = resolve }),
      )

    renderPanel()
    const toggle = await screen.findByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })
    await waitFor(() => expect(toggle).not.toBeDisabled())

    // Two synchronous clicks before React commits disabled={saving}
    fireEvent.click(toggle)
    fireEvent.click(toggle)
    expect(apiJsonMock).toHaveBeenCalledTimes(2)

    await act(async () => {
      resolvePatch({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: true,
      })
    })
    await waitFor(() => expect(toggle).not.toBeDisabled())
    expect(toggle).toHaveAttribute('aria-checked', 'true')
  })

  it('invalidates in-flight GET and PATCH across synchronous A -> B -> A account switches', async () => {
    let resolveOldPatch!: (value: unknown) => void
    apiJsonMock
      .mockResolvedValueOnce({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: false,
      })
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveOldPatch = resolve }),
      )
      .mockResolvedValueOnce({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: false,
      })

    renderPanel()
    const toggle = await screen.findByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })
    await waitFor(() => expect(toggle).not.toBeDisabled())

    // Start PATCH under initial user-1 session
    await userEvent.click(toggle)
    expect(apiJsonMock).toHaveBeenCalledTimes(2)

    // Synchronous A -> B -> A between React renders
    act(() => {
      emitOwnerChange('user-2')
      emitOwnerChange('user-1')
    })

    // Fresh session loads cleanly and ignores the stale pre-switch PATCH completion
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalledTimes(3))
    await act(async () => {
      resolveOldPatch({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: true,
      })
    })

    const freshToggle = await screen.findByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })
    await waitFor(() => expect(freshToggle).not.toBeDisabled())
    expect(freshToggle).toHaveAttribute('aria-checked', 'false')
  })

  it('reloads and ignores stale responses when backend origin changes', async () => {
    let resolveOriginA!: (value: unknown) => void
    apiJsonMock
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveOriginA = resolve }),
      )
      .mockResolvedValueOnce({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: false,
      })

    const { rerender } = renderPanel()
    currentOrigin = 'http://127.0.0.1:9900'
    rerender(
      <I18nProvider>
        <VisualSlidesSettingsPanel />
      </I18nProvider>,
    )

    const toggle = await screen.findByRole('switch', { name: '会议纪要自动生成视觉幻灯片' })
    await waitFor(() => expect(toggle).not.toBeDisabled())
    expect(toggle).toHaveAttribute('aria-checked', 'false')

    await act(async () => {
      resolveOriginA({
        language: 'zh-CN',
        visual_slides_enabled: true,
        visual_slides_auto_generate: true,
      })
    })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
  })
})
