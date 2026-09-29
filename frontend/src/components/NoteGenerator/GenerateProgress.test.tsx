import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { GenerateProgress } from './GenerateProgress'
vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ copy: { progress: { prepareRequest: '准备', downloadAudio: '下载', transcribeAudio: '转写', generateNote: '笔记', processScreenshots: '截图', failed: '失败', completed: '完成' } } }) }))
it('preserves completed steps and the actual bar position on failure', () => {
 render(<GenerateProgress status="failed" progress={30} currentStep="transcribing" />)
 expect(screen.getByText('下载').parentElement).toHaveAttribute('data-state', 'completed')
 expect(screen.getByText('转写').parentElement).toHaveAttribute('data-state', 'failed')
 expect(screen.getByText('笔记').parentElement).toHaveAttribute('data-state', 'pending')
 expect(screen.getByRole('progressbar')).toHaveStyle({ width: '30%' })
})
it('shows real chunk status instead of a misleading completion percentage', () => {
 render(<GenerateProgress status="processing" progress={45} currentStep="transcribing" message="Transcribing chunk 2/3 (16:00 - 32:00)..." />)
 expect(screen.getByRole('status')).toHaveTextContent('正在转写第 2/3 段')
 expect(screen.queryByText('45%')).not.toBeInTheDocument()
})
