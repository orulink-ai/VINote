import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MarkdownContent } from './MarkdownContent'
vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand')
  return { useAuthStore: create(() => ({ user: { id: 'owner' } })) }
})

afterEach(cleanup)
it('retains one image decision during unrelated parent renders, but resets on content changes', () => {
  const source = '# 验收\n\n![图表](https://images.example/a.png)'
  const { container, rerender } = render(<MarkdownContent content={source} className="before" />)
  fireEvent.click(screen.getByRole('button', { name: '加载图片：图表（images.example）' }))
  const image = container.querySelector('img')!
  expect(image).not.toBeNull()
  rerender(<MarkdownContent content={source} className="after" />)
  expect(container.querySelector('img')).toBe(image)
  fireEvent.error(image)
  expect(screen.getByRole('button', { name: '重试加载图片：图表（images.example）' })).toBeInTheDocument()
  rerender(<MarkdownContent content={source + '\n\n新版本'} className="after" />)
  expect(container.querySelector('img')).toBeNull()
})
it('seeks plain recording references and range starts while preserving code and existing links', () => {
  const seek = vi.fn()
  render(<MarkdownContent content={'讨论 [01:23]、[03:00–03:10]。`[00:05]` [原链接 [04:00]](https://example.invalid)'} mediaUrl="/api/notes/test/media" onVideoJump={seek} />)
  fireEvent.click(screen.getByRole('link', { name: '[01:23]' }))
  fireEvent.click(screen.getByRole('link', { name: '[03:00–03:10]' }))
  expect(seek.mock.calls).toEqual([[83], [180]])
  expect(screen.queryByRole('link', { name: '[00:05]' })).toBeNull()
  expect(screen.getByRole('link', { name: '原链接 [04:00]' })).toHaveAttribute('href', 'https://example.invalid')
})

it('links each compound evidence range and visual frame seconds independently', () => {
  const seek = vi.fn()
  render(<MarkdownContent content={'讨论 [01:40–04:10；08:20–09:10]，画面 [105 秒]，长录音 [01:02:03]；日期 [2026年10月10日]。'} mediaUrl="/api/notes/test/media" onVideoJump={seek} />)
  for (const name of ['01:40–04:10', '08:20–09:10', '[105 秒]', '[01:02:03]']) fireEvent.click(screen.getByRole('link', { name }))
  expect(seek.mock.calls).toEqual([[100], [500], [105], [3723]])
  expect(screen.queryByRole('link', { name: '[2026年10月10日]' })).toBeNull()
})

it('defaults saved or generated Markdown to per-image confirmation without changing text or safe flowcharts', () => {
  const source = '# 原文\n\n![图表](https://images.example/a.png)\n\n```mermaid\nflowchart TD\nA[获取] --> B[保存]\n```'
  const { container, rerender } = render(<MarkdownContent content={source} />)
  expect(screen.getByRole('heading', { name: /原文/ })).toBeInTheDocument()
  expect(screen.getByRole('img', { name: /流程图/ })).toBeInTheDocument()
  expect(container.querySelector('img')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '加载图片：图表（images.example）' }))
  expect(container.querySelectorAll('img')).toHaveLength(1)
  rerender(<MarkdownContent content={`${source}\n\n另一版本`} />)
  expect(container.querySelector('img')).toBeNull()
  expect(screen.getByText('另一版本')).toBeInTheDocument()
})
