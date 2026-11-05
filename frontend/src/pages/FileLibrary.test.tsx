import { render, screen, waitFor, cleanup, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ api: vi.fn(), recordings: vi.fn(), owner: 'owner' }))
vi.mock('@/lib/api', () => ({ apiJson: mocks.api }))
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: mocks.recordings }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: Object.assign(() => mocks.owner, { getState: () => ({ user: { id: mocks.owner } }), subscribe: () => () => undefined }) }))
vi.mock('@/stores/teamStore', () => ({ useTeamStore: Object.assign((selector: (state: unknown) => unknown) => selector({ currentWorkspace: { scope: 'personal' }, teams: [] }), { getState: () => ({ currentWorkspace: { scope: 'personal' } }) }), getWorkspaceLabel: () => '个人空间' }))
vi.mock('@/components/MeetingRecorder/LocalRecordingPreview', () => ({ LocalRecordingPreview: () => null }))
import { FileLibrary } from './FileLibrary'
const file = { id: 'file-1', filename: 'test.md', purpose: 'note', category: 'file', size_bytes: 10, created_at: '2026-10-11T10:00:00Z', available: true, content_url: '/api/files/file-1/content', location: '当前电脑', media_type: 'text/markdown', can_delete: true, can_generate: true }
beforeEach(() => { mocks.owner = 'owner'; mocks.api.mockReset(); mocks.recordings.mockResolvedValue([]); sessionStorage.clear(); localStorage.clear() })
afterEach(cleanup)
function Destination() { const location = useLocation(); return <><output aria-label="目标地址">{location.pathname + location.search}</output><output aria-label="返回来源">{location.state?.returnTo}</output><Link to={location.state?.returnTo || '/files'}>返回文件库</Link></> }
function FileRoute() { const location = useLocation(); return <output aria-label="文件库地址">{location.pathname + location.search}</output> }
it('discovers associated summaries from the canonical meeting original', async () => {
  const canonical = '546bfcb5-4cf1-47f2-b4a7-34a1b3612970'
  const child = '4e8efb3a-98cc-4774-a5b0-d99794feec35'
  const operation = '6ef7260e-3815-4b07-a281-84bdf3e50929'
  mocks.api.mockImplementation((path: string) => Promise.resolve(path === '/api/files' ? { items: [{ ...file, id: `task:${canonical}`, task_id: canonical, filename: 'meeting.wav', purpose: 'meeting', can_delete: false }] } : path.endsWith('summary-children') ? { canonical_task_id: canonical, items: [{ task_id: child, operation_id: operation }] } : { task_id: child, status: 'failed', updated_at: '2026-11-04T06:00:00Z' }))
  mount('/files?purpose=meeting'); await userEvent.click(await screen.findByRole('button', { name: /meeting.wav/ }))
  const records = within(screen.getByRole('dialog')).getByLabelText('关联纪要生成记录')
  const summary = await within(records).findByText(/处理记录 · 1次/)
  expect(summary).toHaveTextContent('最近状态 · 处理失败')
  expect(summary.closest('details')).not.toHaveAttribute('open')
  await userEvent.click(summary)
  expect(within(records).getByText(/状态更新于.*处理失败/)).toBeInTheDocument()
  const taskDetails = within(records).getByText(`任务编号：${child}`).closest('details')
  expect(taskDetails).not.toHaveAttribute('open')
  expect(within(records).queryByRole('button', { name: '恢复保存' })).not.toBeInTheDocument()
  expect(mocks.api).toHaveBeenCalledWith(`/api/task/${canonical}/summary-children`)
  expect(mocks.api).toHaveBeenCalledWith(`/api/task/${child}`)
  expect(mocks.api.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
})
it.each([['meeting', '/meetings/files'], ['note', '/notes/files']] as const)('keeps %s conflicting source links in the missing-detail state', async (scope, path) => {
  mocks.api.mockResolvedValue({ items: [file, { ...file, id: 'meeting-file', filename: 'meeting.wav', purpose: 'meeting' }] })
  render(<MemoryRouter initialEntries={[path + '?purpose=' + (scope === 'note' ? 'meeting' : 'note') + '&file=' + (scope === 'note' ? 'meeting-file' : 'file-1')]}><FileLibrary scope={scope} /></MemoryRouter>)
  expect(await screen.findByText('未找到这份原文件')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: '原文件列表' })).not.toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.queryByRole('group', { name: '资料用途' })).not.toBeInTheDocument()
})
const mount = (path = '/files?purpose=note', state?: Record<string, unknown>) => render(<MemoryRouter initialEntries={[{ pathname: path.split('?')[0], search: path.includes('?') ? '?' + path.split('?')[1] : '', state }]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><FileRoute /><Routes><Route path="/files" element={<FileLibrary />} /><Route path="/note/:id" element={<Destination />} /><Route path="/workspace/:key" element={<Destination />} /><Route path="/generate" element={<Destination />} /><Route path="/notes" element={<Destination />} /><Route path="/meetings" element={<Destination />} /></Routes></MemoryRouter>)
it('keeps already loaded files when a refresh fails and recovers in place', async () => {
  mocks.api.mockResolvedValueOnce({ items: [file] }).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ items: [file] })
  mount()
  await screen.findByRole('button', { name: /test.md/ })
  await userEvent.click(screen.getByRole('button', { name: '重新读取文件库' }))
  await screen.findByText(/部分文件未读取成功/)
  expect(screen.getByRole('button', { name: /test.md/ })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '重试' }))
  await waitFor(() => expect(screen.queryByText(/部分文件未读取成功/)).not.toBeInTheDocument())
})
it('closes the file sheet before deletion confirmation and retains the file after failure', async () => {
  mocks.api.mockImplementation((path: string, init?: RequestInit) => init?.method === 'DELETE' ? Promise.reject(new Error('删除失败，请重试')) : Promise.resolve({ items: [file] }))
  mount()
  await userEvent.click(await screen.findByRole('button', { name: /test.md/ }))
  await userEvent.click(screen.getByRole('button', { name: '删除原始文件' }))
  expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '确认删除文件' }))
  await within(screen.getByRole('alertdialog')).findByText('删除失败，请重试')
  expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '取消' }))
  const restored = await screen.findByRole('dialog')
  expect(within(restored).getByRole('heading', { name: 'test.md' })).toBeInTheDocument()
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  expect(screen.getByLabelText('文件库地址')).toHaveTextContent('file=file-1')
  expect(within(restored).getByRole('button', { name: '删除原始文件' })).toHaveFocus()
})
it('cancels deletion back to the same original and keeps filters without sending DELETE', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, note_id: 'saved-note' }] })
  mount('/files?purpose=note&type=document&q=test&file=file-1')
  const sheet = await screen.findByRole('dialog')
  await userEvent.click(within(sheet).getByRole('button', { name: '删除原始文件' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByLabelText('文件库地址')).toHaveTextContent('type=document&q=test&file=file-1')
  await userEvent.click(screen.getByRole('button', { name: '取消' }))
  const restored = await screen.findByRole('dialog')
  expect(within(restored).getByRole('link', { name: '查看关联内容' })).toHaveAttribute('href', '/note/saved-note')
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  expect(mocks.api.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
})
it.each(['取消', '确认删除文件'])('does not restore or delete the old account original after the account changes (%s)', async action => {
  mocks.api.mockResolvedValue({ items: [file] })
  mount('/files?purpose=note&type=document&q=test&file=file-1')
  await screen.findByRole('dialog')
  await userEvent.click(screen.getByRole('button', { name: '删除原始文件' }))
  mocks.owner = 'other-owner'
  await userEvent.click(screen.getByRole('button', { name: action }))
  await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(mocks.api.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
})
it('keeps the same unavailable original after a refresh removes it during confirmation', async () => {
  let finishRefresh!: (value: { items: typeof file[] }) => void
  mocks.api.mockResolvedValueOnce({ items: [file] }).mockImplementationOnce(() => new Promise(resolve => { finishRefresh = resolve }))
  mount()
  await screen.findByRole('button', { name: /test.md/ })
  await userEvent.click(screen.getByRole('button', { name: '重新读取文件库' }))
  await userEvent.click(screen.getByRole('button', { name: /test.md/ }))
  await userEvent.click(screen.getByRole('button', { name: '删除原始文件' }))
  finishRefresh({ items: [] })
  await waitFor(() => expect(screen.getByRole('button', { name: '取消' })).toBeEnabled())
  await userEvent.click(screen.getByRole('button', { name: '取消' }))
  const restored = await screen.findByRole('dialog')
  expect(within(restored).getByRole('heading', { name: 'test.md' })).toBeInTheDocument()
  expect(within(restored).getByRole('button', { name: '原件不可用，暂不能导出' })).toBeDisabled()
  expect(within(restored).getByRole('button', { name: '删除原始文件' })).toBeDisabled()
  expect(mocks.api.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
})
it('keeps file classification and search in the page, with a way to clear a no-result filter', async () => {
  mocks.api.mockResolvedValue({ items: [file, { ...file, id: 'audio-1', filename: '录音.wav', category: 'recording', media_type: 'audio/wav' }] })
  mount('/files?purpose=note&type=audio&q=不存在')
  await screen.findByText('没有匹配的文件')
  expect(screen.getByRole('group', { name: '文件分类' })).toBeInTheDocument(); expect(screen.getByRole('button', { name: '音频', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: '清除筛选' }))
  expect(screen.getByLabelText('搜索文件名称')).toHaveValue(''); expect(screen.getByRole('button', { name: '全部', exact: true })).toHaveAttribute('aria-pressed', 'true')
  expect(await screen.findByRole('button', { name: /test.md/ })).toBeInTheDocument(); expect(screen.getByRole('button', { name: /录音.wav/ })).toBeInTheDocument()
})
it('opens an actual selected original by URL and returns from associated content to the same filter/search/selection', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, note_id: 'saved-note' }] })
  mount('/files?purpose=note&type=document&q=test&file=file-1')
  const sheet = await screen.findByRole('dialog'); expect(within(sheet).getByRole('heading', { name: '文件信息' })).toBeInTheDocument(); expect(within(sheet).getByRole('heading', { name: '关联内容' })).toBeInTheDocument(); expect(within(sheet).getByRole('heading', { name: '原件管理' })).toBeInTheDocument()
  expect(within(sheet).queryByRole('button', { name: '用此原件整理笔记' })).not.toBeInTheDocument()
  await userEvent.click(within(sheet).getByRole('link', { name: '查看关联内容' }))
  expect(screen.getByLabelText('目标地址')).toHaveTextContent('/note/saved-note'); expect(screen.getByLabelText('返回来源')).toHaveTextContent('/files?purpose=note&type=document&q=test&file=file-1')
  await userEvent.click(screen.getByRole('link', { name: '返回文件库' })); await screen.findByRole('dialog'); await userEvent.click(screen.getByRole('button', { name: '关闭', exact: true })); expect(screen.getByLabelText('搜索文件名称')).toHaveValue('test'); expect(screen.getByRole('button', { name: '文档', exact: true })).toHaveAttribute('aria-pressed', 'true')
})
it('saves only the original from the top action without invoking note generation', async () => {
  mocks.api.mockImplementation((_path: string, init?: RequestInit) => Promise.resolve(init?.method === 'POST' ? file : { items: [file] }))
  mount(); await screen.findByRole('button', { name: /test.md/ })
  expect(screen.getByRole('button', { name: '导入资料' })).toBeEnabled()
  expect(screen.getByLabelText('选择保存到文件库的原文件')).toHaveAttribute('aria-describedby', 'file-import-help')
  await userEvent.click(screen.getByRole('button', { name: '导入资料' })); await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /笔记资料/ }))
  await userEvent.upload(screen.getByLabelText('选择保存到文件库的原文件'), new File(['source'], 'source.pdf', { type: 'application/pdf' }))
  await screen.findByText('笔记资料原文件已保存，尚未生成正文。')
  const writes = mocks.api.mock.calls.filter(([, init]) => init?.method === 'POST'); expect(writes).toHaveLength(1); expect(writes[0][0]).toBe('/api/files'); expect(writes[0][1].body).toBeInstanceOf(FormData); expect(writes[0][1].body.get('purpose')).toBe('note')
})
it('uses real availability and does not offer a download or pretend document playback', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, available: false, can_delete: false }] })
  mount(); await userEvent.click(await screen.findByRole('button', { name: /test.md/ })); const sheet = screen.getByRole('dialog')
  expect(within(sheet).queryByRole('link', { name: '导出原文件' })).not.toBeInTheDocument(); expect(within(sheet).getByRole('button', { name: '原件不可用，暂不能导出' })).toBeDisabled(); expect(within(sheet).getByRole('button', { name: '用此原件整理笔记' })).toBeDisabled(); expect(within(sheet).getByRole('button', { name: '删除原始文件' })).toBeDisabled(); expect(within(sheet).getByText(/此原件当前不允许删除/)).toBeInTheDocument(); expect(sheet.querySelector('audio,video')).toBeNull()
})
it('continues a known file task without POST or selecting the file again', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, filename: 'source.pdf', task_id: 'original-task' }] })
  mount('/files?purpose=note&type=document&q=source'); await userEvent.click(await screen.findByRole('button', { name: /source.pdf/ })); await userEvent.click(screen.getByRole('button', { name: /查看(纪要|笔记)生成进度/ }))
  await screen.findByLabelText('目标地址'); expect(screen.getByLabelText('目标地址')).toHaveTextContent('/generate?mode=file')
  expect(localStorage.getItem('vinote:import-receipt:owner:note')).toBeNull(); expect(screen.getByLabelText('目标地址')).toHaveTextContent('task=original-task'); expect(screen.getByLabelText('返回来源')).toHaveTextContent('type=document&q=source&file=file-1'); expect(mocks.api.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
})
it('restores an existing uncertain intake before a new file, without overwriting its request', async () => {
  const original = { operationId: 'unknown-original-operation', workspace: { scope: 'personal' }, submissionState: 'unknown' }
  localStorage.setItem('vinote:import-receipt:owner:note', JSON.stringify(original)); mocks.api.mockResolvedValue({ items: [file] })
  mount(); await userEvent.click(await screen.findByRole('button', { name: /test.md/ })); await userEvent.click(screen.getByRole('button', { name: '用此原件整理笔记' })); await screen.findByLabelText('目标地址')
  expect(JSON.parse(localStorage.getItem('vinote:import-receipt:owner:note')!)).toEqual(original); expect(mocks.api.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
})
it('retains corrupt intake recovery instead of overwriting it for a new file', async () => {
  localStorage.setItem('vinote:import-receipt:owner:note', '{bad'); mocks.api.mockResolvedValue({ items: [file] }); mount(); await userEvent.click(await screen.findByRole('button', { name: /test.md/ })); await userEvent.click(screen.getByRole('button', { name: '用此原件整理笔记' })); await within(screen.getByRole('dialog')).findByText(/已有处理记录无法读取/)
  expect(localStorage.getItem('vinote:import-receipt:owner:note')).toBe('{bad'); expect(mocks.api.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
})
it('keeps a same-task receipt and its original workspace intact', async () => {
  const original = { id: 'original-task', workspace: { scope: 'team', teamId: 'original-team' }, sourceTitle: '原请求名称' }
  localStorage.setItem('vinote:import-receipt:owner:note', JSON.stringify(original)); mocks.api.mockResolvedValue({ items: [{ ...file, task_id: 'original-task' }] }); mount(); await userEvent.click(await screen.findByRole('button', { name: /test.md/ })); await userEvent.click(screen.getByRole('button', { name: /查看(纪要|笔记)生成进度/ })); await screen.findByLabelText('目标地址')
  expect(JSON.parse(localStorage.getItem('vinote:import-receipt:owner:note')!)).toEqual(original)
})
it('preserves a legitimate contextual parent while changing file filters and searching', async () => {
  mocks.api.mockResolvedValue({ items: [file] }); mount('/files?purpose=note', { returnTo: '/notes?project=research&archived=1' }); await screen.findByRole('button', { name: /test.md/ })
  await userEvent.click(screen.getByRole('button', { name: '文档', exact: true })); await userEvent.type(screen.getByLabelText('搜索文件名称'), 'test')
  expect(screen.getByRole('link', { name: '返回笔记' })).toHaveAttribute('href', '/notes?project=research&archived=1')
})
it('organizes the actual selected original and returns with filters without uploading it again', async () => {
  mocks.api.mockImplementation((_path: string, init?: RequestInit) => Promise.resolve(init?.method === 'POST' ? { task_id: 'new-task' } : { items: [{ ...file, filename: 'source.pdf' }] }))
  mount('/files?purpose=note&type=document&q=source'); await userEvent.click(await screen.findByRole('button', { name: /source.pdf/ })); await userEvent.click(screen.getByRole('button', { name: '用此原件整理笔记' })); await screen.findByLabelText('目标地址')
  const writes = mocks.api.mock.calls.filter(([, init]) => init?.method === 'POST'); expect(writes).toHaveLength(1); expect(writes[0][0]).toBe('/api/files/file-1/generate'); expect(JSON.parse(writes[0][1].body)).toEqual({ meeting: false }); expect(screen.getByLabelText('返回来源')).toHaveTextContent('type=document&q=source&file=file-1'); expect(JSON.parse(localStorage.getItem('vinote:import-receipt:owner:note')!)).toMatchObject({ id: 'new-task', localFileId: 'file-1', sourceType: 'file' })
})
it('retains the original parent through an associated-content round trip and rejects external parents', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, note_id: 'saved-note' }] }); mount('/files?purpose=note&type=document&q=test', { returnTo: '/notes?project=research&archived=1' }); await userEvent.click(await screen.findByRole('button', { name: /test.md/ })); await userEvent.click(screen.getByRole('link', { name: '查看关联内容' })); expect(screen.getByLabelText('返回来源')).toHaveTextContent('returnTo=%2Fnotes%3Fproject%3Dresearch%26archived%3D1'); await userEvent.click(screen.getByRole('link', { name: '返回文件库' })); await screen.findByRole('dialog'); await userEvent.click(screen.getByRole('button', { name: '关闭', exact: true })); expect(screen.getByRole('link', { name: '返回笔记' })).toHaveAttribute('href', '/notes?project=research&archived=1')
  cleanup(); mount('/files?purpose=note&returnTo=https%3A%2F%2Fexternal.test'); await screen.findByRole('button', { name: /test.md/ }); expect(screen.queryByRole('link', { name: /^返回/ })).not.toBeInTheDocument()
})
it('filters source originals by real note links only, ignoring matching titles and stale library filters', async () => {
  sessionStorage.setItem('vinote:view:owner:files-query', JSON.stringify('missing'));
  mocks.api.mockResolvedValue({ items: [{ ...file, note_id: 'local-note' }, { ...file, id: 'unrelated', note_id: 'other-note' }] });
  mocks.recordings.mockResolvedValue([{ id: 'real-recording', noteId: 'local-note', options: { title: '真实关联录音' }, startedAt: file.created_at, elapsedSeconds: 30 }]);
  const parent = '/workspace/shared-note?version=historical&returnTo=%2Fnotes%3Farchived%3D1';
  mount('/files?note=local-note&type=video&q=missing&returnTo=' + encodeURIComponent(parent));
  await screen.findByRole('button', { name: /test.md/ });
  expect(screen.getAllByRole('button', { name: /test.md/ })).toHaveLength(1);
  expect(screen.getByRole('button', { name: /真实关联录音/ })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: '来源原文件' })).toBeInTheDocument();
  expect(screen.getByText('本设备关联 2 个原文件')).toBeInTheDocument();
  expect(screen.queryByRole('group', { name: '文件分类' })).not.toBeInTheDocument();
  expect(screen.queryByLabelText('搜索文件名称')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '导入资料' })).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: '返回内容详情' })).toHaveAttribute('href', parent);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(mocks.api.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});
