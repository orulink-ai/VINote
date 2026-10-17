import { useState } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiJson } from '@/lib/api'
import type { FeishuDestination } from '@/lib/feishu'
import { FeishuDestinationPicker } from './FeishuDestinationPicker'

vi.mock('@/lib/api', () => ({ apiJson: vi.fn() }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: Object.assign((selector: (state: { user: { id: string } }) => unknown) => selector({ user: { id: 'owner' } }), { getState: () => ({ user: { id: 'owner' } }) }) }))
const changed = vi.fn(), checked = vi.fn()
function Fixture({ initial }: { initial: FeishuDestination }) {
  const [value, setValue] = useState(initial)
  return <FeishuDestinationPicker value={value} onChange={next => { changed(next); setValue(next) }} onChecked={checked} />
}
beforeEach(() => vi.resetAllMocks())
afterEach(cleanup)

it('browses knowledge spaces and children, shows the selected name and checks unchanged tokens explicitly', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce({ items: [{ kind: 'wiki', space_id: 'space-1', name: '产品知识库' }], has_more: false, page_token: '' })
    .mockResolvedValueOnce({ items: [{ kind: 'wiki', space_id: 'space-1', node_token: 'node-1', name: '会议纪要' }], has_more: false, page_token: '' })
    .mockResolvedValueOnce({ kind: 'wiki', space_id: 'space-1', node_token: 'node-1', name: '会议纪要', path: ['产品知识库', '会议纪要'], path_complete: true, can_attempt_create: true, can_create: false })
  render(<Fixture initial={{ kind: 'wiki', space_id: '', node_token: '' }} />)
  expect(screen.queryByLabelText('知识空间标识')).toBeNull()
  expect(screen.queryByLabelText('父节点标识')).toBeNull()
  expect(apiJson).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: '浏览可见位置' }))
  await screen.findByText('产品知识库')
  await userEvent.click(screen.getByRole('button', { name: '进入' }))
  await screen.findByText('会议纪要')
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/destinations?kind=wiki&space_id=space-1')
  await userEvent.click(screen.getByRole('button', { name: '选择' }))
  const target = { kind: 'wiki', space_id: 'space-1', node_token: 'node-1' }
  expect(changed).toHaveBeenLastCalledWith(target)
  expect(within(screen.getByRole('region', { name: '已选文档位置' })).getByText('会议纪要')).toBeVisible()
  expect(apiJson).toHaveBeenCalledTimes(2)
  expect(checked).toHaveBeenLastCalledWith(null)
  await userEvent.click(screen.getByRole('button', { name: '核验位置与权限' }))
  await screen.findByText('目录可读，创建权限将在提交时核验。')
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/destinations/check', { method: 'POST', body: JSON.stringify(target) })
  expect(screen.getByRole('region', { name: '已选文档位置' })).toHaveTextContent('产品知识库 / 会议纪要')
})

it('keeps folder selection readable with manual tokens collapsed', async () => {
  vi.mocked(apiJson).mockResolvedValue({ items: [{ kind: 'folder', folder_token: 'folder-1', name: '团队会议' }], has_more: false, page_token: '' })
  render(<Fixture initial={{ kind: 'folder', folder_token: '' }} />)
  expect(screen.queryByLabelText('文件夹标识')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: '浏览可见位置' }))
  await screen.findByText('团队会议')
  await userEvent.click(screen.getByRole('button', { name: '选择' }))
  expect(changed).toHaveBeenLastCalledWith({ kind: 'folder', folder_token: 'folder-1' })
  expect(screen.getByRole('region', { name: '已选文档位置' })).toHaveTextContent('团队会议')
  expect(apiJson).toHaveBeenCalledTimes(1)
})

it.each(['folder', 'wiki'] as const)('retains saved %s tokens and exposes manual editing only after expanding advanced settings', async kind => {
  const target: FeishuDestination = kind === 'folder' ? { kind, folder_token: 'saved-folder' } : { kind, space_id: 'saved-space', node_token: 'saved-node' }
  render(<Fixture initial={target} />)
  expect(screen.getByRole('region', { name: '已选文档位置' })).toHaveTextContent('已保留文档位置')
  expect(changed).not.toHaveBeenCalled()
  await userEvent.click(screen.getByText('高级设置 · 手填位置标识'))
  const label = kind === 'folder' ? '文件夹标识' : '父节点标识'
  const input = await screen.findByLabelText(label)
  expect(input).toHaveValue(kind === 'folder' ? 'saved-folder' : 'saved-node')
  fireEvent.change(input, { target: { value: 'manual-target' } })
  expect(changed).toHaveBeenLastCalledWith(kind === 'folder' ? { kind, folder_token: 'manual-target' } : { kind, space_id: 'saved-space', node_token: 'manual-target' })
  expect(checked).toHaveBeenLastCalledWith(null)
  await userEvent.click(screen.getByText('高级设置 · 手填位置标识'))
  await waitFor(() => expect(screen.queryByLabelText(label)).toBeNull())
  expect(apiJson).not.toHaveBeenCalled()
})

