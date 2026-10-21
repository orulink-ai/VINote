import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import type { FeishuDestination } from '@/lib/feishu';
import { FeishuDestinationPicker } from './FeishuDestinationPicker';

vi.mock('@/lib/api', () => ({ apiJson: vi.fn() }));
const changed = vi.fn(), checked = vi.fn();
const folder = { kind: 'folder' as const, folder_token: 'folder-one' };
const listing = { items: [{ ...folder, name: '项目资料' }], has_more: false, page_token: '' };
const result = { ...folder, name: '项目资料', path: ['项目资料'], path_complete: true, can_attempt_create: true, can_create: false };
function Fixture({ initial = { kind: 'personal' }, connectionKey = 'binding-one' }: { initial?: FeishuDestination; connectionKey?: string }) {
  const [value, setValue] = useState(initial);
  return <FeishuDestinationPicker connectionKey={connectionKey} value={value} onChange={next => { changed(next); setValue(next) }} onChecked={checked} />;
}
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear();
  useAuthStore.setState({ user: { id: 'picker-owner', email: 'picker@example.invalid' } });
  vi.mocked(apiJson).mockImplementation(async path => path === '/api/feishu/destinations/check' ? result : listing);
});
afterEach(cleanup);
const open = () => fireEvent.click(screen.getByRole('button', { name: '选择文档位置' }));
const folders = () => fireEvent.change(screen.getByRole('combobox', { name: '文档位置类型' }), { target: { value: 'folder' } });

it('uses one dialog, separates entering from selection, and commits only after the confirmation check', async () => {
  render(<Fixture />); expect(screen.queryByRole('combobox', { name: '文档位置类型' })).toBeNull(); open(); folders();
  const dialog = screen.getByRole('dialog', { name: '选择文档位置' });
  await within(dialog).findByText('项目资料');
  fireEvent.click(within(dialog).getByRole('button', { name: '进入项目资料' }));
  await waitFor(() => expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/destinations?kind=folder&folder_token=folder-one'));
  expect(changed).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: '选择项目资料' }));
  expect(changed).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: '确认位置并核验' }));
  await waitFor(() => expect(changed).toHaveBeenCalledExactlyOnceWith(folder));
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/destinations/check', { method: 'POST', body: JSON.stringify(folder) });
  expect(checked).toHaveBeenLastCalledWith(result);
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.getByRole('region', { name: '已选文档位置' })).toHaveTextContent('项目资料');
});

it('cancel keeps the committed destination and ignores a late confirmation without a second request', async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiJson).mockImplementation(async path => path === '/api/feishu/destinations/check' ? new Promise(resolve => { finish = resolve }) : listing);
  render(<Fixture />); open(); folders(); await screen.findByText('项目资料');
  fireEvent.click(screen.getByRole('button', { name: '选择项目资料' }));
  const confirm = screen.getByRole('button', { name: '确认位置并核验' });
  fireEvent.click(confirm); fireEvent.click(confirm);
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  await act(async () => finish(result));
  expect(changed).not.toHaveBeenCalled();
  expect(vi.mocked(apiJson).mock.calls.filter(([path]) => path.endsWith('/check'))).toHaveLength(1);
  expect(screen.getByRole('region', { name: '已选文档位置' })).toHaveTextContent('个人云文档');
});

it('permission rejection preserves the original and leaves a deliberate check retry', async () => {
  vi.mocked(apiJson).mockImplementation(async path => path.endsWith('/check') ? { ...result, can_attempt_create: false, reason: '无创建权限' } : listing);
  render(<Fixture />); open(); folders(); await screen.findByText('项目资料');
  fireEvent.click(screen.getByRole('button', { name: '选择项目资料' }));
  fireEvent.click(screen.getByRole('button', { name: '确认位置并核验' }));
  await screen.findByText('无创建权限'); expect(changed).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: '确认位置并核验' })).toBeEnabled();
});

