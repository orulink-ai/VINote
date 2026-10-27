import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { PageReturn } from "@/components/Layout/PageReturn";
import { MemoryRouter, Routes, Route, Link, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FeishuDelivery } from "./FeishuDelivery";
import {
  deliveryStatus,
  deliveryByOperation,
  deliveryById,
  retryDelivery,
  verifyDeliveryPermissions,
  publishToFeishu,
  preflightFeishuPublish,
  feishuStatus,
  feishuGroups,
  feishuContacts,
  type Delivery,
} from "@/lib/feishu";
import { apiJson } from "@/lib/api";
import * as connectorPlugins from "@/lib/connectorPlugins";
const identity = vi.hoisted(() => ({ owner: "owner", listeners: [] as Array<(state: { user: { id: string } }) => void> }));
const changeOwner = (owner: string) => { identity.owner = owner; identity.listeners.forEach(listener => listener({ user: { id: owner } })); };

vi.mock("@/lib/feishu", () => ({
  deliveryStatus: vi.fn(),
  deliveryByOperation: vi.fn(),
  deliveryById: vi.fn(),
  retryDelivery: vi.fn(),
  verifyDeliveryPermissions: vi.fn(),
  publishToFeishu: vi.fn(),
  preflightFeishuPublish: vi.fn(),
  feishuStatus: vi.fn(),
  feishuGroups: vi.fn(),
  feishuContacts: vi.fn(),
  contactsValid: (items: { name?: string; expiresAt?: number }[]) => items.every(item => !!item.name && (item.expiresAt || 0) > Date.now()),
  contactRecipients: (items: { open_id: string; selection_token: string }[]) => items.map(({ open_id, selection_token }) => ({ open_id, selection_token })),
  openExternal: vi.fn(),
  recoverDeliveryDocument: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
vi.mock("@/stores/authStore", () => ({ useAuthStore: Object.assign((selector: (state: { user: { id: string } }) => unknown) => selector({ user: { id: identity.owner } }), { getState: () => ({ user: { id: identity.owner } }), subscribe: (listener: (state: { user: { id: string } }) => void) => { identity.listeners.push(listener); return () => {}; } }) }));
const createLabel = "创建并通知";
const retryLabel = "从失败步骤恢复，不重发成功通知";
const partial: Delivery = {
  id: "delivery-a",
  status: "failed",
  phase: "partial_success",
  document_url: "https://company.feishu.cn/docx/doc",
  error: "群未送达",
  recipients: {
    ou_a: { name: "本人", status: "sent" },
    oc_group: { name: "项目群", status: "failed", error: "群权限不足" },
  },
};
const completed: Delivery = {
  ...partial,
  status: "completed",
  phase: "completed",
  error: "",
  recipients: {
    ...partial.recipients,
    oc_group: { name: "项目群", status: "sent" },
  },
};

beforeEach(() => {
  changeOwner("owner");
  localStorage.clear();
  vi.resetAllMocks();
  vi.mocked(preflightFeishuPublish).mockResolvedValue(() => {});
  localStorage.setItem("vinote:connector-plugins:v1:owner", JSON.stringify({ version: 1, feishu: { installed: true, enabled: true } }));
  vi.mocked(deliveryStatus).mockResolvedValue(null);
  vi.mocked(feishuStatus).mockResolvedValue({
    publish_receipt_protocol: 1,
    recipient_access_protocol: 1,
    configured: true,
    connected: true,
    expired: false,
    name: "测试账号",
    notify_self: true,
    groups: [],
    auto_publish: false,
    destination: "personal",
    destination_config: { kind: "personal" },
  });
  vi.mocked(feishuGroups).mockResolvedValue([]);
  vi.mocked(apiJson).mockResolvedValue({
    kind: "personal",
    can_create: true,
    can_attempt_create: true,
    path: ["个人云文档"],
    path_complete: true,
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

async function enableContacts() {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, contact_selection_protocol: 1, capabilities: { contact_search: true } });
}
const candidate = (id: string) => ({ open_id: id, name: '同名联系人', selection_token: `proof-${id}`, expiresAt: Date.now() + 900000 });

it('reads connection and group failures independently in place without replacing selections', async () => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockRejectedValueOnce(new Error('连接读取失败')).mockResolvedValue({ ...status, groups: ['oc_one'] });
  vi.mocked(feishuGroups).mockRejectedValueOnce(new Error('群读取失败')).mockResolvedValue([{ chat_id: 'oc_one', name: '原选择群' }]);
  openPanel();
  await screen.findByText('连接读取失败');
  await waitFor(() => expect(deliveryStatus).toHaveBeenCalledTimes(1));
  expect(screen.getByText('连接读取失败')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '重新读取飞书连接' }));
  await screen.findByText('群读取失败');
  fireEvent.click(screen.getByRole('button', { name: '重新读取通知群' }));
  await screen.findByRole('checkbox', { name: '原选择群' });
  expect(screen.getByRole('checkbox', { name: '原选择群' })).toBeChecked();
  fireEvent.click(screen.getByRole('checkbox', { name: '原选择群' }));
  fireEvent.click(screen.getByRole('button', { name: '刷新通知群' }));
  await waitFor(() => expect(feishuGroups).toHaveBeenCalledTimes(3));
  expect(screen.getByRole('checkbox', { name: '原选择群' })).not.toBeChecked();
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('blocks contact selection without protocol while preserving ordinary notification paths', async () => {
  openPanel();
  await screen.findByText(/尚未支持联系人选择/);
  await expandRecipients();
  expect(screen.getByRole('textbox', { name: '搜索联系人' })).toBeDisabled();
  expect(screen.getByRole('checkbox', { name: '发给本人' })).toBeEnabled();
  await verifyDestination();
  expect(screen.getByRole('button', { name: createLabel })).toBeEnabled();
  expect(feishuContacts).not.toHaveBeenCalled();
});

it('keeps paginated results and selection on failure, retries the same page, and freezes names only for UI', async () => {
  await enableContacts();
  vi.mocked(feishuContacts).mockResolvedValueOnce({ items: [candidate('ou_one')], has_more: true, page_token: 'next', selection_expires_in: 900 })
    .mockRejectedValueOnce(new Error('下一页读取失败'))
    .mockResolvedValueOnce({ items: [candidate('ou_two')], has_more: false, page_token: '', selection_expires_in: 900 });
  vi.mocked(publishToFeishu).mockRejectedValue(new Error('未知提交结果'));
  openPanel();
  await verifyDestination();
  fireEvent.change(screen.getByRole('textbox', { name: '搜索联系人' }), { target: { value: '同名' } });
  fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.click(await screen.findByRole('checkbox', { name: '同名联系人' }));
  fireEvent.click(screen.getByRole('button', { name: '读取下一页联系人' }));
  await screen.findByText('下一页读取失败');
  expect(screen.getByRole('checkbox', { name: '同名联系人' })).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: '重试联系人读取' }));
  await waitFor(() => expect(screen.getAllByRole('checkbox', { name: '同名联系人' })).toHaveLength(2));
  expect(feishuContacts).toHaveBeenLastCalledWith('同名', 'next');
  expect(document.body.textContent).not.toMatch(/ou_one|ou_two|proof-ou_/);
  fireEvent.click(screen.getAllByRole('checkbox', { name: '同名联系人' })[1]);
  fireEvent.click(screen.getAllByRole('button', { name: '移除 同名联系人' })[1]);
  expect(screen.getAllByRole('checkbox', { name: '同名联系人' })[1]).not.toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText('未知提交结果');
  expect(publishToFeishu).toHaveBeenCalledTimes(1);
  expect(vi.mocked(publishToFeishu).mock.calls[0][4]?.contacts).toEqual([{ open_id: 'ou_one', selection_token: 'proof-ou_one' }]);
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  expect(readPublishDraft('owner', 'meeting-a')).toMatchObject({ state: 'unknown', options: { contacts: [{ open_id: 'ou_one', name: '同名联系人', selection_token: 'proof-ou_one' }] } });
  vi.mocked(deliveryByOperation).mockRejectedValue(new Error('原回执不可用'));
  fireEvent.click(screen.getByRole('button', { name: '核验交付状态' }));
  await screen.findByText('原回执不可用');
  expect(screen.getByRole('button', { name: createLabel })).toBeDisabled();
  expect(publishToFeishu).toHaveBeenCalledTimes(1);
});

it('changing the search discards late results and an empty page with a cursor is not no matches', async () => {
  await enableContacts();
  let finish!: (value: Awaited<ReturnType<typeof feishuContacts>>) => void;
  vi.mocked(feishuContacts).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValueOnce({ items: [], has_more: true, page_token: 'next', selection_expires_in: 900 });
  openPanel(); await verifyDestination();
  const input = screen.getByRole('textbox', { name: '搜索联系人' });
  fireEvent.change(input, { target: { value: '旧查询' } }); fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.change(input, { target: { value: '新查询' } });
  await act(async () => finish({ items: [candidate('ou_old')], has_more: false, page_token: '', selection_expires_in: 900 }));
  expect(screen.queryByRole('checkbox', { name: '同名联系人' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  await screen.findByRole('button', { name: '读取下一页联系人' });
  expect(screen.queryByText('没有匹配的联系人。')).toBeNull();
});

it('rechecks contact protocol before freezing dispatch and keeps the draft editable on refusal', async () => {
  await enableContacts();
  vi.mocked(feishuContacts).mockResolvedValue({ items: [candidate('ou_one')], has_more: false, page_token: '', selection_expires_in: 900 });
  openPanel(); await verifyDestination();
  fireEvent.change(screen.getByRole('textbox', { name: '搜索联系人' }), { target: { value: '同名' } });
  fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.click(await screen.findByRole('checkbox', { name: '同名联系人' }));
  const status = await feishuStatus(); vi.mocked(feishuStatus).mockResolvedValue({ ...status, contact_selection_protocol: undefined });
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText(/尚未提交；原选择保留/);
  expect(publishToFeishu).not.toHaveBeenCalled();
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  expect(readPublishDraft('owner', 'meeting-a')?.state).toBe('draft');
  expect(screen.getByRole('button', { name: '移除 同名联系人' })).toBeEnabled();
});
function openPanel() {
  const view = render(
    <MemoryRouter>
      <FeishuDelivery noteId="meeting-a" title="会议" content="# 纪要" />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: "发布到飞书" }));
  return view;
}
async function expandRecipients() {
  const summary = screen.getByText(/^通知(?: ·|（可选）)/);
  const details = summary.closest('details')!;
  if (!details.open) fireEvent.click(summary);
  await waitFor(() => expect(details.open).toBe(true));
  await waitFor(() => expect(details.querySelector('fieldset')?.hidden).toBe(false));
}
async function verifyDestination() {
  await waitFor(() => expect(apiJson).toHaveBeenCalledWith("/api/feishu/destinations/check", {
    method: "POST", body: JSON.stringify({ kind: "personal" }),
  }));
  await waitFor(() => expect(screen.queryByText('正在核验文档位置…')).toBeNull());
  await expandRecipients();
}

it("retries an existing partial delivery instead of creating another document", async () => {
  vi.mocked(deliveryStatus).mockResolvedValue(partial);
  vi.mocked(retryDelivery).mockResolvedValue(completed);
  openPanel();
  await screen.findByText("本人 · 已发送");
  fireEvent.click(screen.getByRole("button", { name: retryLabel }));
  await screen.findByText("项目群 · 已发送");
  expect(retryDelivery).toHaveBeenCalledTimes(1);
  expect(retryDelivery).toHaveBeenCalledWith("delivery-a", undefined);
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('follows an old failed retry response using only GET of the original job until completion', async () => {
  vi.mocked(deliveryStatus).mockResolvedValue(partial);
  vi.mocked(retryDelivery).mockResolvedValue(partial);
  vi.mocked(deliveryById).mockResolvedValue(completed);
  openPanel();
  await screen.findByText('本人 · 已发送');
  expect(screen.getByText('所选联系人/群获得阅读权限并收到链接，不授予编辑权限；通知失败保留文档和权限。')).toBeInTheDocument();
  vi.useFakeTimers();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: retryLabel })));
  expect(screen.getByRole('button', { name: retryLabel })).toBeDisabled();
  await act(async () => vi.advanceTimersByTimeAsync(2500));
  expect(deliveryById).toHaveBeenCalledWith('delivery-a', expect.any(AbortSignal));
  expect(screen.getByText('项目群 · 已发送')).toBeInTheDocument();
  expect(retryDelivery).toHaveBeenCalledTimes(1);
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('bounds GET queries after an unknown retry response and retains the marker on reopen', async () => {
  vi.mocked(deliveryStatus).mockResolvedValue(partial);
  vi.mocked(retryDelivery).mockRejectedValue(new Error('重试响应未知'));
  vi.mocked(deliveryById).mockResolvedValue(partial);
  openPanel();
  await screen.findByText('本人 · 已发送');
  vi.useFakeTimers();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: retryLabel })));
  for (let index = 0; index < 12; index++) await act(async () => vi.advanceTimersByTimeAsync(2500));
  expect(deliveryById).toHaveBeenCalledTimes(12);
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(deliveryById).toHaveBeenCalledTimes(12);
  expect(screen.getByText(/重试结果尚未确认，请核验原任务/)).toBeInTheDocument();
  cleanup(); vi.useRealTimers();
  openPanel();
  await screen.findByText(/重试结果尚未确认，请核验原任务/);
  expect(screen.getByRole('button', { name: retryLabel })).toBeDisabled();
  expect(deliveryStatus).toHaveBeenCalledTimes(1);
  expect(retryDelivery).toHaveBeenCalledTimes(1);
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('keeps failed GETs from permitting another POST and offers read-only recovery', async () => {
  vi.mocked(deliveryStatus).mockResolvedValue(partial);
  vi.mocked(retryDelivery).mockResolvedValue(partial);
  vi.mocked(deliveryById).mockRejectedValue(new Error('原任务读取失败'));
  openPanel(); await screen.findByText('本人 · 已发送');
  vi.useFakeTimers();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: retryLabel })));
  await act(async () => vi.advanceTimersByTimeAsync(2500));
  expect(screen.getByRole('button', { name: retryLabel })).toBeDisabled();
  expect(screen.getByRole('button', { name: '查询原重试任务' })).toBeEnabled();
  expect(retryDelivery).toHaveBeenCalledTimes(1);
});

