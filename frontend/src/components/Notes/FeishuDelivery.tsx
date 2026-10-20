import { feishuVerificationUnavailable, feishuVerificationMessage } from '@/lib/feishuConnectionState'
import { useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { feishuSettingsReturn, takeFeishuDeliveryReturn } from '@/lib/feishuDeliveryReturn';
import { Send } from "lucide-react";
import { createConnectorPluginStore, type ConnectorPluginState } from '@/lib/connectorPlugins';
import { feishuFormattingMessage } from '@/lib/feishuFormatting';
import { useAuthStore } from "@/stores/authStore";
import { readPublishDraft, newPublishDraft, persistPublishDraft, queryPublishReceipt, publishScope, beginPublishAttempt, restoreUndispatchedDraft, type PublishAttempt, type PublishDraft } from "@/lib/feishuPublishReceipt";
import { beginRetryReceipt, readRetryReceipt, observeRetryReceipt, type RetryReceipt } from '@/lib/feishuRetryReceipt';
import {
  deliveryStatus,
  deliveryById,
  publishToFeishu,
  preflightFeishuPublish,
  retryDelivery,
  verifyDeliveryPermissions,
  recoverDeliveryDocument,
  openExternal,
  feishuStatus,
  feishuGroups,
  feishuContacts,
  contactsValid,
  contactRecipients,
  type FeishuContact,
  type Delivery,
  type FeishuStatus,
  type FeishuGroup,
  type DestinationCheck,
  type FeishuDestination,
} from "@/lib/feishu";
import { FeishuDestinationPicker } from "@/components/Settings/FeishuDestinationPicker";
import { FeishuMeetingContainerRecovery } from './FeishuMeetingContainerRecovery';
import { isTauriRuntime } from '@/lib/desktopMicrophonePermission';
import { ErrorState, LoadingState } from "@/components/Feedback/ResourceState";
import { MarkdownContent } from "@/components/Markdown/MarkdownContent";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Field,
  FieldLabel,
  FieldSet,
  FieldLegend,
} from "@/components/ui/field";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

const phases: Record<string, string> = {
  awaiting_authorization: "等待授权",
  pending_create: "等待创建",
  writing: "写入正文",
  setting_permissions: "核验访问权限",
  notifying: "通知中",
  partial_success: "部分完成",
  permission_unknown: "阅读权限结果未知",
  completed: "完成",
  unknown: "结果未知",
  failed: "需处理",
};
const recipientLabels: Record<string, string> = {
  pending: "待发送",
  sending: "正在发送",
  sent: "已发送",
  failed: "发送失败",
  unknown: "发送结果未知，需外部核验",
  permission_unknown: "阅读权限结果未知",
};

