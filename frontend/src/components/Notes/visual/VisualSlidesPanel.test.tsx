import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '@/lib/i18n'
import { ApiError, apiFetch, apiJson } from '@/lib/api'
import * as recordingDownload from '@/lib/recordingDownload'
import {
  allSlidesEmbedded,
  buildSlideDownloadFilename,
  parseVisualSlidesPayload,
} from '@/lib/visualSlides'
import { VisualSlidesPanel } from './VisualSlidesPanel'

const authState = vi.hoisted(() => {
  const listeners = new Set<(state: { user: { id: string } | null }) => void>()
  let state: { user: { id: string } | null } = { user: { id: 'user-a' } }
  return {
    getState: () => state,
    setState: (next: { user: { id: string } | null }) => {
      state = next
      for (const listener of listeners) listener(state)
    },
    subscribe: (listener: (state: { user: { id: string } | null }) => void) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    reset: () => {
      listeners.clear()
      state = { user: { id: 'user-a' } }
    },
  }
})

const languageState = vi.hoisted(() => {
  const listeners = new Set<() => void>()
  let language: 'zh-CN' | 'en' = 'zh-CN'
  return {
    get: () => language,
    set: (next: 'zh-CN' | 'en') => {
      language = next
      for (const listener of listeners) listener()
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    reset: () => {
      listeners.clear()
      language = 'zh-CN'
    },
  }
})

const originState = vi.hoisted(() => ({ value: 'http://127.0.0.1:8900' }))

vi.mock('@/stores/authStore', () => {
  const useAuthStore = (selector?: (s: { user: { id: string } | null }) => unknown) => {
    const s = authState.getState()
    return typeof selector === 'function' ? selector(s) : s
  }
  useAuthStore.getState = authState.getState
  useAuthStore.subscribe = authState.subscribe
  return { useAuthStore }
})

vi.mock('@/stores/languageStore', async () => {
  const React = await import('react')
  return {
    useLanguageStore: () => {
      const language = React.useSyncExternalStore(languageState.subscribe, languageState.get)
      return {
        language,
        setLanguage: vi.fn(),
        syncWithAccount: vi.fn(),
      }
    },
  }
})

vi.mock('@/lib/runtimeConfig', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/runtimeConfig')>()
  return {
    ...actual,
    resolveBackendOrigin: () => originState.value,
  }
})

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    apiJson: vi.fn(),
    apiFetch: vi.fn(),
  }
})

const TASK_ID = '11111111-1111-4111-8111-111111111111'
const OTHER_TASK_ID = '22222222-2222-4222-8222-222222222222'

function makeSlide(index: number, overrides: Record<string, unknown> = {}) {
  const id = `slide-0${index}`
  const pngFilename = `${id}.png`
  return {
    index,
    id,
    title: `图解 ${index}`,
    caption: `这是第 ${index} 页的视觉说明`,
    target_heading: `议题 ${index}`,
    png_filename: pngFilename,
    html_filename: `${id}.html`,
    image_url: `/api/task/${TASK_ID}/artifacts/visuals/${pngFilename}`,
    width: 3200,
    height: 1800,
    png_sha256: `${index}`.repeat(32),
    ...overrides,
  }
}

function makeManifest(
  status: 'idle' | 'queued' | 'generating' | 'ready' | 'empty' | 'failed',
  overrides: Record<string, unknown> = {},
) {
  return {
    protocol: 'visual-slides/1',
    task_id: TASK_ID,
    status,
    error_code: null,
    slide_count: 0,
    dropped_count: 0,
    slides: [],
    ...overrides,
  }
}

function renderPanel(props: Partial<Parameters<typeof VisualSlidesPanel>[0]> = {}) {
  return render(
    <I18nProvider>
      <VisualSlidesPanel
        taskId={TASK_ID}
        noteTitle="季度成本优化会议"
        noteContent="# 季度成本优化会议\n\n纯文字正文。"
        {...props}
      />
    </I18nProvider>,
  )
}