it('aborts a stalled GET after ten seconds and releases a following GET on unmount', async () => {
  vi.mocked(deliveryStatus).mockResolvedValue(partial);
  vi.mocked(retryDelivery).mockResolvedValue(partial);
  const signals: AbortSignal[] = [];
  vi.mocked(deliveryById).mockImplementation((_id, signal) => {
    signals.push(signal!);
    return new Promise((_resolve, reject) => signal!.addEventListener('abort', () => reject(new Error('原任务查询超时或已离开')), { once: true }));
  });
  openPanel(); await screen.findByText('本人 · 已发送');
  vi.useFakeTimers();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: retryLabel })));
  await act(async () => vi.advanceTimersByTimeAsync(2500));
  expect(signals[0].aborted).toBe(false);
  await act(async () => vi.advanceTimersByTimeAsync(10000));
  expect(signals[0].aborted).toBe(true);
  expect(screen.getByRole('button', { name: retryLabel })).toBeDisabled();
  await act(async () => vi.advanceTimersByTimeAsync(2500));
  expect(signals).toHaveLength(2);
  cleanup();
  expect(signals[1].aborted).toBe(true);
  expect(retryDelivery).toHaveBeenCalledTimes(1);
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it("requires both a successful status read and a verified destination before publication", async () => {
  let finish!: (value: null) => void;
  vi.mocked(deliveryStatus).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  openPanel();
  expect(screen.getByRole("button", { name: "创建文档" })).toBeDisabled();
  await act(async () => finish(null));
  await verifyDestination();
  await waitFor(() => expect(screen.getByRole("button", { name: createLabel })).toBeEnabled());
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it("keeps publication disabled when status cannot be read and allows retry", async () => {
  vi.mocked(deliveryStatus)
    .mockRejectedValueOnce(new Error("暂时断网"))
    .mockResolvedValueOnce(null);
  openPanel();
  await screen.findByText("暂时断网");
  await verifyDestination();
  expect(screen.getByRole("button", { name: createLabel })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "核验交付状态" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: createLabel })).toBeEnabled(),
  );
  expect(deliveryStatus).toHaveBeenCalledTimes(2);
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it("retries only the selected failed recipient and preserves the existing document", async () => {
  vi.mocked(deliveryStatus).mockResolvedValue(partial);
  vi.mocked(retryDelivery).mockResolvedValue(completed);
  openPanel();
  fireEvent.click(
    await screen.findByRole("button", { name: "仅重试此失败接收人" }),
  );
  await screen.findByText("项目群 · 已发送");
  expect(retryDelivery).toHaveBeenCalledTimes(1);
  expect(retryDelivery).toHaveBeenCalledWith("delivery-a", ["oc_group"]);
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it("does not offer resending an unknown recipient or recreate an unknown document", async () => {
  vi.mocked(deliveryStatus).mockResolvedValue({
    ...partial,
    phase: "unknown",
    recipients: {
      ou_a: partial.recipients.ou_a,
      oc_group: { name: "项目群", status: "unknown" },
    },
  });
  openPanel();
  await screen.findByText("项目群 · 发送结果未知，需外部核验");
  expect(
    screen.queryByRole("button", { name: "仅重试此失败接收人" }),
  ).toBeNull();
  expect(screen.getByRole("button", { name: retryLabel })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: createLabel }),
  ).toBeDisabled();
  expect(retryDelivery).not.toHaveBeenCalled();
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('blocks new publication on the currently deployed server without receipt protocol', async () => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, publish_receipt_protocol: undefined });
  openPanel();
  await screen.findByText(/飞书服务需要升级发布回执协议/);
  await verifyDestination();
  expect(screen.getByRole('button', { name: createLabel })).toBeDisabled();
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('rechecks capability immediately before POST when service changes after opening', async () => {
  openPanel();
  await verifyDestination();
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, publish_receipt_protocol: undefined });
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText(/尚未提交，原草稿保留/);
  expect(publishToFeishu).not.toHaveBeenCalled();
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  expect(readPublishDraft('owner', 'meeting-a')?.state).toBe('draft');
});

