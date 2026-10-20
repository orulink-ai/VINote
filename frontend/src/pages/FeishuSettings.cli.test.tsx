import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { FeishuSettings } from './FeishuSettings';
import { feishuStatus, type FeishuStatus } from '@/lib/feishu';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';

vi.mock('@/lib/api', () => ({ apiJson: vi.fn() }));
vi.mock('@/lib/feishu', async original => ({ ...await original<typeof import('@/lib/feishu')>(), feishuStatus: vi.fn() }));
vi.mock('@/components/Settings/FeishuApplicationSetup', () => ({ FeishuApplicationSetup: () => <div>HTTP AppSecret 配置</div> }));
const base: FeishuStatus = { transport: 'cli', configured: false, connected: false, expired: false, name: '', notify_self: true, groups: [], auto_publish: false, destination: 'personal', setup: { cli_available: true } };
const flow = (stage: 'application' | 'authorization', id = stage) => ({ url: 'https://accounts.feishu.cn/oauth/device', qr_data_url: 'data:image/png;base64,eA==', expires_at: Date.now() / 1000 + 600, flow_id: id, stage });
const mount = () => render(<MemoryRouter><FeishuSettings /></MemoryRouter>);
const tab = (name: string) => fireEvent.mouseDown(screen.getByRole('tab', { name }));
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  useAuthStore.setState({ user: { id: 'cli-owner', email: 'test@example.invalid' } });
  vi.mocked(feishuStatus).mockResolvedValue(base);
});
afterEach(() => { cleanup(); vi.restoreAllMocks() });