it('uses the actual selected file ID and closes back to the source list without reopening or dropping its context', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, id: 'actual-file-id', note_id: 'local-note' }] });
  const parent = '/workspace/shared-note?version=historical&returnTo=%2Fnotes';
  mount('/files?note=local-note&returnTo=' + encodeURIComponent(parent));
  await userEvent.click(await screen.findByRole('button', { name: /test.md/ }));
  const sheet = screen.getByRole('dialog');
  expect(screen.getByLabelText('文件库地址')).toHaveTextContent('file=actual-file-id');
  expect(within(sheet).getByRole('link', { name: '查看关联内容' })).toHaveAttribute('href', parent);
  await userEvent.click(within(sheet).getByRole('button', { name: '关闭', exact: true }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByLabelText('文件库地址')).toHaveTextContent('note=local-note');
  expect(screen.getByLabelText('文件库地址')).not.toHaveTextContent('file=');
  expect(screen.getByRole('link', { name: '返回内容详情' })).toHaveAttribute('href', parent);
  expect(mocks.api.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});
it('reports zero verified source matches without guessing an original or falling back to the old editor', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, title: '同名PDF', note_id: 'different-note' }] });
  mount('/files?note=local-note&returnTo=%2Fworkspace%2Fshared-note');
  await screen.findByText('当前设备未找到可核验的原文件关联');
  expect(screen.getByText(/这不代表原文件已删除/)).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /同名PDF/ })).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: '返回内容详情' })).toHaveAttribute('href', '/workspace/shared-note');
  expect(mocks.api.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});
