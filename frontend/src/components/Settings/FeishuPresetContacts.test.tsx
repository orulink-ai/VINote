import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { FeishuPresetContacts } from './FeishuPresetContacts';
import { feishuContacts, type FeishuContactPage } from '@/lib/feishu';
import { useAuthStore } from '@/stores/authStore';
vi.mock('@/lib/feishu', () => ({ feishuContacts: vi.fn() }));
vi.mock('@/lib/feishuPublishReceipt', () => ({ publishScope: () => () => {} }));
const page = (name: string): FeishuContactPage => ({ items: [{ open_id: name, name, selection_token: 'proof', expiresAt: Date.now() + 900000 }], has_more: false, page_token: '', selection_expires_in: 900, search_required: true });
const mount = (browseRecent = true, disabled = false) => render(<FeishuPresetContacts value={[]} onChange={vi.fn()} disabled={disabled} connectionKey={1} connectionCurrent={() => true} browseRecent={browseRecent} hideHeading />);
beforeEach(() => { vi.resetAllMocks(); useAuthStore.setState({ user: { id: 'contact-owner', email: 'test@example.invalid' } }); });
afterEach(cleanup);
it('shows recent contacts immediately and supports a name search with Enter', async () => {
  vi.mocked(feishuContacts).mockResolvedValueOnce(page('近期联系人')).mockResolvedValueOnce(page('姓名结果'));
  mount();
  expect(await screen.findByRole('button', { name: '选择联系人近期联系人' })).toBeVisible();
  expect(feishuContacts).toHaveBeenCalledWith('', '');
  expect(screen.getByText(/当前只显示部分联系人/)).toBeVisible();
  const input = screen.getByLabelText('预设通知联系人');
  fireEvent.change(input, { target: { value: '姓名' } }); fireEvent.keyDown(input, { key: 'Enter' });
  expect(await screen.findByRole('button', { name: '选择联系人姓名结果' })).toBeVisible();
  expect(feishuContacts).toHaveBeenLastCalledWith('姓名', '');
});
it('does not let a slow recent response replace a newer name search', async () => {
  let finish!: (value: FeishuContactPage) => void;
  vi.mocked(feishuContacts).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(page('姓名结果'));
  mount();
  const input = screen.getByLabelText('预设通知联系人');
  fireEvent.change(input, { target: { value: '姓名' } }); fireEvent.keyDown(input, { key: 'Enter' });
  await screen.findByRole('button', { name: '选择联系人姓名结果' });
  await act(async () => finish(page('旧列表')));
  expect(screen.queryByRole('button', { name: '选择联系人旧列表' })).toBeNull();
});
it('does not request recent contacts for a transport without recent support', () => { mount(false); expect(feishuContacts).not.toHaveBeenCalled(); });
it('does not request contacts while disconnected', () => { mount(true, true); expect(feishuContacts).not.toHaveBeenCalled(); });
it('explains an empty recent list and keeps name search available', async () => {
  vi.mocked(feishuContacts).mockResolvedValue({ ...page(''), items: [], search_required: false }); mount();
  expect(await screen.findByText('暂无近期联系人，请输入姓名搜索。')).toBeVisible();
  expect(screen.getByLabelText('预设通知联系人')).toBeEnabled();
});