it('offers three tabs and starts CLI application scan without configured credentials or an AppSecret form', async () => {
  vi.mocked(apiJson).mockResolvedValue(flow('application'));
  mount(); expect(screen.getAllByRole('tab').map(item => item.textContent)).toEqual(['授权', '会议纪要发送设置', '对象热词']);
  const connect = await screen.findByRole('button', { name: '连接飞书' }); await waitFor(() => expect(connect).toBeEnabled());
  expect(screen.queryByText('HTTP AppSecret 配置')).toBeNull(); fireEvent.click(connect);
  expect(await screen.findByText(/第一步：/)).toHaveTextContent('应用');
  expect(apiJson).toHaveBeenCalledWith('/api/feishu/authorize', { method: 'POST' });
  expect(screen.getByRole('button', { name: '我已完成授权' })).toBeEnabled();
});
it('programmatic focus restoration does not switch the active tab or submit authorization', async () => {
  mount(); await screen.findByRole('button', { name: '连接飞书' });
  const auth = screen.getByRole('tab', { name: '授权' }), delivery = screen.getByRole('tab', { name: '会议纪要发送设置' });
  fireEvent.focus(delivery); expect(auth).toHaveAttribute('aria-selected', 'true');
  tab('会议纪要发送设置'); fireEvent.focus(auth); expect(delivery).toHaveAttribute('aria-selected', 'true');
  expect(apiJson).not.toHaveBeenCalled();
});
it('completes only on explicit click, accepts the next QR stage, then reads verified status', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce(flow('application')).mockResolvedValueOnce(flow('authorization')).mockResolvedValueOnce({ ...base, configured: true, connected: true, name: '本人' });
  mount(); fireEvent.click(await screen.findByRole('button', { name: '连接飞书' })); await screen.findByRole('img');
  fireEvent(window, new Event('focus')); expect(apiJson).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: '我已完成授权' })); await screen.findByText(/第二步：/);
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/authorize/complete', { method: 'POST', body: JSON.stringify({ flow_id: 'application' }) });
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, configured: true, connected: true, name: '本人' });
  fireEvent.click(screen.getByRole('button', { name: '我已完成授权' })); await screen.findByText('本人'); expect(screen.queryByRole('img')).toBeNull();
  expect(screen.queryByText('尚未收到飞书授权，请完成后再次核验。')).toBeNull();
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/authorize/complete', { method: 'POST', body: JSON.stringify({ flow_id: 'authorization' }) });
});
it('clears obsolete authorization messages after success while retaining unsaved preferences and their prompt', async () => {
  sessionStorage.setItem('vinote:feishu-preferences:cli-owner', JSON.stringify({ notify_self: false, auto_publish: false, groups: [] }));
  vi.mocked(apiJson).mockResolvedValueOnce(flow('authorization')).mockResolvedValueOnce({ ...base, configured: true, connected: true });
  mount(); fireEvent.click(await screen.findByRole('button', { name: '连接飞书' }));
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, configured: true, connected: true, name: '本人' });
  fireEvent.click(await screen.findByRole('button', { name: '我已完成授权' })); await screen.findByText('本人');
  expect(screen.getByText('已恢复未保存的设置，请核对后保存。')).toBeVisible(); expect(screen.queryByText('尚未收到飞书授权，请完成后再次核验。')).toBeNull();
  tab('会议纪要发送设置'); expect(screen.getByRole('checkbox', { name: '发给我本人' })).not.toBeChecked();
  expect(sessionStorage.getItem('vinote:feishu-preferences:cli-owner')).not.toBeNull();
});
it('rejects owner ABA and route-unmounted completion responses without completing a replacement flow', async () => {
  let finish!: (result: ReturnType<typeof flow>) => void;
  vi.mocked(apiJson).mockResolvedValueOnce(flow('application')).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
  const view = mount(); fireEvent.click(await screen.findByRole('button', { name: '连接飞书' })); fireEvent.click(await screen.findByRole('button', { name: '我已完成授权' }));
  act(() => { useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }); useAuthStore.setState({ user: { id: 'cli-owner', email: 'test@example.invalid' } }) });
  await waitFor(() => expect(feishuStatus).toHaveBeenCalledTimes(2));
  await act(async () => finish(flow('authorization'))); expect(screen.queryByRole('img')).toBeNull();
  view.unmount(); mount(); await screen.findByRole('button', { name: '连接飞书' }); expect(apiJson).toHaveBeenCalledTimes(2);
});
it('requires an available CLI, while legacy HTTP authorization remains a status-only completion', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, setup: { cli_available: false } });
  const view = mount(); expect(await screen.findByRole('button', { name: '连接飞书' })).toBeDisabled(); view.unmount();
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, transport: undefined, configured: true }); vi.mocked(apiJson).mockResolvedValue({ ...flow('authorization'), flow_id: undefined, stage: undefined });
  mount(); expect(await screen.findByText('HTTP AppSecret 配置')).toBeVisible(); fireEvent.click(await screen.findByRole('button', { name: '连接飞书' }));
  fireEvent.click(await screen.findByRole('button', { name: '我已完成授权' })); await waitFor(() => expect(feishuStatus).toHaveBeenCalledTimes(3)); expect(apiJson).toHaveBeenCalledTimes(1);
  tab('会议纪要发送设置'); expect(screen.getByText(/请先在授权页签连接飞书/)).toBeVisible();
});
it('same-mounted route changes invalidate a pending completion and never complete a flow on navigation', async () => {
  let finish!: (result: ReturnType<typeof flow>) => void;
  vi.mocked(apiJson).mockResolvedValueOnce(flow('application')).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
  function RouteHarness() { const navigate = useNavigate(); return <><button onClick={() => navigate('/settings/feishu?visit=new')}>切换来源</button><FeishuSettings /></> }
  render(<MemoryRouter><RouteHarness /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: '连接飞书' })); fireEvent.click(await screen.findByRole('button', { name: '我已完成授权' }));
  fireEvent.click(screen.getByRole('button', { name: '切换来源' })); await waitFor(() => expect(feishuStatus).toHaveBeenCalledTimes(2));
  await act(async () => finish(flow('authorization'))); expect(screen.queryByRole('img')).toBeNull(); expect(apiJson).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('button', { name: '连接飞书' })).toBeEnabled();
});
it('keeps an incomplete flow for explicit retry, prevents duplicate completion, and does not persist flow data', async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiJson).mockResolvedValueOnce(flow('application')).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
  mount(); fireEvent.click(await screen.findByRole('button', { name: '连接飞书' }));
  const complete = await screen.findByRole('button', { name: '我已完成授权' }); fireEvent.click(complete); fireEvent.click(complete);
  expect(apiJson).toHaveBeenCalledTimes(2); await act(async () => finish({ ...base, connected: false }));
  await screen.findByText('授权尚未完成，请在有效期内完成扫码后再次确认。'); expect(complete).toBeEnabled();
  expect(screen.getByRole('img')).toBeVisible(); expect(sessionStorage.length).toBe(0);
});
it('reads object hotwords only when its tab is opened, and switching tabs never initiates authorization', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, configured: true, connected: true, name: '本人' });
  vi.mocked(apiJson).mockResolvedValue({ objects: [], aliases: [], partial: false }); mount(); await screen.findByText('本人');
  expect(apiJson).not.toHaveBeenCalled(); tab('对象热词'); await screen.findByText('当前没有可见对象，可更新后再试。');
  expect(apiJson).toHaveBeenCalledTimes(1); expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/object-hotwords', { cache: 'no-store' });
  tab('授权'); fireEvent(window, new Event('focus')); expect(apiJson).toHaveBeenCalledTimes(1);
});
it('shows a pending application process without a QR, and obtains each stage only by explicit completion', async () => {
  const pending = { ...flow('application'), pending: true, url: '', qr_data_url: '' };
  vi.mocked(apiJson).mockResolvedValueOnce(pending).mockResolvedValueOnce(pending).mockResolvedValueOnce(flow('application')).mockResolvedValueOnce(flow('authorization'));
  mount(); fireEvent.click(await screen.findByRole('button', { name: '连接飞书' }));
  const refresh = await screen.findByRole('button', { name: '继续连接/刷新二维码' });
  expect(screen.getByText(/应用连接正在准备/)).toBeVisible(); expect(screen.queryByRole('img')).toBeNull();
  expect(screen.queryByRole('button', { name: '在浏览器中授权飞书' })).toBeNull();
  fireEvent(window, new Event('focus')); vi.useFakeTimers();
  try { await act(async () => { await vi.advanceTimersByTimeAsync(3000) }); expect(apiJson).toHaveBeenCalledTimes(1) }
  finally { vi.useRealTimers() }
  fireEvent.click(refresh); await waitFor(() => expect(refresh).toBeEnabled()); expect(apiJson).toHaveBeenCalledTimes(2);
  fireEvent.click(refresh); await screen.findByRole('img'); expect(apiJson).toHaveBeenCalledTimes(3);
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/authorize/complete', { method: 'POST', body: JSON.stringify({ flow_id: 'application' }) });
  expect(screen.getByRole('button', { name: '我已完成授权' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: '我已完成授权' })); await screen.findByText(/第二步：/);
  expect(apiJson).toHaveBeenCalledTimes(4); expect(sessionStorage.length).toBe(0);
});
