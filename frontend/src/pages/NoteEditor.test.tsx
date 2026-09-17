import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { I18nProvider } from '../lib/i18n'
import { NoteEditor } from './NoteEditor'

const noteStoreMock = vi.hoisted(() => ({
  loadNoteById: vi.fn(),
  updateNote: vi.fn(),
  deleteNote: vi.fn(),
  createShareLink: vi.fn(),
  getShareLink: vi.fn(),
  disableShareLink: vi.fn(),
}))

const apiMock = vi.hoisted(() => ({
  apiJson: vi.fn(),
}))

vi.mock('../lib/api', () => ({ apiJson: apiMock.apiJson }))
vi.mock('../stores/languageStore', () => ({
  useLanguageStore: () => ({ language: 'en', setLanguage: vi.fn(), syncWithAccount: vi.fn() }),
}))
vi.mock('../stores/noteLibraryStore', () => ({ useNoteLibraryStore: () => noteStoreMock }))
vi.mock('../components/Notes/RecordingRetryBar', () => ({ RecordingRetryBar: () => null }))

const transcriptEvidence = {
  language: 'en',
  full_text: 'We agree to active Sort former.',
  aliases: {},
  metadata: { asr_model: 'sensevoice-small' },
  segments: [
    {
      start: 62,
      end: 72,
      text: 'We agreed to activate Sortformer.',
      raw_text: 'We agree to active Sort former.',
      cleaned_text: 'We agreed to activate Sortformer.',
      speaker_id: 'speaker_01',
      speaker_label: 'Speaker 1',
    },
  ],
}

function renderEditor(initialEntry = '/note/note-1') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/note/:id" element={<I18nProvider><NoteEditor /></I18nProvider>} />
        <Route path="/notes" element={<div>Notes</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('NoteEditor transcript evidence', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window.HTMLMediaElement.prototype, 'play', {
      configurable: true,
      value: vi.fn().mockResolvedValue(undefined),
    })
    Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    })
    apiMock.apiJson.mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith('/speakers') && init?.method === 'PATCH') {
        return Promise.resolve({ aliases: { speaker_01: 'Susan Wang' } })
      }
      return Promise.resolve(transcriptEvidence)
    })
    noteStoreMock.loadNoteById.mockResolvedValue({
      id: 'note-1',
      title: 'Meeting note',
      content: '# Meeting minutes\n\nMinutes only.',
      sourceType: 'meeting_recording',
      taskId: 'task-1',
      status: 'done',
      scope: 'personal',
      createdAt: '2026-07-01T00:00:00Z',
      updatedAt: '2026-07-01T00:00:00Z',
    })
    noteStoreMock.getShareLink.mockResolvedValue(null)
  })

  it('requires confirmation and returns to the library only after deletion succeeds', async () => {
    noteStoreMock.deleteNote.mockResolvedValue(undefined)
    renderEditor()
    await screen.findByDisplayValue(/Minutes only/)
    fireEvent.click(screen.getByRole('button', { name: 'Delete note' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(noteStoreMock.deleteNote).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Delete note' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm deletion' }))
    expect(await screen.findByText('Notes')).toBeInTheDocument()
    expect(noteStoreMock.deleteNote).toHaveBeenCalledWith('note-1')
  })

  it('keeps the note open when deletion fails', async () => {
    noteStoreMock.deleteNote.mockRejectedValue(new Error('Access denied'))
    renderEditor()
    await screen.findByDisplayValue(/Minutes only/)
    fireEvent.click(screen.getByRole('button', { name: 'Delete note' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm deletion' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Access denied')
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  })

  it('keeps summary and transcript separate while sharing one audio player', async () => {
    renderEditor()

    expect(await screen.findByDisplayValue(/Minutes only/)).toBeInTheDocument()
    expect(screen.getAllByTestId('source-audio')).toHaveLength(1)
    expect(screen.queryByText('We agreed to activate Sortformer.')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: 'Transcript' }))

    expect(await screen.findByText('We agreed to activate Sortformer.')).toBeInTheDocument()
    expect(screen.getByText('asr_model · sensevoice-small')).toBeInTheDocument()
    expect(screen.getAllByTestId('source-audio')).toHaveLength(1)
    expect(screen.queryByDisplayValue(/Minutes only/)).not.toBeInTheDocument()
  })

  it('toggles raw evidence, seeks playback, follows time and saves speaker aliases', async () => {
    renderEditor('/note/note-1?view=transcript')
    const cleanedTurn = await screen.findByText('We agreed to activate Sortformer.')
    const audio = screen.getByTestId('source-audio') as HTMLAudioElement

    fireEvent.click(cleanedTurn)
    expect(audio.currentTime).toBe(62)
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Show raw ASR' }))
    expect(await screen.findByText('We agree to active Sort former.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Rename speaker_01' }))
    fireEvent.change(screen.getByLabelText('Rename speaker_01'), { target: { value: 'Susan Wang' } })
    fireEvent.click(screen.getByTitle('Save speaker name'))
    expect(await screen.findByText('Susan Wang')).toBeInTheDocument()

    audio.currentTime = 63
    fireEvent.timeUpdate(audio)
    await waitFor(() => {
      expect(screen.getByText('We agree to active Sort former.').closest('button')).toHaveAttribute('aria-current', 'true')
    })
  })

  it('exports transcript markdown independently from the summary', async () => {
    const createObjectUrl = URL.createObjectURL
    const revokeObjectUrl = URL.revokeObjectURL
    URL.createObjectURL = vi.fn(() => 'blob:transcript') as typeof URL.createObjectURL
    URL.revokeObjectURL = vi.fn() as typeof URL.revokeObjectURL
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    try {
      renderEditor('/note/note-1?view=transcript')
      await screen.findByText('We agreed to activate Sortformer.')
      fireEvent.click(screen.getByTitle('Export'))

      expect(clickSpy).toHaveBeenCalled()
      expect(clickSpy.mock.instances[0]?.download).toBe('Meeting note.transcript.md')
    } finally {
      URL.createObjectURL = createObjectUrl
      URL.revokeObjectURL = revokeObjectUrl
      clickSpy.mockRestore()
    }
  })

  it('keeps one shared local video player available from the transcript view', async () => {
    noteStoreMock.loadNoteById.mockResolvedValue({
      id: 'note-1',
      title: 'Video note',
      content: '# Video summary',
      sourceType: 'video',
      taskId: 'task-1',
      status: 'done',
      scope: 'personal',
      createdAt: '2026-07-01T00:00:00Z',
      updatedAt: '2026-07-01T00:00:00Z',
    })

    renderEditor('/note/note-1?view=transcript')
    const turn = await screen.findByText('We agreed to activate Sortformer.')
    const video = screen.getByTestId('source-video') as HTMLVideoElement

    fireEvent.click(turn)

    expect(screen.getAllByTestId('source-video')).toHaveLength(1)
    expect(video.currentTime).toBe(62)
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled()
  })
})
