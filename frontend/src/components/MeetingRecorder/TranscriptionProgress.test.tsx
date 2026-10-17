import { render, screen, cleanup } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { TranscriptionProgress } from './TranscriptionProgress'

afterEach(cleanup)
describe('TranscriptionProgress', () => {
  it('shows actual coverage and estimated transcription time', () => {
    render(<TranscriptionProgress zh processedSeconds={30} totalSeconds={60} etaSeconds={10} />)
    expect(screen.getByText('已转写 0:30 / 1:00 (50%)')).toBeInTheDocument()
    expect(screen.getByText(/还需约 10 秒/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: '音频转写进度' })).toHaveAttribute('aria-valuenow', '50')
    expect(screen.getByRole('progressbar').firstElementChild).toHaveStyle({ width: '50%' })
  })
  it('does not invent an estimate while waiting for the first result', () => {
    render(<TranscriptionProgress zh processedSeconds={0} totalSeconds={60} />)
    expect(screen.getByText(/暂无法估算/)).toBeInTheDocument()
    expect(screen.queryByText(/预计还需/)).not.toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0')
  })
  it('marks completed transcription without showing an old estimate', () => {
    render(<TranscriptionProgress zh processedSeconds={60} totalSeconds={60} etaSeconds={10} />)
    expect(screen.getByText(/音频转写完成/)).toBeInTheDocument()
    expect(screen.queryByText(/预计还需/)).not.toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  })
  it.each([
    [undefined, 60], [30, undefined], [30, 0], [Infinity, 60], [30, NaN], [-1, 60],
  ])('shows an indeterminate bar when coverage is unavailable (%s / %s)', (processedSeconds, totalSeconds) => {
    render(<TranscriptionProgress zh processedSeconds={processedSeconds} totalSeconds={totalSeconds} etaSeconds={10} />)
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
    expect(screen.getByRole('progressbar').firstElementChild).toHaveClass('motion-reduce:animate-none')
    expect(screen.getByText('正在转写完整录音')).toBeVisible()
    expect(screen.queryByText(/预计还需/)).not.toBeInTheDocument()
  })
  it('updates only from new measurements and clamps coverage at completion', () => {
    const { rerender } = render(<TranscriptionProgress zh={false} processedSeconds={15} totalSeconds={60} />)
    expect(screen.getByRole('progressbar', { name: 'Audio transcription progress' })).toHaveAttribute('aria-valuenow', '25')
    rerender(<TranscriptionProgress zh={false} processedSeconds={90} totalSeconds={60} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    expect(screen.getByText('Transcribed 1:00 / 1:00 (100%)')).toBeVisible()
    rerender(<TranscriptionProgress zh={false} />)
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuetext', 'Transcribing; waiting for measured progress')
  })
})
