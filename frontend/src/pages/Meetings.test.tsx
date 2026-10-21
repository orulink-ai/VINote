import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import type { LibraryNote } from '@/hooks/useLibraryNotes'
import type { PendingMeeting } from '@/lib/audioStorage'
import type { ReactNode } from 'react'
import { START_MEETING_EVENT } from '@/lib/meetingCapture'

const state = vi.hoisted(() => ({
  notes: [] as LibraryNote[], recordings: [] as PendingMeeting[],
  loadNotes: vi.fn(), list: vi.fn(), api: vi.fn(), update: vi.fn(),
  workspace: { scope: 'personal' as const },
}))
vi.mock('@/lib/api', () => ({ apiJson: state.api }))
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: state.list, updatePendingMeeting: state.update }))
vi.mock('@/lib/i18n', () => ({ useI18n: () => ({ locale: 'zh' }) }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: Object.assign((select: (s: { user: { id: string } }) => unknown) => select({ user: { id: 'owner' } }), { getState: () => ({ user: { id: 'owner' } }) }) }))
vi.mock('@/stores/teamStore', () => ({ useTeamStore: () => ({ currentWorkspace: state.workspace, teams: [] }), getWorkspaceLabel: () => '个人空间' }))
vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: () => ({ loading: false, error: '', loadNotes: state.loadNotes }) }))
vi.mock('@/stores/meetingRecorderStore', () => ({ isMeetingBusy: () => false, useMeetingRecorderStore: () => ({ phase: 'idle', error: '', recordingId: null }) }))
vi.mock('@/hooks/useLibraryNotes', async () => ({ ...(await vi.importActual<typeof import('@/hooks/useLibraryNotes')>('@/hooks/useLibraryNotes')), useLibraryNotes: () => state.notes }))
vi.mock('@/components/ui/motion', () => ({ TextReveal: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@/components/MeetingRecorder/SavedRecordingChoice', () => ({ SavedRecordingChoice: () => null }))
vi.mock('@/components/MeetingRecorder/MicrophoneCheck', () => ({ MicrophoneCheck: () => null }))
vi.mock('@/components/MeetingRecorder/LocalRecordingPreview', () => ({ LocalRecordingPreview: () => <p>本机原件操作</p> }))
import { Meetings } from './Meetings'
import { meetingRecordingTitle } from '@/lib/meetingGroups'
const captureTime = (task: string) => new Date(Date.UTC(2026, 9, 10, 7, [...task].reduce((sum, c) => sum + c.charCodeAt(0), 0) % 60)).toISOString()
const heading = (id: string, state = '已完成', task = 'task-' + id) => `${meetingRecordingTitle(captureTime(task))} · ${state}`

function note(id: string, archived = false, sourceType = 'meeting_recording', taskId?: string): LibraryNote {
  const canonicalTaskId = taskId || 'task-' + id
  return { id, title: id, archived, sourceType, taskId: canonicalTaskId,
    meetingSource: ['meeting_recording', 'meeting_video'].includes(sourceType) ? { ownerId: 'owner', canonicalTaskId, recordingStartedAt: captureTime(canonicalTaskId) } : undefined,
    content: `${id}正文`, status: 'done', scope: 'personal', createdAt: '2026-10-11T00:00:00Z', updatedAt: '2026-10-11T00:00:00Z' }
}
function recording(id: string): PendingMeeting {
  return { id, ownerId: 'owner', workspace: state.workspace, options: { title: id }, startedAt: '2026-10-11T00:00:00Z', elapsedSeconds: 20, recordingStatus: 'saved', processingStatus: 'idle' } as PendingMeeting
}
function Location() {
  const location = useLocation()
  return <output aria-label="测试位置">{JSON.stringify({ path: location.pathname + location.search + location.hash, state: location.state })}</output>
}
function mount(path = '/meetings') {
  render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Location /><Routes>
    <Route path="/meetings" element={<Meetings />} />
    <Route path="/note/:id" element={<p>会议内容详情</p>} />
    <Route path="/workspace/:id" element={<p>会议内容详情</p>} />
    <Route path="/generate" element={<p>来源确认页</p>} />
  </Routes></MemoryRouter>)
}
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear()
  state.notes = [note('正在使用'), note('已归档纪要', true), note('录屏纪要', true, 'meeting_video'), note('普通文档', true, 'document'), note('名称不是类型', true, 'meeting_unknown')]
  state.recordings = [recording('尚未生成的原录制')]
  state.list.mockImplementation(async () => state.recordings)
  state.api.mockImplementation(async (path: string) => path.startsWith('/api/task/') ? { status: 'success', result: { title: 'Synthetic completed meeting', markdown: 'Synthetic saved minutes' } } : { diarization: { available: true } })
})
afterEach(() => { cleanup(); sessionStorage.clear() })