it('rejects an explicit file selection that is outside the verified source association', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, note_id: 'different-note' }] });
  mount('/files?note=local-note&file=file-1');
  await screen.findByText('当前设备未找到可核验的原文件关联');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(mocks.api.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});
it('opens only the verified recording from a recovery link and retains its parent', async () => {
  mocks.api.mockResolvedValue({ items: [] });
  mocks.recordings.mockResolvedValue([{ id: 'real-record-id', options: { title: '失败录音' }, startedAt: file.created_at, elapsedSeconds: 42 }]);
  sessionStorage.setItem('vinote:view:owner:files-query', JSON.stringify('unrelated'));
  const parent = '/tasks?tab=generation&returnTo=%2Fmeetings%3Fq%3Dold';
  mount('/files?purpose=note&type=all&q=&file=recording%3Areal-record-id&returnTo=' + encodeURIComponent(parent));
  const sheet = await screen.findByRole('dialog');
  expect(within(sheet).getByRole('heading', { name: '失败录音' })).toBeInTheDocument();
  await userEvent.click(within(sheet).getByRole('button', { name: '关闭', exact: true }));
  expect(screen.getByRole('link', { name: '返回任务与恢复' })).toHaveAttribute('href', parent);
  expect(screen.getByLabelText('搜索文件名称')).toHaveValue('');
  expect(mocks.api.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});

it('defaults to meeting materials and separates same-format note media rather than classifying by extension', async () => {
  const meeting = { ...file, id: 'meeting-video', filename: 'meeting.mp4', category: 'video', media_type: 'video/mp4', purpose: 'meeting' };
  const note = { ...meeting, id: 'note-video', filename: 'note.mp4', purpose: 'note' };
  mocks.api.mockResolvedValue({ items: [meeting, note, file] });
  mocks.recordings.mockResolvedValue([{ id: 'captured', options: { title: '会议录制' }, startedAt: file.created_at, elapsedSeconds: 42 }]);
  mount('/files'); await screen.findByRole('button', { name: /meeting.mp4/ });
  expect(screen.getByRole('button', { name: /会议录制/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /note.mp4|test.md/ })).not.toBeInTheDocument();
  const purposes = screen.getByRole('group', { name: '资料用途' });
  expect(within(purposes).getByRole('button', { name: /会议资料/ })).toHaveAttribute('aria-pressed', 'true');
  await userEvent.click(within(purposes).getByRole('button', { name: /笔记资料/ }));
  expect(screen.getByRole('button', { name: /note.mp4/ })).toBeInTheDocument(); expect(screen.getByRole('button', { name: /test.md/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /meeting.mp4|会议录制/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '视频', exact: true }));
  expect(screen.getByRole('button', { name: /note.mp4/ })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: /test.md/ })).not.toBeInTheDocument();
  await userEvent.type(screen.getByLabelText('搜索文件名称'), 'missing'); await userEvent.click(screen.getByRole('button', { name: '清除筛选' }));
  expect(within(purposes).getByRole('button', { name: /笔记资料/ })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByLabelText('文件库地址')).toHaveTextContent('purpose=note');
});
it('honors a previously selected purpose and authoritative purpose even for a PDF', async () => {
  sessionStorage.setItem('vinote:view:owner:files-purpose', JSON.stringify('note'));
  mocks.api.mockResolvedValue({ items: [file, { ...file, id: 'meeting-pdf', filename: 'meeting.pdf', purpose: 'meeting' }] });
  mount('/files'); await screen.findByRole('button', { name: /test.md/ });
  expect(screen.queryByRole('button', { name: /meeting.pdf/ })).not.toBeInTheDocument();
  await userEvent.click(within(screen.getByRole('group', { name: '资料用途' })).getByRole('button', { name: /会议资料/ }));
  expect(screen.getByRole('button', { name: /meeting.pdf/ })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: /test.md/ })).not.toBeInTheDocument();
});
it('routes meeting imports into the unified fresh draft without uploading to the file library', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, purpose: 'meeting', filename: 'meeting.wav' }] });
  mount('/files'); await screen.findByRole('button', { name: /meeting.wav/ });
  await userEvent.click(screen.getByRole('button', { name: '导入资料' }));
  await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /会议资料/ }));
  const route = new URL(screen.getByLabelText('目标地址').textContent!, 'https://test.invalid');
  expect(route.pathname).toBe('/generate'); expect(route.searchParams.get('meeting')).toBe('1');
  expect(route.searchParams.get('intent')).toBe('import'); expect(route.searchParams.get('draft')).toMatch(/^[a-f0-9-]{36}$/);
  expect(mocks.api.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
});
it('starts meeting generation with a meeting receipt and preserves the source selection and parent', async () => {
  const meeting = { ...file, filename: 'meeting.wav', category: 'recording', media_type: 'audio/wav', purpose: 'meeting' };
  mocks.api.mockImplementation((_path, init) => Promise.resolve(init?.method === 'POST' ? { task_id: 'meeting-task' } : { items: [meeting] }));
  const unrelated = { operationId: 'unknown-note' }; localStorage.setItem('vinote:import-receipt:owner:note', JSON.stringify(unrelated));
  mount('/files?purpose=meeting&type=audio&q=meeting', { returnTo: '/meetings?q=original' });
  await userEvent.click(await screen.findByRole('button', { name: /meeting.wav/ })); await userEvent.click(screen.getByRole('button', { name: '用此原件生成纪要' }));
  await screen.findByLabelText('目标地址'); expect(screen.getByLabelText('目标地址')).toHaveTextContent('/generate?mode=file&meeting=1');
  const writes = mocks.api.mock.calls.filter(([, init]) => init?.method === 'POST'); expect(writes).toHaveLength(1);
  expect(JSON.parse(writes[0][1].body)).toEqual({ meeting: true });
  expect(JSON.parse(localStorage.getItem('vinote:import-receipt:owner:meeting')!)).toMatchObject({ id: 'meeting-task', localFileId: 'file-1', meeting: true, sourceType: 'meeting_recording' });
  expect(JSON.parse(localStorage.getItem('vinote:import-receipt:owner:note')!)).toEqual(unrelated);
  expect(screen.getByLabelText('返回来源')).toHaveTextContent('purpose=meeting&type=audio&q=meeting&file=file-1');
  expect(screen.getByLabelText('返回来源')).toHaveTextContent('returnTo=%2Fmeetings%3Fq%3Doriginal');
});
it('reclassifies the original without losing its Sheet, format, selection or generating another body', async () => {
  mocks.api.mockImplementation((_path, init) => Promise.resolve(init?.method === 'PATCH' ? { ...file, purpose: 'meeting' } : { items: [file] }));
  mount('/files?purpose=note&type=document&q=test&file=file-1'); const sheet = await screen.findByRole('dialog');
  await userEvent.selectOptions(within(sheet).getByLabelText('资料用途'), 'meeting');
  await waitFor(() => expect(within(screen.getByRole('dialog')).getByLabelText('资料用途')).toHaveValue('meeting'));
  await waitFor(() => expect(screen.getByLabelText('文件库地址')).toHaveTextContent('purpose=meeting&type=document&q=test&file=file-1'));
  const writes = mocks.api.mock.calls.filter(([, init]) => init?.method); expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe('/api/files/file-1'); expect(writes[0][1].method).toBe('PATCH'); expect(JSON.parse(writes[0][1].body)).toEqual({ purpose: 'meeting' });
  expect(within(screen.getByRole('dialog')).queryByRole('button', { name: '删除原始文件' })).not.toBeInTheDocument();
  expect(within(screen.getByRole('dialog')).getByRole('link', { name: '前往会议档案 · 删除整场会议' })).toBeInTheDocument();
  expect(within(await screen.findByRole('dialog')).getByLabelText('资料用途')).toHaveValue('meeting');
});
it('preserves the original purpose and file detail if reclassification fails', async () => {
  mocks.api.mockImplementation((_path, init) => init?.method === 'PATCH' ? Promise.reject(new Error('用途保存失败')) : Promise.resolve({ items: [file] }));
  mount('/files?purpose=note&file=file-1'); const sheet = await screen.findByRole('dialog');
  await userEvent.selectOptions(within(sheet).getByLabelText('资料用途'), 'meeting');
  await within(sheet).findByText('用途保存失败'); expect(within(sheet).getByLabelText('资料用途')).toHaveValue('note');
  expect(screen.getByLabelText('文件库地址')).toHaveTextContent('purpose=note&file=file-1');
});
it('does not guess ambiguous legacy audio as a meeting and preserves export until its purpose is confirmed', async () => {
  const legacy = { ...file, purpose: undefined, filename: 'unknown.wav', category: 'recording', media_type: 'audio/wav' };
  mocks.api.mockResolvedValue({ items: [legacy] }); mount('/files');
  const purposes = await screen.findByRole('group', { name: '资料用途' });
  await waitFor(() => expect(within(purposes).getByRole('button', { name: /待确认用途/ })).toBeInTheDocument());
  expect(screen.queryByRole('button', { name: /unknown.wav/ })).not.toBeInTheDocument();
  await userEvent.click(within(purposes).getByRole('button', { name: /待确认用途/ }));
  await userEvent.click(screen.getByRole('button', { name: /unknown.wav/ })); const sheet = screen.getByRole('dialog');
  expect(within(sheet).getByRole('button', { name: '导出原文件' })).toBeInTheDocument();
  expect(within(sheet).getByRole('button', { name: '用此原件整理笔记' })).toBeDisabled();
});

