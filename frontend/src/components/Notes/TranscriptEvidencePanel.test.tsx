import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { TranscriptEvidencePanel } from './TranscriptEvidencePanel'

vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'en' }) }))

it('distinguishes provider speaker IDs when no labels were supplied', () => {
  render(<TranscriptEvidencePanel evidence={{ full_text: 'Hello there', aliases: {}, segments: [{ start: 0, end: 1, text: 'Hello', speaker_id: '1' }, { start: 1, end: 2, text: 'there', speaker_id: '2' }] }} loading={false} currentTimestamp={0} textMode="raw" onTextModeChange={vi.fn()} onSeek={vi.fn()} onSaveAlias={vi.fn()} />)
  expect(screen.getByText('Speaker 1')).toBeVisible()
  expect(screen.getByText('Speaker 2')).toBeVisible()
})

it('groups consecutive speaker labels while retaining individual seek targets', () => {
  const seek = vi.fn()
  render(<TranscriptEvidencePanel evidence={{ full_text: 'First Second Third', aliases: {}, segments: [{ start: 0, end: 1, text: 'First', speaker_id: '1' }, { start: 1, end: 2, text: 'Second', speaker_id: '1' }, { start: 2, end: 3, text: 'Third', speaker_id: '2' }] }} loading={false} currentTimestamp={0} textMode="raw" onTextModeChange={vi.fn()} onSeek={seek} onSaveAlias={vi.fn()} />)
  expect(screen.getAllByText('Speaker 1')).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: 'Rename 1' })).toHaveLength(1)
  expect(screen.getByText(/Speaker labels · 2/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Second' }))
  expect(seek).toHaveBeenCalledWith(1)
})

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
