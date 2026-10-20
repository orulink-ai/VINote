import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { FeishuSettings } from './FeishuSettings';
import { feishuContacts, feishuStatus, type FeishuStatus, type FeishuContactPage } from '@/lib/feishu';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import { connectorPluginKey } from '@/lib/connectorPlugins';
vi.mock('@/lib/feishu', async original => ({ ...await original<typeof import('@/lib/feishu')>(), feishuStatus: vi.fn(), feishuContacts: vi.fn(), feishuGroups: vi.fn(async () => []) }));
vi.mock('@/lib/api', () => ({ apiJson: vi.fn() }));
vi.mock('@/components/Settings/FeishuApplicationSetup', () => ({ FeishuApplicationSetup: () => null }));
const base: FeishuStatus = { configured: true, connected: true, expired: false, name: '测试连接', notify_self: false, groups: [], contacts: [], auto_publish: false, destination: 'personal', destination_config: { kind: 'personal' }, permission_policy: 'private', capabilities: { background_delivery: true }, automatic_delivery_protocol: 1, automatic_delivery: { policy_id: null, enabled: false }, contact_selection_protocol: 1 };
const proof = { open_id: 'ou_new', name: '服务端联系人', selection_token: 'short-lived-proof', expiresAt: Date.now() + 900000 };
const page = (items = [proof], more = false): FeishuContactPage => ({ items, has_more: more, page_token: more ? 'next-page' : '', selection_expires_in: 900 });
const puts = () => vi.mocked(apiJson).mock.calls.filter(([path, options]) => path === '/api/feishu/preferences' && options?.method === 'PUT');
const tab = (name: string) => fireEvent.mouseDown(screen.getByRole('tab', { name }));
const mount = () => { const view = render(<MemoryRouter><FeishuSettings /></MemoryRouter>); tab('会议纪要发送设置'); return view };
const ready = async () => { await screen.findByRole('switch', { name: '自动交付新纪要' }); await waitFor(() => expect(screen.getByRole('checkbox', { name: '发给我本人' })).toBeEnabled()) };
const verify = async () => { fireEvent.click(screen.getByRole('button', { name: '核验位置与权限' })); await waitFor(() => expect(screen.getByRole('button', { name: '保存设置' })).toBeEnabled()) };
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear(); localStorage.clear();
  useAuthStore.setState({ user: { id: 'auto-owner', email: 'test@example.invalid' } });
  vi.mocked(feishuStatus).mockResolvedValue(base); vi.mocked(feishuContacts).mockResolvedValue(page());
  vi.mocked(apiJson).mockImplementation(async path => path === '/api/feishu/preferences' ? base : { kind: 'personal', path: ['个人云文档'], can_attempt_create: true });
});
afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear(); vi.restoreAllMocks() });

it('defaults participant notification/version grouping off and freezes both beside self notification in explicit consent', async () => {
  mount(); await ready();
  const participants = screen.getByRole('checkbox', { name: '发给会议参会人' });
  const versions = screen.getByRole('checkbox', { name: '按会议归组历史版本' });
  expect(participants).not.toBeChecked(); expect(versions).not.toBeChecked();
  fireEvent.click(screen.getByRole('checkbox', { name: '发给我本人' })); fireEvent.click(participants); fireEvent.click(versions);
  fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); await verify();
  const draft = JSON.parse(sessionStorage.getItem('vinote:feishu-preferences:auto-owner')!);
  expect(draft).toMatchObject({ notify_self: true, notify_participants: true, group_meeting_versions: true });
  fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  const confirmation = await screen.findByRole('alertdialog');
  expect(confirmation).toHaveTextContent('我本人、已核验的会议参会人');
  expect(confirmation).toHaveTextContent('在知识库按会议归组，保留历史稿');
  expect(puts()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: '取消，保留修改' }));
  expect(puts()).toHaveLength(0); expect(participants).toBeChecked();
  vi.mocked(apiJson).mockResolvedValue({ ...base, auto_publish: true, notify_self: true, notify_participants: true, group_meeting_versions: true });
  fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  fireEvent.click(await screen.findByRole('button', { name: '确认自动交付并保存' }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect(JSON.parse(puts()[0][1]!.body as string)).toMatchObject({ notify_self: true, notify_participants: true, group_meeting_versions: true, automatic_delivery_consent: true });
});

