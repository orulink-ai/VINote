import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import { FeishuMeetingContainerRecovery } from './FeishuMeetingContainerRecovery';

vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: vi.fn() }));
const state = { protocol: 1, delivery_id: 'delivery-one', state: 'unknown', title: '已冻结的会议目录',
  root_destination: { kind: 'wiki', space_id: 'space', node_token: 'root' }, context_revision: 'a'.repeat(64), can_recover: true, document_url: '' };
const done = { ...state, state: 'confirmed', can_recover: false, context_revision: 'b'.repeat(64), document_url: 'https://www.feishu.cn/wiki/existing' };
const recovered = vi.fn();
const mount = () => render(<MemoryRouter><FeishuMeetingContainerRecovery deliveryId="delivery-one" onRecovered={recovered} /></MemoryRouter>);
const posts = () => vi.mocked(apiJson).mock.calls.filter(([, options]) => options?.method === 'POST');
async function prepare() {
  const input = await screen.findByLabelText('已有会议目录的 Wiki 链接或节点标识');
  fireEvent.change(input, { target: { value: 'existingNode' } });
  fireEvent.click(screen.getByRole('checkbox', { name: '我已核对这是原会议目录' }));
}
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  useAuthStore.setState({ user: { id: 'recovery-owner', email: 'synthetic@example.invalid' } });
  vi.mocked(apiJson).mockResolvedValue(state);
});
afterEach(cleanup);

it('mount only reads the exact receipt and requires explicit URL/token plus confirmation before association', async () => {
  mount(); await screen.findByText('已冻结的会议目录');
  expect(posts()).toHaveLength(0);
  expect(screen.getByRole('button', { name: '核验并关联现有目录' })).toBeDisabled();
  await prepare(); vi.mocked(apiJson).mockResolvedValueOnce(done);
  fireEvent.click(screen.getByRole('button', { name: '核验并关联现有目录' }));
  await screen.findByText('会议目录已关联，尚未继续交付。');
  expect(posts()).toHaveLength(1);
  expect(JSON.parse(posts()[0][1]!.body as string)).toEqual({ expected_user_id: 'recovery-owner', confirmed: true, context_revision: state.context_revision, url: 'existingNode' });
  expect(recovered).toHaveBeenCalledOnce();
  expect(vi.mocked(apiJson).mock.calls.every(([path]) => path.startsWith('/api/feishu/meeting-containers/by-delivery/delivery-one'))).toBe(true);
});

it.each(['confirmed', 'creating', 'failed'])('does not offer a recovery entrance for a %s container', async status => {
  vi.mocked(apiJson).mockResolvedValue({ ...state, state: status, can_recover: false });
  mount(); await waitFor(() => expect(apiJson).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
  expect(screen.queryByLabelText('已有会议目录的 Wiki 链接或节点标识')).toBeNull(); expect(posts()).toHaveLength(0);
});

it('cancel discards only the draft and never associates or resumes', async () => {
  mount(); await prepare(); fireEvent.click(screen.getByRole('button', { name: '取消关联' }));
  expect(screen.getByLabelText('已有会议目录的 Wiki 链接或节点标识')).toHaveValue('');
  expect(posts()).toHaveLength(0); expect(recovered).not.toHaveBeenCalled();
});

it('double confirmation sends once; unknown/remount/refresh only GET the original receipt', async () => {
  let reject!: (error: Error) => void;
  const view = mount(); await prepare();
  vi.mocked(apiJson).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }));
  const submit = screen.getByRole('button', { name: '核验并关联现有目录' });
  fireEvent.click(submit); fireEvent.click(submit);
  await act(async () => reject(new Error('synthetic transport lost')));
  expect(posts()).toHaveLength(1);
  expect(screen.queryByRole('button', { name: '核验并关联现有目录' })).toBeNull();
  view.unmount(); mount(); await screen.findByRole('button', { name: '查询原目录状态' });
  expect(posts()).toHaveLength(1);
  vi.mocked(apiJson).mockResolvedValueOnce(done);
  fireEvent.click(screen.getByRole('button', { name: '查询原目录状态' }));
  await screen.findByText('会议目录已关联，尚未继续交付。'); expect(posts()).toHaveLength(1);
});

it('owner ABA discards late association success and never calls the new account callback', async () => {
  let finish!: (value: unknown) => void;
  mount(); await prepare(); vi.mocked(apiJson).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
  fireEvent.click(screen.getByRole('button', { name: '核验并关联现有目录' }));
  act(() => {
    useAuthStore.setState({ user: { id: 'other-owner', email: 'other@example.invalid' } });
    useAuthStore.setState({ user: { id: 'recovery-owner', email: 'synthetic@example.invalid' } });
  });
  await act(async () => finish(done));
  expect(recovered).not.toHaveBeenCalled(); expect(posts()).toHaveLength(1);
});

it('a known validation refusal preserves the editable draft without automatically retrying', async () => {
  mount(); await prepare();
  vi.mocked(apiJson).mockRejectedValueOnce(new ApiError('目录不在原父节点下', 409, {}));
  fireEvent.click(screen.getByRole('button', { name: '核验并关联现有目录' }));
  await screen.findByText('目录不在原父节点下');
  expect(screen.getByLabelText('已有会议目录的 Wiki 链接或节点标识')).toHaveValue('existingNode');
  expect(posts()).toHaveLength(1); expect(recovered).not.toHaveBeenCalled();
});

it('storage failure stops before POST and never claims an association succeeded', async () => {
  mount(); await prepare(); vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('quota') });
  fireEvent.click(screen.getByRole('button', { name: '核验并关联现有目录' }));
  await screen.findByText(/恢复状态无法保存在此浏览器/); expect(posts()).toHaveLength(0);
  vi.restoreAllMocks();
});

it('route changes discard late recovery success and only reload the exact receipt', async () => {
  let finish!: (value: unknown) => void;
  function Harness() { const navigate = useNavigate(); return <><button onClick={() => navigate('/elsewhere')}>离开来源</button><FeishuMeetingContainerRecovery deliveryId="delivery-one" onRecovered={recovered} /></> }
  render(<MemoryRouter><Harness /></MemoryRouter>); await prepare();
  vi.mocked(apiJson).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
  fireEvent.click(screen.getByRole('button', { name: '核验并关联现有目录' })); fireEvent.click(screen.getByRole('button', { name: '离开来源' }));
  await act(async () => finish(done));
  expect(recovered).not.toHaveBeenCalled(); expect(posts()).toHaveLength(1);
});
