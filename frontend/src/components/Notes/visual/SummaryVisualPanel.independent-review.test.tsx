import { webcrypto } from 'node:crypto'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SummaryVisualPanel } from './SummaryVisualPanel'
import { useAuthStore } from '@/stores/authStore'
import { makeVisualFixture, visualSavedBody, visualTitle } from '../../../../test-fixtures/summaryVisual'

vi.mock('@/lib/recordingDownload', () => ({ downloadRecording: vi.fn() }))
beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto)
  useAuthStore.setState({ user: { id: 'review-owner' } as never })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('returns focus to the surviving frame retry action when the thumbnail fails while its dialog is open', async () => {
  const visual = await makeVisualFixture(), user = userEvent.setup()
  render(<SummaryVisualPanel visual={visual} savedBody={visualSavedBody} title={visualTitle} />)
  const thumbnail = screen.getAllByRole('img')[0]
  await user.click(screen.getAllByRole('button', { name: /^放大查看/ })[0])
  await screen.findByRole('dialog')
  fireEvent.error(thumbnail)
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  const retry = screen.getByRole('button', { name: '重新读取画面' })
  await waitFor(() => expect(retry).toHaveFocus())
})