it('publishes the confirmed current content without depending on retired sync revisions', async () => {
  vi.mocked(publishToFeishu).mockImplementation(async (_key, _title, _content, _automatic, options) => ({
    ...completed,
    operation_id: options?.operation_id,
  }));
  render(<MemoryRouter><FeishuDelivery noteId="meeting-a" title="当前标题" content="当前正文" versionId="current-2" revisionId="2" /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: '发布到飞书' }));
  await verifyDestination();
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await waitFor(() => expect(publishToFeishu).toHaveBeenCalledTimes(1));
  expect(publishToFeishu).toHaveBeenCalledWith('publish:meeting-a', '当前标题', '当前正文', false,
    expect.objectContaining({ source_mode: 'local_snapshot' }), expect.objectContaining({ operationId: expect.any(String) }));
  const options = vi.mocked(publishToFeishu).mock.calls[0][4];
  expect(options?.version_id).toBeUndefined();
  expect(options?.revision_id).toBeUndefined();
});

it('reopening dispatched intent preserves frozen source/options and a 404 never falls back to latest', async () => {
  const { newPublishDraft, persistPublishDraft } = await import('@/lib/feishuPublishReceipt');
  const original = newPublishDraft('owner', 'meeting-a', { title: '原版本', content: '冻结原正文', versionId: 'v2', revisionId: '2' }, { destination_config: { kind: 'personal' }, permission_policy: 'private', notify_self: false, groups: [] });
  persistPublishDraft({ ...original, state: 'unknown' });
  vi.mocked(deliveryByOperation).mockRejectedValue(new Error('原回执接口404，等待升级'));
  openPanel();
  await screen.findByText('原回执接口404，等待升级');
  expect(screen.getByRole('button', { name: '创建文档' })).toBeDisabled();
  expect(deliveryStatus).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('发布内容与选择'));
  await expandRecipients();
  expect(screen.getByRole('checkbox', { name: '发给本人' })).not.toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: '核验交付状态' }));
  await waitFor(() => expect(deliveryByOperation).toHaveBeenCalledTimes(2));
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it.each([
  ['__vinote:current:r1', '此次发布固定正文 · 保存修订 1'],
  ['historical-v1', '此次发布固定历史版本 · 保存修订 1'],
])('labels restored %s as frozen r1 even when the current note has r2, without POST', async (versionId, label) => {
  const { newPublishDraft, persistPublishDraft, readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  const original = newPublishDraft('owner', 'meeting-a', { title: '原冻结标题', content: '冻结r1正文', versionId, revisionId: '1' }, { destination_config: { kind: 'personal' }, notify_self: false, groups: [] });
  persistPublishDraft(original);
  render(<MemoryRouter><FeishuDelivery noteId="meeting-a" title="r2新标题" content="desktop-marker-r2" versionId="__vinote:current:r2" revisionId="2" /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: '发布到飞书' }));
  await screen.findByText(label);
  expect(screen.getByText('原冻结标题')).toBeInTheDocument();
  expect(screen.queryByText(/最新已保存正文/)).not.toBeInTheDocument();
  expect(readPublishDraft('owner', 'meeting-a')?.snapshot.content).toBe('冻结r1正文');
  expect(publishToFeishu).not.toHaveBeenCalled();
});


