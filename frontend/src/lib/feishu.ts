import { apiJson } from "./api";
import type { FormattingReceipt } from './feishuFormatting';
import { useAuthStore } from '@/stores/authStore';
import { publishScope, markPublishAttempt, type PublishAttempt } from './feishuPublishReceipt';
import { createConnectorPluginStore } from './connectorPlugins';
import { feishuVerificationUnavailable } from './feishuConnectionState';

export type FeishuDestination =
  | { kind: "personal" }
  | { kind: "folder"; folder_token: string }
  | { kind: "wiki"; space_id: string; node_token: string };
export type DestinationCheck = FeishuDestination & {
  name: string;
  path: string[];
  path_complete: boolean;
  tenant_key: string;
  can_create: boolean;
  can_attempt_create: boolean;
  permission_state: string;
  reason: string;
  error_code: string;
};
export type FeishuStatus = {
  transport?: 'cli' | 'http';
  automatic_delivery_protocol?: number;
  automatic_delivery?: { policy_id: string | null; enabled: boolean };
  device_auto_enabled?: boolean;
  contacts?: FeishuPreferenceContact[];
  publish_receipt_protocol?: number;
  contact_selection_protocol?: number;
  recipient_access_protocol?: number;
  setup?: { ready?: boolean; missing?: string[]; cli_available?: boolean };
  connection_state?: string;
  grant_state?: string;
  configured: boolean;
  connected: boolean;
  expired: boolean;
  name: string;
  notify_self: boolean;
  groups: string[];
  auto_publish: boolean;
  destination: "personal" | "folder" | "wiki";
  destination_config?: FeishuDestination;
  permission_policy?: "private" | "inherit";
  tenant_key?: string;
  capabilities?: Record<string, boolean>;
  capability_reason?: string;
};
export type FeishuAuthorization = { url: string; qr_data_url: string; expires_at: number; flow_id?: string; stage?: 'application' | 'authorization'; pending?: boolean };
export function isFeishuAuthorization(value: unknown): value is FeishuAuthorization {
  if (!value || typeof value !== 'object') return false;
  const item = value as FeishuAuthorization;
  const pendingApplication = item.pending === true && item.stage === 'application' && !!item.flow_id && item.url === '' && item.qr_data_url === '';
  return typeof item.url === 'string' && (!!item.url || pendingApplication) && Number.isFinite(item.expires_at) && item.expires_at > 0
    && (item.pending === undefined || typeof item.pending === 'boolean')
    && (item.pending !== true || item.stage === 'application' && !!item.flow_id)
    && (item.flow_id === undefined || typeof item.flow_id === 'string' && !!item.flow_id)
    && (item.stage === undefined || item.stage === 'application' || item.stage === 'authorization');
}
export const completeFeishuAuthorization = (flow_id: string) => apiJson<FeishuAuthorization | FeishuStatus>('/api/feishu/authorize/complete', { method: 'POST', body: JSON.stringify({ flow_id }) });

