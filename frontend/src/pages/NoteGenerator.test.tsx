import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../lib/i18n'
import { useNoteGenerationStore } from '../stores/noteGenerationStore'
import { NoteGenerator } from './NoteGenerator'

const apiMock = vi.hoisted(() => ({
  apiJson: vi.fn(),
}))
const navigateMock = vi.hoisted(() => vi.fn())

vi.mock('../lib/api', () => ({
  apiJson: apiMock.apiJson,
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
  useSearchParams: () => [new URLSearchParams()],
}))

vi.mock('../stores/languageStore', () => ({
  useLanguageStore: () => ({
    language: 'en',
    setLanguage: vi.fn(),
    syncWithAccount: vi.fn(),
  }),
}))

vi.mock('../stores/modelProfileStore', () => ({
  useModelProfileStore: () => ({
    profiles: [],
    selectedProfileId: '',
    selectProfile: vi.fn(),
    loadProfiles: vi.fn(),
  }),
}))

vi.mock('../stores/sttProfileStore', () => ({
  useSTTProfileStore: () => ({
    profiles: [],
    selectedProfileId: '',
    selectProfile: vi.fn(),
    loadProfiles: vi.fn(),
  }),
}))

vi.mock('../stores/noteLibraryStore', () => ({
  useNoteLibraryStore: () => ({
    saveNote: vi.fn(),
  }),
}))

vi.mock('../stores/teamStore', async () => {
  const actual = await vi.importActual<typeof import('../stores/teamStore')>('../stores/teamStore')
  return {
    ...actual,
    useTeamStore: () => ({
      currentWorkspace: 'personal',
      teams: [],
      loadTeams: vi.fn(),
    }),
  }
})

function renderGenerator() {
  return render(
    <I18nProvider>
      <NoteGenerator />
    </I18nProvider>
  )
}

describe('NoteGenerator failed generation recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useNoteGenerationStore.getState().reset()
  })

  it('stops polling when the task record is missing', async () => {
    apiMock.apiJson.mockResolvedValueOnce({ task_id: 'missing-task' })
      .mockResolvedValue({ status: 'not_found', message: 'Task not found' })
    renderGenerator()
    await userEvent.type(
      screen.getByPlaceholderText('Paste a YouTube, Bilibili, or other supported video URL...'),
      'https://example.com/video'
    )
    await userEvent.click(screen.getByRole('button', { name: 'Start generation' }))
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('failed'), { timeout: 4000 })
    expect(screen.getByText('Task record is missing. Please try again.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeEnabled()
  })

  it('lets users regenerate directly with the same video URL after a generation request fails', async () => {
    apiMock.apiJson
      .mockRejectedValueOnce(new Error('backend unavailable'))
      .mockResolvedValueOnce({ task_id: 'retry-task' })

    renderGenerator()

    await userEvent.type(
      screen.getByPlaceholderText('Paste a YouTube, Bilibili, or other supported video URL...'),
      'https://example.com/video'
    )
    await userEvent.click(screen.getByRole('button', { name: 'Start generation' }))

    expect(await screen.findByText('backend unavailable')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Regenerate' }))

    await waitFor(() => expect(apiMock.apiJson).toHaveBeenCalledTimes(2))
    const [, retryOptions] = apiMock.apiJson.mock.calls[1]
    expect(apiMock.apiJson.mock.calls[1][0]).toBe('/api/generate')
    expect(JSON.parse(retryOptions.body)).toMatchObject({
      video_url: 'https://example.com/video',
      summary_mode: 'default',
      output_language: 'en',
    })
  })
})