it('returns through settings to the same saved route, reopens once and performs no POST', async () => {
  function Saved() {
    const location = useLocation();
    return <><output data-testid="saved-path">{location.pathname + location.search + location.hash}</output><FeishuDelivery noteId="saved" title="已保存" content="保存正文" /><Link to="/notes">返回列表</Link></>;
  }
  render(<MemoryRouter initialEntries={['/note/saved?returnTo=%2Fnotes%3Fquery%3Dmeeting#body']}><Routes>
    <Route path="/note/:id" element={<Saved />} />
    <Route path="/settings/feishu" element={<PageReturn to="/connections" label="返回插件" />} />
    <Route path="/notes" element={<Link to="/note/saved?returnTo=%2Fnotes%3Fquery%3Dmeeting#body">再次打开</Link>} />
  </Routes></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: /发布到飞书/ }));
  await screen.findByRole('button', { name: '管理飞书连接' });
  await waitFor(() => expect(screen.getByRole('button', { name: '管理飞书连接' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '管理飞书连接' }));
  fireEvent.click(await screen.findByRole('link', { name: '返回内容详情' }));
  await screen.findByRole('dialog');
  await waitFor(() => expect(screen.getByTestId('saved-path').textContent).toBe('/note/saved?returnTo=%2Fnotes%3Fquery%3Dmeeting#body'));
  expect(publishToFeishu).not.toHaveBeenCalled(); expect(retryDelivery).not.toHaveBeenCalled(); expect(apiJson).toHaveBeenCalledWith('/api/feishu/destinations/check', expect.any(Object));
});


it('unavailable grants do not imply missing scopes and retry is a status read', async () => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockClear().mockResolvedValueOnce({ ...status, connected: false, connection_state: 'service_unavailable', grant_state: 'unavailable', contact_selection_protocol: 1, capabilities: { folder: false, wiki: false, contact_search: false } }).mockResolvedValue(status);
  openPanel();
  const retry = await screen.findByRole('button', { name: '重新核验飞书连接' });
  expect(screen.getByText('联系人能力暂时无法核验。')).toBeInTheDocument();
  expect(screen.queryByText(/需连接或重新授权/)).toBeNull();
  expect(screen.queryByText(/尚未授予联系人/)).toBeNull();
  expect(screen.queryByText(/当前飞书应用尚未开放/)).toBeNull();
  fireEvent.click(retry);
  await waitFor(() => expect(feishuStatus).toHaveBeenCalledTimes(2));
  expect(publishToFeishu).not.toHaveBeenCalled();
  expect(retryDelivery).not.toHaveBeenCalled();
});

it('temporary verification blocks the exact failed group retry without replacing its receipt', async () => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, grant_state: 'unavailable' });
  vi.mocked(deliveryStatus).mockResolvedValue(partial);
  openPanel();
  const retry = await screen.findByRole('button', { name: '仅重试此失败接收人' });
  expect(retry).toBeDisabled();
  expect(screen.getByText(/项目群/)).toBeInTheDocument();
  fireEvent.click(retry);
  expect(retryDelivery).not.toHaveBeenCalled();
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it.each([false, true])('explicit inline activation reuses the linked account (installed=%s)', async installed => {
  localStorage.setItem('vinote:connector-plugins:v1:owner', JSON.stringify({ version: 1, feishu: { installed, enabled: false } }));
  openPanel();
  const enable = await screen.findByRole('button', { name: '启用飞书插件' });
  await verifyDestination();
  expect(screen.getByRole('button', { name: createLabel })).toBeDisabled();
  expect(JSON.parse(localStorage.getItem('vinote:connector-plugins:v1:owner')!).feishu.enabled).toBe(false);
  expect(publishToFeishu).not.toHaveBeenCalled();
  fireEvent.click(enable);
  await waitFor(() => expect(screen.getByRole('button', { name: createLabel })).toBeEnabled());
  expect(JSON.parse(localStorage.getItem('vinote:connector-plugins:v1:owner')!).feishu).toEqual({ installed: true, enabled: true });
  expect(screen.getByText('已连接 · 测试账号')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '启用飞书插件' })).toBeNull();
  expect(publishToFeishu).not.toHaveBeenCalled();
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  expect(readPublishDraft('owner', 'meeting-a')?.state).toBe('draft');
  vi.mocked(publishToFeishu).mockImplementationOnce(async (_key, _title, _body, _automatic, options) => ({ ...completed, operation_id: options?.operation_id }));
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByRole('button', { name: '打开飞书文档' });
  expect(publishToFeishu).toHaveBeenCalledTimes(1);
  expect(readPublishDraft('owner', 'meeting-a')?.state).toBe('acknowledged');
  expect(screen.getByText('本人 · 已发送')).toBeInTheDocument();
});
it('preflight plugin refusal leaves the same operation editable and a double click never overlaps', async () => {
  openPanel(); await verifyDestination();
  await waitFor(() => expect(screen.getByRole('button', { name: createLabel })).toBeEnabled());
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  const original = readPublishDraft('owner', 'meeting-a')!;
  vi.mocked(preflightFeishuPublish).mockRejectedValue(new Error('请先启用飞书插件'));
  const button = screen.getByRole('button', { name: createLabel });
  fireEvent.click(button); fireEvent.click(button);
  await screen.findByText('请先启用飞书插件');
  expect(preflightFeishuPublish).toHaveBeenCalledTimes(1);
  expect(publishToFeishu).not.toHaveBeenCalled();
  expect(readPublishDraft('owner', 'meeting-a')).toMatchObject({ state: 'draft', operationId: original.operationId });
  expect(screen.getByRole('checkbox', { name: '发给本人' })).toBeEnabled();
});

it('cancel and reopen preserve an unactivated draft without enabling the plugin', async () => {
  localStorage.removeItem('vinote:connector-plugins:v1:owner');
  openPanel();
  await screen.findByRole('button', { name: '启用飞书插件' });
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  await waitFor(() => expect(readPublishDraft('owner', 'meeting-a')?.state).toBe('draft'));
  const original = readPublishDraft('owner', 'meeting-a')!;
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getByRole('button', { name: '发布到飞书' }));
  await screen.findByRole('button', { name: '启用飞书插件' });
  expect(readPublishDraft('owner', 'meeting-a')).toMatchObject({ state: 'draft', operationId: original.operationId });
  expect(localStorage.getItem('vinote:connector-plugins:v1:owner')).toBeNull();
  expect(publishToFeishu).not.toHaveBeenCalled();
});
it('inline activation is guarded against double clicks and late account changes', async () => {
  let finish!: () => void;
  const save = vi.fn(async (_owner: string, _next: connectorPlugins.ConnectorPluginState, current: () => boolean) => {
    await new Promise<void>(resolve => { finish = resolve; });
    current();
    return { installed: true, enabled: true };
  });
  const read = vi.fn(async (_owner: string, current: () => boolean) => { current(); return { installed: false, enabled: false }; });
  vi.spyOn(connectorPlugins, 'createConnectorPluginStore').mockReturnValue({ read, save });
  const view = openPanel();
  const enable = await screen.findByRole('button', { name: '启用飞书插件' });
  fireEvent.click(enable); fireEvent.click(enable);
  expect(save).toHaveBeenCalledTimes(1);
  changeOwner('other');
  view.rerender(<MemoryRouter><FeishuDelivery noteId="meeting-a" title="会议" content="# 纪要" /></MemoryRouter>);
  await act(async () => finish());
  await screen.findByRole('button', { name: '启用飞书插件' });
  expect(screen.queryByText('发布面板已变化')).toBeNull();
  expect(save).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem('vinote:connector-plugins:v1:other')).toBeNull();
  expect(publishToFeishu).not.toHaveBeenCalled();
});
it('restores a live not_dispatched attempt but never replays a POST automatically', async () => {
  const { markPublishAttempt, readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  openPanel(); await verifyDestination();
  await waitFor(() => expect(screen.getByRole('button', { name: createLabel })).toBeEnabled());
  const operationId = readPublishDraft('owner', 'meeting-a')!.operationId;
  vi.mocked(publishToFeishu).mockImplementationOnce(async (_key, _title, _content, _automatic, _options, attempt) => {
    markPublishAttempt(attempt!, 'not_dispatched');
    throw new Error('插件已停用，尚未提交');
  });
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText('插件已停用，尚未提交');
  await waitFor(() => expect(screen.getByRole('button', { name: createLabel })).toBeEnabled());
  expect(readPublishDraft('owner', 'meeting-a')).toMatchObject({ state: 'draft', operationId });
  expect(publishToFeishu).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('checkbox', { name: '发给本人' })).toBeEnabled();
});

