import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { FeishuObjectHotwords } from './FeishuObjectHotwords';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import type { FeishuObjectHotwords as Directory } from '@/lib/feishu';
vi.mock('@/lib/api', () => ({ apiJson: vi.fn() }));
const directory: Directory = { objects: [{ id: 'ou_one', name: '同名', kind: 'contact' }, { id: 'oc_one', name: '同名', kind: 'group' }], aliases: [], partial: true };
const mount = () => render(<FeishuObjectHotwords connectionKey={1} connectionCurrent={() => true} />);
const openPicker = async () => {
  const trigger = await screen.findByRole('combobox', { name: '绑定对象' });
  await waitFor(() => expect(trigger).toBeEnabled());
  if (trigger.getAttribute('aria-expanded') !== 'true') fireEvent.click(trigger);
};
const choose = async (alias = '项目组') => {
  await openPicker();
  fireEvent.click(await screen.findByRole('option', { name: /^同名 · 群(?: · oc_one)?$/ }));
  fireEvent.change(screen.getByLabelText('别称'), { target: { value: alias } });
};
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');
beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  vi.resetAllMocks(); useAuthStore.setState({ user: { id: 'hotwords-owner', email: 'test@example.invalid' } });
  vi.mocked(apiJson).mockResolvedValue(directory);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll); else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView') });

