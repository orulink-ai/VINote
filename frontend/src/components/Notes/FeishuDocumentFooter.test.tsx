import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { FeishuDocumentFooter } from './FeishuDocumentFooter';
import { deliveryStatus, deliveryById, readAutomaticDelivery, checkAutomaticDelivery, openExternal, type Delivery } from '@/lib/feishu';
import { useAuthStore } from '@/stores/authStore';
vi.mock('@/lib/feishu', () => ({ deliveryStatus: vi.fn(), deliveryById: vi.fn(), readAutomaticDelivery: vi.fn(), checkAutomaticDelivery: vi.fn(), openExternal: vi.fn() }));
beforeEach(() => { useAuthStore.setState({ user: { id: 'footer-owner', email: 'test@example.invalid' } }); vi.mocked(readAutomaticDelivery).mockResolvedValue(null); vi.mocked(deliveryStatus).mockResolvedValue(null) });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); });
it.each([
  [{ protocol: 'feishu-markdown-selective-v2', status: 'written', native_write_confirmed: true, native_required: ['table'] }, 'completed', '原生表格已确认写入。'],
  [{ protocol: 'feishu-markdown-selective-v2', status: 'pending', native_required: ['table'] }, 'failed', '原生表格写入结果尚未确认。'],
  [undefined, 'completed', '正文格式尚未核验。'],
] as const)('renders the original GET receipt formatting without dispatching writes', async (formatting, status, message) => {
  vi.mocked(deliveryStatus).mockResolvedValue({ id: 'original', status, document_url: 'https://company.feishu.cn/docx/original', error: '', recipients: {}, formatting: formatting ? { ...formatting, native_required: [...formatting.native_required] } : undefined });
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>);
  expect(await screen.findByRole('status')).toHaveTextContent(message);
  expect(deliveryStatus).toHaveBeenCalledExactlyOnceWith('saved-note');
});
it('an absent automatic record stays quiet and preserves ordinary delivery reads', async () => {
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>);
  await screen.findByText('飞书 · 尚未交付');
  expect(screen.queryByRole('alert')).toBeNull(); expect(checkAutomaticDelivery).not.toHaveBeenCalled();
});
it('shows attendee waiting as a preparation state without querying or retrying a write', async () => {
  vi.mocked(readAutomaticDelivery).mockResolvedValue({ status: 'waiting_participants', error: '' });
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>);
  expect(await screen.findByText(/等待确认本会议参会人/)).toBeVisible();
  expect(screen.queryByText(/自动交付失败/)).toBeNull();
  expect(checkAutomaticDelivery).not.toHaveBeenCalled();
  expect(deliveryById).not.toHaveBeenCalled();
});
it.each(['queued', 'failed'] as const)('shows %s without retrying or altering the original note', async status => {
  vi.mocked(readAutomaticDelivery).mockResolvedValue({ status, error: status === 'failed' ? '权限不足' : '' });
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>);
  await screen.findByText(status === 'queued' ? /等待自动交付/ : /自动交付失败/);
  expect(checkAutomaticDelivery).not.toHaveBeenCalled(); expect(deliveryById).not.toHaveBeenCalled();
});
it('unknown only checks the original operation and reads the exact accepted job', async () => {
  vi.mocked(readAutomaticDelivery).mockResolvedValue({ status: 'unknown', can_check: true });
  vi.mocked(checkAutomaticDelivery).mockResolvedValue({ status: 'accepted', job_id: 'exact-job' });
  vi.mocked(deliveryById).mockResolvedValue({ id: 'exact-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/original', error: '', recipients: {} });
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: '核验交付结果' }));
  await screen.findByRole('button', { name: '查看文档 ↗' });
  expect(checkAutomaticDelivery).toHaveBeenCalledExactlyOnceWith('saved-note'); expect(deliveryById).toHaveBeenCalledExactlyOnceWith('exact-job');
});
it('explicit exact-job check invalidates a late generic GET for the same note', async () => {
  let finish!: (value: Delivery) => void;
  vi.mocked(deliveryStatus).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
  vi.mocked(readAutomaticDelivery).mockResolvedValue({ status: 'unknown', can_check: true });
  vi.mocked(checkAutomaticDelivery).mockResolvedValue({ status: 'accepted', job_id: 'exact-job' });
  vi.mocked(deliveryById).mockResolvedValue({ id: 'exact-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/exact', error: '', recipients: {} });
  vi.mocked(openExternal).mockResolvedValue(undefined);
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: '核验交付结果' })); await screen.findByRole('button', { name: '查看文档 ↗' });
  expect(screen.getByText('飞书文档 · 已交付')).toBeVisible();
  await act(async () => finish({ id: 'old-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/old', error: '', recipients: {} }));
  fireEvent.click(screen.getByRole('button', { name: '查看文档 ↗' })); expect(openExternal).toHaveBeenLastCalledWith('https://company.feishu.cn/docx/exact');
});
it('claims the exact job before its deferred GET returns, so a generic URL is never shown meanwhile', async () => {
  let generic!: (value: Delivery) => void, exact!: (value: Delivery) => void;
  vi.mocked(deliveryStatus).mockImplementationOnce(() => new Promise(resolve => { generic = resolve }));
  vi.mocked(readAutomaticDelivery).mockResolvedValue({ status: 'unknown', can_check: true }); vi.mocked(checkAutomaticDelivery).mockResolvedValue({ status: 'accepted', job_id: 'exact-job' });
  vi.mocked(deliveryById).mockImplementationOnce(() => new Promise(resolve => { exact = resolve }));
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>); fireEvent.click(await screen.findByRole('button', { name: '核验交付结果' }));
  await waitFor(() => expect(deliveryById).toHaveBeenCalledWith('exact-job'));
  await act(async () => generic({ id: 'old-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/old', error: '', recipients: {} }));
  expect(screen.queryByRole('button', { name: '查看文档 ↗' })).toBeNull();
  await act(async () => exact({ id: 'exact-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/exact', error: '', recipients: {} }));
  expect(screen.getByText('飞书文档 · 已交付')).toBeVisible();
});
it('same-scope refresh after check accepted/processing preserves the exact claim and visible receipt', async () => {
  let generic!: (value: Delivery) => void, refreshed!: (value: Delivery) => void;
  vi.mocked(deliveryStatus).mockImplementationOnce(() => new Promise(resolve => { generic = resolve })).mockResolvedValue({ id: 'old-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/old', error: '', recipients: {} });
  vi.mocked(readAutomaticDelivery).mockResolvedValueOnce({ status: 'unknown', can_check: true }).mockResolvedValue({ status: 'accepted', job_id: 'exact-job' });
  vi.mocked(checkAutomaticDelivery).mockResolvedValue({ status: 'accepted', job_id: 'exact-job' });
  vi.mocked(deliveryById).mockResolvedValueOnce({ id: 'exact-job', status: 'processing', document_url: 'https://company.feishu.cn/docx/exact', error: '', recipients: {} }).mockImplementationOnce(() => new Promise(resolve => { refreshed = resolve }));
  vi.mocked(openExternal).mockResolvedValue(undefined);
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" revision="r1" /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: '核验交付结果' }));
  await waitFor(() => expect(deliveryById).toHaveBeenCalledTimes(2));
  // The exact receipt remains visible while the new exact GET is pending.
  fireEvent.click(screen.getByRole('button', { name: '查看文档 ↗' })); expect(openExternal).toHaveBeenLastCalledWith('https://company.feishu.cn/docx/exact');
  await act(async () => generic({ id: 'old-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/old', error: '', recipients: {} }));
  fireEvent.click(screen.getByRole('button', { name: '查看文档 ↗' })); expect(openExternal).toHaveBeenLastCalledWith('https://company.feishu.cn/docx/exact');
  await act(async () => refreshed({ id: 'exact-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/exact', error: '', recipients: {} }));
  expect(screen.getByText('飞书文档 · 已交付')).toBeVisible(); expect(deliveryStatus).toHaveBeenCalledTimes(1);
});
it('a revision change clears the exact claim and permits the new scopes generic receipt', async () => {
  vi.mocked(deliveryStatus).mockResolvedValueOnce(null).mockResolvedValue({ id: 'new-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/new', error: '', recipients: {} });
  vi.mocked(readAutomaticDelivery).mockResolvedValueOnce({ status: 'accepted', job_id: 'exact-job' }).mockResolvedValue(null);
  vi.mocked(deliveryById).mockResolvedValue({ id: 'exact-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/exact', error: '', recipients: {} });
  vi.mocked(openExternal).mockResolvedValue(undefined);
  const view = render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" revision="r1" /></MemoryRouter>); await screen.findByRole('button', { name: '查看文档 ↗' });
  fireEvent.click(screen.getByRole('button', { name: '查看文档 ↗' })); expect(openExternal).toHaveBeenLastCalledWith('https://company.feishu.cn/docx/exact');
  view.rerender(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" revision="r2" /></MemoryRouter>); await screen.findByText('飞书文档 · 已交付');
  fireEvent.click(screen.getByRole('button', { name: '查看文档 ↗' })); expect(openExternal).toHaveBeenLastCalledWith('https://company.feishu.cn/docx/new'); expect(deliveryStatus).toHaveBeenCalledTimes(2);
});
it('can_check false never presents a query action or resubmission shortcut', async () => {
  vi.mocked(readAutomaticDelivery).mockResolvedValue({ status: 'unknown', can_check: false });
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>);
  await screen.findByText(/自动交付结果尚未确认/); expect(screen.queryByRole('button', { name: '核验交付结果' })).toBeNull(); expect(checkAutomaticDelivery).not.toHaveBeenCalled();
});
it('a different job receipt never supplies a document link for the accepted automatic task', async () => {
  vi.mocked(readAutomaticDelivery).mockResolvedValue({ status: 'accepted', job_id: 'exact-job' });
  vi.mocked(deliveryById).mockResolvedValue({ id: 'other-job', status: 'completed', document_url: 'https://company.feishu.cn/docx/other', error: '', recipients: {} });
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>);
  await screen.findByText(/交付回执不属于原任务/); expect(screen.queryByRole('button', { name: '查看文档 ↗' })).toBeNull();
});
it('late state and check results cannot replace another note or account', async () => {
  let finish!: (value: { status: 'failed'; error: string }) => void;
  vi.mocked(readAutomaticDelivery).mockResolvedValueOnce({ status: 'unknown', can_check: true }).mockResolvedValue(null);
  vi.mocked(checkAutomaticDelivery).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
  const view = render(<MemoryRouter><FeishuDocumentFooter noteId="old-note" /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: '核验交付结果' }));
  view.rerender(<MemoryRouter><FeishuDocumentFooter noteId="new-note" /></MemoryRouter>);
  act(() => useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }));
  await act(async () => finish({ status: 'failed', error: '旧页错误' }));
  await waitFor(() => expect(screen.queryByText('旧页错误')).toBeNull());
});

