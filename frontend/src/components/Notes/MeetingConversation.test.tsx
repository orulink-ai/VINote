import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { MeetingConversation } from './MeetingConversation'
import { apiJson } from '@/lib/api'

vi.mock('@/lib/api', () => ({ apiJson: vi.fn() }))
vi.mock('@/components/Markdown/MarkdownContent', () => ({ MarkdownContent: ({ content }: { content: string }) => <p>{content}</p> }))
beforeEach(() => vi.clearAllMocks())

it('keeps a failed question and submits it again without losing the conversation', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('暂时断网')).mockResolvedValueOnce({ answer: '会议确认保留原录音。' })
  render(<MeetingConversation noteId="meeting-a" />)
  fireEvent.change(screen.getByLabelText('会议问题'), { target: { value: '会议确认了什么？' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await screen.findByText('暂时断网')
  expect(screen.getByLabelText('会议问题')).toHaveValue('会议确认了什么？')
  fireEvent.click(screen.getByRole('button', { name: '重试提问' }))
  await screen.findByText('会议确认保留原录音。')
  await waitFor(() => expect(screen.getByLabelText('会议问题')).toHaveValue(''))
  expect(apiJson).toHaveBeenLastCalledWith('/api/notes/meeting-a/ask', expect.objectContaining({ body: JSON.stringify({ question: '会议确认了什么？' }) }))
})

it('treats an empty successful response as a retryable failure and retains the question', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce({ answer: '   ' }).mockResolvedValueOnce({ answer: '没有明确负责人。' })
  render(<MeetingConversation noteId="meeting-empty" />)
  fireEvent.change(screen.getByLabelText('会议问题'), { target: { value: '负责人是谁？' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await screen.findByRole('button', { name: '重试提问' })
  expect(screen.getByLabelText('会议问题')).toHaveValue('负责人是谁？')
  fireEvent.click(screen.getByRole('button', { name: '重试提问' }))
  await screen.findByText('没有明确负责人。')
})