it('groups screen captures and imported videos under one video filter with distinct source badges', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, id: 'imported-video', filename: 'imported.mp4', purpose: 'meeting', category: 'video', media_type: 'video/mp4' }] });
  mocks.recordings.mockResolvedValue([{ id: 'screen-original', options: { title: '屏幕原件', screen: true }, startedAt: file.created_at, elapsedSeconds: 42 }]);
  mount('/files?purpose=meeting&type=screen');
  await screen.findByRole('button', { name: /屏幕原件/ });
  const formats = screen.getByRole('group', { name: '文件分类' });
  expect(within(formats).getAllByRole('button').map(button => button.textContent)).toEqual(['全部', '音频', '视频', '文档']);
  expect(within(formats).getByRole('button', { name: '视频' })).toHaveAttribute('aria-pressed', 'true');
  expect(within(formats).queryByRole('button', { name: '录屏' })).not.toBeInTheDocument();
  expect(within(screen.getByRole('button', { name: /屏幕原件/ })).getByText('录屏')).toBeInTheDocument();
  expect(within(screen.getByRole('button', { name: /imported.mp4/ })).getByText('导入视频')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /imported.mp4/ }));
  expect(screen.getByLabelText('文件库地址')).toHaveTextContent('purpose=meeting&type=video');
});