it('freezes explicit view-and-notify policy with selected contact identities', async () => {
  await enableContacts();
  vi.mocked(feishuContacts).mockResolvedValue({ items: [candidate('ou_one')], has_more: false, page_token: '', selection_expires_in: 900 });
  vi.mocked(publishToFeishu).mockRejectedValue(new Error('network unknown'));
  openPanel(); await verifyDestination();
  fireEvent.change(screen.getByRole('textbox', { name: '搜索联系人' }), { target: { value: '同名' } });
  fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.click(await screen.findByRole('checkbox', { name: '同名联系人' }));
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText('network unknown');
  expect(vi.mocked(publishToFeishu).mock.calls[0][4]).toMatchObject({ recipient_access_policy: 'grant_view_and_notify', contacts: [{ open_id: 'ou_one', selection_token: 'proof-ou_one' }] });
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  expect(readPublishDraft('owner', 'meeting-a')).toMatchObject({ state: 'unknown', options: { recipient_access_policy: 'grant_view_and_notify' } });
});
it('requires recipient access protocol for contact/group grants but not self-only publication', async () => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, recipient_access_protocol: undefined });
  vi.mocked(feishuGroups).mockResolvedValue([{ chat_id: 'oc_one', name: '通知群' }]);
  openPanel(); await verifyDestination();
  await waitFor(() => expect(screen.getByRole('button', { name: createLabel })).toBeEnabled());
  fireEvent.click(await screen.findByRole('checkbox', { name: '通知群' }));
  expect(screen.getByRole('button', { name: createLabel })).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: '通知群' }));
  expect(screen.getByRole('button', { name: createLabel })).toBeEnabled();
  vi.mocked(publishToFeishu).mockRejectedValue(new Error('self request unknown'));
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText('self request unknown');
  expect(vi.mocked(publishToFeishu).mock.calls[0][4]?.recipient_access_policy).toBeUndefined();
});
it('rechecks recipient access protocol before freezing a selected group grant', async () => {
  vi.mocked(feishuGroups).mockResolvedValue([{ chat_id: 'oc_one', name: '通知群' }]);
  openPanel(); await verifyDestination();
  fireEvent.click(await screen.findByRole('checkbox', { name: '通知群' }));
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, recipient_access_protocol: undefined });
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText(/尚未支持向所选联系人或群授予阅读权限/);
  expect(publishToFeishu).not.toHaveBeenCalled();
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  expect(readPublishDraft('owner', 'meeting-a')?.state).toBe('draft');
});
it.each(['permission_unknown', 'failed'])('unknown reading permission is queried, never sent through retry (%s)', async recipientStatus => {
  vi.mocked(deliveryStatus).mockResolvedValue({ ...partial, recipients: { ou_one: { name: '联系人', kind: 'contact', status: recipientStatus, reading_permission: { status: 'unknown' } } } });
  vi.mocked(verifyDeliveryPermissions).mockResolvedValue({ ...partial, recipients: { ou_one: { name: '联系人', kind: 'contact', status: 'permission_unknown', reading_permission: { status: 'unknown' } } } });
  openPanel();
  const verify = await screen.findByRole('button', { name: '核验阅读权限' });
  expect(screen.getByRole('button', { name: retryLabel })).toBeDisabled();
  expect(screen.queryByRole('button', { name: '仅重试此失败接收人' })).toBeNull();
  fireEvent.click(verify);
  await waitFor(() => expect(verifyDeliveryPermissions).toHaveBeenCalledWith('delivery-a'));
  expect(retryDelivery).not.toHaveBeenCalled();
  expect(publishToFeishu).not.toHaveBeenCalled();
});
it('querying a legacy frozen operation never backfills access policy', async () => {
  const { newPublishDraft, persistPublishDraft, readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  const draft = newPublishDraft('owner', 'meeting-a', { title: 'old', content: 'old body' }, { destination_config: { kind: 'personal' }, permission_policy: 'private', groups: ['oc_one'], notify_self: false });
  persistPublishDraft({ ...draft, state: 'unknown' });
  vi.mocked(deliveryByOperation).mockResolvedValue({ ...partial, operation_id: draft.operationId });
  openPanel();
  await screen.findByText('本人 · 已发送');
  expect(readPublishDraft('owner', 'meeting-a')?.options.recipient_access_policy).toBeUndefined();
  expect(publishToFeishu).not.toHaveBeenCalled();
});

const accessUnknown: Delivery = {
  ...partial, phase: 'permission_unknown', error_code: 'permission_unknown',
  recipient_access_policy: 'grant_view_and_notify', error: '',
  recipients: { ou_one: { name: '联系人甲', kind: 'contact', status: 'permission_unknown', reading_permission: { status: 'unknown' } } },
};
const accessVerified: Delivery = {
  ...accessUnknown, phase: 'partial_success', error_code: '',
  recipients: { ou_one: { name: '联系人甲', kind: 'contact', status: 'pending', reading_permission: { status: 'verified' } } },
};
it('default self notification names the linked person and leaves all recipient search collapsed', async () => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, name: '阳晓冰' });
  openPanel();
  await screen.findByText('已连接 · 阳晓冰');
  await waitFor(() => expect(screen.getByRole('button', { name: createLabel })).toBeEnabled());
  const summary = screen.getByText('通知 · 本人（阳晓冰）');
  expect(summary.closest('details')?.open).toBe(false);
  expect(screen.queryByRole('textbox', { name: '搜索联系人' })).toBeNull();
  expect(screen.queryByRole('button', { name: '搜索联系人' })).toBeNull();
  expect(feishuGroups).not.toHaveBeenCalled();
  expect(feishuContacts).not.toHaveBeenCalled();
  await expandRecipients();
  expect(screen.getByRole('checkbox', { name: '发给本人' })).toBeChecked();
  expect(publishToFeishu).not.toHaveBeenCalled();
});
it('collapsed summary names groups and contacts without IDs or proof tokens', async () => {
  await enableContacts();
  vi.mocked(feishuGroups).mockResolvedValue([{ chat_id: 'oc_private_group_id', name: '研发群' }]);
  vi.mocked(feishuContacts).mockResolvedValue({ items: [{ ...candidate('ou_private_person_id'), name: '小李' }], has_more: false, page_token: '', selection_expires_in: 900 });
  openPanel(); await verifyDestination();
  fireEvent.click(await screen.findByRole('checkbox', { name: '研发群' }));
  fireEvent.change(screen.getByRole('textbox', { name: '搜索联系人' }), { target: { value: '小李' } });
  fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.click(await screen.findByRole('checkbox', { name: '小李' }));
  const summary = screen.getByText('通知 · 本人（测试账号）、研发群、小李');
  fireEvent.click(summary);
  await waitFor(() => expect(summary.closest('details')?.open).toBe(false));
  expect(document.body.textContent).not.toMatch(/oc_private_group_id|ou_private_person_id|proof-ou_/);
});
it('permission verification is separate from explicit continuation and never auto-sends', async () => {
  vi.mocked(deliveryStatus).mockResolvedValue(accessUnknown);
  vi.mocked(verifyDeliveryPermissions).mockResolvedValue(accessVerified);
  vi.mocked(retryDelivery).mockResolvedValue({ ...completed, recipients: { ou_one: { name: '联系人甲', status: 'sent' } } });
  openPanel();
  fireEvent.click(await screen.findByRole('button', { name: '核验阅读权限' }));
  const proceed = await screen.findByRole('button', { name: '继续通知' });
  expect(proceed).toBeEnabled();
  expect(verifyDeliveryPermissions).toHaveBeenCalledTimes(1);
  expect(verifyDeliveryPermissions).toHaveBeenCalledWith('delivery-a');
  expect(retryDelivery).not.toHaveBeenCalled();
  expect(publishToFeishu).not.toHaveBeenCalled();
  expect(screen.getByText('阅读权限已核验，通知尚未发送。点击“继续通知”将发送文档链接。')).toBeInTheDocument();
  fireEvent.click(proceed);
  await screen.findByText('联系人甲 · 已发送');
  expect(retryDelivery).toHaveBeenCalledTimes(1);
  expect(retryDelivery).toHaveBeenCalledWith('delivery-a', undefined);
});
it.each(['granting', 'unknown'] as const)('allows permission verification alongside message unknown (%s) but never continuation', async status => {
  const original: Delivery = { ...accessUnknown, phase: 'unknown', recipients: {
    ou_one: { name: '联系人甲', status: 'unknown', reading_permission: { status } },
  } };
  vi.mocked(deliveryStatus).mockResolvedValue(original);
  vi.mocked(verifyDeliveryPermissions).mockResolvedValue({ ...original, recipients: {
    ou_one: { ...original.recipients.ou_one, reading_permission: { status: 'verified' } },
  } });
  openPanel();
  const verify = await screen.findByRole('button', { name: '核验阅读权限' });
  expect(screen.getByText('联系人甲 · 发送结果未知，需外部核验')).toBeInTheDocument();
  fireEvent.click(verify);
  await waitFor(() => expect(verifyDeliveryPermissions).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.queryByRole('button', { name: '核验阅读权限' })).toBeNull());
  expect(screen.queryByRole('button', { name: '继续通知' })).toBeNull();
  expect(screen.getByRole('button', { name: retryLabel })).toBeDisabled();
  expect(retryDelivery).not.toHaveBeenCalled();
});
it('failed verification stays recoverable and a double click performs one check', async () => {
  vi.mocked(deliveryStatus).mockResolvedValue(accessUnknown);
  let reject!: (cause: Error) => void;
  vi.mocked(verifyDeliveryPermissions).mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
  openPanel();
  const verify = await screen.findByRole('button', { name: '核验阅读权限' });
  fireEvent.click(verify); fireEvent.click(verify);
  expect(verifyDeliveryPermissions).toHaveBeenCalledTimes(1);
  await act(async () => reject(new Error('权限核验暂不可用')));
  await screen.findByText('权限核验暂不可用');
  expect(screen.getByRole('button', { name: '核验阅读权限' })).toBeEnabled();
  expect(screen.getByRole('button', { name: retryLabel })).toBeDisabled();
  expect(retryDelivery).not.toHaveBeenCalled();
});
it('late permission results cannot replace a new owner or operation', async () => {
  vi.mocked(deliveryStatus).mockResolvedValue(accessUnknown);
  let finish!: (job: Delivery) => void;
  vi.mocked(verifyDeliveryPermissions).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const view = openPanel();
  fireEvent.click(await screen.findByRole('button', { name: '核验阅读权限' }));
  changeOwner('other');
  vi.mocked(deliveryStatus).mockResolvedValue(null);
  view.rerender(<MemoryRouter><FeishuDelivery noteId="meeting-b" title="另一正文" content="内容" /></MemoryRouter>);
  await act(async () => finish(accessVerified));
  expect(screen.queryByRole('button', { name: '继续通知' })).toBeNull();
  expect(screen.queryByText('联系人甲 · 待发送')).toBeNull();
  expect(retryDelivery).not.toHaveBeenCalled();
});
it('wrong-job verification response cannot unlock notification retries', async () => {
  vi.mocked(deliveryStatus).mockResolvedValue(accessUnknown);
  vi.mocked(verifyDeliveryPermissions).mockResolvedValue({ ...accessVerified, id: 'another-job' });
  openPanel(); fireEvent.click(await screen.findByRole('button', { name: '核验阅读权限' }));
  await screen.findByText('权限核验回执不属于原发布操作');
  expect(screen.getByRole('button', { name: retryLabel })).toBeDisabled();
  expect(screen.queryByRole('button', { name: '继续通知' })).toBeNull();
});