it.each(['发给会议参会人', '按会议归组历史版本'])('changing %s on enabled automatic delivery requires another explicit consent', async label => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, auto_publish: true });
  mount(); await ready(); fireEvent.click(screen.getByRole('checkbox', { name: label })); await verify();
  fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  expect(await screen.findByRole('alertdialog')).toBeVisible(); expect(puts()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: '取消，保留修改' })); expect(puts()).toHaveLength(0);
});

it('participant and version drafts never migrate to another owner', async () => {
  mount(); await ready(); fireEvent.click(screen.getByRole('checkbox', { name: '发给会议参会人' })); fireEvent.click(screen.getByRole('checkbox', { name: '按会议归组历史版本' }));
  act(() => useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }));
  await waitFor(() => expect(feishuStatus).toHaveBeenCalledTimes(2)); await ready();
  expect(screen.getByRole('checkbox', { name: '发给会议参会人' })).not.toBeChecked();
  expect(screen.getByRole('checkbox', { name: '按会议归组历史版本' })).not.toBeChecked();
  expect(sessionStorage.getItem('vinote:feishu-preferences:other')).toBeNull(); expect(puts()).toHaveLength(0);
});

it('legacy background capability alone cannot enable automatic delivery', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, automatic_delivery_protocol: undefined });
  mount(); await ready(); expect(screen.getByRole('switch', { name: '自动交付新纪要' })).toBeDisabled(); expect(puts()).toHaveLength(0);
});
it('protocol one with runtime capability false still cannot enable automatic delivery', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, capabilities: { background_delivery: false } });
  mount(); await ready(); expect(screen.getByRole('switch', { name: '自动交付新纪要' })).toBeDisabled();
});
it('closing existing automatic delivery alone does not require a new destination check or consent', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, auto_publish: true }); mount(); await ready();
  fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  await waitFor(() => expect(puts()).toHaveLength(1)); expect(screen.queryByRole('alertdialog')).toBeNull();
  expect(JSON.parse(puts()[0][1]!.body as string).auto_publish).toBe(false);
});
it('requires explicit consent with personal meeting boundaries; cancel preserves draft and sends no PUT', async () => {
  mount(); await ready(); fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); await verify();
  fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  expect(await screen.findByRole('alertdialog')).toHaveTextContent('新个人会议纪要');
  expect(screen.getByRole('alertdialog')).toHaveTextContent('只创建文档，不发送通知'); expect(puts()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: '取消，保留修改' }));
  expect(screen.getByRole('switch', { name: '自动交付新纪要' })).toBeChecked(); expect(puts()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: '保存设置' })); fireEvent.click(await screen.findByRole('button', { name: '确认自动交付并保存' }));
  await waitFor(() => expect(puts()).toHaveLength(1)); expect(JSON.parse(puts()[0][1]!.body as string).automatic_delivery_consent).toBe(true);
});
it('explicit successful automatic consent installs and enables this owners plugin without another installation', async () => {
  vi.mocked(apiJson).mockImplementation(async path => path === '/api/feishu/preferences' ? { ...base, auto_publish: true, automatic_delivery: { policy_id: 'policy', enabled: true } } : { kind: 'personal', path: ['个人云文档'], can_attempt_create: true });
  mount(); await ready(); fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  expect(await screen.findByRole('alertdialog')).toHaveTextContent('安装并启用这台桌面的飞书插件'); expect(localStorage.getItem(connectorPluginKey('auto-owner'))).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '确认自动交付并保存' })); await screen.findAllByText('自动交付已保存，飞书插件已安装并启用。');
  expect(JSON.parse(localStorage.getItem(connectorPluginKey('auto-owner'))!).feishu).toEqual({ installed: true, enabled: true });
});
it('a failed automatic preference save never installs the plugin', async () => {
  vi.mocked(apiJson).mockImplementation(async path => { if (path === '/api/feishu/preferences') throw new Error('保存失败'); return { kind: 'personal', path: ['个人云文档'], can_attempt_create: true } });
  mount(); await ready(); fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  fireEvent.click(await screen.findByRole('button', { name: '确认自动交付并保存' })); await screen.findByRole('button', { name: '重试保存' });
  expect(localStorage.getItem(connectorPluginKey('auto-owner'))).toBeNull();
});
it('plugin persistence failure compensates device automatic delivery and reports partial success honestly', async () => {
  vi.mocked(apiJson).mockImplementation(async path => path === '/api/feishu/preferences' ? { ...base, auto_publish: true } : path === '/api/feishu/automatic-deliveries/device-disable' ? { disabled: true } : { kind: 'personal', path: ['个人云文档'], can_attempt_create: true });
  mount(); await ready(); fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  await screen.findByRole('alertdialog'); vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('quota') });
  fireEvent.click(screen.getByRole('button', { name: '确认自动交付并保存' })); await screen.findByText(/偏好已保存，但飞书插件启用状态未能保存/);
  expect(apiJson).toHaveBeenCalledWith('/api/feishu/automatic-deliveries/device-disable', expect.objectContaining({ body: JSON.stringify({ expected_user_id: 'auto-owner' }) }));
  expect(localStorage.getItem(connectorPluginKey('auto-owner'))).toBeNull(); expect(screen.getByRole('switch', { name: '自动交付新纪要' })).not.toBeChecked();
});
it('failed plugin enable and unconfirmed compensation never claim automatic delivery stopped', async () => {
  vi.mocked(apiJson).mockImplementation(async path => { if (path === '/api/feishu/preferences') return { ...base, auto_publish: true }; if (path === '/api/feishu/automatic-deliveries/device-disable') throw new Error('关闭失败'); return { kind: 'personal', path: ['个人云文档'], can_attempt_create: true } });
  mount(); await ready(); fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  await screen.findByRole('alertdialog'); vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('quota') });
  fireEvent.click(screen.getByRole('button', { name: '确认自动交付并保存' })); await screen.findByText(/设备自动交付是否关闭也未确认/);
  expect(screen.getByRole('switch', { name: '自动交付新纪要' })).toBeChecked(); expect(screen.queryByText(/已停止设备自动交付/)).toBeNull();
});
it('old-owner preference success never installs the plugin after an account switch', async () => {
  let finish!: (value: FeishuStatus) => void;
  vi.mocked(apiJson).mockImplementation(async path => path === '/api/feishu/preferences' ? new Promise(resolve => { finish = resolve }) : { kind: 'personal', path: ['个人云文档'], can_attempt_create: true });
  mount(); await ready(); fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  fireEvent.click(await screen.findByRole('button', { name: '确认自动交付并保存' }));
  act(() => useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }));
  await act(async () => finish({ ...base, auto_publish: true }));
  expect(localStorage.getItem(connectorPluginKey('auto-owner'))).toBeNull(); expect(localStorage.getItem(connectorPluginKey('other'))).toBeNull();
});
it('batched owner ABA resets the lifecycle and busy lock without accepting an old save response', async () => {
  let finish!: (value: FeishuStatus) => void;
  vi.mocked(apiJson).mockImplementation(async path => path === '/api/feishu/preferences' ? new Promise(resolve => { finish = resolve }) : { kind: 'personal', path: ['个人云文档'], can_attempt_create: true });
  mount(); await ready(); fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  fireEvent.click(await screen.findByRole('button', { name: '确认自动交付并保存' }));
  act(() => { useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }); useAuthStore.setState({ user: { id: 'auto-owner', email: 'test@example.invalid' } }) });
  await act(async () => finish({ ...base, auto_publish: true }));
  await waitFor(() => expect(screen.getByRole('checkbox', { name: '发给我本人' })).toBeEnabled());
  expect(feishuStatus).toHaveBeenCalledTimes(2); expect(puts()).toHaveLength(1); expect(localStorage.getItem(connectorPluginKey('auto-owner'))).toBeNull();
});
it('an old save finally cannot unlock a new current visit save after batched ABA', async () => {
  let oldSave!: (value: FeishuStatus) => void, currentSave!: (value: FeishuStatus) => void;
  let saves = 0;
  vi.mocked(apiJson).mockImplementation(async path => path === '/api/feishu/preferences' ? new Promise(resolve => { if (++saves === 1) oldSave = resolve; else currentSave = resolve }) : { kind: 'personal', path: ['个人云文档'], can_attempt_create: true });
  mount(); await ready(); fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  fireEvent.click(await screen.findByRole('button', { name: '确认自动交付并保存' }));
  act(() => { useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }); useAuthStore.setState({ user: { id: 'auto-owner', email: 'test@example.invalid' } }) });
  await waitFor(() => expect(feishuStatus).toHaveBeenCalledTimes(2)); await ready(); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  fireEvent.click(await screen.findByRole('button', { name: '确认自动交付并保存' })); await waitFor(() => expect(puts()).toHaveLength(2));
  await act(async () => oldSave({ ...base, auto_publish: true })); expect(screen.getByRole('checkbox', { name: '发给我本人' })).toBeDisabled(); expect(localStorage.getItem(connectorPluginKey('auto-owner'))).toBeNull();
  await act(async () => currentSave({ ...base, auto_publish: true })); await ready(); expect(JSON.parse(localStorage.getItem(connectorPluginKey('auto-owner'))!).feishu.enabled).toBe(true);
});
it('with auto off, changed contact presets require frozen-target consent without enabling or installing', async () => {
  vi.mocked(apiJson).mockImplementation(async (path, options) => {
    if (path !== '/api/feishu/preferences') return { kind: 'personal', path: ['个人云文档'], can_attempt_create: true };
    const body = JSON.parse(options!.body as string); if (!body.automatic_delivery_consent) throw new Error('automatic_consent_required');
    return { ...base, contacts: [{ open_id: proof.open_id, name: proof.name }] };
  });
  mount(); await ready(); fireEvent.change(screen.getByLabelText('预设通知联系人'), { target: { value: '姓名' } }); fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.click(await screen.findByRole('button', { name: '选择联系人服务端联系人' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  const dialog = await screen.findByRole('alertdialog'); expect(dialog).toHaveTextContent('自动交付保持关闭'); expect(dialog).toHaveTextContent('不会安装或启用'); expect(dialog).toHaveTextContent('服务端联系人'); expect(puts()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: '取消，保留修改' })); expect(puts()).toHaveLength(0); expect(localStorage.getItem(connectorPluginKey('auto-owner'))).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '保存设置' })); fireEvent.click(await screen.findByRole('button', { name: '确认保存预设' }));
  await waitFor(() => expect(puts()).toHaveLength(1)); const body = JSON.parse(puts()[0][1]!.body as string);
  expect(body.auto_publish).toBe(false); expect(body.automatic_delivery_consent).toBe(true); expect(body.contacts).toEqual([{ open_id: proof.open_id, selection_token: proof.selection_token }]);
  expect(localStorage.getItem(connectorPluginKey('auto-owner'))).toBeNull(); expect(screen.getByRole('switch', { name: '自动交付新纪要' })).not.toBeChecked();
});
it('removing a saved contact while auto is off also confirms the frozen empty preset without installation', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, contacts: [{ open_id: proof.open_id, name: proof.name }] });
  mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: '移除联系人服务端联系人' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  expect(await screen.findByRole('alertdialog')).toHaveTextContent('未选择通知对象'); expect(puts()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: '确认保存预设' })); await waitFor(() => expect(puts()).toHaveLength(1));
  const body = JSON.parse(puts()[0][1]!.body as string); expect(body.contacts).toEqual([]); expect(body.auto_publish).toBe(false); expect(body.automatic_delivery_consent).toBe(true); expect(localStorage.getItem(connectorPluginKey('auto-owner'))).toBeNull();
});
it('requires new consent when enabled recipients change, while disabling saves directly', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, auto_publish: true }); mount(); await ready();
  fireEvent.click(screen.getByRole('checkbox', { name: '发给我本人' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  expect(await screen.findByRole('alertdialog')).toHaveTextContent('我本人'); expect(puts()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: '取消，保留修改' })); fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' }));
  fireEvent.click(screen.getByRole('button', { name: '保存设置' })); await waitFor(() => expect(puts()).toHaveLength(1));
  const body = JSON.parse(puts()[0][1]!.body as string); expect(body.auto_publish).toBe(false); expect(body.automatic_delivery_consent).toBeUndefined();
});
it('changing an enabled destination requires a new explicit confirmation', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, auto_publish: true, destination_config: { kind: 'folder', folder_token: 'old-folder' } });
  vi.mocked(apiJson).mockImplementation(async path => path.includes('/destinations?') ? { items: [], has_more: false, page_token: '' } : { kind: 'personal', path: ['个人云文档'], can_attempt_create: true });
  mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: '选择文档位置' }));
  await waitFor(() => expect(screen.getByRole('combobox', { name: '文档位置类型' })).toBeEnabled());
  fireEvent.change(screen.getByRole('combobox', { name: '文档位置类型' }), { target: { value: 'personal' } });
  fireEvent.click(screen.getByRole('button', { name: '确认位置并核验' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  expect(await screen.findByRole('alertdialog')).toHaveTextContent('文档位置：个人云文档'); expect(puts()).toHaveLength(0);
});
it('an open consent dialog cannot submit after the owner changes', async () => {
  mount(); await ready(); fireEvent.click(screen.getByRole('switch', { name: '自动交付新纪要' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  await screen.findByRole('alertdialog'); act(() => useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }));
  await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull()); expect(puts()).toHaveLength(0); expect(sessionStorage.getItem('vinote:feishu-preferences:other')).toBeNull();
});
it('keeps previously saved contacts without a short-lived token or fabricated name', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, contacts: [{ open_id: 'ou_saved', name: '已保存姓名' }] });
  mount(); await ready(); expect(screen.getByRole('button', { name: '移除联系人已保存姓名' })).toBeVisible();
  fireEvent.click(screen.getByRole('checkbox', { name: '发给我本人' })); await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' }));
  await waitFor(() => expect(puts()).toHaveLength(1)); expect(JSON.parse(puts()[0][1]!.body as string).contacts).toEqual([{ open_id: 'ou_saved' }]); expect(feishuContacts).not.toHaveBeenCalled();
});
it('uses proof for a new contact, never persists proof, and keeps a failed draft', async () => {
  mount(); await ready(); fireEvent.change(screen.getByLabelText('预设通知联系人'), { target: { value: '姓名' } }); fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.click(await screen.findByRole('button', { name: '选择联系人服务端联系人' }));
  expect(sessionStorage.getItem('vinote:feishu-preferences:auto-owner')).not.toContain('short-lived-proof');
  vi.mocked(apiJson).mockImplementation(async path => { if (path === '/api/feishu/preferences') throw new Error('保存暂不可用'); return { kind: 'personal', path: ['个人云文档'], can_attempt_create: true } });
  await verify(); fireEvent.click(screen.getByRole('button', { name: '保存设置' })); fireEvent.click(await screen.findByRole('button', { name: '确认保存预设' })); await screen.findByRole('button', { name: '重试保存' });
  expect(screen.getByRole('button', { name: '移除联系人服务端联系人' })).toBeVisible();
  expect(JSON.parse(puts()[0][1]!.body as string).contacts).toEqual([{ open_id: 'ou_new', selection_token: 'short-lived-proof' }]);
});
it('restored unsaved new contacts require a fresh search rather than treating storage as consent', async () => {
  sessionStorage.setItem('vinote:feishu-preferences:auto-owner', JSON.stringify({ notify_self: false, auto_publish: false, groups: [], destination_config: { kind: 'personal' }, contacts: [proof], automatic_delivery_protocol: 99 }));
  mount(); await ready(); expect(screen.getByRole('button', { name: '移除联系人待重新选择联系人' })).toBeVisible(); await verify();
  fireEvent.click(screen.getByRole('button', { name: '保存设置' })); await screen.findByText(/新联系人选择已过期/); expect(puts()).toHaveLength(0);
});
it('input and owner ABA invalidate late contact results and never copy the old draft to another account', async () => {
  let finish!: (value: FeishuContactPage) => void;
  vi.mocked(feishuContacts).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })); mount(); await ready();
  fireEvent.change(screen.getByLabelText('预设通知联系人'), { target: { value: '旧查询' } }); fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.change(screen.getByLabelText('预设通知联系人'), { target: { value: '新查询' } });
  await act(async () => finish(page())); expect(screen.queryByRole('button', { name: '选择联系人服务端联系人' })).toBeNull();
  fireEvent.click(screen.getByRole('checkbox', { name: '发给我本人' }));
  act(() => useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } })); await ready();
  expect(sessionStorage.getItem('vinote:feishu-preferences:other')).toBeNull();
  expect(screen.getByRole('checkbox', { name: '发给我本人' })).not.toBeChecked();
});
it('contact read failure and pagination retain chosen contacts and support explicit retry', async () => {
  vi.mocked(feishuContacts).mockRejectedValueOnce(new Error('通讯录暂不可用')).mockResolvedValueOnce(page([proof], true)).mockResolvedValueOnce(page([{ ...proof, open_id: 'ou_next', name: '下一页姓名' }]));
  mount(); await ready(); fireEvent.change(screen.getByLabelText('预设通知联系人'), { target: { value: '姓名' } }); fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.click(await screen.findByRole('button', { name: '重试搜索联系人' })); fireEvent.click(await screen.findByRole('button', { name: '选择联系人服务端联系人' }));
  fireEvent.click(screen.getByRole('button', { name: '下一页联系人' })); await screen.findByRole('button', { name: '选择联系人下一页姓名' });
  expect(feishuContacts).toHaveBeenLastCalledWith('姓名', 'next-page'); expect(screen.getByRole('button', { name: '移除联系人服务端联系人' })).toBeVisible();
});
it('same-owner disconnect invalidates a pending contact query before it can return', async () => {
  let finish!: (value: FeishuContactPage) => void;
  vi.mocked(feishuContacts).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })); mount(); await ready();
  fireEvent.change(screen.getByLabelText('预设通知联系人'), { target: { value: '姓名' } }); fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  tab('授权'); fireEvent.click(screen.getByRole('button', { name: '断开' }));
  vi.mocked(feishuStatus).mockResolvedValue({ ...base, connected: false });
  fireEvent.click(await screen.findByRole('button', { name: '断开连接' })); await waitFor(() => expect(feishuStatus).toHaveBeenCalledTimes(2));
  await act(async () => finish(page())); expect(screen.queryByRole('button', { name: '选择联系人服务端联系人' })).toBeNull(); expect(puts()).toHaveLength(0);
});
it('owner ABA rejects a late contact page even after returning to the same account', async () => {
  let finish!: (value: FeishuContactPage) => void;
  vi.mocked(feishuContacts).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })); mount(); await ready();
  fireEvent.change(screen.getByLabelText('预设通知联系人'), { target: { value: '姓名' } }); fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  act(() => useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } })); await waitFor(() => expect(feishuStatus).toHaveBeenCalledTimes(2));
  act(() => useAuthStore.setState({ user: { id: 'auto-owner', email: 'test@example.invalid' } })); await waitFor(() => expect(feishuStatus).toHaveBeenCalledTimes(3));
  await act(async () => finish(page())); expect(screen.queryByRole('button', { name: '选择联系人服务端联系人' })).toBeNull();
});
it('expired in-memory proof fails before PUT and leaves the contact available to reselect', async () => {
  mount(); await ready(); fireEvent.change(screen.getByLabelText('预设通知联系人'), { target: { value: '姓名' } }); fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.click(await screen.findByRole('button', { name: '选择联系人服务端联系人' })); await verify();
  vi.spyOn(Date, 'now').mockReturnValue(proof.expiresAt + 1);
  fireEvent.click(screen.getByRole('button', { name: '保存设置' })); await screen.findByText(/新联系人选择已过期/);
  expect(puts()).toHaveLength(0); expect(screen.getByRole('button', { name: '移除联系人服务端联系人' })).toBeVisible();
});