it('owner ABA invalidates a pending check, without recording recent destinations or committing', async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiJson).mockImplementation(async path => path.endsWith('/check') ? new Promise(resolve => { finish = resolve }) : listing);
  render(<Fixture />); open(); folders(); await screen.findByText('项目资料');
  fireEvent.click(screen.getByRole('button', { name: '选择项目资料' })); fireEvent.click(screen.getByRole('button', { name: '确认位置并核验' }));
  act(() => {
    useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } });
    useAuthStore.setState({ user: { id: 'picker-owner', email: 'picker@example.invalid' } });
  });
  await act(async () => finish(result));
  expect(changed).not.toHaveBeenCalled(); expect(localStorage.length).toBe(0);
  expect(screen.queryByRole('dialog')).toBeNull();
});

it('isolates recent/favorites by VINote owner and verified Feishu binding, and checks reused shortcuts again', async () => {
  const view = render(<Fixture />); open(); folders(); await screen.findByText('项目资料');
  fireEvent.click(screen.getByRole('button', { name: '选择项目资料' }));
  fireEvent.click(screen.getByRole('button', { name: '收藏位置' }));
  fireEvent.click(screen.getByRole('button', { name: '确认位置并核验' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  const stored = localStorage.getItem('vinote:feishu-destinations:picker-owner:' + encodeURIComponent(window.location.origin) + ':binding-one');
  expect(stored).toContain('folder-one'); expect(stored).not.toContain('can_attempt_create');
  view.rerender(<Fixture connectionKey="binding-two" />); open();
  await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
  expect(screen.queryByRole('region', { name: '收藏位置' })).toBeNull();
  expect(screen.queryByRole('region', { name: '最近使用' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  view.rerender(<Fixture connectionKey="binding-one" />); open();
  await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
  const recent = screen.getByRole('region', { name: '最近使用' });
  fireEvent.click(within(recent).getByRole('button', { name: '项目资料' }));
  await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
  const before = vi.mocked(apiJson).mock.calls.filter(([path]) => path.endsWith('/check')).length;
  fireEvent.click(screen.getByRole('button', { name: '确认位置并核验' }));
  await waitFor(() => expect(vi.mocked(apiJson).mock.calls.filter(([path]) => path.endsWith('/check'))).toHaveLength(before + 1));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  act(() => useAuthStore.setState({ user: { id: 'another-owner', email: 'another@example.invalid' } }));
  open(); await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
  expect(screen.queryByRole('region', { name: '最近使用' })).toBeNull();
});

it('without a verified connection binding never reads old shortcuts or saves favorites', () => {
  localStorage.setItem('vinote:feishu-destinations:picker-owner:' + encodeURIComponent(window.location.origin), JSON.stringify({ favorites: [{ target: folder, name: '旧目录' }], recent: [] }));
  render(<FeishuDestinationPicker value={{ kind: 'personal' }} onChange={changed} />); open();
  expect(screen.queryByText('旧目录')).toBeNull();
  expect(screen.getByRole('button', { name: '收藏位置' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(localStorage.length).toBe(1); expect(apiJson).not.toHaveBeenCalled();
});

it('a binding change cancels a pending permission check and does not update the new connection', async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiJson).mockImplementation(async path => path.endsWith('/check') ? new Promise(resolve => { finish = resolve }) : listing);
  const view = render(<Fixture />); open(); folders(); await screen.findByText('项目资料');
  fireEvent.click(screen.getByRole('button', { name: '选择项目资料' })); fireEvent.click(screen.getByRole('button', { name: '确认位置并核验' }));
  view.rerender(<Fixture connectionKey="binding-two" />);
  await act(async () => finish(result));
  expect(changed).not.toHaveBeenCalled(); expect(checked).toHaveBeenLastCalledWith(null);
  expect(localStorage.length).toBe(0); expect(screen.queryByRole('dialog')).toBeNull();
});
