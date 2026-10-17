import { apiJson } from "./api";
import type { FormattingReceipt } from './feishuFormatting';
import { useAuthStore } from '@/stores/authStore';
import { publishScope, markPublishAttempt, type PublishAttempt } from './feishuPublishReceipt';
import { createConnectorPluginStore } from './connectorPlugins';

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
  publish_receipt_protocol?: number;
  contact_selection_protocol?: number;
  recipient_access_protocol?: number;
  setup?: { ready: boolean; missing: string[] };
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
export type FeishuAuthorization = { url: string; qr_data_url: string; expires_at: number };
export type FeishuGroup = { chat_id: string; name: string };
export type FeishuContact = { open_id: string; selection_token: string; name?: string; expiresAt?: number };
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
export const feishuGroups = () => apiJson<FeishuGroup[]>("/api/feishu/groups");
export const deliveryStatus = (key: string) =>
  apiJson<Delivery | null>("/api/feishu/deliveries/" + encodeURIComponent(key));
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
