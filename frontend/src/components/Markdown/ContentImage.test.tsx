import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const services = vi.hoisted(() => ({ access: vi.fn(), fetch: vi.fn(), blob: vi.fn() }))
vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand')
  return { useAuthStore: create(() => ({ user: { id: 'owner-a' } })) }
})
vi.mock('@/lib/api', () => ({ apiFetch: services.fetch }))
vi.mock('@/lib/workspaceAttachments', () => ({
  attachmentId: (src: string) => /^attachment:\/\/([a-f0-9]{64})$/.exec(src)?.[1],
  attachmentAccess: services.access, boundedContentImage: services.blob,
}))
vi.mock('@/lib/videoLinks', () => ({ resolveContentUrl: (src: string) => src }))
import { ContentImage } from './ContentImage'
import { useAuthStore } from '@/stores/authStore'

beforeEach(() => { vi.clearAllMocks(); useAuthStore.setState({ user: { id: 'owner-a' } } as never) })
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('ordinary saved content waits for each image click and discloses only its actual hostname', () => {
  const { container } = render(<><ContentImage src="https://images.example/a.png?secret=do-not-display" alt="第一张" /><ContentImage src="https://other.example/b.png" alt="第二张" /></>)
  expect(container.querySelector('img')).toBeNull()
  expect(container.querySelector('link')).toBeNull()
  expect(container.textContent).toContain('第一张 · images.example')
  expect(container.textContent).not.toContain('secret=')
  fireEvent.click(screen.getByRole('button', { name: '加载图片：第一张（images.example）' }))
  const images = container.querySelectorAll('img')
  expect(images).toHaveLength(1)
  expect(images[0]).toHaveAttribute('referrerpolicy', 'no-referrer')
  expect(images[0]).toHaveAttribute('crossorigin', 'anonymous')
  expect(screen.getByRole('button', { name: '加载图片：第二张（other.example）' })).toBeEnabled()
  expect(services.fetch).not.toHaveBeenCalled()
  expect(services.access).not.toHaveBeenCalled()
})

it('failed external image keeps its explanation and retries only after another click', () => {
  const { container } = render(<ContentImage src="https://images.example/a.png" alt="图表" />)
  fireEvent.click(screen.getByRole('button', { name: /加载图片/ }))
  fireEvent.error(container.querySelector('img')!)
  expect(container.querySelector('img')).toBeNull()
  expect(screen.getByText('图表 · images.example')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('图片加载失败')
  fireEvent.click(screen.getByRole('button', { name: /重试加载图片/ }))
  fireEvent.load(container.querySelector('img')!)
  expect(screen.queryByRole('button')).toBeNull()
})

it.each(['javascript:alert(1)', 'data:image/png;base64,AA', 'blob:local', 'file:///private.png', '/api/auth/session', '//images.example/x.png', 'https://trusted.example@evil.example/x', 'https://%65vil.example/x', 'https://images.example\\@evil.example/x', 'attachment://invalid'])('unsupported or ambiguous source has no execution control: %s', src => {
  const { container } = render(<ContentImage src={src} />)
  expect(container.querySelector('img')).toBeNull()
  expect(screen.queryByRole('button')).toBeNull()
  expect(screen.getByText(/图片未提供说明/)).toBeInTheDocument()
})

it('source/session/owner changes revoke a prior image authorization', () => {
  const { container, rerender } = render(<ContentImage src="https://images.example/a.png" imageSessionKey="preview-1" />)
  const load = () => fireEvent.click(screen.getByRole('button', { name: /加载图片/ }))
  load()
  rerender(<ContentImage src="https://images.example/b.png" imageSessionKey="preview-1" />)
  expect(container.querySelector('img')).toBeNull()
  load()
  rerender(<ContentImage src="https://images.example/b.png" imageSessionKey="preview-2" />)
  expect(container.querySelector('img')).toBeNull()
  load()
  act(() => useAuthStore.setState({ user: { id: 'owner-b' } } as never))
  expect(container.querySelector('img')).toBeNull()
})

it('preserves authenticated task screenshot routes but does not trust arbitrary relative resources', () => {
  const path = '/api/task/12345678-1234-1234-1234-123456789abc/artifacts/screenshots/frame_1.png'
  const { container } = render(<ContentImage src={path} />)
  expect(container.querySelector('img')).toHaveAttribute('src', path)
  expect(screen.queryByRole('button')).toBeNull()
})

it('owner attachment signed URLs remain in the attachment channel without an external-image prompt', async () => {
  services.access.mockResolvedValue({ url: 'https://storage.example/signed.png?token=opaque', authenticated: false })
  const id = 'a'.repeat(64)
  const { container } = render(<ContentImage src={`attachment://${id}`} alt="附件" />)
  await waitFor(() => expect(container.querySelector('img')).not.toBeNull())
  expect(services.access).toHaveBeenCalledWith(id)
  expect(container.querySelector('img')).toHaveAttribute('src', 'https://storage.example/signed.png?token=opaque')
  expect(screen.queryByRole('button')).toBeNull()
  expect(services.fetch).not.toHaveBeenCalled()
})

it('owner-authenticated attachments still use the bounded fetch and revoke their blob on unmount', async () => {
  services.access.mockResolvedValue({ url: '/api/workspace/attachments/image/content', authenticated: true })
  services.fetch.mockResolvedValue({ ok: true })
  services.blob.mockResolvedValue(new Blob(['image']))
  const create = vi.fn(() => 'blob:owner-image'), revoke = vi.fn()
  const OriginalURL = URL
  vi.stubGlobal('URL', class extends OriginalURL { static createObjectURL = create; static revokeObjectURL = revoke })
  const { container, unmount } = render(<ContentImage src={`attachment://${'b'.repeat(64)}`} />)
  await waitFor(() => expect(container.querySelector('img')).toHaveAttribute('src', 'blob:owner-image'))
  expect(services.fetch).toHaveBeenCalledWith('/api/workspace/attachments/image/content', { signal: expect.any(AbortSignal) })
  expect(services.blob).toHaveBeenCalledTimes(1)
  unmount()
  expect(revoke).toHaveBeenCalledWith('blob:owner-image')
})
