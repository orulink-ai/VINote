import { feishuVerificationUnavailable, feishuVerificationMessage } from '@/lib/feishuConnectionState'
import { useEffect, useRef, useState } from "react";
import { useLocation } from 'react-router-dom';
import { ChevronRight } from "lucide-react";
import { FeishuDestinationPicker } from "@/components/Settings/FeishuDestinationPicker";
import { FeishuPresetContacts } from '@/components/Settings/FeishuPresetContacts';
import { FeishuObjectHotwords } from '@/components/Settings/FeishuObjectHotwords';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { apiJson } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";
import { publishScope } from '@/lib/feishuPublishReceipt';
import { createConnectorPluginStore } from '@/lib/connectorPlugins';
import {
  feishuGroups,
  feishuStatus,
  preferenceContacts,
  automaticConsentNeeded,
  disableDeviceAutomaticDelivery,
  openExternal,
  completeFeishuAuthorization,
  isFeishuAuthorization,
  type FeishuGroup,
  type FeishuStatus,
  type DestinationCheck,
  type FeishuAuthorization,
} from "@/lib/feishu";
import { PageHeading } from "@/components/Layout/PageHeading";
import { PageReturn } from '@/components/Layout/PageReturn';
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";

import { FeishuApplicationSetup } from '@/components/Settings/FeishuApplicationSetup'

const pluginStore = createConnectorPluginStore({ getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) });

