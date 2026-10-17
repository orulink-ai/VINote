import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FeishuSettings } from "./FeishuSettings";
import { feishuGroups, feishuStatus } from "@/lib/feishu";
import { apiJson } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";

vi.mock("@/lib/feishu", () => ({
  feishuStatus: vi.fn(),
  feishuGroups: vi.fn(async () => []),
  openExternal: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ apiJson: vi.fn() }));
// These tests exercise account/preferences/group reads. Application credential
// management has its own component and must not consume preference-response mocks.
vi.mock('@/components/Settings/FeishuApplicationSetup', () => ({ FeishuApplicationSetup: () => null }));
const status = {
  configured: true,
  connected: true,
  expired: false,
  name: "测试账号",
  notify_self: true,
  groups: [],
  auto_publish: false,
  destination: "personal" as const,
  destination_config: { kind: "personal" as const },
  permission_policy: "private" as const,
  capabilities: { background_delivery: false },
};
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  useAuthStore.setState({
    user: { id: "draft-owner", email: "owner@example.invalid" },
  });
  vi.mocked(feishuStatus).mockResolvedValue(status);
  vi.mocked(feishuGroups).mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  sessionStorage.clear();
});

it('does not claim an empty group list during refresh or allow duplicate reads, and keeps selections', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...status, groups: ['existing-group'] });
  let finish!: (value: []) => void;
  vi.mocked(feishuGroups).mockResolvedValueOnce([]).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  render(<MemoryRouter><FeishuSettings /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole('button', { name: '选择群' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '选择群' }));
  await screen.findByText('没有可用群。请将机器人加入目标群，再刷新。');
  fireEvent.click(screen.getByRole('button', { name: '刷新群列表' }));
  expect(screen.getByRole('button', { name: '正在刷新…' })).toBeDisabled();
  expect(screen.queryByText('没有可用群。请将机器人加入目标群，再刷新。')).toBeNull();
  expect(screen.getByText('正在读取群列表，已选群继续保留…')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '正在刷新…' }));
  expect(feishuGroups).toHaveBeenCalledTimes(2);
  await act(async () => finish([]));
  expect(screen.getByRole('button', { name: '刷新群列表' })).toBeEnabled();
  expect(screen.getByText('没有可用群。请将机器人加入目标群，再刷新。')).toBeVisible();
  expect(apiJson).not.toHaveBeenCalled();
  expect(sessionStorage.getItem('vinote:feishu-preferences:draft-owner')).toBeNull();
});

it("ignores a late response from the previous account", async () => {
  let finishOld!: (value: typeof status) => void;
  vi.mocked(feishuStatus).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishOld = resolve;
      }),
  );
  render(
    <MemoryRouter>
      <FeishuSettings />
    </MemoryRouter>,
  );
  act(() =>
    useAuthStore.setState({
      user: { id: "next-owner", email: "next@example.invalid" },
    }),
  );
  await screen.findByText("测试账号");
  await act(async () => finishOld({ ...status, name: "旧账号" }));
  expect(screen.queryByText("旧账号")).toBeNull();
  expect(screen.getByText("测试账号")).toBeVisible();
});