it('uses the verified connection scope for real picker favorites and recent places across reopening', async () => {
  const status = await feishuStatus(), binding = 'a'.repeat(64);
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: binding });
  const view = openPanel(); await verifyDestination();
  fireEvent.click(screen.getByRole('button', { name: '选择文档位置' }));
  fireEvent.click(await screen.findByRole('button', { name: '收藏位置' }));
  fireEvent.click(screen.getByRole('button', { name: '确认位置并核验' }));
  await waitFor(() => expect(screen.queryByRole('button', { name: '确认位置并核验' })).toBeNull());
  const key = `vinote:feishu-destinations:owner:${encodeURIComponent(window.location.origin)}:${binding}`;
  expect(JSON.parse(localStorage.getItem(key)!)).toMatchObject({
    favorites: [{ target: { kind: 'personal' } }], recent: [{ target: { kind: 'personal' } }],
  });
  view.unmount(); openPanel(); await verifyDestination();
  fireEvent.click(screen.getByRole('button', { name: '选择文档位置' }));
  expect(within(await screen.findByRole('region', { name: '收藏位置' })).getByRole('button', { name: '个人云文档' })).toBeEnabled();
  expect(screen.getByRole('region', { name: '最近使用' })).toBeInTheDocument();
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it.each([undefined, '', 'unverified-binding'])('keeps shortcuts disabled without a verified binding: %s', async binding => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: binding });
  openPanel(); await verifyDestination();
  fireEvent.click(screen.getByRole('button', { name: '选择文档位置' }));
  expect(await screen.findByText('连接身份尚未核验，暂不读取或保存最近与收藏位置。')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '收藏位置' })).toBeDisabled();
  expect(Object.keys(localStorage).filter(key => key.startsWith('vinote:feishu-destinations:'))).toEqual([]);
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('clears unsubmitted selections on a pre-submit connection change and rejects the old late group response', async () => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockReset().mockResolvedValueOnce({ ...status, connection_binding_hash: 'a'.repeat(64), groups: ['oc_old'] })
    .mockResolvedValue({ ...status, connection_binding_hash: 'b'.repeat(64) });
  let finish!: (value: Awaited<ReturnType<typeof feishuGroups>>) => void;
  vi.mocked(feishuGroups).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  openPanel(); await verifyDestination();
  await waitFor(() => expect(feishuGroups).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText('飞书账号或连接已变化，请重新核验并确认；原交付回执保留。');
  await act(async () => finish([{ chat_id: 'oc_old', name: '旧连接迟到群' }]));
  await expandRecipients();
  expect(screen.queryByText('旧连接迟到群')).toBeNull();
  expect(screen.getByRole('checkbox', { name: '发给本人' })).not.toBeChecked();
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  expect(readPublishDraft('owner', 'meeting-a')).toMatchObject({ state: 'draft', connectionBindingHash: 'b'.repeat(64), options: {
    destination_config: { kind: 'personal' }, groups: [], notify_self: false,
  } });
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('discards a contact search response from the previous connection', async () => {
  await enableContacts(); const status = await feishuStatus();
  vi.mocked(feishuStatus).mockReset().mockResolvedValueOnce({ ...status, connection_binding_hash: 'a'.repeat(64) })
    .mockResolvedValue({ ...status, connection_binding_hash: 'b'.repeat(64) });
  let finish!: (value: Awaited<ReturnType<typeof feishuContacts>>) => void;
  vi.mocked(feishuContacts).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  openPanel(); await verifyDestination();
  fireEvent.change(screen.getByRole('textbox', { name: '搜索联系人' }), { target: { value: '旧查询' } });
  fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  await waitFor(() => expect(feishuContacts).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText('飞书账号或连接已变化，请重新核验并确认；原交付回执保留。');
  await act(async () => finish({ items: [{ ...candidate('ou_old'), name: '旧连接迟到联系人' }], has_more: false, page_token: '', selection_expires_in: 900 }));
  await expandRecipients();
  expect(screen.queryByText('旧连接迟到联系人')).toBeNull();
  expect(screen.getByRole('textbox', { name: '搜索联系人' })).toHaveValue('');
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('preserves the frozen body but resets a restored unsubmitted draft from another connection', async () => {
  const { newPublishDraft, persistPublishDraft, readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  const original = { ...newPublishDraft('owner', 'meeting-a', { title: '原草稿', content: '原正文' }, {
    destination_config: { kind: 'folder' as const, folder_token: 'old-folder' }, permission_policy: 'inherit' as const,
    notify_self: true, groups: ['oc_old'],
  }), connectionBindingHash: 'a'.repeat(64) };
  persistPublishDraft(original);
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: 'b'.repeat(64) });
  openPanel();
  await screen.findByText('飞书连接已变化或原草稿未绑定当前连接，已清除未提交的位置与通知选择；请重新核验后确认。');
  await waitFor(() => expect(readPublishDraft('owner', 'meeting-a')).toMatchObject({
    state: 'draft', connectionBindingHash: 'b'.repeat(64), snapshot: original.snapshot,
    options: { destination_config: { kind: 'personal' }, groups: [], notify_self: false },
  }));
  expect(readPublishDraft('owner', 'meeting-a')?.operationId).not.toBe(original.operationId);
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it.each(['unknown', 'acknowledged'] as const)('keeps the exact historical %s receipt unchanged when another verified connection is loaded', async state => {
  const { newPublishDraft, persistPublishDraft } = await import('@/lib/feishuPublishReceipt');
  const original = { ...newPublishDraft('owner', 'meeting-a', { title: '原草稿', content: '原正文' }, {
    destination_config: { kind: 'personal' as const }, permission_policy: 'private' as const,
    notify_self: true, groups: [],
  }), state, connectionBindingHash: 'a'.repeat(64) };
  persistPublishDraft(original);
  const before = JSON.stringify({ ...localStorage });
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: 'b'.repeat(64) });
  vi.mocked(deliveryByOperation).mockRejectedValue(new Error('原回执待核验'));
  openPanel(); await screen.findByText('原回执待核验');
  expect(JSON.stringify({ ...localStorage })).toBe(before);
  expect(deliveryByOperation).toHaveBeenCalledWith(original.operationId);
  expect(publishToFeishu).not.toHaveBeenCalled();
  expect(retryDelivery).not.toHaveBeenCalled();
});

it('preserves a bound draft through temporary identity verification unavailability and recovers the same cache scope', async () => {
  const status = await feishuStatus(), binding = 'a'.repeat(64);
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: binding });
  openPanel(); await verifyDestination();
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  const before = readPublishDraft('owner', 'meeting-a');
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connected: false, connection_state: 'service_unavailable', connection_binding_hash: undefined });
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  const reconnect = await screen.findByRole('button', { name: '重新核验飞书连接' });
  expect(readPublishDraft('owner', 'meeting-a')).toEqual(before);
  expect(screen.queryByText(/已清除未提交的位置与通知选择/)).toBeNull();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: binding });
  fireEvent.click(reconnect);
  await waitFor(() => expect(screen.queryByRole('button', { name: '重新核验飞书连接' })).toBeNull());
  expect(readPublishDraft('owner', 'meeting-a')).toEqual(before);
  fireEvent.click(screen.getByRole('button', { name: '选择文档位置' }));
  expect(await screen.findByRole('button', { name: '收藏位置' })).toBeEnabled();
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('keeps the cache hash out of a real submission payload and never repeats an ambiguous POST', async () => {
  const status = await feishuStatus(), binding = 'a'.repeat(64);
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: binding });
  vi.mocked(publishToFeishu).mockRejectedValue(new Error('提交结果未知'));
  openPanel(); await verifyDestination();
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText('提交结果未知');
  expect(publishToFeishu).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(vi.mocked(publishToFeishu).mock.calls[0])).not.toContain(binding);
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  expect(readPublishDraft('owner', 'meeting-a')).toMatchObject({ state: 'unknown', connectionBindingHash: binding });
  expect(screen.getByRole('button', { name: createLabel })).toBeDisabled();
});