export function FeishuDelivery({
  noteId,
  title,
  content,
  disabled = false,
  onClose,
}: {
  noteId: string;
  title: string;
  content: string;
  disabled?: boolean;
  onClose?: () => void;
  versionId?: string;
  revisionId?: string;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const owner = useAuthStore(s => s.user?.id);
  // Keep deliberate publication separate from retired workspace records with
  // the same content ID. Old frozen receipts retain their original note key.
  const publicationKey = `publish:${noteId}`;
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const result = takeFeishuDeliveryReturn(location.pathname + location.search + location.hash, owner, noteId, disabled);
    if (!result) return;
    navigate(result.clean, { replace: true, state: location.state });
    if (result.reopen) setOpen(true);
  }, [location.pathname, location.search, location.hash, owner, noteId, disabled, navigate]);
  const [job, setJob] = useState<Delivery | null>(null);
  const jobRef = useRef<Delivery | null>(null);
  const rememberJob = (value: Delivery | null) => { jobRef.current = value; setJob(value); };
  const [preferences, setPreferences] = useState<FeishuStatus | null>(null);
  const [plugin, setPlugin] = useState<ConnectorPluginState | null>(null);
  const [pluginLoading, setPluginLoading] = useState(false);
  const [pluginError, setPluginError] = useState('');
  const pluginSequence = useRef(0), pluginLock = useRef(false);
  const [groups, setGroups] = useState<FeishuGroup[]>([]);
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const [notifySelf, setNotifySelf] = useState(false);
  const [destination, setDestination] = useState<FeishuDestination>({
    kind: "personal",
  });
  const [checked, setChecked] = useState<DestinationCheck | null>(null);
  const [error, setError] = useState("");
  const [groupError, setGroupError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [connectionLoading, setConnectionLoading] = useState(false);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [groupsLoaded, setGroupsLoaded] = useState(false);
  const connectionSequence = useRef(0), groupSequence = useRef(0), contactSequence = useRef(0);
  const connectionInitialized = useRef(false);
  const groupLock = useRef(false);
  const groupAttempted = useRef(false);
  const [contactQuery, setContactQuery] = useState('');
  const [contactItems, setContactItems] = useState<FeishuContact[]>([]);
  const [selectedContacts, setSelectedContacts] = useState<FeishuContact[]>([]);
  const [contactPage, setContactPage] = useState('');
  const [contactHasMore, setContactHasMore] = useState(false);
  const [contactLoading, setContactLoading] = useState(false);
  const [contactLoaded, setContactLoaded] = useState(false);
  const [contactError, setContactError] = useState('');
  const contactAttempt = useRef({ query: '', page: '', append: false });
  const [busy, setBusy] = useState(false);
  const actionLock = useRef(false);
  const [showRecipients, setShowRecipients] = useState(false);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const [recoveryUrl, setRecoveryUrl] = useState("");
  const [snapshot, setSnapshot] = useState<PublishDraft['snapshot']>({
    title,
    content,
  });
  const [uncertain, setUncertain] = useState(false);
  const [retryPending, setRetryPending] = useState<RetryReceipt | null>(null);
  const [retryReads, setRetryReads] = useState(0);
  const retryReadAbort = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const [receipt, setReceipt] = useState<PublishDraft | null>(null);
  const receiptRef = useRef<PublishDraft | null>(null);
  const remember = (value: PublishDraft | null) => { receiptRef.current = value; setReceipt(value); };
  const frozen = !!receipt && receipt.state !== "draft";
  const running = job && ["queued", "processing"].includes(job.status);
  const verificationUnavailable = feishuVerificationUnavailable(preferences);
  const contactSupported = preferences?.contact_selection_protocol === 1 && preferences?.capabilities?.contact_search === true;
  const grantingRecipients = selectedGroups.length > 0 || selectedContacts.length > 0;
  const permissionUnknown = (recipient: Delivery['recipients'][string]) => recipient.status === 'permission_unknown' || ['granting', 'unknown'].includes(recipient.reading_permission?.status || '');
  const hasUnknownPermission = !!job && Object.values(job.recipients).some(permissionUnknown);
  const permissionRecovery = hasUnknownPermission || job?.phase === 'permission_unknown';
  const hasUnknownMessage = job?.phase === 'unknown' || !!job && Object.values(job.recipients).some(recipient => recipient.status === 'unknown');
  const continueNotifications = job?.status === 'failed' && job.phase === 'partial_success' && !permissionRecovery && !hasUnknownMessage && Object.values(job.recipients).some(recipient => recipient.status === 'pending' && recipient.reading_permission?.status === 'verified');
  const recipientSummary = [
    ...(notifySelf ? [`本人${preferences?.name ? `（${preferences.name}）` : ''}`] : []),
    ...selectedGroups.map(id => groups.find(group => group.chat_id === id)?.name || '群名称待核验'),
    ...selectedContacts.map(contact => contact.name?.trim() || '联系人姓名待核验'),
  ].join('、');
  const draftOptions = (): PublishDraft['options'] => ({ destination_config: destination, permission_policy: destination.kind === 'personal' ? 'private' : 'inherit', notify_self: notifySelf, groups: selectedGroups, ...(selectedContacts.length ? { contacts: selectedContacts } : {}), ...(grantingRecipients ? { recipient_access_policy: 'grant_view_and_notify' as const } : {}) });
  const selectionDisabled = busy || frozen || uncertain || !!running || verificationUnavailable || !preferences?.connected || preferences.expired;
  const checkedTarget = !!checked?.can_attempt_create && checked.kind === destination.kind &&
    (destination.kind !== 'folder' || checked.kind === 'folder' && checked.folder_token === destination.folder_token) &&
    (destination.kind !== 'wiki' || checked.kind === 'wiki' && checked.space_id === destination.space_id && checked.node_token === destination.node_token);
  const loadPlugin = async (activate = false) => {
    if (!owner || pluginLock.current) return;
    pluginLock.current = true;
    const request = ++pluginSequence.current;
    setPluginLoading(true); setPluginError('');
    try {
      const guard = publishScope(owner);
      const current = () => { guard(); if (request !== pluginSequence.current) throw new Error('发布面板已变化'); return true; };
      const store = createConnectorPluginStore(localStorage);
      if (activate) await store.save(owner, { installed: true, enabled: true }, current);
      const next = await store.read(owner, current);
      current(); setPlugin(next);
    } catch (cause) { if (request === pluginSequence.current) { setPlugin(null); setPluginError((cause as Error).message); } }
    finally { if (request === pluginSequence.current) { pluginLock.current = false; setPluginLoading(false); } }
  };
  const loadGroups = async () => {
    if (!owner || groupLock.current) return;
    groupLock.current = true;
    groupAttempted.current = true;
    const request = ++groupSequence.current;
    setGroupsLoading(true); setGroupError('');
    try {
      const guard = publishScope(owner);
      const list = await feishuGroups(); guard();
      if (request !== groupSequence.current) return;
      setGroups(list); setGroupsLoaded(true);
    } catch (cause) { if (request === groupSequence.current) setGroupError((cause as Error).message); }
    finally { if (request === groupSequence.current) { groupLock.current = false; setGroupsLoading(false); } }
  };
  const loadConnection = async () => {
    if (!owner) return;
    const request = ++connectionSequence.current;
    setConnectionLoading(true); setConnectionError('');
    try {
      const guard = publishScope(owner);
      const status = await feishuStatus(); guard();
      if (request !== connectionSequence.current) return;
      setPreferences(status);
      if (!connectionInitialized.current) {
        const saved = receiptRef.current;
        setNotifySelf(saved?.options.notify_self ?? status.notify_self);
        setSelectedGroups(saved?.options.groups ?? status.groups);
        setSelectedContacts(saved?.options.contacts || []);
        setDestination(saved?.options.destination_config || status.destination_config || { kind: 'personal' });
        setShowRecipients(savedRecipients(status));
        connectionInitialized.current = true;
      }
      if (status.connected && !status.expired && !feishuVerificationUnavailable(status) && (showRecipients || savedRecipients(status))) void loadGroups();
    } catch (cause) { if (request === connectionSequence.current) setConnectionError((cause as Error).message); }
    finally { if (request === connectionSequence.current) setConnectionLoading(false); }
  };
  const savedRecipients = (status: FeishuStatus) => {
    const options = receiptRef.current?.options;
    return !!(options?.groups ?? status.groups).length || !!options?.contacts?.length;
  };
  const searchContacts = async (attempt = { query: contactQuery.trim(), page: '', append: false }) => {
    if (!owner || selectionDisabled || !contactSupported || contactLoading || !attempt.query) return;
    const request = ++contactSequence.current;
    contactAttempt.current = attempt;
    setContactLoading(true); setContactError('');
    try {
      const guard = publishScope(owner);
      const result = await feishuContacts(attempt.query, attempt.page); guard();
      if (request !== contactSequence.current) return;
      setContactItems(previous => Array.from(new Map([...(attempt.append ? previous : []), ...result.items].map(item => [item.open_id, item])).values()));
      setContactPage(result.page_token); setContactHasMore(result.has_more); setContactLoaded(true);
    } catch (cause) { if (request === contactSequence.current) setContactError((cause as Error).message); }
    finally { if (request === contactSequence.current) setContactLoading(false); }
  };
  const refresh = async () => {
    const request = ++sequence.current;
    setLoading(true);
    try {
      if (!owner) throw new Error("请重新登录");
      const guard = publishScope(owner);
      const saved = readPublishDraft(owner, noteId);
      if (saved) remember(saved);
      const pending = readRetryReceipt(owner, noteId);
      const exact = !pending && saved && saved.state !== "draft" ? await queryPublishReceipt(saved) : null;
      let result: Delivery | null;
      if (pending) {
        const controller = new AbortController();
        retryReadAbort.current = controller;
        const timeout = setTimeout(() => controller.abort(), 10000);
        try { result = await deliveryById(pending.jobId, controller.signal); }
        finally { clearTimeout(timeout); if (retryReadAbort.current === controller) retryReadAbort.current = null; }
      } else if (exact) result = exact.job;
      else if (jobRef.current) {
        const id = jobRef.current.id;
        result = await deliveryById(id);
        if (!result || result.id !== id) throw new Error('返回回执不属于原发布任务');
      } else result = await deliveryStatus(saved?.snapshot.versionId ? noteId : publicationKey);
      guard();
      if (request !== sequence.current) return;
      setRetryPending(result ? observeRetryReceipt(owner, noteId, result) : pending);
      if (exact) remember(exact.draft);
      rememberJob(result);
      setReady(true);
      setError("");
      setUncertain(false); // Only an exact query can settle a dispatched intent.
    } catch (cause) {
      if (request === sequence.current) setError((cause as Error).message);
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  };
  useEffect(() => {
    if (!open) return;
    let saved: PublishDraft | null;
    try { if (!owner) throw new Error("请重新登录"); saved = readPublishDraft(owner, noteId); }
    catch (cause) { setError((cause as Error).message); setReady(false); setUncertain(true); return; }
    remember(saved);
    rememberJob(null);
    setSnapshot(saved?.snapshot || { title, content });
    setReady(false);
    setPreferences(null);
    setPlugin(null); setPluginError('');
    connectionInitialized.current = false;
    setConnectionError(''); setGroups([]); setGroupsLoaded(false); setGroupsLoading(false);
    groupAttempted.current = false;
    setSelectedContacts(saved?.options.contacts || []);
    setContactQuery(''); setContactItems([]); setContactPage(''); setContactHasMore(false); setContactLoaded(false); setContactLoading(false); setContactError('');
    setChecked(null);
    setShowRecipients(false);
    setError("");
    setGroupError("");
    setUncertain(saved?.state === "unknown");
    setRetryPending(null); setRetryReads(0);
    void refresh();
    void loadConnection();
    void loadPlugin();
    return () => {
      retryReadAbort.current?.abort();
      sequence.current++;
      actionLock.current = false;
      setBusy(false);
      connectionSequence.current++; groupSequence.current++; contactSequence.current++;
      pluginSequence.current++; pluginLock.current = false;
      groupLock.current = false;
    };
  }, [open, noteId, owner]);
  useEffect(() => {
    if (!open || !ready || !owner || !preferences || !connectionInitialized.current || frozen || busy) return;
    try {
      const options = draftOptions();
      const draft = receiptRef.current || newPublishDraft(owner, noteId, snapshot, options);
      const next = { ...draft, options };
      persistPublishDraft(next);
      remember(next);
    } catch (cause) { setError((cause as Error).message); setUncertain(true); }
  }, [open, ready, owner, preferences, destination, notifySelf, selectedGroups, selectedContacts, frozen, busy]);
  useEffect(() => {
    if (!open || busy || loading || !running || retryPending) return;
    // Schedule after the previous read completes; never overlap polls.
    const timer = setTimeout(() => void refresh(), 2500);
    return () => clearTimeout(timer);
  }, [open, busy, job, running, loading, retryPending]);
  useEffect(() => {
    if (!open || busy || loading || !retryPending || retryReads <= 0) return;
    const timer = setTimeout(() => { setRetryReads(left => left - 1); void refresh(); }, 2500);
    return () => clearTimeout(timer);
  }, [open, busy, loading, retryPending, retryReads]);
  const act = async (retry = false, recipients?: string[]) => {
    if (actionLock.current || busy || !ready || loading || uncertain || retryPending || receiptRef.current?.state === 'unknown' || hasUnknownMessage || (retry && permissionRecovery)) return;
    actionLock.current = true;
    const request = sequence.current;
    setBusy(true);
    setError("");
    let dispatched = false;
    let attempt: PublishAttempt | undefined;
    try {
      if (!owner) throw new Error('请重新登录');
      const guard = publishScope(owner);
      const service = await feishuStatus();
      guard();
      if (request !== sequence.current) return;
      if (service.publish_receipt_protocol !== 1) throw new Error('飞书服务需要升级发布回执协议；尚未提交，原草稿保留');
      if (feishuVerificationUnavailable(service)) throw new Error(feishuVerificationMessage);
      if (!service.configured || !service.connected || service.expired) throw new Error('请先连接飞书，再创建文档');
      if (!retry && selectedContacts.length && (service.contact_selection_protocol !== 1 || service.capabilities?.contact_search !== true)) throw new Error('飞书服务尚未支持当前联系人选择，尚未提交；原选择保留');
      if (!retry && !contactsValid(selectedContacts)) throw new Error('联系人选择已过期，请移除后重新搜索选择；尚未提交');
      if (!retry && grantingRecipients && service.recipient_access_protocol !== 1) throw new Error('飞书服务尚未支持向所选联系人或群授予阅读权限，尚未提交；原选择保留');
      let intent = receiptRef.current;
      if (!retry && !(intent?.snapshot.versionId || snapshot.versionId) && publicationKey.length > 160) throw new Error('内容标识过长，无法创建飞书发布记录');
      if (!retry) {
        if (!checkedTarget || !snapshot.title.trim() || !snapshot.content.trim() || (destination.kind === 'folder' && !destination.folder_token) || (destination.kind === 'wiki' && (!destination.space_id || !destination.node_token))) throw new Error('请检查标题、正文与文档位置，尚未提交');
        await preflightFeishuPublish();
        guard();
        if (request !== sequence.current) return;
        if (!contactsValid(selectedContacts)) throw new Error('联系人选择已过期，请移除后重新搜索选择；尚未提交');
        if (intent && intent.state !== 'draft') throw new Error('请明确准备新的发布草稿；原交付保留');
        const options = draftOptions();
        intent ??= newPublishDraft(owner, noteId, snapshot, options);
        intent = { ...intent, options, state: 'draft' };
        persistPublishDraft(intent);
        attempt = beginPublishAttempt(intent, () => { if (request !== sequence.current) throw new Error('发布面板已变化，原草稿保留'); });
        intent = { ...intent, state: 'unknown' };
        persistPublishDraft(intent);
        remember(intent);
      }
      if (retry && job) {
        setRetryPending(beginRetryReceipt(owner, noteId, job.id));
        setRetryReads(12);
      }
      dispatched = true;
      const next =
        retry && job
          ? await retryDelivery(job.id, recipients)
          : await publishToFeishu(
              intent!.snapshot.versionId ? intent!.noteKey : publicationKey,
              intent!.snapshot.title,
              intent!.snapshot.content,
              false,
              {
                ...intent!.options,
                ...(intent!.options.contacts ? { contacts: contactRecipients(intent!.options.contacts) } : {}),
                operation_id: intent!.operationId,
                ...(!intent!.snapshot.versionId ? { source_mode: 'local_snapshot' as const } : {}),
                ...(intent!.snapshot.versionId
                  ? {
                      version_id: intent!.snapshot.versionId,
                      revision_id: intent!.snapshot.revisionId,
                    }
                  : {}),
              },
              attempt,
            );
      guard();
      if (request !== sequence.current) return;
      if (!next || (retry ? next.id !== job?.id : next.operation_id !== intent!.operationId)) throw new Error("未收到原发布回执，请查询原操作，不自动重新发布");
      if (intent && !retry) { const confirmed = { ...intent, state: 'acknowledged' as const, jobId: next.id }; persistPublishDraft(confirmed); remember(confirmed); }
      rememberJob(next);
    } catch (cause) {
      if (request === sequence.current) {
        let restored = false;
        try {
          if (attempt) { const draft = restoreUndispatchedDraft(attempt); if (draft) { remember(draft); restored = true; } }
        } catch { /* Changed identity/Origin must preserve the original receipt. */ }
        setError((cause as Error).message); setUncertain(dispatched && !restored);
        void loadPlugin();
      }
    } finally {
      if (request === sequence.current) { actionLock.current = false; setBusy(false); }
    }
  };
  const verifyPermissions = async () => {
    if (actionLock.current || busy || loading || !ready || !owner || !job || !permissionRecovery) return;
    const request = sequence.current, original = job;
    actionLock.current = true; setBusy(true); setError('');
    try {
      const guard = publishScope(owner);
      const next = await verifyDeliveryPermissions(original.id);
      guard();
      if (request !== sequence.current) return;
      if (next.id !== original.id || (original.operation_id && next.operation_id !== original.operation_id)) throw new Error('权限核验回执不属于原发布操作');
      rememberJob(next);
      // Neither an ambiguous retry POST nor message/body uncertainty is settled
      // by checking access. Keep their receipts/guards and never auto-continue.
    } catch (cause) {
      if (request === sequence.current) setError((cause as Error).message);
    } finally {
      if (request === sequence.current) { actionLock.current = false; setBusy(false); }
    }
  };
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        disabled={disabled}
        title={disabled ? "请先保存修改，再发布" : undefined}
        onClick={() => setOpen(true)}
      >
        <Send />
        发布到飞书
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!busy) {
            setOpen(next);
            if (!next) onClose?.();
          }
        }}
      >
        <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden sm:max-w-2xl">
          <DialogHeader className="shrink-0 pr-8">
            <DialogTitle>发布到飞书</DialogTitle>
            <DialogDescription>
              {preferences?.connected && !preferences.expired ? `已连接 · ${preferences.name || "飞书账号"}` : "创建文档，可同时发送通知。"}
            </DialogDescription>
          <Button className="h-auto w-fit p-0 text-xs" variant="link" disabled={busy || loading || !owner} onClick={() => {
                try {
                  if (!owner) return;
                  const target = feishuSettingsReturn(location.pathname + location.search + location.hash, owner, noteId, receiptRef.current?.operationId);
                  setOpen(false);
                  navigate(target);
                } catch (cause) { setError((cause as Error).message); }
              }}>管理飞书连接</Button>
          </DialogHeader>
          <div className="flex min-h-0 flex-col gap-5 overflow-y-auto">
          {error && (
            <ErrorState
              error={error}
              onRetry={() => void refresh()}
              busy={busy || loading}
              retryLabel="核验交付状态"
            />
          )}
          {connectionLoading && <LoadingState label="正在读取飞书连接…" rows={1} />}
          {connectionError && <ErrorState error={connectionError} onRetry={() => void loadConnection()} busy={busy || connectionLoading} retryLabel="重新读取飞书连接" />}
          {pluginLoading && <p role="status" className="text-sm text-muted-foreground">正在读取飞书插件状态…</p>}
          {pluginError && <ErrorState error={pluginError} onRetry={() => void loadPlugin()} busy={pluginLoading} retryLabel="重新读取插件状态" />}
          {plugin && (!plugin.installed || !plugin.enabled) && <Alert>
            <AlertDescription>
              <p>{plugin.installed ? '飞书插件已停用' : '飞书插件尚未安装'}</p>
              <Button variant="outline" disabled={pluginLoading || busy} onClick={() => void loadPlugin(true)}>启用飞书插件</Button>
            </AlertDescription>
          </Alert>}
          {preferences && preferences.publish_receipt_protocol !== 1 && <Alert><AlertDescription>飞书服务需要升级发布回执协议，暂不能新发布或重试交付；原草稿与未确认请求保留。</AlertDescription></Alert>}
          {!ready && loading && (
            <LoadingState label="正在读取交付状态…" rows={1} />
          )}
          {preferences && !preferences.configured && (
            <Alert>
              <AlertDescription>
                飞书接入尚未配置，请由管理员配置企业应用；Markdown
                导出仍可使用。
              </AlertDescription>
            </Alert>
          )}
          {preferences && (verificationUnavailable || !preferences.connected || preferences.expired) && (
            <Alert>
              <AlertDescription>
                {verificationUnavailable ? feishuVerificationMessage : "需连接或重新授权飞书。当前发布内容保留，完成授权后重新打开发布面板核验。"}
              </AlertDescription>
              {verificationUnavailable && <Button variant="outline" disabled={busy || loading} onClick={() => void loadConnection()}>重新核验飞书连接</Button>}
            </Alert>
          )}
          {job && (
            <section className="flex flex-col gap-3 border-t pt-4">
              <h2 className="font-medium">{job.status === "completed" ? "文档已创建" : "发布结果"}</h2>
              <Badge
                variant={job.status === "failed" ? "destructive" : "secondary"}
                className="w-fit"
              >
                {phases[job.phase || ""] ||
                  (job.status === "completed"
                    ? "完成"
                    : job.status === "failed"
                      ? "需处理"
                      : "处理中")}
              </Badge>
              <p className="text-sm">
                文档：
                {job.document_url
                  ? "已创建，可打开核验"
                  : job.needs_document_recovery
                    ? "创建结果未知"
                    : "尚未确认创建"}
              </p>
              <p className="text-sm">
                权限：
                {job.permission?.status === "verified"
                  ? "已核验"
                  : job.permission?.status === "failed"
                    ? "未通过核验"
                    : job.permission?.status === "legacy_unverified"
                      ? "旧记录未核验"
                      : "尚未确认"}
              </p>
              <p role="status" className="text-xs text-muted-foreground">{feishuFormattingMessage(job.formatting, job.status)}</p>
              {job.permission?.note && <p className="text-xs text-muted-foreground">{job.permission.note}</p>}
              {job.version_id && (
                <p className="text-xs text-muted-foreground">
                  已发布保存修订 {job.revision_id}；历史文档保留。
                </p>
              )}
              {job.document_url && (
                <Button
                  variant="link"
                  className="w-fit px-0"
                  onClick={() =>
                    void openExternal(job.document_url).catch((cause) =>
                      setError(cause.message),
                    )
                  }
                >
                  查看文档链接
                </Button>
              )}
              {job.error && <ErrorState error={job.error} />}
              {isTauriRuntime() && (job.status === 'failed' || job.phase === 'unknown') && <FeishuMeetingContainerRecovery
                key={job.id} deliveryId={job.id} onRecovered={() => { void refresh(); }} />}
              {Object.entries(job.recipients).map(([id, recipient]) => (
                <div key={id} className="flex flex-col gap-2 border-b py-2">
                  <p className="text-sm">
                    {recipient.name} ·{" "}
                    {recipient.status === 'unknown' ? recipientLabels.unknown : permissionUnknown(recipient) ? '阅读权限结果未知' : recipientLabels[recipient.status] || recipient.status}
                  </p>
                  {recipient.error && (
                    <p className="text-xs text-destructive">
                      {recipient.error}
                    </p>
                  )}
                  {(recipient.kind === 'contact' || recipient.reading_permission) && <p className="text-xs text-muted-foreground">文档读取权限：{recipient.reading_permission?.status === 'verified' ? '已核验阅读权限，实际阅读未确认' : permissionUnknown(recipient) ? '结果未知' : '尚未核验'}。{recipient.reading_permission?.note}</p>}
                  {recipient.status === "failed" && !permissionUnknown(recipient) && (
                    <Button
                      variant="outline"
                      disabled={verificationUnavailable || busy || loading || uncertain || permissionRecovery || hasUnknownMessage || !!retryPending || preferences?.publish_receipt_protocol !== 1}
                      onClick={() => void act(true, [id])}
                    >
                      仅重试此失败接收人
                    </Button>
                  )}
                </div>
              ))}
              {permissionRecovery && <div className="flex flex-col gap-2">
                <p className="text-xs text-muted-foreground">仅核验已有阅读权限，不重复授权或发送通知。核验通过后可另行继续通知。</p>
                <Button variant="outline" disabled={busy || loading || !ready || verificationUnavailable} onClick={() => void verifyPermissions()}>核验阅读权限</Button>
              </div>}
              {continueNotifications && <p className="text-sm text-muted-foreground">阅读权限已核验，通知尚未发送。点击“继续通知”将发送文档链接。</p>}
            </section>
          )}
          {frozen && <p className="text-xs text-muted-foreground">此次发布的内容、位置与收件人已固定。</p>}
          <details open={!frozen}>
          <summary className={frozen ? "cursor-pointer text-sm font-medium" : "hidden"}>发布内容与选择</summary>
          <div className="mt-4 flex flex-col gap-5">
          <section className="flex flex-col gap-2 border-b pb-4">
            <h2 className="font-medium break-words">{snapshot.title}</h2>
            {(snapshot.versionId || snapshot.revisionId || frozen) && <p className="text-xs text-muted-foreground">
              {snapshot.versionId && !snapshot.versionId.startsWith('__vinote:current:')
                ? '此次发布固定历史版本'
                : '此次发布固定正文'}
              {snapshot.revisionId ? ` · 保存修订 ${snapshot.revisionId}` : ' · 已确认正文快照'}
            </p>}
            <details>
              <summary className="cursor-pointer text-sm">预览发布正文</summary>
              <div className="max-h-64 overflow-auto py-3">
                <MarkdownContent
                  content={snapshot.content}
                  className="prose prose-sm max-w-none break-words dark:prose-invert"
                />
              </div>
            </details>
          </section>
          <section className="flex flex-col gap-3 border-b pb-4">
            <FeishuDestinationPicker
              key={`${owner}:${noteId}`}
              autoCheck
              value={destination}
              onChange={setDestination}
              capabilities={verificationUnavailable ? undefined : preferences?.capabilities}
              disabled={
                verificationUnavailable || busy ||
                frozen || uncertain ||
                !!running ||
                !preferences?.connected ||
                preferences.expired
              }
              onChecked={setChecked}
            />
            <p className="text-xs text-muted-foreground">
              {destination.kind === "personal" ? "关闭链接及组织外分享。" : "沿用目标位置的访问权限。"}
            </p>
          </section>
          <details open={showRecipients} onToggle={event => {
            const expanded = event.currentTarget.open;
            setShowRecipients(expanded);
            if (expanded && !groupAttempted.current && !selectionDisabled) void loadGroups();
          }}>
          <summary className="cursor-pointer break-words text-sm font-medium">{recipientSummary ? `通知 · ${recipientSummary}` : '通知（可选）'}</summary>
          <FieldSet className="mt-4" hidden={!showRecipients}
            disabled={
              verificationUnavailable || busy ||
              frozen || uncertain ||
              !!running ||
              !preferences?.connected ||
              preferences.expired
            }
          >
            <FieldLegend className="sr-only">通知收件人</FieldLegend>
            <p className="text-sm text-muted-foreground">{frozen && receipt?.options.recipient_access_policy !== 'grant_view_and_notify'
              ? '此发布保留原权限约定；联系人仅核验已有阅读权限，群按原选择处理。'
              : '所选联系人/群获得阅读权限并收到链接，不授予编辑权限；通知失败保留文档和权限。'}</p>
            {grantingRecipients && preferences?.recipient_access_protocol !== 1 && !frozen && <p role="status" className="text-sm text-destructive">飞书服务尚未支持收件人阅读授权，请升级服务或仅通知本人。</p>}
            <Field orientation="horizontal">
              <Checkbox
                id="publish-self"
                checked={notifySelf}
                onCheckedChange={(value) => setNotifySelf(value === true)}
              />
              <FieldLabel htmlFor="publish-self">发给本人</FieldLabel>
            </Field>
            {groups.map((group) => (
              <Field key={group.chat_id} orientation="horizontal">
                <Checkbox
                  id={`publish-${group.chat_id}`}
                  checked={selectedGroups.includes(group.chat_id)}
                  onCheckedChange={(value) =>
                    setSelectedGroups((old) =>
                      value
                        ? [...old, group.chat_id]
                        : old.filter((id) => id !== group.chat_id),
                    )
                  }
                />
                <FieldLabel htmlFor={`publish-${group.chat_id}`}>
                  {group.name}
                </FieldLabel>
              </Field>
            ))}
            {selectedGroups
              .filter((id) => !groups.some((g) => g.chat_id === id))
              .map((id) => (
                <Field key={id} orientation="horizontal">
                  <Checkbox
                    id={`publish-${id}`}
                    checked
                    onCheckedChange={() =>
                      setSelectedGroups((old) =>
                        old.filter((value) => value !== id),
                      )
                    }
                  />
                  <FieldLabel htmlFor={`publish-${id}`}>
                    已选群（当前未核验）
                  </FieldLabel>
                </Field>
              ))}
            {groupsLoading && <LoadingState label="正在读取通知群…" rows={1} />}
            {groupError && <ErrorState error={groupError} onRetry={() => void loadGroups()} busy={busy || groupsLoading} retryLabel="重新读取通知群" />}
            {groupsLoaded && !groupsLoading && !groupError && !groups.length && <p className="text-sm text-muted-foreground">没有本人和机器人均可见的通知群。</p>}
            <Button variant="outline" disabled={selectionDisabled || groupsLoading} onClick={() => void loadGroups()}>刷新通知群</Button>
            <Field>
              <FieldLabel htmlFor="publish-contact-query">搜索联系人</FieldLabel>
              <Input id="publish-contact-query" value={contactQuery} maxLength={50} disabled={selectionDisabled || !contactSupported} onChange={event => {
                contactSequence.current++; setContactQuery(event.target.value); setContactItems([]); setContactLoaded(false); setContactPage(''); setContactHasMore(false); setContactError(''); setContactLoading(false);
              }} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void searchContacts(); } }} />
              {verificationUnavailable ? <p>联系人能力暂时无法核验。</p> : !preferences ? <p>联系人能力尚未核验。</p> : preferences.contact_selection_protocol !== 1 ? <p>飞书服务尚未支持联系人选择，暂不可选；本人和群路径仍可使用。</p> : !contactSupported ? <p>当前账号尚未授予联系人搜索权限，暂不可选。</p> : null}
              <Button variant="outline" disabled={selectionDisabled || !contactSupported || contactLoading || !contactQuery.trim()} onClick={() => void searchContacts()}>搜索联系人</Button>
            </Field>
            {contactLoading && <LoadingState label="正在读取联系人…" rows={1} />}
            {contactError && <ErrorState error={contactError} retryLabel="重试联系人读取" busy={contactLoading || selectionDisabled || !contactSupported} onRetry={() => void searchContacts(contactAttempt.current)} />}
            {contactLoaded && !contactLoading && !contactError && !contactItems.length && !contactHasMore && <p role="status">没有匹配的联系人。</p>}
            {contactItems.map(contact => <Field key={contact.open_id} orientation="horizontal">
              <Checkbox id={`contact-${contact.open_id}`} disabled={selectionDisabled || !contactSupported || (!selectedContacts.some(item => item.open_id === contact.open_id) && selectedContacts.length >= 20)} checked={selectedContacts.some(item => item.open_id === contact.open_id)} onCheckedChange={value => setSelectedContacts(previous => value === true ? [...previous.filter(item => item.open_id !== contact.open_id), contact] : previous.filter(item => item.open_id !== contact.open_id))} />
              <FieldLabel htmlFor={`contact-${contact.open_id}`}>{contact.name || '姓名未核验'}</FieldLabel>
            </Field>)}
            {contactHasMore && <Button variant="outline" disabled={selectionDisabled || !contactSupported || contactLoading} onClick={() => void searchContacts({ query: contactAttempt.current.query, page: contactPage, append: true })}>读取下一页联系人</Button>}
            {selectedContacts.map(contact => <div key={contact.open_id} className="flex items-center justify-between gap-2">
              <span>已选联系人：{contact.name || '姓名未核验'}</span>
              <Button variant="outline" disabled={selectionDisabled} onClick={() => setSelectedContacts(previous => previous.filter(item => item.open_id !== contact.open_id))}>移除 {contact.name || '姓名未核验'}</Button>
            </div>)}
            <p className="text-xs text-muted-foreground">
              不选择收件人则仅发布文档，不发送通知。
            </p>
          </FieldSet>
          </details>
          </div>
          </details>
          {job?.needs_document_recovery && (
            <Field>
              <FieldLabel htmlFor="recover-document">
                关联本次已创建的空文档
              </FieldLabel>
              <Input
                id="recover-document"
                value={recoveryUrl}
                disabled={busy}
                onChange={(e) => setRecoveryUrl(e.target.value)}
                placeholder="https://公司.feishu.cn/docx/… 或 /wiki/…"
              />
              <Button
                variant="outline"
                disabled={busy || preferences?.publish_receipt_protocol !== 1 || !recoveryUrl.trim()}
                onClick={async () => {
                  if (actionLock.current || !owner) return;
                  const request = sequence.current;
                  actionLock.current = true;
                  setBusy(true);
                  try {
                    const guard = publishScope(owner);
                    const next = await recoverDeliveryDocument(job.id, recoveryUrl.trim());
                    guard(); if (request !== sequence.current) return;
                    if (next.id !== job.id) throw new Error('返回回执不属于原发布任务');
                    rememberJob(next);
                    setError("");
                    setUncertain(false);
                  } catch (cause) {
                    if (request === sequence.current) setError((cause as Error).message);
                  } finally {
                    if (request === sequence.current) { actionLock.current = false; setBusy(false); }
                  }
                }}
              >
                核验并恢复关联
              </Button>
            </Field>
          )}
          {job?.status === "failed" && (
            <Button
              variant="outline"
              disabled={
                busy ||
                loading ||
                uncertain ||
                permissionRecovery ||
                !!retryPending ||
                job.needs_document_recovery ||
                hasUnknownMessage
                || preferences?.publish_receipt_protocol !== 1
              }
              onClick={() => void act(true)}
            >
              {continueNotifications ? '继续通知' : '从失败步骤恢复，不重发成功通知'}
            </Button>
          )}
          {uncertain && (
            <Alert>
              <AlertDescription>
                先核验现有任务。创建或发送结果未知时，不自动新建文档或再次发送。
              </AlertDescription>
            </Alert>
          )}
          {(uncertain || hasUnknownMessage || job?.needs_document_recovery) && <Button variant="outline" disabled={busy || loading} onClick={() => void refresh()}>查询原发布任务</Button>}
          {retryPending && <Alert><AlertDescription>
            {retryReads > 0 ? '正在查询原任务的重试结果…' : '重试结果尚未确认，请核验原任务；不会再次提交重试。'}
            <Button variant="outline" disabled={busy || loading} onClick={() => setRetryReads(12)}>查询原重试任务</Button>
          </AlertDescription></Alert>}
          {receipt?.state === 'acknowledged' && job?.status === 'completed' && <Button variant="outline" disabled={busy || loading} onClick={() => {
            try {
              if (!owner) throw new Error('请重新登录');
              const next = newPublishDraft(owner, noteId, { title, content }, draftOptions());
              persistPublishDraft(next); remember(next); setSnapshot(next.snapshot); setChecked(null);
            } catch (cause) { setError((cause as Error).message); }
          }}>准备发布当前已保存版本</Button>}
          </div>
          <DialogFooter className="shrink-0 border-t pt-4">
          {frozen && job?.status === 'completed' && job.document_url ? <Button onClick={() => void openExternal(job.document_url).catch(cause => setError((cause as Error).message))}>打开飞书文档</Button> : <Button
            disabled={
              verificationUnavailable || busy ||
              loading ||
              !ready ||
              !preferences?.configured ||
              !plugin?.installed || !plugin.enabled || pluginLoading ||
              !preferences.connected ||
              preferences.expired ||
              !checkedTarget ||
              !!running ||
              uncertain ||
              !!retryPending ||
              frozen ||
              preferences?.publish_receipt_protocol !== 1 ||
              (!!selectedContacts.length && !contactSupported) ||
              (grantingRecipients && preferences?.recipient_access_protocol !== 1) ||
              job?.status === "failed" ||
              !snapshot.title.trim() || !snapshot.content.trim()
            }
            onClick={() => void act()}
          >
            {busy ? "正在提交…" : notifySelf || selectedGroups.length || selectedContacts.length ? "创建并通知" : "创建文档"}
          </Button>}

          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
