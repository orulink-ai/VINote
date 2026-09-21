import { render, screen, cleanup } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { TranscriptionProgress } from './TranscriptionProgress'

afterEach(cleanup)
describe('TranscriptionProgress', () => {
  it('shows actual coverage and estimated transcription time', () => {
    render(<TranscriptionProgress zh processedSeconds={30} totalSeconds={60} etaSeconds={10} />)
    expect(screen.getByText('已转写 0:30 / 1:00 (50%)')).toBeInTheDocument()
    expect(screen.getByText(/还需约 10 秒/)).toBeInTheDocument()
  })
  it('does not invent an estimate while waiting for the first result', () => {
    render(<TranscriptionProgress zh processedSeconds={0} totalSeconds={60} />)
    expect(screen.getByText(/暂无法估算/)).toBeInTheDocument()
    expect(screen.queryByText(/预计还需/)).not.toBeInTheDocument()
  })
  it('marks completed transcription without showing an old estimate', () => {
    render(<TranscriptionProgress zh processedSeconds={60} totalSeconds={60} etaSeconds={10} />)
    expect(screen.getByText(/音频转写完成/)).toBeInTheDocument()
    expect(screen.queryByText(/预计还需/)).not.toBeInTheDocument()
  })
})