it('reads visible objects on entry, explicitly binds a real object and deletes only the chosen alias', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce(directory).mockResolvedValueOnce({ ...directory, aliases: [{ id: 'alias/one', alias: '项目组', target_id: 'oc_one', target_name: '同名', kind: 'group' }] }).mockResolvedValueOnce(directory);
  mount(); expect(await screen.findByText('当前仅显示部分可见对象，可更新后再查找。')).toBeVisible();
  await openPicker(); expect(screen.getAllByRole('option').map(item => item.textContent)).toEqual(['同名 · 联系人', '同名 · 群']);
  await choose(); fireEvent.click(screen.getByRole('button', { name: '保存别称' }));
  const remove = await screen.findByRole('button', { name: '删除别称项目组' });
  expect(apiJson).toHaveBeenNthCalledWith(2, '/api/feishu/object-hotwords', { method: 'POST', body: JSON.stringify({ alias: '项目组', target_id: 'oc_one' }) });
  fireEvent.click(remove); await waitFor(() => expect(screen.queryByRole('button', { name: '删除别称项目组' })).toBeNull());
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/object-hotwords/alias%2Fone', { method: 'DELETE' });
  expect(vi.mocked(apiJson).mock.calls.every(([path]) => !path.includes('deliveries') && !path.includes('preferences'))).toBe(true);
});
it('read errors and malformed responses are not successful empty directories, and explicit refresh retries', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('读取暂不可用')).mockResolvedValueOnce({ objects: [], aliases: [] }).mockResolvedValueOnce({ objects: [], aliases: [], partial: false });
  mount(); await screen.findByText('读取暂不可用'); expect(screen.queryByText('当前没有可见对象，可更新后再试。')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '重新读取对象' })); await screen.findByText('对象目录响应未核验，请重新读取');
  expect(screen.queryByLabelText('绑定对象')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '更新可见对象' })); await screen.findByText('当前没有可见对象，可更新后再试。');
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/object-hotwords/refresh', { method: 'POST' });
});
it('requires a selection, limits alias length and refuses ambiguous names without any POST', async () => {
  mount(); await screen.findByLabelText('别称'); fireEvent.change(screen.getByLabelText('别称'), { target: { value: '项目组' } });
  expect(screen.getByRole('button', { name: '保存别称' })).toBeDisabled(); await choose('字'.repeat(51)); expect(screen.getByRole('button', { name: '保存别称' })).toBeDisabled();
  await choose('同名'); fireEvent.click(screen.getByRole('button', { name: '保存别称' })); await screen.findByText(/这个别称已对应/);
  expect(apiJson).toHaveBeenCalledTimes(1);
});
it('keeps failed save drafts and revalidates the directory before another explicit save', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce(directory).mockRejectedValueOnce(new Error('保存失败')).mockResolvedValueOnce(directory).mockResolvedValue(directory);
  mount(); await choose(); fireEvent.click(screen.getByRole('button', { name: '保存别称' })); await screen.findByText('保存失败');
  expect(screen.getByLabelText('别称')).toHaveValue('项目组'); expect(screen.getByRole('combobox', { name: '绑定对象' })).toHaveTextContent('同名 · 群');
  fireEvent.click(screen.getByRole('button', { name: '重新读取对象' })); await waitFor(() => expect(screen.getByRole('button', { name: '保存别称' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '保存别称' })); await screen.findByText('别称已保存。');
});
it('owner ABA rejects a late directory and old finally cannot unlock a new read', async () => {
  let old!: (value: Directory) => void, latest!: (value: Directory) => void;
  vi.mocked(apiJson).mockImplementationOnce(() => new Promise(resolve => { old = resolve })).mockImplementationOnce(() => new Promise(resolve => { latest = resolve }));
  mount(); act(() => { useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }); useAuthStore.setState({ user: { id: 'hotwords-owner', email: 'test@example.invalid' } }) });
  await waitFor(() => expect(apiJson).toHaveBeenCalledTimes(2)); await act(async () => old(directory));
  expect(screen.queryByLabelText('绑定对象')).toBeNull(); expect(screen.getByRole('button', { name: '更新可见对象' })).toBeDisabled();
  await act(async () => latest(directory)); expect(await screen.findByLabelText('绑定对象')).toBeEnabled();
});
it('unmount and a changed connection discard late reads and do not mutate an alias automatically', async () => {
  let old!: (value: Directory) => void;
  vi.mocked(apiJson).mockImplementationOnce(() => new Promise(resolve => { old = resolve }));
  const view = mount(); view.rerender(<FeishuObjectHotwords connectionKey={2} connectionCurrent={() => true} />);
  await screen.findByLabelText('别称'); view.unmount(); await act(async () => old(directory));
  expect(apiJson).toHaveBeenCalledTimes(2); expect(vi.mocked(apiJson).mock.calls.every(([, options]) => !options?.method)).toBe(true);
});
it('a late mutation from an earlier owner visit cannot replace the new directory or restore its alias', async () => {
  let oldSave!: (value: Directory) => void;
  vi.mocked(apiJson).mockResolvedValueOnce(directory).mockImplementationOnce(() => new Promise(resolve => { oldSave = resolve })).mockResolvedValue({ objects: [{ id: 'ou_new', name: '新账号对象', kind: 'contact' }], aliases: [], partial: false });
  mount(); await choose(); fireEvent.click(screen.getByRole('button', { name: '保存别称' }));
  act(() => { useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }); useAuthStore.setState({ user: { id: 'hotwords-owner', email: 'test@example.invalid' } }) });
  await openPicker(); await screen.findByRole('option', { name: '新账号对象 · 联系人' });
  await act(async () => oldSave({ ...directory, aliases: [{ id: 'old-alias', alias: '旧别称', target_id: 'oc_one', target_name: '同名', kind: 'group' }] }));
  expect(screen.queryByRole('button', { name: '删除别称旧别称' })).toBeNull(); expect(screen.getByLabelText('别称')).toHaveValue('');
  expect(screen.getByRole('button', { name: '更新可见对象' })).toBeEnabled();
});
it('rejects an already bound normalized alias and keeps separate IDs for same-kind same-name objects', async () => {
  vi.mocked(apiJson).mockResolvedValue({ ...directory, objects: [...directory.objects, { id: 'oc_two', name: '同名', kind: 'group' }], aliases: [{ id: 'saved', alias: 'TEAM', target_id: 'ou_one', target_name: '同名', kind: 'contact' }] });
  mount(); await choose('ＴＥＡＭ'); fireEvent.click(screen.getByRole('button', { name: '保存别称' }));
  await screen.findByText(/这个别称已对应/); expect(apiJson).toHaveBeenCalledTimes(1);
  await openPicker(); expect(screen.getByRole('option', { name: '同名 · 群 · oc_one' })).toBeVisible(); expect(screen.getByRole('option', { name: '同名 · 群 · oc_two' })).toBeVisible();
});

it('binds the explicitly selected visible contact without an employment check or reauthorization request', async () => {
  mount(); await openPicker();
  fireEvent.click(screen.getByRole('option', { name: '同名 · 联系人' }));
  fireEvent.change(screen.getByLabelText('别称'), { target: { value: '负责同事' } });
  expect(screen.queryByRole('button', { name: '重新授权获取状态' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '保存别称' }));
  await screen.findByText('别称已保存。');
  expect(apiJson).toHaveBeenCalledTimes(2);
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/object-hotwords', { method: 'POST', body: JSON.stringify({ alias: '负责同事', target_id: 'ou_one' }) });
  expect(vi.mocked(apiJson).mock.calls.some(([path]) => path.includes('authorize') || path.includes('deliveries'))).toBe(false);
});