it("retains failed settings across page changes and removes the draft only after a successful save", async () => {
  const checked = {
    kind: "personal",
    can_attempt_create: true,
    can_create: true,
    path: ["个人云文档"],
    path_complete: true,
  };
  vi.mocked(apiJson)
    .mockResolvedValueOnce(checked)
    .mockRejectedValueOnce(new Error("网络暂不可用"));
  const view = render(
    <MemoryRouter>
      <FeishuSettings />
    </MemoryRouter>,
  );
  const notify = await screen.findByRole("checkbox", { name: "发给我本人" });
  await waitFor(() => expect(notify).toBeEnabled());
  expect(screen.getByRole("switch", { name: "自动交付新纪要" })).toBeDisabled();
  fireEvent.click(notify);
  expect(screen.getByRole("button", { name: "保存设置" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "核验位置与权限" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "保存设置" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "保存设置" }));
  await screen.findByRole("button", { name: "重试保存" });
  expect(
    JSON.parse(sessionStorage.getItem("vinote:feishu-preferences:draft-owner")!)
      .notify_self,
  ).toBe(false);
  view.unmount();
  render(
    <MemoryRouter>
      <FeishuSettings />
    </MemoryRouter>,
  );
  const restored = await screen.findByRole("checkbox", { name: "发给我本人" });
  await waitFor(() => expect(restored).not.toBeChecked());
  await waitFor(() => expect(restored).toBeEnabled());
  vi.mocked(apiJson)
    .mockResolvedValueOnce(checked)
    .mockResolvedValueOnce({ ...status, notify_self: false });
  fireEvent.click(screen.getByRole("button", { name: "核验位置与权限" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "保存设置" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "保存设置" }));
  await waitFor(() =>
    expect(
      sessionStorage.getItem("vinote:feishu-preferences:draft-owner"),
    ).toBeNull(),
  );
  expect(apiJson).toHaveBeenLastCalledWith(
    "/api/feishu/preferences",
    expect.objectContaining({
      body: JSON.stringify({
        notify_self: false,
        groups: [],
        auto_publish: false,
        destination_config: { kind: "personal" },
        permission_policy: "private",
      }),
    }),
  );
});

it("shows group refresh failure inside the picker and preserves selections for retry", async () => {
  const groups = [{ chat_id: "group-1", name: "项目群" }];
  vi.mocked(feishuGroups)
    .mockResolvedValueOnce(groups)
    .mockRejectedValueOnce(new Error("网络暂不可用"))
    .mockResolvedValueOnce(groups);
  render(
    <MemoryRouter>
      <FeishuSettings />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "选择群" }));
  const selected = await screen.findByRole("checkbox", { name: "项目群" });
  fireEvent.click(selected);
  fireEvent.click(screen.getByRole("button", { name: "刷新群列表" }));
  const failure = await screen.findByText(
    "网络暂不可用，已选群继续保留，请重试刷新。",
  );
  expect(failure.closest('[role="dialog"]')).not.toBeNull();
  expect(selected.getAttribute("aria-checked")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "刷新群列表" }));
  await waitFor(() =>
    expect(
      screen.queryByText("网络暂不可用，已选群继续保留，请重试刷新。"),
    ).toBeNull(),
  );
  expect(
    screen
      .getByRole("checkbox", { name: "项目群" })
      .getAttribute("aria-checked"),
  ).toBe("true");
});

it("keeps an initial group failure separate from connection state and supports a picker retry", async () => {
  vi.mocked(feishuGroups).mockRejectedValueOnce(new Error("群服务暂不可用"));
  render(
    <MemoryRouter>
      <FeishuSettings />
    </MemoryRouter>,
  );
  await screen.findByText("测试账号");
  await screen.findByText("群服务暂不可用，已选群继续保留，请重试刷新。");
  expect(screen.queryByRole("button", { name: "重新加载" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "选择群" }));
  fireEvent.click(screen.getByRole("button", { name: "刷新群列表" }));
  await waitFor(() =>
    expect(
      screen.queryByText("群服务暂不可用，已选群继续保留，请重试刷新。"),
    ).toBeNull(),
  );
});


it.each([{ connection_state: 'service_unavailable' }, { grant_state: 'unavailable' }])('temporary grant verification retries status without authorizing or losing the saved destination %j', async unavailable => {
  vi.mocked(feishuStatus).mockResolvedValueOnce({ ...status, connected: false, ...unavailable, capabilities: { folder: false, wiki: false, contact_search: false } }).mockResolvedValue(status);
  render(<MemoryRouter><FeishuSettings /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: '重新核验飞书连接' }));
  await screen.findByText('测试账号');
  await waitFor(() => expect(feishuStatus).toHaveBeenCalledTimes(2));
  expect(apiJson).not.toHaveBeenCalled();
  expect(screen.queryByText(/需重新授权/)).toBeNull();
  expect(feishuGroups).toHaveBeenCalledTimes(1);
});