describe('VisualSlidesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.reset()
    languageState.reset()
    originState.value = 'http://127.0.0.1:8900'
  })

  afterEach(() => {
    vi.useRealTimers()
    cleanup()
    vi.restoreAllMocks()
  })

  it('does not fetch or render when signed out or given a non-UUID task id', () => {
    authState.setState({ user: null })
    const first = renderPanel()
    expect(first.container).toBeEmptyDOMElement()
    expect(apiJson).not.toHaveBeenCalled()
    first.unmount()

    authState.setState({ user: { id: 'user-a' } })
    const second = renderPanel({ taskId: 'legacy-non-uuid' })
    expect(second.container).toBeEmptyDOMElement()
    expect(apiJson).not.toHaveBeenCalled()
  })

  it('hides gracefully without error noise when GET returns 404', async () => {
    vi.mocked(apiJson).mockRejectedValueOnce(new ApiError('not found', 404, {}))
    const { container } = renderPanel()
    await waitFor(() => expect(apiJson).toHaveBeenCalledTimes(1))
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows idle state and triggers manual generation with force=false, then polls until ready', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false })
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('idle'))
      .mockResolvedValueOnce(makeManifest('queued'))
      .mockResolvedValueOnce(makeManifest('generating'))
      .mockResolvedValueOnce(
        makeManifest('ready', {
          slide_count: 2,
          slides: [makeSlide(1), makeSlide(2)],
        }),
      )

    renderPanel({ pollIntervalMs: 100 })

    await act(async () => {
      await Promise.resolve()
    })

    const button = screen.getByRole('button', { name: '生成视觉幻灯片' })
    expect(button).toBeEnabled()

    await act(async () => {
      fireEvent.click(button)
      await Promise.resolve()
    })

    expect(apiJson).toHaveBeenNthCalledWith(
      2,
      `/api/task/${TASK_ID}/visual-slides`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ force: false }),
      }),
    )
    expect(screen.getByRole('button', { name: /正在生成视觉幻灯片/ })).toBeDisabled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100)
    })
    expect(apiJson).toHaveBeenCalledTimes(3)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100)
    })
    expect(apiJson).toHaveBeenCalledTimes(4)

    expect(screen.getByText('图解 1')).toBeInTheDocument()
    expect(screen.getByText('图解 2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新生成' })).toBeEnabled()

    const img = screen.getByAltText('这是第 1 页的视觉说明') as HTMLImageElement
    expect(img.getAttribute('src')).toContain(
      `/api/task/${TASK_ID}/artifacts/visuals/slide-01.png?v=${'1'.repeat(12)}`,
    )

    // Polling stops once ready
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })
    expect(apiJson).toHaveBeenCalledTimes(4)
  })

  it('defaults to collapsed bar when all ready slides are already embedded in noteContent, and expands on demand', async () => {
    const slide1 = makeSlide(1)
    vi.mocked(apiJson).mockResolvedValueOnce(
      makeManifest('ready', { slide_count: 1, slides: [slide1] }),
    )

    renderPanel({
      noteContent: `# 会议纪要\n\n![说明](${slide1.image_url})\n`,
    })

    expect(await screen.findByText(/已生成 1 页视觉幻灯片/)).toBeInTheDocument()
    expect(screen.queryByAltText(slide1.caption)).not.toBeInTheDocument()

    const expandBtn = screen.getByRole('button', { name: '展开卡片视图' })
    expect(expandBtn).toHaveAttribute('aria-expanded', 'false')
    expect(expandBtn).toHaveAttribute('aria-controls')
    fireEvent.click(expandBtn)
    expect(screen.getByAltText(slide1.caption)).toBeInTheDocument()

    const collapseBtn = screen.getByRole('button', { name: '收起卡片视图' })
    expect(collapseBtn).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(collapseBtn)
    expect(screen.queryByAltText(slide1.caption)).not.toBeInTheDocument()
  })

  it('sends force=true when regenerating from ready or empty state and busts image cache', async () => {
    const oldSlide = makeSlide(1, { png_sha256: 'a'.repeat(32) })
    const newSlide = makeSlide(1, { title: '新版图解 1', caption: '新版说明', png_sha256: 'b'.repeat(32) })

    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('ready', { slide_count: 1, slides: [oldSlide] }))
      .mockResolvedValueOnce(makeManifest('ready', { slide_count: 1, slides: [newSlide] }))

    renderPanel({
      noteContent: `# 会议纪要\n\n![旧说明](${oldSlide.image_url})\n`,
    })

    const regen = await screen.findByRole('button', { name: '重新生成' })
    fireEvent.click(regen)

    await waitFor(() => expect(screen.getByText('新版图解 1')).toBeInTheDocument())
    expect(apiJson).toHaveBeenNthCalledWith(
      2,
      `/api/task/${TASK_ID}/visual-slides`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ force: true }),
      }),
    )
    const img = screen.getByAltText('新版说明') as HTMLImageElement
    expect(img.getAttribute('src')).toContain(`?v=${'b'.repeat(12)}`)
  })

  it('sends force=true when retrying from empty state', async () => {
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('empty'))
      .mockResolvedValueOnce(makeManifest('ready', { slide_count: 1, slides: [makeSlide(1)] }))

    renderPanel()
    expect(await screen.findByText(/未生成额外视觉幻灯片/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '重新尝试生成' }))
    await waitFor(() => expect(screen.getByText('图解 1')).toBeInTheDocument())
    expect(apiJson).toHaveBeenNthCalledWith(
      2,
      `/api/task/${TASK_ID}/visual-slides`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ force: true }),
      }),
    )
  })

  it('auto-polls when initial GET reports generating (background auto-generation)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false })
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('generating'))
      .mockResolvedValueOnce(makeManifest('ready', { slide_count: 1, slides: [makeSlide(1)] }))

    renderPanel({ pollIntervalMs: 100 })
    await act(async () => {
      await Promise.resolve()
    })

    expect(screen.getByRole('button', { name: /正在生成视觉幻灯片/ })).toBeDisabled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100)
    })

    expect(screen.getByText('图解 1')).toBeInTheDocument()
  })

  it('prevents same-tick double POST with synchronous claim lock', async () => {
    let resolvePost!: (value: unknown) => void
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('idle'))
      .mockImplementationOnce(() => new Promise((resolve) => { resolvePost = resolve }))

    renderPanel()
    const button = await screen.findByRole('button', { name: '生成视觉幻灯片' })
    fireEvent.click(button)
    fireEvent.click(button)

    const postCalls = vi.mocked(apiJson).mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(postCalls).toHaveLength(1)

    await act(async () => {
      resolvePost(makeManifest('ready', { slide_count: 1, slides: [makeSlide(1)] }))
    })
    expect(screen.getByText('图解 1')).toBeInTheDocument()
  })

  it('handles 409 server disabled without crashing and disables trigger', async () => {
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('idle'))
      .mockRejectedValueOnce(new ApiError('视觉幻灯片功能已禁用', 409, '视觉幻灯片功能已禁用'))

    renderPanel()
    const button = await screen.findByRole('button', { name: '生成视觉幻灯片' })
    fireEvent.click(button)

    expect(await screen.findByRole('alert')).toHaveTextContent('视觉幻灯片功能已禁用')
    expect(screen.getByRole('button', { name: '生成视觉幻灯片' })).toBeDisabled()
  })

  it('maps backend error_code in both zh and en without refiring GET on locale switch', async () => {
    vi.mocked(apiJson).mockResolvedValueOnce(
      makeManifest('failed', { error_code: 'renderer_unavailable' }),
    )

    renderPanel()
    expect(await screen.findByRole('alert')).toHaveTextContent(/缺少本地浏览器或渲染服务/)
    expect(apiJson).toHaveBeenCalledTimes(1)

    act(() => {
      languageState.set('en')
    })

    expect(screen.getByRole('alert')).toHaveTextContent(/renderer is unavailable/i)
    expect(screen.getByRole('button', { name: 'Retry visual slides' })).toBeEnabled()
    expect(apiJson).toHaveBeenCalledTimes(1)
  })

  it('disables trigger and shows helper message when disabled prop is true (unsaved changes)', async () => {
    vi.mocked(apiJson).mockResolvedValueOnce(makeManifest('idle'))

    renderPanel({ disabled: true })
    const button = await screen.findByRole('button', { name: '生成视觉幻灯片' })
    expect(button).toBeDisabled()
    expect(button).toHaveAccessibleDescription(/请先保存当前修改/)
    expect(screen.getByText(/请先保存当前修改/)).toBeInTheDocument()
  })

  it('stops polling cleanly after maxPollAttempts and offers manual refresh', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false })
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('generating'))
      .mockResolvedValueOnce(makeManifest('generating'))
      .mockResolvedValueOnce(makeManifest('generating'))
      .mockResolvedValueOnce(makeManifest('ready', { slide_count: 1, slides: [makeSlide(1)] }))

    renderPanel({ pollIntervalMs: 50, maxPollAttempts: 2 })
    await act(async () => {
      await Promise.resolve()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250)
    })

    // 1 initial + 2 polls = 3, then stopped
    expect(apiJson).toHaveBeenCalledTimes(3)
    expect(screen.getByText(/仍在后台生成中/)).toBeInTheDocument()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
      await Promise.resolve()
    })
    expect(screen.getByText('图解 1')).toBeInTheDocument()
  })

  it('drops stale responses and clears polling on synchronous A→B→A account switch', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false })
    let resolveOldPost!: (value: unknown) => void
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('idle'))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOldPost = resolve }))
      .mockResolvedValue(makeManifest('idle'))

    renderPanel({ pollIntervalMs: 100 })
    await act(async () => {
      await Promise.resolve()
    })

    fireEvent.click(screen.getByRole('button', { name: '生成视觉幻灯片' }))

    act(() => {
      authState.setState({ user: { id: 'user-b' } })
      authState.setState({ user: { id: 'user-a' } })
    })

    await act(async () => {
      resolveOldPost(
        makeManifest('ready', {
          slide_count: 1,
          slides: [makeSlide(1, { title: '不应出现的旧账号幻灯片' })],
        }),
      )
      await Promise.resolve()
    })

    expect(screen.queryByText('不应出现的旧账号幻灯片')).not.toBeInTheDocument()
  })

  it('drops stale responses when backend origin changes mid-flight', async () => {
    let resolveLoad!: (value: unknown) => void
    vi.mocked(apiJson).mockImplementationOnce(() => new Promise((resolve) => { resolveLoad = resolve }))

    renderPanel()
    originState.value = 'http://192.168.1.99:8900'

    await act(async () => {
      resolveLoad(makeManifest('ready', { slide_count: 1, slides: [makeSlide(1, { title: '旧来源图解' })] }))
    })

    expect(screen.queryByText('旧来源图解')).not.toBeInTheDocument()
  })

  it('rejects malformed payloads and unsafe slide URLs (traversal, external, wrong task, html)', async () => {
    vi.mocked(apiJson).mockResolvedValueOnce('<html>proxy error page</html>')
    const first = renderPanel()
    expect(await screen.findByRole('alert')).toHaveTextContent(/无法读取视觉幻灯片状态/)
    first.unmount()

    vi.mocked(apiJson).mockResolvedValueOnce(
      makeManifest('ready', {
        slide_count: 4,
        slides: [
          makeSlide(1, { image_url: 'https://evil.invalid/slide-01.png' }),
          makeSlide(2, { image_url: `/api/task/${OTHER_TASK_ID}/artifacts/visuals/slide-02.png` }),
          makeSlide(3, { image_url: `/api/task/${TASK_ID}/artifacts/visuals/slide-03.html`, png_filename: 'slide-03.html' }),
          makeSlide(4, { image_url: `/api/task/${TASK_ID}/artifacts/visuals/../secret.png`, png_filename: '../secret.png' }),
        ],
      }),
    )
    renderPanel()
    expect(await screen.findByRole('alert')).toHaveTextContent(/无法读取视觉幻灯片状态/)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('opens zoom lightbox and downloads PNG safely via apiFetch + downloadRecording', async () => {
    const slide = makeSlide(1)
    vi.mocked(apiJson).mockResolvedValueOnce(
      makeManifest('ready', { slide_count: 1, slides: [slide] }),
    )
    const pngBlob = new Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' })
    vi.mocked(apiFetch).mockImplementation(async () =>
      new Response(pngBlob, { status: 200, headers: { 'content-type': 'image/png' } }),
    )
    const dlSpy = vi.spyOn(recordingDownload, 'downloadRecording').mockImplementation(async (source) => {
      if (typeof source === 'function') await source()
      return 'saved'
    })

    renderPanel()
    const zoomTrigger = await screen.findByRole('button', { name: /放大查看.*图解 1/ })
    fireEvent.click(zoomTrigger)
    expect(await screen.findByRole('dialog')).toHaveTextContent('图解 1')

    // Close lightbox
    fireEvent.click(screen.getByRole('button', { name: '关闭幻灯片预览' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    // Download PNG
    fireEvent.click(screen.getByRole('button', { name: /下载 PNG.*图解 1/ }))
    await waitFor(() => expect(dlSpy).toHaveBeenCalledTimes(1))
    expect(dlSpy.mock.calls[0][2]).toMatch(/slide-01\.png$/)
    expect(apiFetch).toHaveBeenCalledWith(
      `${slide.image_url}?v=${'1'.repeat(12)}`,
      expect.objectContaining({ cache: 'no-store', redirect: 'error' }),
    )
    expect(await screen.findByText(/幻灯片已保存到所选位置/)).toBeInTheDocument()
  })

  it('rejects uppercase UUIDs fail-fast, validates taskId in parser, builds bounded filenames, and matches markdown images strictly', () => {
    const upperTask = 'AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE'
    const view = renderPanel({ taskId: upperTask })
    expect(view.container).toBeEmptyDOMElement()
    expect(apiJson).not.toHaveBeenCalled()
    view.unmount()

    expect(parseVisualSlidesPayload(makeManifest('idle', { task_id: '../evil' }), '../evil')).toBeNull()

    const longPng = `${'a'.repeat(115)}.png`
    const filename = buildSlideDownloadFilename('...季度成本复盘'.repeat(20), longPng)
    expect(filename.length).toBeLessThanOrEqual(160)
    expect(filename.endsWith(longPng)).toBe(true)
    expect(filename.startsWith('.')).toBe(false)

    const slide = parseVisualSlidesPayload(
      makeManifest('ready', { slides: [makeSlide(1)] }),
      TASK_ID,
    )!.slides
    expect(allSlidesEmbedded(slide, `Plain mention: ${slide[0].imageUrl}`)).toBe(false)
    expect(allSlidesEmbedded(slide, `![图解](${slide[0].imageUrl})`)).toBe(true)
  })

  it('keeps generate disabled and refresh busy without idle flash while manual refresh is in flight', async () => {
    let resolveRefresh!: (value: unknown) => void
    vi.mocked(apiJson)
      .mockRejectedValueOnce(new Error('network down'))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve }))

    renderPanel()
    expect(await screen.findByRole('alert')).toHaveTextContent('network down')

    const refreshBtn = screen.getByRole('button', { name: '刷新状态' })
    fireEvent.click(refreshBtn)
    fireEvent.click(refreshBtn)

    expect(apiJson).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: '正在刷新状态…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '正在刷新状态…' })).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByRole('button', { name: '生成视觉幻灯片' })).toBeDisabled()
    expect(screen.queryByText(/一键生成 16:9/)).not.toBeInTheDocument()

    await act(async () => {
      resolveRefresh(makeManifest('idle'))
    })
    expect(screen.getByRole('button', { name: '生成视觉幻灯片' })).toBeEnabled()
  })

  it('keeps trigger enabled on 409 task_not_completed and sends force=false when retrying from failed', async () => {
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('failed', { error_code: 'render_failed' }))
      .mockRejectedValueOnce(new ApiError('任务尚未完成，暂不能生成视觉幻灯片', 409, 'task_not_completed'))
      .mockResolvedValueOnce(makeManifest('ready', { slide_count: 1, slides: [makeSlide(1)] }))

    renderPanel()
    const retryBtn = await screen.findByRole('button', { name: '重新生成视觉幻灯片' })
    fireEvent.click(retryBtn)

    expect(await screen.findByText(/任务尚未完成/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新生成视觉幻灯片' })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: '重新生成视觉幻灯片' }))
    expect(await screen.findByText('图解 1')).toBeInTheDocument()
    expect(apiJson).toHaveBeenNthCalledWith(
      3,
      `/api/task/${TASK_ID}/visual-slides`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ force: false }),
      }),
    )
  })

  it('aborts in-flight poll and clears polling timer on synchronous A→B→A account switch', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false })
    let pollSignal: AbortSignal | undefined
    let resolvePoll!: (value: unknown) => void
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('generating'))
      .mockImplementationOnce((_path, init) => {
        pollSignal = init?.signal ?? undefined
        return new Promise((resolve) => { resolvePoll = resolve })
      })
      .mockResolvedValue(makeManifest('idle'))

    renderPanel({ pollIntervalMs: 50 })
    await act(async () => {
      await Promise.resolve()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50)
    })
    expect(pollSignal?.aborted).toBe(false)

    act(() => {
      authState.setState({ user: { id: 'user-b' } })
      authState.setState({ user: { id: 'user-a' } })
    })
    expect(pollSignal?.aborted).toBe(true)

    await act(async () => {
      resolvePoll(
        makeManifest('ready', {
          slide_count: 1,
          slides: [makeSlide(1, { title: '旧账号轮询结果' })],
        }),
      )
      await Promise.resolve()
    })
    expect(screen.queryByText('旧账号轮询结果')).not.toBeInTheDocument()
  })

  it('closes lightbox and revokes active PNG download on synchronous A→B→A switch', async () => {
    const slide = makeSlide(1)
    vi.mocked(apiJson).mockResolvedValue(
      makeManifest('ready', { slide_count: 1, slides: [slide] }),
    )

    let downloadSignal: AbortSignal | undefined
    let currentChecker: (() => boolean) | undefined
    let resolveFetch!: (value: Response) => void
    vi.mocked(apiFetch).mockImplementation((_path, init) => {
      downloadSignal = init?.signal ?? undefined
      return new Promise((resolve) => { resolveFetch = resolve })
    })
    vi.spyOn(recordingDownload, 'downloadRecording').mockImplementation(async (source, _title, _file, current) => {
      currentChecker = current
      if (typeof source === 'function') await source()
      return 'saved'
    })

    renderPanel()
    const opener = await screen.findByRole('button', { name: /放大查看.*图解 1/ })
    fireEvent.click(opener)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    // Close lightbox and verify focus restoration
    fireEvent.click(screen.getByRole('button', { name: '关闭幻灯片预览' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(document.activeElement).toBe(opener)

    // Start download, re-open lightbox, then trigger synchronous A→B→A
    fireEvent.click(screen.getByRole('button', { name: /下载 PNG.*图解 1/ }))
    await waitFor(() => expect(downloadSignal).toBeDefined())
    expect(currentChecker?.()).toBe(true)
    fireEvent.click(opener)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    act(() => {
      authState.setState({ user: { id: 'user-b' } })
      authState.setState({ user: { id: 'user-a' } })
    })

    expect(downloadSignal?.aborted).toBe(true)
    expect(currentChecker?.()).toBe(false)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await act(async () => {
      resolveFetch(
        new Response(new Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' }), {
          status: 200,
          headers: { 'content-type': 'image/png' },
        }),
      )
    })
    expect(screen.queryByText(/幻灯片已保存到所选位置/)).not.toBeInTheDocument()
  })

  it('shows poll-specific error copy on malformed poll response and rejects oversized PNG content-length', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false })
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('generating'))
      .mockResolvedValueOnce('<html>bad gateway</html>')
      .mockResolvedValueOnce(makeManifest('ready', { slide_count: 1, slides: [makeSlide(1)] }))

    renderPanel({ pollIntervalMs: 50 })
    await act(async () => {
      await Promise.resolve()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50)
    })

    expect(screen.getByRole('alert')).toHaveTextContent(/无法获取最新视觉幻灯片状态/)
    expect(screen.getByRole('button', { name: '刷新状态' })).toBeEnabled()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
      await Promise.resolve()
    })
    expect(screen.getByText('图解 1')).toBeInTheDocument()

    // Oversized content-length rejected before reading body
    vi.useRealTimers()
    vi.mocked(apiFetch).mockResolvedValueOnce(
      new Response(new Uint8Array([1, 2, 3]), {
        status: 200,
        headers: { 'content-type': 'image/png', 'content-length': String(20 * 1024 * 1024) },
      }),
    )
    vi.spyOn(recordingDownload, 'downloadRecording').mockImplementation(async (source) => {
      if (typeof source === 'function') await source()
      return 'saved'
    })
    fireEvent.click(screen.getByRole('button', { name: /下载 PNG.*图解 1/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('幻灯片文件大小异常')

    // Thumbnail load failure allows reload and aria-describedby links unsaved helper copy
    const img = screen.getByAltText('这是第 1 页的视觉说明')
    fireEvent.error(img)
    expect(screen.getByText('幻灯片预览加载失败。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新加载图片' }))
    expect(screen.getByAltText('这是第 1 页的视觉说明')).toBeInTheDocument()
  })

  it('deduplicates slides by id and sorts them by index', async () => {
    vi.mocked(apiJson).mockResolvedValueOnce(
      makeManifest('ready', {
        slide_count: 3,
        slides: [
          makeSlide(2, { title: '第二页' }),
          makeSlide(1, { title: '第一页' }),
          makeSlide(1, { title: '重复的第一页' }),
        ],
      }),
    )

    renderPanel()
    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('第一页')
    expect(items[1]).toHaveTextContent('第二页')
    expect(screen.queryByText('重复的第一页')).not.toBeInTheDocument()
  })

  it('disables trigger when initial GET fails and recovers on manual refresh', async () => {
    vi.mocked(apiJson)
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(makeManifest('idle'))

    renderPanel()
    expect(await screen.findByRole('alert')).toHaveTextContent('network down')
    expect(screen.getByRole('button', { name: '生成视觉幻灯片' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '生成视觉幻灯片' })).toBeEnabled(),
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('stops polling after consecutive network errors and allows manual refresh recovery', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false })
    vi.mocked(apiJson)
      .mockResolvedValueOnce(makeManifest('generating'))
      .mockRejectedValueOnce(new Error('transient 1'))
      .mockRejectedValueOnce(new Error('transient 2'))
      .mockRejectedValueOnce(new Error('transient 3'))
      .mockResolvedValueOnce(makeManifest('ready', { slide_count: 1, slides: [makeSlide(1)] }))

    renderPanel({ pollIntervalMs: 50, maxPollAttempts: 10 })
    await act(async () => {
      await Promise.resolve()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })

    expect(apiJson).toHaveBeenCalledTimes(4)
    expect(screen.getByRole('alert')).toHaveTextContent('transient 3')
    expect(screen.getByRole('button', { name: '后台生成中' })).toBeDisabled()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
      await Promise.resolve()
    })
    expect(screen.getByText('图解 1')).toBeInTheDocument()
  })

  it('keeps download error messages locale-reactive without refiring GET', async () => {
    const slide = makeSlide(1)
    vi.mocked(apiJson).mockResolvedValueOnce(
      makeManifest('ready', { slide_count: 1, slides: [slide] }),
    )
    vi.mocked(apiFetch).mockImplementation(async () =>
      new Response('<html>not png</html>', {
        status: 200,
        headers: { 'content-type': 'text/html' },
      }),
    )
    vi.spyOn(recordingDownload, 'downloadRecording').mockImplementation(async (source) => {
      if (typeof source === 'function') await source()
      return 'saved'
    })

    renderPanel()
    fireEvent.click(await screen.findByRole('button', { name: /下载 PNG.*图解 1/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('返回内容不是有效的 PNG 图片')

    act(() => {
      languageState.set('en')
    })
    expect(screen.getByRole('alert')).toHaveTextContent('Response is not a valid PNG image.')
    expect(apiJson).toHaveBeenCalledTimes(1)
  })
})