const receipt = (status: 'processing' | 'completed') => ({ id: 'exact-job', status, document_url: 'https://company.feishu.cn/docx/original', error: '', recipients: {} });
const flush = async () => { await act(async () => { await Promise.resolve() }) };
const advance = async (ms = 3000) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) };
it('bounded GET polling follows queued to accepted to completed without automatic check or publish', async () => {
  vi.useFakeTimers();
  vi.mocked(readAutomaticDelivery).mockResolvedValueOnce({ status: 'queued' }).mockResolvedValue({ status: 'accepted', job_id: 'exact-job' });
  vi.mocked(deliveryById).mockResolvedValueOnce(receipt('processing')).mockResolvedValue(receipt('completed'));
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>); await flush();
  expect(readAutomaticDelivery).toHaveBeenCalledTimes(1);
  await advance(); expect(readAutomaticDelivery).toHaveBeenCalledTimes(2); expect(deliveryById).toHaveBeenCalledExactlyOnceWith('exact-job');
  await advance(); expect(screen.getByText('飞书文档 · 已交付')).toBeVisible();
  await advance(60000); expect(readAutomaticDelivery).toHaveBeenCalledTimes(3); expect(deliveryById).toHaveBeenCalledTimes(2); expect(checkAutomaticDelivery).not.toHaveBeenCalled();
});
it('twelve total rounds exhaust the budget; a manual read never restarts that budget', async () => {
  vi.useFakeTimers(); vi.mocked(readAutomaticDelivery).mockResolvedValue({ status: 'queued' });
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>); await flush();
  for (let n = 1; n < 12; n++) await advance();
  expect(readAutomaticDelivery).toHaveBeenCalledTimes(12); expect(screen.getByRole('button', { name: '刷新交付状态' })).toBeVisible();
  await advance(60000); expect(readAutomaticDelivery).toHaveBeenCalledTimes(12);
  fireEvent.click(screen.getByRole('button', { name: '刷新交付状态' })); await flush();
  expect(readAutomaticDelivery).toHaveBeenCalledTimes(13);
  await advance(60000); expect(readAutomaticDelivery).toHaveBeenCalledTimes(13); expect(checkAutomaticDelivery).not.toHaveBeenCalled();
});
it.each(['unknown', 'failed', 'cancelled'] as const)('%s stops automatic reads and never triggers a check', async status => {
  vi.useFakeTimers(); vi.mocked(readAutomaticDelivery).mockResolvedValue({ status, can_check: true });
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>); await flush();
  await advance(60000); expect(readAutomaticDelivery).toHaveBeenCalledTimes(1); expect(checkAutomaticDelivery).not.toHaveBeenCalled();
});
it('route, revision and owner changes cancel timers; old deferred reads cannot replace the new scope', async () => {
  vi.useFakeTimers();
  let finish!: (value: { status: 'failed'; error: string }) => void;
  vi.mocked(readAutomaticDelivery).mockResolvedValueOnce({ status: 'queued' }).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockResolvedValue(null);
  const view = render(<MemoryRouter><FeishuDocumentFooter noteId="old-note" revision="r1" /></MemoryRouter>); await flush(); await advance();
  expect(readAutomaticDelivery).toHaveBeenCalledTimes(2);
  view.rerender(<MemoryRouter><FeishuDocumentFooter noteId="new-note" revision="r2" /></MemoryRouter>); await flush();
  act(() => useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } })); await flush();
  await act(async () => finish({ status: 'failed', error: '旧轮询错误' })); await advance(60000);
  expect(screen.queryByText('旧轮询错误')).toBeNull(); expect(readAutomaticDelivery).toHaveBeenCalledTimes(4); expect(checkAutomaticDelivery).not.toHaveBeenCalled();
});
it.each(['note', 'revision', 'owner'])('%s change clears a scheduled polling timer', async kind => {
  vi.useFakeTimers(); vi.mocked(readAutomaticDelivery).mockResolvedValueOnce({ status: 'queued' }).mockResolvedValue(null);
  const view = render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" revision="r1" /></MemoryRouter>); await flush();
  expect(vi.getTimerCount()).toBe(1);
  if (kind === 'owner') act(() => useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }));
  else view.rerender(<MemoryRouter><FeishuDocumentFooter noteId={kind === 'note' ? 'new-note' : 'saved-note'} revision={kind === 'revision' ? 'r2' : 'r1'} /></MemoryRouter>);
  await flush(); expect(vi.getTimerCount()).toBe(0);
  await advance(60000); expect(readAutomaticDelivery).toHaveBeenCalledTimes(2); expect(checkAutomaticDelivery).not.toHaveBeenCalled();
});
it('a deferred exact-job polling response cannot replace a new note or install another timer', async () => {
  vi.useFakeTimers(); let finish!: (value: ReturnType<typeof receipt>) => void;
  vi.mocked(readAutomaticDelivery).mockResolvedValueOnce({ status: 'queued' }).mockResolvedValueOnce({ status: 'accepted', job_id: 'exact-job' }).mockResolvedValue(null);
  vi.mocked(deliveryById).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
  const view = render(<MemoryRouter><FeishuDocumentFooter noteId="old-note" /></MemoryRouter>); await flush(); await advance();
  view.rerender(<MemoryRouter><FeishuDocumentFooter noteId="new-note" /></MemoryRouter>); await flush();
  await act(async () => finish(receipt('completed'))); await advance(60000);
  expect(screen.queryByRole('button', { name: '查看文档 ↗' })).toBeNull(); expect(vi.getTimerCount()).toBe(0); expect(readAutomaticDelivery).toHaveBeenCalledTimes(3);
});