it('retained failed meeting source queries the same task without another upload', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, id: 'task:original', filename: 'discussion.webm', purpose: 'meeting', task_id: 'failed-video', processing_status: 'failed', error_code: 'unknown_result', can_generate: false, can_delete: false, media_type: 'video/webm', category: 'video' }] });
  mount('/files?purpose=meeting&file=task%3Aoriginal');
  expect(await screen.findByText('处理结果尚未确认。原文件已保留，请查询原结果，不重复提交。')).toBeInTheDocument();
  expect(within(screen.getByRole('dialog')).queryByRole('combobox', { name: '资料用途' })).not.toBeInTheDocument();
  expect(within(screen.getByRole('dialog')).getByLabelText('资料用途')).toHaveTextContent('会议资料');
  await userEvent.click(screen.getByRole('button', { name: /查看(纪要|笔记)生成进度/ }));
  await screen.findByLabelText('目标地址');
  expect(localStorage.getItem('vinote:import-receipt:owner:meeting')).toBeNull(); expect(screen.getByLabelText('目标地址')).toHaveTextContent('task=failed-video');
  expect(mocks.api.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
});

it('opens exact failed task read-only while preserving a different global receipt', async () => {
  const originalReceipt = { id: 'newer-task', submissionState: 'accepted', workspace: { scope: 'personal' }, meeting: true };
  localStorage.setItem('vinote:import-receipt:owner:meeting', JSON.stringify(originalReceipt));
  mocks.api.mockResolvedValue({ items: [{ ...file, id: 'task:old', filename: 'old.webm', purpose: 'meeting', task_id: 'old-task', can_generate: false, can_delete: false }] });
  mount('/files?purpose=meeting&file=task%3Aold');
  await userEvent.click(await screen.findByRole('button', { name: /查看(纪要|笔记)生成进度/ }));
  await screen.findByLabelText('目标地址'); expect(screen.getByLabelText('目标地址')).toHaveTextContent('task=old-task'); expect(screen.getByLabelText('返回来源')).toHaveTextContent('purpose=meeting&file=task%3Aold');
  expect(JSON.parse(localStorage.getItem('vinote:import-receipt:owner:meeting')!)).toEqual(originalReceipt);
  expect(screen.getByLabelText('目标地址')).toHaveTextContent('meeting=1');
  expect(mocks.api.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
});


it.each(['processing', 'failed', 'success'])('retained task original %s does not promise deletion after processing', async processing_status => {
  mocks.api.mockResolvedValue({ items: [{ ...file, id: 'task:retained', filename: 'retained.webm', purpose: 'meeting', task_id: 'selected-task', processing_status, can_delete: false, can_generate: false }] });
  mount('/files?purpose=meeting&file=task%3Aretained&q=retained');
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByRole('link', { name: '前往会议档案 · 删除整场会议' })).toHaveAttribute('href', expect.stringContaining('locate_task=selected-task'));
  expect(within(dialog).queryByRole('button', { name: '删除原始文件' })).not.toBeInTheDocument();
  expect(within(dialog).queryByText(/请先完成或核验/)).not.toBeInTheDocument();
  expect(within(dialog).getByRole('button', { name: '导出原文件' })).toBeInTheDocument();
  expect(mocks.api.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true);
});

