import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { StartMeetingButton } from './StartMeetingButton'
import type { MeetingType } from '../../lib/meetingCapture'

vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }))

function SourceChoice({ disabled = false, onStart }: { disabled?: boolean; onStart: (type: MeetingType) => void }) {
  const [type, setType] = useState<MeetingType>('audio')
  return <StartMeetingButton disabled={disabled} type={type} onTypeChange={setType} onStart={onStart} />
}

describe('StartMeetingButton', () => {
  it.each([['仅录音', 'audio'], ['录音与屏幕', 'video']])('starts only after choosing %s and confirming start', async (label, type) => {
    const onStart = vi.fn()
    render(<SourceChoice onStart={onStart} />)
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: label }))
    expect(onStart).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: '开始录制' }))
    expect(onStart).toHaveBeenCalledExactlyOnceWith(type)
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
  it('selecting a source does not begin capture', async () => {
    const onStart = vi.fn()
    render(<SourceChoice onStart={onStart} />)
    await userEvent.click(screen.getByRole('radio', { name: '录音与屏幕' }))
    expect(onStart).not.toHaveBeenCalled()
  })
  it('does not start another meeting while capture is busy', () => {
    render(<SourceChoice disabled onStart={vi.fn()} />)
    expect(screen.getByRole('button', { name: '开始录制' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: '录音与屏幕' })).toBeDisabled()
  })
  it('starts screen capture synchronously within the confirmation click', () => {
    const onStart = vi.fn()
    render(<StartMeetingButton disabled={false} type="video" onTypeChange={vi.fn()} onStart={onStart} />)
    fireEvent.click(screen.getByRole('button', { name: '开始录制' }))
    expect(onStart).toHaveBeenCalledExactlyOnceWith('video')
  })
})
