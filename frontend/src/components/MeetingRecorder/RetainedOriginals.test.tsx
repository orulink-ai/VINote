import { expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { RetainedOriginals } from './RetainedOriginals'
import { apiJson } from '@/lib/api'
import type { LibraryNote } from '@/hooks/useLibraryNotes'
vi.mock('@/lib/api', () => ({ apiJson: vi.fn() }))
it('shows only verified local files and retries failed metadata reads without loading media', async () => {
  const api = vi.mocked(apiJson)
  api.mockResolvedValueOnce({ available: true, filename: 'kept.m4a', size_bytes: 1024 }).mockRejectedValueOnce(new Error('offline'))
  const notes = [
    { id: 'local', taskId: 'one', title: 'Kept' },
    { id: 'unread', taskId: 'two', title: 'Unknown' },
    { id: 'remote', workspaceKey: 'remote', title: 'Remote' },
  ] as LibraryNote[]
  render(<MemoryRouter><RetainedOriginals owner="owner" notes={notes} excludedIds={[]} /></MemoryRouter>)
  expect(await screen.findByRole('link', { name: /Kept/ })).toHaveAttribute('href', '/note/local')
  expect(screen.queryByRole('link', { name: /Remote|Unknown/ })).not.toBeInTheDocument()
  await screen.findByRole('button', { name: '重新核验' })
  api.mockResolvedValue({ available: true, filename: 'kept.m4a', size_bytes: 1024 })
  fireEvent.click(screen.getByRole('button', { name: '重新核验' }))
  expect(await screen.findByRole('link', { name: /Unknown/ })).toBeInTheDocument()
  expect(api.mock.calls.every(call => String(call[0]).endsWith('/recording'))).toBe(true)
})