it('protected note source explains capability without guessing a processing reason', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, id: 'note:protected', can_delete: false, note_id: 'saved-note' }] });
  mount('/files?purpose=note&file=note%3Aprotected');
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByText('此原件当前不允许删除；已有正文与版本继续保留。')).toBeInTheDocument();
  expect(within(dialog).getByRole('link', { name: '查看关联内容' })).toBeInTheDocument();
});

it('FileLibrary body scroll is separate from close control and keeps list query', async () => {
  mocks.api.mockResolvedValue({ items: [file] });
  mount('/files?purpose=note&file=file-1&q=test&type=file');
  const dialog = await screen.findByRole('dialog');
  const body = within(dialog).getByTestId('file-details-body');
  expect(dialog).toHaveClass('overflow-hidden', 'flex-col');
  expect(body).toHaveClass('overflow-y-auto', 'min-h-0', 'flex-1');
  expect(body).not.toContainElement(within(dialog).getByRole('button', { name: '关闭' }));
  await userEvent.click(within(dialog).getByRole('button', { name: '关闭' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByLabelText('文件库地址')).toHaveTextContent('purpose=note');
  expect(screen.getByLabelText('文件库地址')).toHaveTextContent('q=test');
  expect(mocks.api.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false);
});

it('opens a scoped original as a full detail page without library controls or a side sheet', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, purpose: 'meeting', filename: '整场会议.wav' }] })
  render(<MemoryRouter initialEntries={['/meetings/files?file=file-1']}><FileLibrary scope="meeting" /></MemoryRouter>)
  expect(await screen.findByRole('heading', { name: '未命名会议', level: 1 })).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: '文件筛选' })).not.toBeInTheDocument()
  expect(screen.queryByRole('list', { name: '原文件列表' })).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: '返回会议' })).toHaveAttribute('href', '/meetings')
  expect(screen.getByRole('heading', { name: '原件管理' })).toBeInTheDocument()
})