export function FeishuSettings() {
  const location = useLocation();
  const routeKey = JSON.stringify([location.key, location.pathname, location.search, location.hash]);
  const currentRoute = useRef(routeKey); currentRoute.current = routeKey;
  const owner = useAuthStore((state) => state.user?.id);
  const [identityVisit, setIdentityVisit] = useState(0);
  const draftKey = owner ? `vinote:feishu-preferences:${owner}` : "";
  const [value, setValue] = useState<FeishuStatus | null>(null);
  const valueOwner = useRef<string>();
  const [groups, setGroups] = useState<FeishuGroup[]>([]);
  const [groupPicker, setGroupPicker] = useState(false);
  const [groupError, setGroupError] = useState("");
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [groupsLoaded, setGroupsLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [saveFailed, setSaveFailed] = useState(false);
  const [message, setMessage] = useState("");
  const verificationUnavailable = feishuVerificationUnavailable(value);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [authUrl, setAuthUrl] = useState("");
  const [authorization, setAuthorizationState] = useState<FeishuAuthorization | null>(null);
  const authorizationRef = useRef<FeishuAuthorization | null>(null);
  const setAuthorization = (next: FeishuAuthorization | null) => { authorizationRef.current = next; setAuthorizationState(next) };
  const [authExpired, setAuthExpired] = useState(false);
  const authPending = useRef(false);
  const [disconnect, setDisconnect] = useState(false);
  const savedValue = useRef<FeishuStatus>();
  const editRevision = useRef(0);
  const [consent, setConsent] = useState<{ snapshot: FeishuStatus; revision: number; current: () => boolean; destinationLabel: string; recipientLabel: string } | null>(null);
  const currentValue = useRef(value); currentValue.current = value;
  const canEnableAutomatic = value?.automatic_delivery_protocol === 1 && value.capabilities?.background_delivery === true;
  const cliMode = value?.transport === 'cli';
  const canAuthorize = cliMode ? value?.setup?.cli_available === true : !!value?.configured;
  const [destinationCheck, setDestinationCheck] =
    useState<DestinationCheck | null>(null);
  const renderScope = owner ? publishScope(owner) : null;
  const isCurrentOwner = () => {
    try { renderScope?.(); return !!renderScope && currentRoute.current === routeKey && useAuthStore.getState().user?.id === owner } catch { return false }
  };
  const statusRequest = useRef(0);
  const displayedStatus = statusRequest.current;
  const groupRequest = useRef(0);
  const groupPending = useRef(false);
  const requestGuard = (sequence: { current: number }) => {
    const request = ++sequence.current;
    const scope = owner ? publishScope(owner) : null;
    return () => {
      if (!scope || !isCurrentOwner() || request !== sequence.current || currentRoute.current !== routeKey) return false;
      try { scope(); return true; } catch { return false; }
    };
  };
  const load = async () => {
    if (!owner || !isCurrentOwner()) return false;
    const current = requestGuard(statusRequest);
    const revision = editRevision.current;
    // A fresh connection check invalidates in-flight group results from the earlier grant.
    groupRequest.current++;
    groupPending.current = false;
    setGroupsLoading(false);
    setGroupsLoaded(false);
    setBusy(true);
    setConsent(null);
    setError("");
    setSaveFailed(false);
    try {
      const next = await feishuStatus();
      if (!current()) return false;
      let draft: Partial<FeishuStatus> | undefined;
      try {
        const stored = draftKey && sessionStorage.getItem(draftKey);
        const parsed = stored ? JSON.parse(stored) : null;
        if (
          parsed &&
          typeof parsed.notify_self === "boolean" &&
          typeof parsed.auto_publish === "boolean" &&
          Array.isArray(parsed.groups) &&
          parsed.groups.every((id: unknown) => typeof id === "string")
        )
          draft = {
            notify_self: parsed.notify_self, notify_participants: parsed.notify_participants === true, group_meeting_versions: parsed.group_meeting_versions === true, auto_publish: parsed.auto_publish, groups: parsed.groups,
            destination_config: parsed.destination_config, permission_policy: parsed.permission_policy,
            ...(Array.isArray(parsed.contacts) ? { contacts: parsed.contacts.filter((contact: { open_id?: unknown }) => contact && typeof contact.open_id === 'string' && /^ou_[A-Za-z0-9_-]+$/.test(contact.open_id)).map((contact: { open_id: string }) => ({ open_id: contact.open_id, name: '' })) } : {}),
          };
      } catch {
        /* Browser storage may be unavailable; the visible form still works. */
      }
      if (!draft && dirty && value && valueOwner.current === owner)
        draft = {
          notify_self: value.notify_self,
          notify_participants: value.notify_participants === true,
          group_meeting_versions: value.group_meeting_versions === true,
          auto_publish: value.auto_publish,
          groups: value.groups,
          destination_config: value.destination_config,
          permission_policy: value.permission_policy,
          contacts: value.contacts,
        };
      if (revision !== editRevision.current && currentValue.current && valueOwner.current === owner) {
        const latest = currentValue.current;
        draft = { notify_self: latest.notify_self, notify_participants: latest.notify_participants === true, group_meeting_versions: latest.group_meeting_versions === true, auto_publish: latest.auto_publish, groups: latest.groups, contacts: latest.contacts, destination_config: latest.destination_config, permission_policy: latest.permission_policy };
      }
      valueOwner.current = owner;
      savedValue.current = next;
      if (draft?.contacts) draft.contacts = draft.contacts.map(contact => (next.contacts || []).find(saved => saved.open_id === contact.open_id) || { open_id: contact.open_id, name: '待重新选择联系人' });
      setValue({ ...next, ...draft });
      const connected = next.connected && !next.expired && !feishuVerificationUnavailable(next);
      if (!authorizationRef.current?.flow_id && connected) {
        setAuthUrl(''); setAuthorization(null); setAuthExpired(false);
        if (!draft) setMessage('');
      } else if (authUrl && !connected) setMessage(feishuVerificationUnavailable(next) ? feishuVerificationMessage : next.expired ? '需要重新授权，请使用新的授权链接。' : '尚未收到飞书授权，请完成后再次核验。');
      setDirty(!!draft);
      if (draft) setMessage("已恢复未保存的设置，请核对后保存。");
      setGroupError("");
      if (!next.connected || next.expired || feishuVerificationUnavailable(next)) {
        setGroups([]);
        setGroupPicker(false);
      }
      return true;
    } catch (cause) {
      if (!current()) return false;
      setError(cause instanceof Error ? cause.message : "读取失败，请重试");
      return false;
    } finally {
      if (current()) setBusy(false);
    }
  };
  const loadGroups = async () => {
    if (groupPending.current || busy || !owner || !isCurrentOwner() || !value?.connected || value.expired || verificationUnavailable) return;
    const current = requestGuard(groupRequest);
    groupPending.current = true;
    setGroupsLoading(true);
    setGroupError("");
    try {
      const nextGroups = await feishuGroups();
      if (!current()) return;
      setGroups(nextGroups);
      setGroupsLoaded(true);
    } catch (cause) {
      if (current()) setGroupError(cause instanceof Error ? cause.message : "读取群列表失败");
    } finally {
      if (current()) {
        groupPending.current = false;
        setGroupsLoading(false);
      }
    }
  };
  useEffect(() => {
    if (groupPicker && !groupsLoaded && !groupError && !busy) void loadGroups();
  }, [groupPicker, groupsLoaded, groupError, busy, value?.connected, value?.expired, verificationUnavailable]);
  useEffect(() => useAuthStore.subscribe((state, previous) => {
    if (state.user?.id !== previous.user?.id) {
      ++statusRequest.current; ++groupRequest.current; groupPending.current = false;
      authPending.current = false;
      setIdentityVisit(visit => visit + 1);
    }
  }), []);
  useEffect(() => {
    valueOwner.current = undefined;
    setValue(null);
    setGroups([]);
    setDirty(false);
    setMessage("");
    setAuthUrl("");
    setAuthorization(null);
    authPending.current = false;
    setAuthExpired(false);
    setGroupPicker(false);
    setGroupError("");
    setGroupsLoading(false);
    setGroupsLoaded(false);
    setQuery("");
    setDestinationCheck(null);
    setDisconnect(false);
    setBusy(false); setSaveFailed(false);
    savedValue.current = undefined;
    setConsent(null); ++editRevision.current;
    void load();
    return () => {
      statusRequest.current++;
      groupRequest.current++;
      groupPending.current = false;
      authPending.current = false;
    };
  }, [owner, identityVisit, routeKey]);
  useEffect(() => {
    if (!authorization) return;
    const timer = window.setTimeout(() => setAuthExpired(true), Math.max(0, authorization.expires_at * 1000 - Date.now()));
    return () => window.clearTimeout(timer);
  }, [authorization]);
  useEffect(() => {
    if (!authUrl || authorization?.flow_id || cliMode) return;
    const verify = () => {
      if (document.visibilityState === "visible") void load();
    };
    window.addEventListener("focus", verify);
    return () => window.removeEventListener("focus", verify);
  }, [authUrl, authorization, cliMode]);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  const change = (patch: Partial<FeishuStatus>) => {
    if (!isCurrentOwner() || valueOwner.current !== owner || displayedStatus !== statusRequest.current) return;
    ++editRevision.current;
    setConsent(null);
    if (currentValue.current) {
      const next = { ...currentValue.current, ...patch };
      currentValue.current = next;
      setValue(next);
      try {
        if (draftKey)
          sessionStorage.setItem(
            draftKey,
            JSON.stringify({
              notify_self: next.notify_self,
              notify_participants: next.notify_participants === true,
              group_meeting_versions: next.group_meeting_versions === true,
              auto_publish: next.auto_publish,
              groups: next.groups,
              destination_config: next.destination_config,
              permission_policy: next.permission_policy,
              // Never persist short-lived contact proof or claim a stored name is verified.
              ...(next.contacts ? { contacts: next.contacts.map(({ open_id }) => ({ open_id })) } : {}),
            }),
          );
      } catch {
        setError("设置草稿无法保存到本机，请在离开前保存设置");
      }
    }
    setDirty(true);
    setMessage("");
  };
  const save = async (snapshot: FeishuStatus, accepted = false) => {
    if (busy || !owner || !isCurrentOwner() || valueOwner.current !== owner || displayedStatus !== statusRequest.current || snapshot !== currentValue.current || !snapshot.connected || snapshot.expired || feishuVerificationUnavailable(snapshot)) return;
    if (snapshot.auto_publish && !(snapshot.automatic_delivery_protocol === 1 && snapshot.capabilities?.background_delivery)) {
      setError('当前服务尚不支持经确认的自动交付，请关闭自动交付后保存。'); return;
    }
    // Validate before asking for consent; recheck after confirmation for expiring proofs.
    let contacts: ReturnType<typeof preferenceContacts> | undefined;
    try { contacts = snapshot.contacts || snapshot.automatic_delivery_protocol === 1 ? preferenceContacts(snapshot.contacts || [], savedValue.current?.contacts || []) : undefined }
    catch (cause) { setSaveFailed(true); setError(cause instanceof Error ? cause.message : '联系人未核验，请重新搜索'); return }
    if (automaticConsentNeeded(snapshot, savedValue.current) && !accepted) {
      setConsent({ snapshot, revision: editRevision.current, current: requestGuard(statusRequest),
        destinationLabel: destinationCheck?.path?.join(' / ') || (snapshot.destination_config?.kind === 'folder' ? '所选文件夹' : snapshot.destination_config?.kind === 'wiki' ? '所选知识库' : '个人云文档'),
        recipientLabel: [snapshot.notify_self ? '我本人' : '', snapshot.notify_participants ? '已核验的会议参会人' : '', ...(snapshot.contacts || []).map(contact => contact.name), ...snapshot.groups.map(id => groups.find(group => group.chat_id === id)?.name || `已选群（${id}）`)].filter(Boolean).join('、') || (snapshot.auto_publish ? '未选择通知对象：只创建文档，不发送通知。' : '未选择通知对象。'),
      }); return;
    }
    const current = requestGuard(statusRequest);
    setBusy(true); setError(''); setSaveFailed(false);
    try {
      const saved = await apiJson<FeishuStatus>('/api/feishu/preferences', {
        method: 'PUT', body: JSON.stringify({ notify_self: snapshot.notify_self, groups: snapshot.groups, auto_publish: snapshot.auto_publish,
          notify_participants: snapshot.notify_participants === true, group_meeting_versions: snapshot.group_meeting_versions === true,
          destination_config: snapshot.destination_config, permission_policy: snapshot.permission_policy,
          ...(contacts ? { contacts } : {}), ...(accepted ? { automatic_delivery_consent: true } : {}),
        }),
      });
      if (!current()) return;
      savedValue.current = saved; setValue(saved); setDirty(false);
      try { if (draftKey) sessionStorage.removeItem(draftKey) } catch { /* Server acknowledgement is authoritative. */ }
      if (accepted && snapshot.auto_publish) {
        if (!saved.auto_publish || saved.automatic_delivery_protocol !== 1) throw new Error('偏好已保存，但服务未确认启用自动交付，请重新核验。');
        try {
          await pluginStore.save(owner, { installed: true, enabled: true }, current);
          if (!current()) return;
        } catch {
          if (!current()) return;
          try {
            const stopped = await disableDeviceAutomaticDelivery(owner);
            if (!current()) return;
            if (stopped.legacy) throw new Error('设备关闭接口未确认');
            const paused = { ...saved, auto_publish: false, device_auto_enabled: false, automatic_delivery: saved.automatic_delivery ? { ...saved.automatic_delivery, enabled: false } : undefined };
            savedValue.current = paused; setValue(paused);
            setError('偏好已保存，但飞书插件启用状态未能保存；已停止设备自动交付。请到插件商店启用后重新确认自动交付。');
          } catch { if (current()) setError('自动交付设置已保存，但插件启用失败，设备自动交付是否关闭也未确认。请重试关闭自动交付。') }
          return;
        }
        setMessage('自动交付已保存，飞书插件已安装并启用。');
        return;
      }
      setMessage('设置已保存，将用于下一份纪要。');
    } catch (cause) {
      if (current()) { setSaveFailed(true); setError(cause instanceof Error ? cause.message : '保存失败，修改已保留') }
    } finally { if (current()) setBusy(false) }
  };
  const closingAutomaticOnly = !!value && !!savedValue.current?.auto_publish && !value.auto_publish && !automaticConsentNeeded({ ...value, auto_publish: true }, savedValue.current);
  return (
    <div className="workspace-page min-w-0 max-w-5xl">
      <div>
        <PageReturn to="/connections" label="返回插件" />
        <div className="mt-4">
          <PageHeading
            title="飞书"
            description="把会议纪要送到你的工作空间。"
          />
        </div>
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
          <Button variant="outline" disabled={busy} onClick={() => void load()}>
            重新加载
          </Button>
        </Alert>
      )}
      {message && (
        <Alert>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}
      <Tabs defaultValue="authorization" activationMode="manual" className="flex min-w-0 flex-col gap-4">
        <TabsList aria-label="飞书设置" className="h-auto flex-wrap self-start">
          <TabsTrigger value="authorization">授权</TabsTrigger>
          <TabsTrigger value="delivery">会议纪要发送设置</TabsTrigger>
          <TabsTrigger value="hotwords">对象热词</TabsTrigger>
        </TabsList>
      {!value ? (
        !error ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <p className="text-sm text-muted-foreground">
            连接状态尚未读取。请重新加载后再连接飞书。
          </p>
        )
      ) : (
        <>
          <TabsContent value="authorization" className="flex flex-col gap-4">
          {cliMode && <p className="text-sm text-muted-foreground">使用你自己的飞书应用扫码连接，凭据由这台桌面管理，直接连接飞书。</p>}
          {cliMode && !canAuthorize && <Alert><AlertDescription>飞书授权工具尚未就绪，请完成安装后重新检查。</AlertDescription><Button variant="outline" disabled={busy} onClick={() => void load()}>重新检查接入</Button></Alert>}
          {!cliMode && !value.configured && (
            <Alert>
              <AlertDescription>
                授权服务尚未就绪，当前无法生成有效的飞书授权链接。你的笔记和会议纪要仍可正常保存。
              </AlertDescription>
              <p className="mt-2 text-sm text-muted-foreground">尚缺：{(value.setup?.missing || ['application']).map(key => ({ application: 'VINote 企业应用', callback: '授权回调', organization: '公司绑定', documents: '云文档地址', encryption: '授权存储配置' }[key] || '服务配置')).join('、')}。完成配置后可重新检查。</p>
              <Button variant="outline" className="mt-3" disabled={busy} onClick={() => void load()}>重新检查接入</Button>
            </Alert>
          )}
          {value.expired && !verificationUnavailable && (
            <Alert variant="destructive">
              <AlertDescription>
                飞书授权已过期。重新连接后可在会议详情继续交付。
              </AlertDescription>
            </Alert>
          )}
          <section
            aria-label="账号连接"
            className="flex flex-col gap-4 rounded-2xl border border-border/80 bg-card p-5 shadow-sm"
          >
            <h2 className="font-medium">账号连接</h2>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-md border text-sm">
                  {value.connected ? value.name?.slice(0, 1) || "飞" : "飞"}
                </span>
                <div className="flex flex-col gap-1">
                  <span>
                    {verificationUnavailable ? value.name || "飞书账号" : value.connected ? value.name : "连接你的公司飞书账号"}
                  </span>
                  {value.tenant_key && (
                    <span className="text-xs text-muted-foreground">
                      公司账号 · 身份已核验
                    </span>
                  )}
                  <Badge variant="secondary" className="w-fit">
                    {authExpired ? '授权链接已过期' : authorization?.pending ? '正在准备应用连接' : authUrl ? '等待你授权' : !canAuthorize ? '授权服务未就绪' : verificationUnavailable ? '连接暂时无法核验' : value.expired
                      ? "需重新授权"
                      : value.connected
                        ? "已连接"
                        : "未连接"}
                  </Badge>
                </div>
              </div>
              <div className="flex gap-2">
                {value.connected && (
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() => setDisconnect(true)}
                  >
                    断开
                  </Button>
                )}
                <Button
                  disabled={busy || !canAuthorize}
                  onClick={async () => {
                    if (!isCurrentOwner() || authPending.current) return;
                    if (verificationUnavailable && !cliMode) { await load(); return; }
                    const current = requestGuard(statusRequest);
                    authPending.current = true;
                    setBusy(true);
                    setError("");
                    setMessage('');
                    setSaveFailed(false);
                    try {
                      const auth = await apiJson<FeishuAuthorization>(
                        "/api/feishu/authorize",
                        { method: "POST" },
                      );
                      if (!current()) return;
                      if (!isFeishuAuthorization(auth) || cliMode && !auth.flow_id) throw new Error('授权流程未核验，请重新连接。');
                      setAuthUrl(auth.url);
                      setAuthorization(auth);
                      setAuthExpired(false);
                    } catch (cause) {
                      if (current()) setError((cause as Error).message);
                    } finally {
                      if (current()) { authPending.current = false; setBusy(false) }
                    }
                  }}
                >
                  {busy ? "处理中…" : verificationUnavailable && !cliMode ? "重新核验飞书连接" : authExpired ? '重新生成授权' : value.connected ? "重新连接" : "连接飞书"}
                </Button>
              </div>
            </div>
            {(authUrl || authorization?.flow_id) && (
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-5 rounded-xl bg-muted/40 p-4">
                  {authorization?.qr_data_url && !authExpired && <img src={authorization.qr_data_url} alt="用飞书扫描二维码授权 VINote" className="size-36 rounded-lg bg-white p-2" />}
                  <div className="grid gap-3"><p className="text-sm text-muted-foreground" role="status">{authExpired ? '本次授权已过期，请重新生成链接。' : authorization?.pending ? '应用连接正在准备，首次启动可能需要几秒。请稍后点击“继续连接/刷新二维码”查看进度。' : authorization?.stage === 'application' ? '第一步：扫码连接你自己的飞书应用，完成后返回确认。' : authorization?.stage === 'authorization' ? '第二步：扫码授予飞书用户权限，完成后返回确认。' : '扫码或打开官方授权页，同意后返回 VINote。请在链接有效期内完成。'}</p>
                    {authUrl && <Button variant="outline" disabled={authExpired} onClick={() => { if (isCurrentOwner()) void openExternal(authUrl).catch(cause => { if (isCurrentOwner()) setError((cause as Error).message) }) }}>在浏览器中授权飞书</Button>}
                  </div>
                </div>
                <Button
                  variant="outline"
                  disabled={busy || authExpired || cliMode && !authorization?.flow_id}
                  onClick={async () => {
                    if (!isCurrentOwner() || authPending.current) return;
                    if (authorization && authorization.expires_at * 1000 <= Date.now()) { setAuthExpired(true); return }
                    if (!authorization?.flow_id) { if (!cliMode && await load()) setMessage('连接状态已核验，请查看账号状态。'); return }
                    const current = requestGuard(statusRequest);
                    const flowId = authorization.flow_id;
                    authPending.current = true; setBusy(true); setError('');
                    try {
                      const result = await completeFeishuAuthorization(flowId);
                      if (!current()) return;
                      if (isFeishuAuthorization(result)) {
                        if (!result.flow_id) throw new Error('授权流程缺少确认标识，请重新连接。');
                        setAuthorization(result); setAuthUrl(result.url); setAuthExpired(false); setMessage(result.pending ? '应用连接仍在准备，请稍后继续连接。' : '请继续完成下一步扫码授权。');
                      } else {
                        if (!result || typeof result.connected !== 'boolean' || typeof result.configured !== 'boolean') throw new Error('授权结果未核验，请重新确认。');
                        if (!result.connected || result.expired || feishuVerificationUnavailable(result)) throw new Error('授权尚未完成，请在有效期内完成扫码后再次确认。');
                        setAuthorization(null); setAuthUrl(''); setAuthExpired(false);
                        setMessage('');
                        authPending.current = false;
                        await load();
                      }
                    } catch (cause) { if (current()) setError(cause instanceof Error ? cause.message : '授权未完成，请重试') }
                    finally { if (current()) { authPending.current = false; setBusy(false) } }
                  }}
                >
                  {authorization?.pending ? busy ? '正在读取连接进度…' : '继续连接/刷新二维码' : '我已完成授权'}
                </Button>
              </div>
            )}
          </section>
          {!cliMode && <FeishuApplicationSetup key={JSON.stringify([owner, identityVisit])} onChanged={() => void load()} />}
          {verificationUnavailable && <Alert><AlertDescription>{feishuVerificationMessage}</AlertDescription></Alert>}
          </TabsContent>
          <TabsContent value="delivery" className="flex flex-col gap-4">
          {(!value.connected || value.expired || verificationUnavailable) && <Alert><AlertDescription>请先在授权页签连接飞书并核验权限，再设置会议纪要发送。</AlertDescription></Alert>}
          {value.connected && !value.expired && !verificationUnavailable && <><section
            aria-labelledby="delivery-preferences-heading"
            className="grid min-w-0 overflow-hidden rounded-2xl border border-border/80 bg-background lg:grid-cols-2"
          >
            <header className="border-b bg-muted/40 px-5 py-4 lg:col-span-2">
              <h2 id="delivery-preferences-heading" className="font-semibold">
                发布偏好
              </h2>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                设置文档位置和通知对象。自动交付需在这台桌面单独确认启用，手动发布仍在详情确认。
              </p>
            </header>
            <section className="flex min-w-0 flex-col gap-3 border-b p-5 lg:border-r">
              <h3 className="text-sm font-medium">文档存放位置</h3>
              <FeishuDestinationPicker
                key={JSON.stringify([owner, identityVisit, 'connection_binding_hash' in value ? value.connection_binding_hash : null])}
                connectionKey={'connection_binding_hash' in value && typeof value.connection_binding_hash === 'string' ? value.connection_binding_hash : undefined}
                value={value.destination_config || { kind: "personal" }}
                capabilities={verificationUnavailable ? undefined : value.capabilities}
                disabled={busy || !value.connected || value.expired}
                onChecked={setDestinationCheck}
                onChange={(destination) =>
                  change({
                    destination_config: destination,
                    permission_policy:
                      destination.kind === "personal" ? "private" : "inherit",
                  })
                }
              />
              <p className="text-sm text-muted-foreground">
                {value.destination_config?.kind &&
                value.destination_config.kind !== "personal"
                  ? "权限沿用目标目录或知识库，无法在此缩窄继承权限。"
                  : "关闭链接及组织外分享；组织内部访问遵循飞书策略，通知前另行核验接收人阅读权限。"}
              </p>
              {value.capability_reason && (
                <p className="text-xs text-muted-foreground">
                  {value.capability_reason}
                </p>
              )}
            </section>
            <section className="min-w-0 border-b p-5">
              <FieldGroup>
                <FieldSet disabled={busy || !value.connected || value.expired}>
                  <FieldLegend>{cliMode ? '文档通知' : '机器人通知'}</FieldLegend>
                  <Field orientation="horizontal">
                    <Checkbox
                      id="feishu-self"
                      checked={value.notify_self}
                      onCheckedChange={(checked) =>
                        change({ notify_self: checked === true })
                      }
                    />
                    <FieldLabel htmlFor="feishu-self">发给我本人</FieldLabel>
                  </Field>
                  <Field orientation="horizontal">
                    <Checkbox id="feishu-participants" checked={value.notify_participants === true} onCheckedChange={checked => change({ notify_participants: checked === true })} />
                    <FieldLabel htmlFor="feishu-participants">发给会议参会人</FieldLabel>
                  </Field>
                  <FieldDescription>仅通知已明确关联并核验的飞书参会人；不会按转写姓名猜测接收人。可同时通知本人。</FieldDescription>
                  <Field orientation="horizontal">
                    <Checkbox
                      id="feishu-groups-enabled"
                      checked={value.groups.length > 0}
                      onCheckedChange={(checked) =>
                        checked ? setGroupPicker(true) : change({ groups: [] })
                      }
                    />
                    <FieldLabel htmlFor="feishu-groups-enabled">
                      发给指定群
                    </FieldLabel>
                  </Field>
                  <Button
                    className="w-full justify-between"
                    variant="outline"
                    aria-label="选择群"
                    onClick={() => setGroupPicker(true)}
                  >
                    <span className="truncate">
                      {value.groups.length
                        ? value.groups
                            .map(
                              (id) =>
                                groups.find((group) => group.chat_id === id)
                                  ?.name || "已选群",
                            )
                            .join("、")
                        : "选择通知群"}
                    </span>
                    <ChevronRight aria-hidden="true" />
                  </Button>
                  <FieldDescription>
                    {cliMode ? '列出当前授权账号可见的群，以你的身份发送通知。' : '仅列出你与机器人共同加入的群。'}交付前核验群的文档阅读权限，失败时保留文档。
                  </FieldDescription>
                  {value.contact_selection_protocol === 1 ? <FeishuPresetContacts value={value.contacts || []} onChange={contacts => change({ contacts })} disabled={busy || !value.connected || value.expired || verificationUnavailable} connectionKey={statusRequest.current} connectionCurrent={() => displayedStatus === statusRequest.current && isCurrentOwner()} /> : <FieldDescription>当前服务暂不支持选择预设联系人；已保存的联系人继续保留。</FieldDescription>}
                  {groupError && !groupPicker && (
                    <Alert variant="destructive">
                      <AlertDescription>
                        {groupError}，已选群继续保留，请重试刷新。
                      </AlertDescription>
                    </Alert>
                  )}
                </FieldSet>
              </FieldGroup>
            </section>
            <section className="min-w-0 bg-muted/20 p-5 lg:col-span-2">
              <FieldSet disabled={busy || !value.connected || value.expired}>
                <Field orientation="horizontal">
                  <FieldLabel htmlFor="feishu-auto">自动交付新纪要</FieldLabel>
                  <Switch
                    id="feishu-auto"
                    checked={value.auto_publish}
                    disabled={!canEnableAutomatic && !value.auto_publish}
                    onCheckedChange={(checked) =>
                      change({ auto_publish: checked })
                    }
                  />
                </Field>
                <FieldDescription>
                  {canEnableAutomatic
                    ? "仅这台桌面今后成功生成并保存的新个人会议纪要自动交付。历史稿、编辑稿和失败任务不发送；请保持应用运行。"
                    : "当前服务暂不支持经确认的自动交付，可在详情页手动发布。"}
                </FieldDescription>
                <Field orientation="horizontal">
                  <Checkbox id="feishu-group-versions" checked={value.group_meeting_versions === true} disabled={!canEnableAutomatic && !value.group_meeting_versions} onCheckedChange={checked => change({ group_meeting_versions: checked === true })} />
                  <FieldLabel htmlFor="feishu-group-versions">按会议归组历史版本</FieldLabel>
                </Field>
                <FieldDescription>知识库中同一会议的后续纪要放在该会议容器下，保留每份历史稿；不会按相似标题合并不同会议。</FieldDescription>
                <FieldDescription>{!value.notify_self && !value.notify_participants && !value.groups.length && !value.contacts?.length ? '未选择通知对象：自动交付只创建文档，不发送通知。' : '通知所选联系人和群时会授予文档阅读权限。'}</FieldDescription>
                <FieldDescription>
                  当前服务不支持更新已有飞书链接；新修订发布为新文档，历史文档继续保留。
                </FieldDescription>
              </FieldSet>
            </section>
          </section>
          <div
            aria-label="保存发布偏好"
            className="sticky bottom-0 flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-background/95 px-5 py-4 shadow-sm backdrop-blur-sm"
          >
            <span className="text-sm text-muted-foreground">
              {saveFailed && dirty
                ? "保存失败，修改已保留。"
                : error && dirty
                  ? "操作未完成，未保存修改仍保留。"
                  : dirty
                    ? "有未保存的修改，切换页面后会保留草稿"
                    : message || "目的地和通知偏好随账号保存；自动交付需在这台桌面确认启用。"}
            </span>
            <Button
              disabled={
                busy ||
                !dirty ||
                !value.connected ||
                value.expired ||
                (!closingAutomaticOnly && !!value.destination_config &&
                  !destinationCheck?.can_attempt_create)
              }
              onClick={() => void save(value)}
            >
              {busy ? "处理中…" : saveFailed && dirty ? "重试保存" : "保存设置"}
            </Button>
          </div></>}
          </TabsContent>
          <TabsContent value="hotwords">
            {value.connected && !value.expired && !verificationUnavailable
              ? <FeishuObjectHotwords key={JSON.stringify([owner, identityVisit])} connectionKey={statusRequest.current} connectionCurrent={() => displayedStatus === statusRequest.current && isCurrentOwner()} />
              : <Alert><AlertDescription>请先在授权页签连接飞书，再读取当前可见对象。</AlertDescription></Alert>}
          </TabsContent>
        </>
      )}
      </Tabs>
      <AlertDialog open={!!consent} onOpenChange={open => { if (!open) setConsent(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{consent?.snapshot.auto_publish ? '确认这台桌面的自动交付' : '确认保存通知联系人预设'}</AlertDialogTitle>
            <AlertDialogDescription>{consent?.snapshot.auto_publish ? '确认后将安装并启用这台桌面的飞书插件。今后在这台桌面成功生成并保存的新个人会议纪要将自动创建飞书文档。未生成或失败的不发，不回溯旧稿，编辑已有纪要不发送。' : '仅保存所选联系人和发布预设，自动交付保持关闭。不会安装或启用飞书插件，也不会创建文档、授予阅读权限或发送通知。'}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="flex flex-col gap-3 text-sm">
            <p>文档位置：{consent?.destinationLabel}</p>
            <p>通知对象：{consent?.recipientLabel}</p>
            <p>会议版本：{consent?.snapshot.group_meeting_versions ? '在知识库按会议归组，保留历史稿' : '不启用会议版本归组'}</p>
            <p>{consent?.snapshot.auto_publish ? '通知联系人或群会授予文档阅读权限。断开飞书或关闭自动交付将停止尚未启动的任务；自动交付需要应用保持运行。' : '当前仅保存预设。将来开启自动交付时需要再次确认目的地、通知对象和阅读权限。'}</p>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>取消，保留修改</AlertDialogCancel>
            <AlertDialogAction onClick={() => {
              const pending = consent; setConsent(null);
              if (pending && pending.current() && pending.revision === editRevision.current) void save(pending.snapshot, true);
            }}>{consent?.snapshot.auto_publish ? '确认自动交付并保存' : '确认保存预设'}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Dialog
        open={groupPicker}
        onOpenChange={(next) => {
          if (!busy) setGroupPicker(next);
        }}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>选择通知群</DialogTitle>
            <DialogDescription>
              可同时选择多个群。完成选择后，请保存设置。
            </DialogDescription>
          </DialogHeader>
          <FieldSet disabled={busy || !value?.connected || value?.expired}>
            <FieldGroup>
              {value && (
                <>
                  <Field>
                    <FieldLabel htmlFor="feishu-group-search">
                      指定群
                    </FieldLabel>
                    <Input
                      id="feishu-group-search"
                      placeholder={cliMode ? '搜索当前账号可见的群' : '搜索机器人已加入的群'}
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                    />
                  </Field>
                  {groups
                    .filter((group) =>
                      group.name
                        .toLowerCase()
                        .includes(query.trim().toLowerCase()),
                    )
                    .map((group) => (
                      <Field key={group.chat_id} orientation="horizontal">
                        <Checkbox
                          id={group.chat_id}
                          checked={value.groups.includes(group.chat_id)}
                          onCheckedChange={(checked) =>
                            change({
                              groups: checked
                                ? [...value.groups, group.chat_id]
                                : value.groups.filter(
                                    (id) => id !== group.chat_id,
                                  ),
                            })
                          }
                        />
                        <FieldLabel htmlFor={group.chat_id}>
                          {group.name}
                        </FieldLabel>
                      </Field>
                    ))}
                  {groupError && (
                    <Alert variant="destructive">
                      <AlertDescription>
                        {groupError}，已选群继续保留，请重试刷新。
                      </AlertDescription>
                    </Alert>
                  )}
                  {groupsLoading && <p role="status" className="text-sm text-muted-foreground">正在读取群列表，已选群继续保留…</p>}
                  {groupsLoaded && !groupsLoading && groups.length === 0 && !groupError && (
                    <FieldDescription>
                      {cliMode ? '暂未读取到可用群，请确认当前账号已加入目标群后刷新。' : '没有可用群。请将机器人加入目标群，再刷新。'}
                    </FieldDescription>
                  )}
                  {groups.length > 0 &&
                    !groups.some((group) =>
                      group.name
                        .toLowerCase()
                        .includes(query.trim().toLowerCase()),
                    ) && (
                      <FieldDescription>
                        没有匹配的群，请调整搜索关键词。
                      </FieldDescription>
                    )}
                  <Button
                    variant="outline"
                    disabled={busy || groupsLoading}
                    onClick={() => void loadGroups()}
                  >
                    {groupsLoading ? "正在刷新…" : "刷新群列表"}
                  </Button>
                </>
              )}
            </FieldGroup>
          </FieldSet>
          <DialogFooter>
            <Button disabled={busy} onClick={() => setGroupPicker(false)}>
              完成选择
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <AlertDialog open={disconnect} onOpenChange={setDisconnect}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>断开飞书？</AlertDialogTitle>
            <AlertDialogDescription>
              停止后续交付，已创建的飞书文档继续保留。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>取消</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              onClick={async () => {
                if (displayedStatus !== statusRequest.current || !isCurrentOwner()) return;
                ++groupRequest.current;
                setConsent(null);
                const current = requestGuard(statusRequest);
                setBusy(true);
                try {
                  await apiJson("/api/feishu/connection", { method: "DELETE" });
                  if (!current()) return;
                  await load();
                } catch (cause) {
                  if (current()) setError((cause as Error).message);
                } finally {
                  if (current()) setBusy(false);
                }
              }}
            >
              断开连接
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