export type FeishuObject = { id: string; name: string; kind: 'contact' | 'group' };
export type FeishuObjectAlias = { id: string; alias: string; target_id: string; target_name: string; kind: 'contact' | 'group' };
export type FeishuObjectHotwords = { objects: FeishuObject[]; aliases: FeishuObjectAlias[]; partial: boolean; updated_at?: number };
const validObjectKind = (value: unknown) => value === 'contact' || value === 'group';
const nonempty = (value: unknown): value is string => typeof value === 'string' && !!value.trim();
export const normalizeObjectAlias = (alias: string) => alias.normalize('NFKC').trim().toLocaleLowerCase();
function validateObjectHotwords(value: FeishuObjectHotwords): FeishuObjectHotwords {
  if (!value || !Array.isArray(value.objects) || !Array.isArray(value.aliases) || typeof value.partial !== 'boolean'
    || value.objects.some(item => !item || !nonempty(item.id) || !nonempty(item.name) || !validObjectKind(item.kind))
    || value.aliases.some(item => !item || !nonempty(item.id) || !nonempty(item.alias) || !nonempty(item.target_id) || !nonempty(item.target_name) || !validObjectKind(item.kind))
    || new Set(value.objects.map(item => item.id)).size !== value.objects.length
    || new Set(value.aliases.map(item => item.id)).size !== value.aliases.length
    || value.updated_at !== undefined && (!Number.isFinite(value.updated_at) || value.updated_at < 0)) throw new Error('对象目录响应未核验，请重新读取');
  return value;
}
export const feishuObjectHotwords = async () => validateObjectHotwords(await apiJson<FeishuObjectHotwords>('/api/feishu/object-hotwords', { cache: 'no-store' }));
export const refreshFeishuObjectHotwords = async () => validateObjectHotwords(await apiJson<FeishuObjectHotwords>('/api/feishu/object-hotwords/refresh', { method: 'POST' }));
export const bindFeishuObjectAlias = async (alias: string, target_id: string) => validateObjectHotwords(await apiJson<FeishuObjectHotwords>('/api/feishu/object-hotwords', { method: 'POST', body: JSON.stringify({ alias, target_id }) }));
export const deleteFeishuObjectAlias = async (id: string) => validateObjectHotwords(await apiJson<FeishuObjectHotwords>('/api/feishu/object-hotwords/' + encodeURIComponent(id), { method: 'DELETE' }));
export type FeishuGroup = { chat_id: string; name: string };
export type FeishuContact = { open_id: string; selection_token: string; name?: string; expiresAt?: number };
export type FeishuPreferenceContact = { open_id: string; name: string; selection_token?: string; expiresAt?: number };
// Preferences are a separate contract from one-shot manual publication proofs.
export function preferenceContacts(contacts: FeishuPreferenceContact[], saved: FeishuPreferenceContact[]) {
  const known = new Set(saved.map(contact => contact.open_id));
  return contacts.map(contact => {
    if (!/^ou_[A-Za-z0-9_-]+$/.test(contact.open_id)) throw new Error('联系人未核验，请重新搜索并选择');
    if (known.has(contact.open_id)) return { open_id: contact.open_id };
    if (!contact.selection_token || !contact.name?.trim() || !contact.expiresAt || contact.expiresAt <= Date.now()) throw new Error('新联系人选择已过期，请重新搜索并选择后保存');
    return { open_id: contact.open_id, selection_token: contact.selection_token };
  });
}
type AutomaticTarget = Pick<FeishuStatus, 'auto_publish' | 'notify_self' | 'groups' | 'contacts' | 'destination_config' | 'permission_policy'>;
export function automaticConsentNeeded(next: AutomaticTarget, saved?: AutomaticTarget) {
  const target = (value: AutomaticTarget) => JSON.stringify([value.destination_config || { kind: 'personal' }, value.permission_policy || 'private', value.notify_self, [...value.groups].sort(), (value.contacts || []).map(contact => contact.open_id).sort()]);
  const contactIds = (value?: AutomaticTarget) => JSON.stringify([...new Set((value?.contacts || []).map(contact => contact.open_id))].sort());
  return contactIds(next) !== contactIds(saved) || next.auto_publish && (!saved?.auto_publish || target(next) !== target(saved));
}
export type FeishuContactPage = { items: FeishuContact[]; has_more: boolean; page_token: string; selection_expires_in: number };
export const contactRecipients = (contacts: FeishuContact[]) => contacts.map(({ open_id, selection_token }) => ({ open_id, selection_token }));
export const contactsValid = (contacts: FeishuContact[]) => contacts.every(item => !!item.name?.trim() && !!item.selection_token && !!item.expiresAt && item.expiresAt > Date.now());
export async function feishuContacts(query: string, page_token = "") {
  const started = Date.now();
  const result = await apiJson<FeishuContactPage>("/api/feishu/contacts?" + new URLSearchParams({ query, page_size: "20", page_token }), { cache: "no-store" });
  if (!Array.isArray(result.items) || typeof result.has_more !== 'boolean' || typeof result.page_token !== 'string' || (result.has_more && !result.page_token) || !Number.isFinite(result.selection_expires_in) || !(result.selection_expires_in > 0) || result.items.some(item => !item || typeof item.name !== 'string' || !item.name.trim() || typeof item.open_id !== 'string' || !/^ou_[A-Za-z0-9_-]+$/.test(item.open_id) || typeof item.selection_token !== 'string' || !item.selection_token)) throw new Error('联系人响应未核验，请重新读取');
  return { ...result, items: result.items.map(({ open_id, name, selection_token }) => ({ open_id, name, selection_token, expiresAt: started + Math.min(result.selection_expires_in, 900) * 1000 })) };
}
export type Delivery = {
  formatting?: FormattingReceipt;
  id: string;
  operation_id?: string;
  recipient_access_policy?: string | null;
  status: "queued" | "processing" | "failed" | "completed";
  needs_document_recovery?: boolean;
  document_url: string;
  error: string;
  phase?: string;
  error_code?: string;
  permission?: {
    status: string;
    policy?: string;
    error?: string;
    note?: string;
  };
  destination?: Partial<DestinationCheck>;
  revision_id?: string | null;
  version_id?: string | null;
  content_revision?: string;
  publication_mode?: string;
  recipients: Record<string, { status: string; name: string; error?: string; kind?: string; reading_permission?: { status: 'granting' | 'unknown' | 'verified' | 'failed' | 'unverified'; note?: string } }>;
};
export const recoverDeliveryDocument = (id: string, url: string) =>
  apiJson<Delivery>(
    "/api/feishu/deliveries/" + encodeURIComponent(id) + "/document",
    { method: "POST", body: JSON.stringify({ url }) },
  );