it('retains the selected name on a failed browse and resets advanced settings when the location type changes', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce({ items: [{ kind: 'folder', folder_token: 'folder-1', name: '已选会议' }], has_more: false, page_token: '' }).mockRejectedValueOnce(new Error('读取失败'))
  render(<Fixture initial={{ kind: 'folder', folder_token: '' }} />)
  await userEvent.click(screen.getByRole('button', { name: '浏览可见位置' }))
  await screen.findByText('已选会议')
  await userEvent.click(screen.getByRole('button', { name: '选择' }))
  await userEvent.click(screen.getByRole('button', { name: '刷新当前目录' }))
  await screen.findByText('读取失败')
  expect(screen.getByRole('region', { name: '已选文档位置' })).toHaveTextContent('已选会议')
  await userEvent.click(screen.getByText('高级设置 · 手填位置标识'))
  await screen.findByLabelText('文件夹标识')
  await userEvent.selectOptions(screen.getByRole('combobox', { name: '文档位置类型' }), 'wiki')
  expect(screen.queryByLabelText('父节点标识')).toBeNull()
  expect(screen.getByRole('region', { name: '已选文档位置' })).toHaveTextContent('尚未选择')
})
it('shows the verified personal location and permissions without exposing a tenant key or inventing an organization name', async () => {
  vi.mocked(apiJson).mockResolvedValue({ kind: 'personal', name: '个人云文档', path: ['个人云文档'], path_complete: true, tenant_key: 'tenant-test-key', can_attempt_create: true, can_create: true })
  render(<Fixture initial={{ kind: 'personal' }} />)
  await userEvent.click(screen.getByRole('button', { name: '核验位置与权限' }))
  await screen.findByText('已具备创建条件，提交时仍由飞书核验。')
  expect(document.body.textContent).not.toContain('tenant-test-key')
  expect(document.body.textContent).not.toContain('组织：')
  expect(checked).toHaveBeenLastCalledWith(expect.objectContaining({ tenant_key: 'tenant-test-key' }))
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/destinations/check', { method: 'POST', body: JSON.stringify({ kind: 'personal' }) })
})

it('automatically checks a complete default without changing it or creating a document', async () => {
  const target = { kind: 'personal' as const };
  vi.mocked(apiJson).mockResolvedValue({ ...target, name: '个人云文档', path: ['个人云文档'], can_attempt_create: true });
  render(<FeishuDestinationPicker value={target} onChange={changed} onChecked={checked} autoCheck />);
  await waitFor(() => expect(checked).toHaveBeenLastCalledWith(expect.objectContaining({ can_attempt_create: true })));
  expect(changed).not.toHaveBeenCalled();
  expect(apiJson).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button', { name: '核验位置与权限' })).toBeNull();
});
it('discards a late old-target check and never unlocks the replacement target', async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(apiJson).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValueOnce({ kind: 'folder', folder_token: 'new', name: '新位置', path: ['新位置'], can_attempt_create: false });
  const view = render(<FeishuDestinationPicker value={{ kind: 'folder', folder_token: 'old' }} onChange={changed} onChecked={checked} autoCheck />);
  view.rerender(<FeishuDestinationPicker value={{ kind: 'folder', folder_token: 'new' }} onChange={changed} onChecked={checked} autoCheck />);
  await waitFor(() => expect(checked).toHaveBeenLastCalledWith(expect.objectContaining({ folder_token: 'new' })));
  await act(async () => finish({ kind: 'folder', folder_token: 'old', name: '旧位置', path: ['旧位置'], can_attempt_create: true }));
  expect(checked).toHaveBeenLastCalledWith(expect.objectContaining({ folder_token: 'new', can_attempt_create: false }));
  expect(screen.queryByText(/旧位置/)).toBeNull();
});
it('keeps a failed automatic check retryable without treating failure as permission', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('位置服务暂不可用')).mockResolvedValueOnce({ kind: 'personal', name: '个人云文档', path: [], can_attempt_create: true });
  render(<FeishuDestinationPicker value={{ kind: 'personal' }} onChange={changed} onChecked={checked} autoCheck />);
  await screen.findByText('位置服务暂不可用');
  expect(checked).toHaveBeenLastCalledWith(null);
  fireEvent.click(screen.getByRole('button', { name: '核验位置与权限' }));
  await waitFor(() => expect(checked).toHaveBeenLastCalledWith(expect.objectContaining({ can_attempt_create: true })));
});
it('preserves a completed manual Settings check across a temporary disabled state', async () => {
  const result = { kind: 'personal', name: '个人云文档', path: [], can_attempt_create: true };
  vi.mocked(apiJson).mockResolvedValue(result);
  const view = render(<FeishuDestinationPicker value={{ kind: 'personal' }} onChange={changed} onChecked={checked} />);
  fireEvent.click(screen.getByRole('button', { name: '核验位置与权限' }));
  await waitFor(() => expect(checked).toHaveBeenLastCalledWith(result));
  view.rerender(<FeishuDestinationPicker value={{ kind: 'personal' }} onChange={changed} onChecked={checked} disabled />);
  view.rerender(<FeishuDestinationPicker value={{ kind: 'personal' }} onChange={changed} onChecked={checked} />);
  expect(checked).toHaveBeenLastCalledWith(result);
  expect(apiJson).toHaveBeenCalledTimes(1);
});
