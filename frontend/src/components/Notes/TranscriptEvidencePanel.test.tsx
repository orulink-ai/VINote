import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { TranscriptEvidencePanel } from './TranscriptEvidencePanel'

vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'en' }) }))

it('exposes unrecognized intervals for replay without labeling prior speech as current', () => {
  const seek = vi.fn()
  render(<TranscriptEvidencePanel evidence={{ full_text: 'Speech', aliases: {}, segments: [{ start: 0, end: 60, text: 'Speech' }], metadata: { unrecognized_segments: [{ start: 60, end: 90 }, { start: -1, end: 1 }, { start: 0, end: 'invalid' }] } }} loading={false} currentTimestamp={65} textMode="raw" onTextModeChange={vi.fn()} onSeek={seek} onSaveAlias={vi.fn()} />)
  expect(screen.getByText(/does not establish silence/)).toBeVisible()
  expect(screen.getByText('1 unrecognized intervals')).toBeVisible()
  expect(screen.queryByText('Current segment')).toBeNull()
  fireEvent.click(screen.getByText('1 unrecognized intervals'))
  fireEvent.click(screen.getByRole('button', { name: '01:00–01:30' }))
  expect(seek).toHaveBeenCalledWith(60)
})