it.each(['meeting', 'note'] as const)('keeps %s source detail isolated through loading, failure and retry', async scope => {
  let reject!: (reason: Error) => void
  let attempt = 0
  mocks.api.mockImplementation((path: string) => path === '/api/files' && attempt++ === 0 ? new Promise((_, fail) => { reject = fail }) : Promise.resolve({ items: path === '/api/files' ? [{ ...file, purpose: scope }] : [] }))
  render(<MemoryRouter initialEntries={[`/${scope === 'meeting' ? 'meetings' : 'notes'}/files?file=file-1`]}><FileLibrary scope={scope} /></MemoryRouter>)
  expect(screen.getByText('正在读取原文件…')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: '原文件列表' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '导入资料' })).not.toBeInTheDocument()
  reject(new Error('offline'))
  await screen.findByText('原文件暂未读取成功')
  expect(screen.queryByRole('region', { name: '文件筛选' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '重试' }))
  await screen.findByRole('heading', { name: scope === 'meeting' ? '未命名会议' : 'test.md', level: 1 })
  expect(screen.queryByRole('list', { name: '原文件列表' })).not.toBeInTheDocument()
})


it('meeting original management has no second upload entry and keeps originals reachable', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, purpose: 'meeting', filename: 'audio.wav', title: '项目讨论' }] });
  render(<MemoryRouter initialEntries={['/meetings/files']}><FileLibrary scope="meeting" /></MemoryRouter>);
  expect(await screen.findByRole('button', { name: /项目讨论/ })).toBeVisible();
  expect(screen.queryByRole('button', { name: '导入资料' })).toBeNull();
  expect(screen.queryByLabelText('选择保存到文件库的原文件')).toBeNull();
});
it('meeting files prefer the human meeting title and retain a copyable source filename', async () => {
  mocks.api.mockImplementation(async (path: string) => path.endsWith('/display') ? { items: [{ source_key: 'file:file-1', title: '采购方案讨论', meeting_date: null }] } : { items: [{ ...file, purpose: 'meeting', filename: 'device_001.wav', title: '旧标题', category: 'recording', media_type: 'audio/wav' }] });
  mount('/files?purpose=meeting');
  await userEvent.click(await screen.findByRole('button', { name: /采购方案讨论/ }));
  const detail = screen.getByRole('dialog');
  expect(within(detail).getByRole('heading', { name: '采购方案讨论' })).toBeVisible();
  expect(within(detail).getByText('device_001.wav')).toBeVisible();
  expect(within(detail).getByRole('button', { name: '复制原始文件名' })).toBeVisible();
});