it('shows every linked meeting dossier including historical personal archived content', async () => {
  mount()
  await screen.findByRole('button', { name: `${meetingRecordingTitle('2026-10-11T00:00:00Z')} · 未生成` })
  expect(screen.getByRole('tab', { name: '全部会议' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('button', { name: heading('正在使用') })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: heading('已归档纪要') })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '导入会议文件' })).toBeInTheDocument()
})
it('keeps legacy archived deep links reachable without applying the old personal archive filter', async () => {
  mount('/meetings?archived=1')
  await waitFor(() => expect(state.list).toHaveBeenCalled())
  expect(screen.getByRole('button', { name: heading('已归档纪要') })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: heading('录屏纪要') })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /普通文档|名称不是类型/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: heading('正在使用') })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: `${meetingRecordingTitle('2026-10-11T00:00:00Z')} · 未生成` })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '录制会议' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '导入会议文件' })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: '全部会议' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.queryByText('本机原件操作')).not.toBeInTheDocument()
  expect(state.update).not.toHaveBeenCalled()
  expect(state.api.mock.calls.every(([, options]) => !options?.method)).toBe(true)
})
it('preserves project/query/hash and the meeting status filter when switching to pending association', async () => {
  state.notes.push({ ...note('未关联旧稿', true), taskId: undefined, meetingSource: undefined })
  mount('/meetings?project=Review&filter=processing#list')
  const user = userEvent.setup()
  await user.click(screen.getByRole('tab', { name: '需处理' }))
  await user.click(screen.getByRole('tab', { name: '待归档' }))
  expect(screen.getByLabelText('测试位置')).toHaveTextContent('project=Review&filter=processing&view=pending#list')
  expect(screen.getByRole('button', { name: /查看纪要 · 未关联旧稿/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: heading('已归档纪要') })).not.toBeInTheDocument()
  await user.click(screen.getByRole('tab', { name: '全部会议' }))
  expect(screen.getByRole('tab', { name: '需处理' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByLabelText('测试位置')).not.toHaveTextContent('view=pending')
  expect(screen.getByLabelText('测试位置')).toHaveTextContent('project=Review&filter=processing#list')
})
it('opens an archived detail with the complete meeting parent instead of a generic return', async () => {
  mount('/meetings?archived=1&project=Review#list')
  await userEvent.click(await screen.findByRole('button', { name: heading('已归档纪要') }))
  expect(screen.queryByText('会议内容详情')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /查看纪要 · 已归档纪要/ }))
  expect(screen.getByText('会议内容详情')).toBeInTheDocument()
  const location = JSON.parse(screen.getByLabelText('测试位置').textContent!)
  expect(location.state.returnTo).toBe('/meetings?archived=1&project=Review#list')
})
it('keeps old and new archive flags inside one dossier and out of pending association', async () => {
  const old = note('较早归档历史', true, 'meeting_recording', 'same-task')
  const current = { ...note('当前会议', false, 'meeting_recording', 'same-task'), updatedAt: '2026-10-12T00:00:00Z' }
  state.notes = [old, current]; mount('/meetings?archived=1')
  expect(await screen.findByRole('button', { name: heading('较早归档历史', '已完成', 'same-task') })).toBeInTheDocument()
  expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(2) // the separate retained recording also remains visible
  expect(screen.getByText(/^关联纪要（2条）/)).toBeInTheDocument()
  await userEvent.click(screen.getByText(/^关联纪要（2条）/))
  expect(screen.getByRole('button', { name: /查看纪要 · 较早归档历史/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /查看纪要 · 当前会议/ })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('tab', { name: '待归档' }))
  expect(screen.getByText('暂无待归档内容')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /查看纪要/ })).not.toBeInTheDocument()
})
it('retains every version and original under the same dossier despite historical archive flags', async () => {
  const old = note('较早活动历史', false, 'meeting_recording', 'same-task')
  const current = { ...note('当前归档会议', true, 'meeting_recording', 'same-task'), updatedAt: '2026-10-12T00:00:00Z' }
  state.notes = [old, current]
  state.recordings = [{ ...recording('保留原件'), taskId: 'same-task', noteId: current.id }]
  const before = JSON.stringify({ notes: state.notes, recordings: state.recordings })
  mount('/meetings?archived=1'); await waitFor(() => expect(state.list).toHaveBeenCalled())
  expect(await screen.findAllByRole('button', { name: heading('保留原件', '已完成', 'same-task') })).toHaveLength(1)
  expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(1)
  await userEvent.click(screen.getByText('关联纪要（2条）与原录制'))
  expect(screen.getByRole('button', { name: /查看纪要 · 较早活动历史/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /查看纪要 · 当前归档会议/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /查看原录制 · 保留原件/ })).toBeInTheDocument()
  expect(JSON.stringify({ notes: state.notes, recordings: state.recordings })).toBe(before)
  expect(state.update).not.toHaveBeenCalled()
})
it('clears search within pending association without changing the dossier view or old archive metadata', async () => {
  state.notes.push({ ...note('未关联旧稿', true), taskId: undefined, meetingSource: undefined })
  mount('/meetings?view=pending')
  await userEvent.type(screen.getByRole('textbox', { name: '搜索记录' }), 'missing')
  expect(screen.getByText('没有匹配的待归档内容')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '清除筛选' }))
  expect(within(screen.getByRole('tablist', { name: '会议档案视图' })).getByRole('tab', { name: '待归档' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('button', { name: /查看纪要 · 未关联旧稿/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: heading('已归档纪要') })).not.toBeInTheDocument()
})

