import { webcrypto } from 'node:crypto'
import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SummaryVisualPanel } from './SummaryVisualPanel'
import { useAuthStore } from '@/stores/authStore'
import { downloadRecording } from '@/lib/recordingDownload'
import { makeVisualFixture, visualSavedBody, visualTitle } from '../../../../test-fixtures/summaryVisual'
import type { SummaryVisual } from '@/lib/summaryVisual'

vi.mock('@/lib/recordingDownload', () => ({ downloadRecording: vi.fn() }))

beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto)
  useAuthStore.setState({ user: { id: 'frame-owner' } as never })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); vi.unstubAllGlobals() })

function panel(visual: SummaryVisual, savedBody = visualSavedBody) {
  return <SummaryVisualPanel visual={visual} savedBody={savedBody} title={visualTitle} />
}
function loaded(image: HTMLElement) {
  Object.defineProperties(image, { naturalWidth: { value: 1920 }, naturalHeight: { value: 1080 } })
  fireEvent.load(image)
}
async function openFirst() {
  const user = userEvent.setup()
  const trigger = screen.getAllByRole('button', { name: /^放大查看/ })[0]
  await user.click(trigger)
  const dialog = await screen.findByRole('dialog')
  return { user, trigger, dialog }
}

it('opens the exact original frame and offers original pixel dimensions without changing the plan or image', async () => {
  const visual = await makeVisualFixture(), before = JSON.stringify(visual)
  render(panel(visual))
  const src = screen.getAllByRole('img')[0].getAttribute('src')
  const { user, dialog } = await openFirst()
  expect(within(dialog).getByRole('heading', { name: '原始录屏画面 · 01:04' })).toBeInTheDocument()
  const image = within(dialog).getByRole('img')
  expect(image).toHaveAttribute('src', src)
  expect(image).toHaveAttribute('alt', visual.frames[0].grounded_label)
  expect(within(dialog).getByText(visual.frames[0].grounded_label)).toBeInTheDocument()
  expect(within(dialog).getByRole('button', { name: '原始尺寸' })).toBeDisabled()
  loaded(image)
  const zoom = within(dialog).getByRole('button', { name: '原始尺寸' })
  await user.click(zoom)
  expect(zoom).toHaveAttribute('aria-pressed', 'true')
  expect(image).toHaveStyle({ width: '1920px', height: '1080px' })
  expect(image).not.toHaveClass('object-cover')
  expect(within(dialog).getByRole('region', { name: '原始画面，可滚动查看' })).toHaveAttribute('tabindex', '0')
  await user.click(zoom)
  expect(zoom).toHaveAttribute('aria-pressed', 'false')
  expect(image.style.width).toBe('')
  expect(JSON.stringify(visual)).toBe(before)
  expect(downloadRecording).not.toHaveBeenCalled()
})

it('opens by keyboard, closes with Escape, and restores focus to the same frame trigger under StrictMode', async () => {
  render(<StrictMode>{panel(await makeVisualFixture())}</StrictMode>)
  const user = userEvent.setup(), trigger = screen.getAllByRole('button', { name: /^放大查看/ })[1]
  trigger.focus()
  await user.keyboard('{Enter}')
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toContainElement(document.activeElement as HTMLElement)
  expect(within(dialog).getByRole('heading', { name: '原始录屏画面 · 02:12' })).toBeInTheDocument()
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(trigger).toHaveFocus())
})

it('closes through the named close control and returns to its opener', async () => {
  render(panel(await makeVisualFixture()))
  const { user, trigger, dialog } = await openFirst()
  await user.click(within(dialog).getByRole('button', { name: '关闭画面预览' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(trigger).toHaveFocus())
})

it('keeps a failed full-size frame explicitly retryable with the same authenticated frame path', async () => {
  const visual = await makeVisualFixture()
  render(panel(visual))
  const { user, dialog } = await openFirst(), failed = within(dialog).getByRole('img'), src = failed.getAttribute('src')
  fireEvent.error(failed)
  expect(within(dialog).queryByRole('img')).toBeNull()
  expect(within(dialog).getByRole('status')).toHaveTextContent('原始画面加载失败，说明和正文保留。')
  expect(within(dialog).getByText(visual.frames[0].grounded_label)).toBeInTheDocument()
  await user.click(within(dialog).getByRole('button', { name: '重新读取大图' }))
  const replacement = within(dialog).getByRole('img')
  expect(replacement).not.toBe(failed)
  expect(replacement).toHaveAttribute('src', src)
  loaded(replacement)
  expect(within(dialog).queryByRole('status')).toBeNull()
  expect(within(dialog).getByRole('button', { name: '原始尺寸' })).toBeEnabled()
})

it('preserves thumbnail failure/retry and the scene caption and source disclosure', async () => {
  const visual = await makeVisualFixture()
  render(panel(visual))
  const failed = screen.getAllByRole('img')[0], src = failed.getAttribute('src')
  fireEvent.error(failed)
  expect(screen.getByRole('status')).toHaveTextContent('此处原始画面暂不可用')
  expect(screen.getByText(visual.scenes[0].grounded_label)).toBeInTheDocument()
  expect(screen.getAllByText('查看对应原文')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: '重新读取画面' }))
  expect(screen.getAllByRole('img')[0]).toHaveAttribute('src', src)
  expect(screen.getAllByRole('button', { name: /^放大查看/ })).toHaveLength(2)
})

it.each(['different-owner', 'A-B-A', 'signed-out'])('revokes an open image and late events on account transition: %s', async transition => {
  render(panel(await makeVisualFixture()))
  const { dialog } = await openFirst(), stale = within(dialog).getByRole('img')
  act(() => {
    useAuthStore.setState({ user: transition === 'signed-out' ? null : { id: 'other-owner' } as never })
    if (transition === 'A-B-A') useAuthStore.setState({ user: { id: 'frame-owner' } as never })
  })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  fireEvent.error(stale); loaded(stale)
  expect(screen.queryAllByRole('img')).toHaveLength(0)
  expect(screen.queryAllByRole('button', { name: /^放大查看|重新读取/ })).toHaveLength(0)
  expect(screen.queryByText('原始画面加载失败，说明和正文保留。')).toBeNull()
})

it.each(['task', 'body-hash', 'saved-body', 'screenshot-index'])('closes a stale frame when its identity changes: %s', async change => {
  const visual = await makeVisualFixture(), view = render(panel(visual))
  const { dialog } = await openFirst(), stale = within(dialog).getByRole('img')
  const next = structuredClone(visual)
  if (change === 'task') next.task_id = '22222222-2222-4222-8222-222222222222'
  if (change === 'body-hash') next.body_sha256 = 'b'.repeat(64)
  if (change === 'screenshot-index') next.frames[0].screenshot_index = 7
  view.rerender(panel(next, change === 'saved-body' ? 'New saved revision' : visualSavedBody))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  fireEvent.error(stale)
  expect(screen.queryByText('原始画面加载失败，说明和正文保留。')).toBeNull()
  const { dialog: current } = await openFirst()
  expect(within(current).getByRole('img')).toHaveAttribute('src', `/api/task/${next.task_id}/artifacts/screenshots/summary-source-${next.frames[0].screenshot_index}.jpg`)
})
