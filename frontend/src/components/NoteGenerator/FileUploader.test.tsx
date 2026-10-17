import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FileUploader } from './FileUploader'

vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ copy: { fileUploader: {
  videoUrl: '链接', localFile: '文件', videoPlaceholder: '粘贴链接', selectFile: '选择文件',
} } }) }))

const callbacks = () => ({ onVideoUrlChange: vi.fn(), onFileSelect: vi.fn(), onModeChange: vi.fn() })
afterEach(cleanup)

describe('source input labels', () => {
  it('associates the URL label and help with the actual input and focuses it on click', async () => {
    render(<FileUploader {...callbacks()} videoUrl="" />)
    const input = screen.getByRole('textbox', { name: '网页或视频链接' })
    expect(screen.getByLabelText('网页或视频链接')).toBe(input)
    expect(input).toHaveAccessibleDescription('支持普通网页、B 站等公开视频、PDF 和 DOCX 文档链接。需要登录的来源请导出文件再导入。')
    await userEvent.click(screen.getByText('网页或视频链接'))
    expect(input).toHaveFocus()
  })

  it('gives multiple uploader instances distinct label targets', () => {
    render(<><FileUploader {...callbacks()} videoUrl="" /><FileUploader {...callbacks()} videoUrl="" /></>)
    const inputs = screen.getAllByLabelText('网页或视频链接')
    expect(inputs[0].id).not.toBe(inputs[1].id)
    for (const input of inputs) expect((input as HTMLInputElement).labels?.[0]).toHaveAttribute('for', input.id)
  })

  it('labels the native file input and retains document selection and removal behavior', async () => {
    const handlers = callbacks()
    render(<FileUploader {...handlers} videoUrl="" initialMode="file" />)
    const input = screen.getByLabelText('选择或拖入音视频、PDF、Word 和文字文件')
    expect(input).toHaveAttribute('type', 'file')
    const file = new File(['正文'], 'review.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
    await userEvent.upload(input, file)
    expect(handlers.onFileSelect).toHaveBeenCalledWith(file)
    expect(handlers.onModeChange).toHaveBeenCalledWith('document')
    await userEvent.click(screen.getByRole('button', { name: '移除所选文件' }))
    expect(handlers.onFileSelect).toHaveBeenLastCalledWith(null)
  })

  it('keeps documents out of the meeting flow while accepting meeting audio', async () => {
    const handlers = callbacks()
    render(<FileUploader {...handlers} videoUrl="" initialMode="file" urlEnabled={false} meetingOnly />)
    const input = screen.getByLabelText('选择或拖入会议音视频或逐字稿')
    expect(input).toHaveAttribute('accept', expect.not.stringContaining('.pdf'))
    await userEvent.upload(input, new File(['document'], 'agenda.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }), { applyAccept: false })
    expect(screen.getByRole('alert')).toHaveTextContent('PDF、Word 和网页请在笔记中整理')
    expect(handlers.onFileSelect).not.toHaveBeenCalledWith(expect.objectContaining({ name: 'agenda.docx' }))
    const audio = new File(['audio'], 'meeting.m4a', { type: 'audio/mp4' })
    await userEvent.upload(input, audio)
    expect(handlers.onFileSelect).toHaveBeenCalledWith(audio)
  })
})