it('hides unused format filters and search in a truly empty file library', async () => {
  mocks.api.mockResolvedValue({ items: [] }); mount();
  await screen.findByText('暂无笔记资料');
  expect(screen.queryByRole('region', { name: '文件筛选' })).toBeNull();
});

it.each([{ task_id: 'meeting-task', note_id: 'meeting-note' }, {}])('meeting originals route to whole-meeting deletion even when can_delete is true: %j', async identities => {
  mocks.api.mockResolvedValue({ items: [{ ...file, purpose: 'meeting', ...identities }] })
  mount('/files?purpose=meeting&file=file-1')
  const dialog = await screen.findByRole('dialog')
  const link = within(dialog).getByRole('link', { name: '前往会议档案 · 删除整场会议' })
  expect(link.getAttribute('href')).toContain('/meetings?')
  expect(link.getAttribute('href')).toContain('returnTo=')
  if ('task_id' in identities) expect(link.getAttribute('href')).toContain('locate_task=meeting-task')
  else expect(within(dialog).getByText(/尚未关联会议档案/)).toBeInTheDocument()
  expect(within(dialog).queryByRole('button', { name: '删除原始文件' })).not.toBeInTheDocument()
  expect(mocks.api.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
})

it('does not restore original-only deletion after relabeling an evidenced meeting as a note', async () => {
  mocks.api.mockResolvedValue({ items: [{ ...file, source_type: 'meeting_recording', task_id: 'meeting-task' }] })
  mount('/files?purpose=note&file=file-1')
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).queryByRole('button', { name: '删除原始文件' })).not.toBeInTheDocument()
  expect(within(dialog).getByRole('link', { name: '前往会议档案 · 删除整场会议' })).toHaveAttribute('href', expect.stringContaining('locate_task=meeting-task'))
})