it.each([undefined, '', 'invalid-proof'])('invalidates unsubmitted recipients immediately when a verified binding is lost (%s)', async missing => {
  const status = await feishuStatus(), binding = 'a'.repeat(64);
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: binding, groups: ['oc_old'] });
  vi.mocked(feishuGroups).mockResolvedValue([{ chat_id: 'oc_old', name: '旧连接群' }]);
  openPanel(); await verifyDestination();
  await screen.findByRole('checkbox', { name: '旧连接群' });
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  const before = readPublishDraft('owner', 'meeting-a')!;
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: missing });
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText('飞书账号或连接已变化，请重新核验并确认；原交付回执保留。');
  await waitFor(() => expect(readPublishDraft('owner', 'meeting-a')).toMatchObject({
    state: 'draft', connectionBindingHash: binding, snapshot: before.snapshot,
    options: { groups: [], notify_self: false, destination_config: { kind: 'personal' } },
  }));
  expect(screen.getByRole('button', { name: '创建文档' })).toBeDisabled();
  await expandRecipients();
  expect(screen.getByRole('checkbox', { name: '发给本人' })).toBeDisabled();
  expect(screen.getByRole('checkbox', { name: '发给本人' })).not.toBeChecked();
  expect(screen.queryByRole('checkbox', { name: '旧连接群' })).toBeNull();
  expect(preflightFeishuPublish).not.toHaveBeenCalled();
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it.each(['a', 'b'])('returning from a binding gap to %s requires fresh confirmation and never revives a late group result', async returning => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: 'a'.repeat(64), groups: ['oc_old'] });
  let finish!: (value: Awaited<ReturnType<typeof feishuGroups>>) => void;
  vi.mocked(feishuGroups).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  openPanel(); await verifyDestination();
  await waitFor(() => expect(feishuGroups).toHaveBeenCalledTimes(1));
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: undefined });
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  const reconnect = await screen.findByRole('button', { name: '重新核验飞书连接' });
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: returning.repeat(64), groups: ['oc_old'] });
  fireEvent.click(reconnect);
  await waitFor(() => expect(screen.queryByRole('button', { name: '重新核验飞书连接' })).toBeNull());
  await act(async () => finish([{ chat_id: 'oc_old', name: '回环后迟到旧群' }]));
  await verifyDestination();
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  expect(readPublishDraft('owner', 'meeting-a')).toMatchObject({ connectionBindingHash: returning.repeat(64), options: { groups: [], notify_self: false } });
  expect(screen.queryByRole('checkbox', { name: '回环后迟到旧群' })).toBeNull();
  expect(screen.getByRole('checkbox', { name: '发给本人' })).not.toBeChecked();
  expect(publishToFeishu).not.toHaveBeenCalled();
  vi.mocked(publishToFeishu).mockRejectedValue(new Error('新的明确提交结果未知'));
  fireEvent.click(screen.getByRole('button', { name: '创建文档' }));
  await screen.findByText('新的明确提交结果未知');
  expect(publishToFeishu).toHaveBeenCalledTimes(1);
  expect(vi.mocked(publishToFeishu).mock.calls[0][4]).toMatchObject({ groups: [], notify_self: false });
});