export const feishuStatus = () => apiJson<FeishuStatus>("/api/feishu/status", { cache: "no-store" });
export async function disableDeviceAutomaticDelivery(owner: string): Promise<{ legacy: boolean }> {
  const guard = publishScope(owner);
  try {
    await apiJson('/api/feishu/automatic-deliveries/device-disable', {
      method: 'POST', cache: 'no-store', body: JSON.stringify({ expected_user_id: owner }),
    });
    guard(); return { legacy: false };
  } catch (cause) {
    guard();
    if (!cause || typeof cause !== 'object' || !('status' in cause) || cause.status !== 404) throw cause;
    const status = await feishuStatus();
    guard();
    if (!status || typeof status.configured !== 'boolean' || typeof status.connected !== 'boolean' || typeof status.auto_publish !== 'boolean' || !Array.isArray(status.groups) || feishuVerificationUnavailable(status) || status.automatic_delivery_protocol !== undefined) throw new Error('设备自动交付关闭接口不可用，插件仍保持原状态，请重试。');
    return { legacy: true };
  }
}
export const feishuGroups = () => apiJson<FeishuGroup[]>("/api/feishu/groups");
export const deliveryStatus = (key: string) =>
  apiJson<Delivery | null>("/api/feishu/deliveries/" + encodeURIComponent(key));
