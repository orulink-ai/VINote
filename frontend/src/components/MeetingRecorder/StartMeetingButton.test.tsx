import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { StartMeetingButton } from './StartMeetingButton'

vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }))

describe('StartMeetingButton', () => {
  it.each([['不共享，开始会议', 'audio'], ['共享屏幕并开始', 'video']])('starts only after choosing %s', async (label, type) => {
    const onStart = vi.fn()
    render(<StartMeetingButton disabled={false} onStart={onStart} />)
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '开始会议' }))
    expect(onStart).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: label }))
    expect(onStart).toHaveBeenCalledExactlyOnceWith(type)
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
  it('does not capture when cancelled', async () => {
    const onStart = vi.fn()
    render(<StartMeetingButton disabled={false} onStart={onStart} />)
    await userEvent.click(screen.getByRole('button', { name: '开始会议' }))
    await userEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(onStart).not.toHaveBeenCalled()
  })
  it('does not start another meeting while capture is busy', () => {
    render(<StartMeetingButton disabled onStart={vi.fn()} />)
    expect(screen.getByRole('button', { name: '开始会议' })).toBeDisabled()
  })
})