it.each([false, true])('a binding interruption invalidates old contact searches even after A returns (typed outage=%s)', async unavailable => {
  await enableContacts(); const status = await feishuStatus(), binding = 'a'.repeat(64);
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: binding });
  let finish!: (value: Awaited<ReturnType<typeof feishuContacts>>) => void;
  vi.mocked(feishuContacts).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  openPanel(); await verifyDestination();
  fireEvent.change(screen.getByRole('textbox', { name: '搜索联系人' }), { target: { value: '旧搜索' } });
  fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  await waitFor(() => expect(feishuContacts).toHaveBeenCalledTimes(1));
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: undefined,
    ...(unavailable ? { connected: false, connection_state: 'service_unavailable' } : {}) });
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  const reconnect = await screen.findByRole('button', { name: '重新核验飞书连接' });
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: binding });
  fireEvent.click(reconnect);
  await waitFor(() => expect(screen.queryByRole('button', { name: '重新核验飞书连接' })).toBeNull());
  await act(async () => finish({ items: [{ ...candidate('ou_old'), name: '回环后旧联系人' }], has_more: false, page_token: '', selection_expires_in: 900 }));
  await expandRecipients();
  expect(screen.queryByRole('checkbox', { name: '回环后旧联系人' })).toBeNull();
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('a typed outage preserves draft choices but cannot accept a pending old group result after recovery', async () => {
  const status = await feishuStatus(), binding = 'a'.repeat(64);
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: binding, groups: ['oc_old'] });
  let finish!: (value: Awaited<ReturnType<typeof feishuGroups>>) => void;
  vi.mocked(feishuGroups).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValue([{ chat_id: 'oc_current', name: '恢复后重新读取群' }]);
  openPanel(); await verifyDestination();
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  const before = readPublishDraft('owner', 'meeting-a');
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connected: false, connection_state: 'service_unavailable', connection_binding_hash: undefined });
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  const reconnect = await screen.findByRole('button', { name: '重新核验飞书连接' });
  expect(readPublishDraft('owner', 'meeting-a')).toEqual(before);
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: binding });
  fireEvent.click(reconnect);
  await screen.findByRole('checkbox', { name: '恢复后重新读取群' });
  await act(async () => finish([{ chat_id: 'oc_old', name: '暂停前迟到群' }]));
  expect(screen.queryByRole('checkbox', { name: '暂停前迟到群' })).toBeNull();
  expect(readPublishDraft('owner', 'meeting-a')).toEqual(before);
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('a lost binding survives unmount without degrading to initial legacy capability', async () => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: 'a'.repeat(64), groups: ['oc_old'] });
  const view = openPanel(); await verifyDestination();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: undefined });
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByRole('button', { name: '重新核验飞书连接' });
  view.unmount(); openPanel();
  await screen.findByRole('button', { name: '重新核验飞书连接' });
  expect(screen.getByRole('button', { name: '创建文档' })).toBeDisabled();
  expect(publishToFeishu).not.toHaveBeenCalled();
});

it('initial legacy status still permits one explicitly confirmed manual publication without inventing a binding', async () => {
  vi.mocked(publishToFeishu).mockRejectedValue(new Error('旧协议明确提交结果未知'));
  openPanel(); await verifyDestination();
  fireEvent.click(screen.getByRole('button', { name: createLabel }));
  await screen.findByText('旧协议明确提交结果未知');
  expect(publishToFeishu).toHaveBeenCalledTimes(1);
  const { readPublishDraft } = await import('@/lib/feishuPublishReceipt');
  expect(readPublishDraft('owner', 'meeting-a')).not.toHaveProperty('connectionBindingHash');
});

it('an account A-B-A transition cannot accept the original A group request', async () => {
  const status = await feishuStatus();
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, connection_binding_hash: 'a'.repeat(64), groups: ['oc_old'] });
  let finish!: (value: Awaited<ReturnType<typeof feishuGroups>>) => void;
  vi.mocked(feishuGroups).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue([]);
  const view = openPanel(); await verifyDestination();
  await waitFor(() => expect(feishuGroups).toHaveBeenCalledTimes(1));
  localStorage.setItem('vinote:connector-plugins:v1:other', JSON.stringify({ version: 1, feishu: { installed: true, enabled: true } }));
  changeOwner('other');
  view.rerender(<MemoryRouter><FeishuDelivery noteId="meeting-a" title="另一个账号" content="另一正文" /></MemoryRouter>);
  await waitFor(() => expect(deliveryStatus).toHaveBeenCalledTimes(2));
  changeOwner('owner');
  view.rerender(<MemoryRouter><FeishuDelivery noteId="meeting-a" title="会议" content="# 纪要" /></MemoryRouter>);
  await waitFor(() => expect(deliveryStatus).toHaveBeenCalledTimes(3));
  await act(async () => finish([{ chat_id: 'oc_old', name: '账号回环迟到群' }]));
  expect(screen.queryByRole('checkbox', { name: '账号回环迟到群' })).toBeNull();
  expect(publishToFeishu).not.toHaveBeenCalled();
  expect(retryDelivery).not.toHaveBeenCalled();
});

it.each(['failed', 'unknown'])('keeps the old grouping %s receipt and offers no new-publication escape', async phase => {
  const { newPublishDraft, persistPublishDraft } = await import('@/lib/feishuPublishReceipt');
  const draft = newPublishDraft('owner', 'meeting-a', { title: '会议', content: '# 纪要' }, {
    destination_config: { kind: 'personal' }, permission_policy: 'private', notify_self: true, groups: [],
  });
  persistPublishDraft({ ...draft, state: 'acknowledged', jobId: 'original-unwritten' });
  const originalKey = `vinote:owner:feishu-publish:meeting-a:${draft.operationId}`;
  const originalReceipt = localStorage.getItem(originalKey);
  vi.mocked(deliveryById).mockResolvedValue({ id: 'original-unwritten', status: 'failed', phase,
    document_url: '', error: '原会议来源未核验', error_code: 'meeting_source_unverified', recipients: {} });
  openPanel();
  await screen.findByText(/关闭归组设置或另建操作不会恢复此记录/);
  expect(screen.queryByRole('button', { name: retryLabel })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '准备新的发布草稿' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: createLabel })).toBeDisabled();
  expect(publishToFeishu).not.toHaveBeenCalled();
  expect(retryDelivery).not.toHaveBeenCalled();
  expect(localStorage.getItem(originalKey)).toBe(originalReceipt);
});