export type AutomaticDeliveryLocal = {
  status: 'queued' | 'submitting' | 'unknown' | 'accepted' | 'failed' | 'cancelled';
  error?: string; job_id?: string | null; operation_id?: string; can_check?: boolean;
};
async function automaticDeliveryLocal(noteId: string, check: boolean): Promise<AutomaticDeliveryLocal | null> {
  const owner = useAuthStore.getState().user?.id;
  if (!owner || !noteId) throw new Error('请登录后核验原纪要的交付状态');
  const guard = publishScope(owner);
  try {
    const result = await apiJson<AutomaticDeliveryLocal>('/api/feishu/automatic-deliveries/local/' + encodeURIComponent(noteId) + (check ? '/check' : ''), { cache: 'no-store', ...(check ? { method: 'POST' } : {}) });
    guard();
    if (!result || !['queued', 'submitting', 'unknown', 'accepted', 'failed', 'cancelled'].includes(result.status) || (result.error != null && typeof result.error !== 'string') || (result.job_id != null && typeof result.job_id !== 'string') || (result.operation_id != null && typeof result.operation_id !== 'string') || (result.can_check != null && typeof result.can_check !== 'boolean')) throw new Error('自动交付状态未核验，请重新读取');
    return result;
  } catch (cause) {
    guard();
    if (!check && cause && typeof cause === 'object' && 'status' in cause && cause.status === 404) return null;
    throw cause;
  }
}
export const readAutomaticDelivery = (noteId: string) => automaticDeliveryLocal(noteId, false);
// Queries only: the backend check must never create/replay a document or notification.
export const checkAutomaticDelivery = (noteId: string) => automaticDeliveryLocal(noteId, true);
export const deliveryById = (id: string, signal?: AbortSignal) => apiJson<Delivery>("/api/feishu/deliveries/by-id/" + encodeURIComponent(id), { cache: 'no-store', ...(signal ? { signal } : {}) });
export const deliveryByOperation = (id: string) => apiJson<Delivery>("/api/feishu/deliveries/by-operation/" + encodeURIComponent(id));
// The POST triggers only external permission GETs and local evidence updates.
// It never grants access, writes a document, schedules a worker or sends a message.
export async function verifyDeliveryPermissions(id: string) {
  const owner = useAuthStore.getState().user?.id;
  if (!owner || !id) throw new Error('请重新登录并读取原发布任务');
  const guard = publishScope(owner);
  const result = await apiJson<Delivery>('/api/feishu/deliveries/' + encodeURIComponent(id) + '/verify-permissions', { method: 'POST', cache: 'no-store' });
  guard();
  if (!result || result.id !== id) throw new Error('权限核验回执不属于原发布任务');
  return result;
}
export async function preflightFeishuPublish() {
  const owner = useAuthStore.getState().user?.id;
  if (!owner) throw new Error('请先登录');
  const guard = publishScope(owner);
  const plugin = await createConnectorPluginStore(localStorage).read(owner, () => { guard(); return true; });
  guard();
  if (!plugin.installed || !plugin.enabled) throw new Error('请先在插件中安装并启用飞书，再发布文档');
  return guard;
}
export const publishToFeishu = async (
  key: string,
  title: string,
  content: string,
  automatic = false,
  options: {
    destination_config?: FeishuDestination;
    permission_policy?: "private" | "inherit";
    notify_self?: boolean;
    groups?: string[];
    version_id?: string;
    revision_id?: string;
    source_mode?: "local_snapshot";
    operation_id?: string;
    recipient_access_policy?: 'grant_view_and_notify';
    contacts?: FeishuContact[];
  } = {},
  attempt?: PublishAttempt,
) => {
  let guard: () => void;
  let body: string;
  try {
    guard = await preflightFeishuPublish();
    if (!key.trim() || key.length > 160 || !title.trim() || !content.trim()) throw new Error('发布标题、正文或内容标识无效，尚未提交');
    if (attempt && attempt.operationId !== options.operation_id) throw new Error('发布操作已变化，尚未提交');
    body = JSON.stringify({
      note_key: key,
      title,
      content,
      automatic,
      ...options,
      ...(options.contacts ? { contacts: contactRecipients(options.contacts) } : {}),
    });
    guard();
    if (!automatic) {
      if (attempt) markPublishAttempt(attempt, 'not_dispatched');
      const pending = await readAutomaticDelivery(key);
      guard();
      if (pending && ['queued', 'submitting', 'unknown'].includes(pending.status)) throw new Error('自动交付正在等待或结果尚未确认，请先核验交付结果，不会重复发送');
    }
  } catch (cause) {
    if (attempt) markPublishAttempt(attempt, 'not_dispatched');
    throw cause;
  }
  if (attempt) markPublishAttempt(attempt, 'unknown');
  const result = await apiJson<Delivery | null>("/api/feishu/deliveries", { method: "POST", body });
  guard();
  return result;
};
export const retryDelivery = (id: string, recipients?: string[]) =>
  apiJson<Delivery>(
    "/api/feishu/deliveries/" + encodeURIComponent(id) + "/retry",
    {
      method: "POST",
      ...(recipients ? { body: JSON.stringify({ recipients }) } : {}),
    },
  );

export async function openExternal(url: string) {
  if (!/^https:\/\/(accounts\.feishu\.cn|[a-z0-9.-]+\.feishu\.cn)\//.test(url))
    throw new Error("飞书链接无效");
  // Native Windows/macOS/Linux opener is used by the Tauri command; browsers use a new tab.
  const { isTauri, invoke } = await import("@tauri-apps/api/core");
  if (isTauri()) await invoke("open_external_url", { url });
  else window.open(url, "_blank", "noopener,noreferrer");
}