it('keeps pending historical project content reachable with an exact return route', async () => {
  state.notes = [{ ...note('项目历史纪要', true), taskId: undefined, meetingSource: undefined,
    project: 'Review', workspaceKey: 'saved-project-key' }]
  mount('/meetings?project=Review&view=pending#list')
  await userEvent.click(await screen.findByRole('button', { name: /查看纪要 · 项目历史纪要/ }))
  const location = JSON.parse(screen.getByLabelText('测试位置').textContent!)
  expect(location.path).toBe('/workspace/saved-project-key')
  expect(location.state.returnTo).toBe('/meetings?project=Review&view=pending#list')
  expect(state.update).not.toHaveBeenCalled()
})

it('keeps an optional title and source choice while cancelling setup without beginning capture', async () => {
  mount()
  const user = userEvent.setup()
  const started = vi.fn()
  window.addEventListener(START_MEETING_EVENT, started)
  try {
    await user.click(screen.getByRole('button', { name: '录制会议' }))
    const dialog = screen.getByRole('dialog', { name: '准备录制' })
    expect(within(dialog).getByRole('textbox', { name: '会议标题（可选）' })).not.toBeRequired()
    expect(within(dialog).getByRole('radio', { name: '仅录音' })).toBeChecked()
    expect(within(dialog).queryByText(/1080p/)).not.toBeInTheDocument()
    await user.type(within(dialog).getByRole('textbox', { name: '会议标题（可选）' }), '设计审查')
    await user.click(within(dialog).getByRole('radio', { name: '录音与屏幕' }))
    expect(within(dialog).queryByText(/笔记归属/)).not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '开始录制' })).toBeEnabled()
    expect(within(dialog).getByText('测试麦克风（可选）').closest('details')).not.toHaveAttribute('open')
    await user.click(within(dialog).getByRole('button', { name: '取消准备，返回会议' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(started).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '录制会议' }))
    expect(screen.getByRole('textbox', { name: '会议标题（可选）' })).toHaveValue('设计审查')
    expect(screen.getByRole('radio', { name: '录音与屏幕' })).toBeChecked()
    await user.click(screen.getByRole('radio', { name: '仅录音' }))
    expect(screen.queryByText(/1080p/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '关闭准备录制' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(started).not.toHaveBeenCalled()
  } finally {
    window.removeEventListener(START_MEETING_EVENT, started)
  }
})

it.each(['', '设计审查'])('starts only on confirmation with the exact optional title %j and screen selection', async title => {
  mount()
  const user = userEvent.setup()
  const started = vi.fn()
  window.addEventListener(START_MEETING_EVENT, started)
  try {
    await user.click(screen.getByRole('button', { name: '录制会议' }))
    if (title) await user.type(screen.getByRole('textbox', { name: '会议标题（可选）' }), title)
    await user.click(screen.getByRole('radio', { name: '录音与屏幕' }))
    expect(started).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '开始录制' }))
    expect(started).toHaveBeenCalledTimes(1)
    expect((started.mock.calls[0][0] as CustomEvent).detail).toMatchObject({ title, meetingType: 'video', screen: true, systemAudio: false, mode: 'recording' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  } finally {
    window.removeEventListener(START_MEETING_EVENT, started)
  }
})


it('renders a default-done retained placeholder from its failed task rather than claiming completed minutes', async () => {
  state.notes = [{ ...note('Synthetic capture', false, 'meeting_video', 'failed-capture'), content: '原始媒体已保存，正在进行会后处理。' }]
  state.recordings = []
  state.api.mockImplementation(async (path: string) => path === '/api/task/failed-capture' ? { task_id: 'failed-capture', status: 'failed', failed_stage: 'transcribing', retryable: false } : { diarization: { available: true } })
  mount()
  await screen.findByRole('button', { name: heading('Synthetic capture', '需处理', 'failed-capture') })
  expect(screen.queryByText('· 纪要已完成')).toBeNull()
  expect(state.api).toHaveBeenCalledWith('/api/task/failed-capture', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  expect(state.api.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
