import { feishuVerificationUnavailable, feishuVerificationMessage } from '@/lib/feishuConnectionState'
import { useEffect, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { FeishuDestinationPicker } from "@/components/Settings/FeishuDestinationPicker";
import { FeishuPresetContacts } from '@/components/Settings/FeishuPresetContacts';
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
  const [authorization, setAuthorization] = useState<FeishuAuthorization | null>(null);
  const [authExpired, setAuthExpired] = useState(false);
  const [disconnect, setDisconnect] = useState(false);
  const savedValue = useRef<FeishuStatus>();
  const editRevision = useRef(0);
  const [consent, setConsent] = useState<{ snapshot: FeishuStatus; revision: number; current: () => boolean; destinationLabel: string; recipientLabel: string } | null>(null);
  const currentValue = useRef(value); currentValue.current = value;
  const canEnableAutomatic = value?.automatic_delivery_protocol === 1 && value.capabilities?.background_delivery === true;
  const [destinationCheck, setDestinationCheck] =
    useState<DestinationCheck | null>(null);
  const renderScope = owner ? publishScope(owner) : null;
  const isCurrentOwner = () => {
    try { renderScope?.(); return !!renderScope && useAuthStore.getState().user?.id === owner } catch { return false }
  };
  const statusRequest = useRef(0);
  const displayedStatus = statusRequest.current;
  const groupRequest = useRef(0);
  const groupPending = useRef(false);
  const requestGuard = (sequence: { current: number }) => {
    const request = ++sequence.current;
    const scope = owner ? publishScope(owner) : null;
    return () => {
      if (!scope || !isCurrentOwner() || request !== sequence.current) return false;
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
            notify_self: parsed.notify_self, auto_publish: parsed.auto_publish, groups: parsed.groups,
            destination_config: parsed.destination_config, permission_policy: parsed.permission_policy,
            ...(Array.isArray(parsed.contacts) ? { contacts: parsed.contacts.filter((contact: { open_id?: unknown }) => contact && typeof contact.open_id === 'string' && /^ou_[A-Za-z0-9_-]+$/.test(contact.open_id)).map((contact: { open_id: string }) => ({ open_id: contact.open_id, name: '' })) } : {}),
          };
      } catch {
        /* Browser storage may be unavailable; the visible form still works. */
      }
      if (!draft && dirty && value && valueOwner.current === owner)
        draft = {
          notify_self: value.notify_self,
          auto_publish: value.auto_publish,
          groups: value.groups,
          destination_config: value.destination_config,
          permission_policy: value.permission_policy,
          contacts: value.contacts,
        };
      if (revision !== editRevision.current && currentValue.current && valueOwner.current === owner) {
        const latest = currentValue.current;
        draft = { notify_self: latest.notify_self, auto_publish: latest.auto_publish, groups: latest.groups, contacts: latest.contacts, destination_config: latest.destination_config, permission_policy: latest.permission_policy };
      }
      valueOwner.current = owner;
      savedValue.current = next;
      if (draft?.contacts) draft.contacts = draft.contacts.map(contact => (next.contacts || []).find(saved => saved.open_id === contact.open_id) || { open_id: contact.open_id, name: '待重新选择联系人' });
      setValue({ ...next, ...draft });
      if (next.connected && !next.expired && !feishuVerificationUnavailable(next)) {
        setAuthUrl(''); setAuthorization(null); setAuthExpired(false);
      } else if (authUrl) setMessage(feishuVerificationUnavailable(next) ? feishuVerificationMessage : next.expired ? '需要重新授权，请使用新的授权链接。' : '尚未收到飞书授权，请完成后再次核验。');
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
    };
  }, [owner, identityVisit]);
  useEffect(() => {
    if (!authorization) return;
    const timer = window.setTimeout(() => setAuthExpired(true), Math.max(0, authorization.expires_at * 1000 - Date.now()));
    return () => window.clearTimeout(timer);
  }, [authorization]);
  useEffect(() => {
    if (!authUrl) return;
    const verify = () => {
      if (document.visibilityState === "visible") void load();
    };
    window.addEventListener("focus", verify);
    return () => window.removeEventListener("focus", verify);
  }, [authUrl]);
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
        recipientLabel: [snapshot.notify_self ? '我本人' : '', ...(snapshot.contacts || []).map(contact => contact.name), ...snapshot.groups.map(id => groups.find(group => group.chat_id === id)?.name || `已选群（${id}）`)].filter(Boolean).join('、') || (snapshot.auto_publish ? '未选择通知对象：只创建文档，不发送通知。' : '未选择通知对象。'),
      }); return;
    }
    const current = requestGuard(statusRequest);
    setBusy(true); setError(''); setSaveFailed(false);
    try {
      const saved = await apiJson<FeishuStatus>('/api/feishu/preferences', {
        method: 'PUT', body: JSON.stringify({ notify_self: snapshot.notify_self, groups: snapshot.groups, auto_publish: snapshot.auto_publish,
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
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-6 px-6 py-8">
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
          {!value.configured && (
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
                    {!value.configured ? '授权服务未就绪' : verificationUnavailable ? '连接暂时无法核验' : authExpired ? '授权链接已过期' : authUrl ? '等待你授权' : value.expired
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
                  disabled={busy || !value.configured}
                  onClick={async () => {
                    if (verificationUnavailable) { await load(); return; }
                    const current = requestGuard(statusRequest);
                    setBusy(true);
                    setError("");
                    setSaveFailed(false);
                    try {
                      const auth = await apiJson<FeishuAuthorization>(
                        "/api/feishu/authorize",
                        { method: "POST" },
                      );
                      if (!current()) return;
                      setAuthUrl(auth.url);
                      setAuthorization(auth);
                      setAuthExpired(false);
                    } catch (cause) {
                      if (current()) setError((cause as Error).message);
                    } finally {
                      if (current()) setBusy(false);
                    }
                  }}
                >
                  {busy ? "处理中…" : verificationUnavailable ? "重新核验飞书连接" : authExpired ? '重新生成授权' : value.connected ? "重新连接" : "连接飞书"}
                </Button>
              </div>
            </div>
            {authUrl && (
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-5 rounded-xl bg-muted/40 p-4">
                  {authorization?.qr_data_url && !authExpired && <img src={authorization.qr_data_url} alt="用飞书扫描二维码授权 VINote" className="size-36 rounded-lg bg-white p-2" />}
                  <div className="grid gap-3"><p className="text-sm text-muted-foreground" role="status">{authExpired ? '本次授权已过期，请重新生成链接。' : '扫码或打开官方授权页，同意后返回 VINote。链接有效期 10 分钟。'}</p>
                    <Button variant="outline" disabled={authExpired} onClick={() => void openExternal(authUrl).catch(cause => setError((cause as Error).message))}>在浏览器中授权飞书</Button>
                  </div>
                </div>
                <Button
                  variant="outline"
                  disabled={busy || authExpired}
                  onClick={async () => {
                    if (await load())
                      setMessage("连接状态已核验，请查看账号状态。");
                  }}
                >
                  我已完成授权
                </Button>
              </div>
            )}
          </section>
          {verificationUnavailable && <Alert><AlertDescription>{feishuVerificationMessage}</AlertDescription></Alert>}
          {value.connected && !value.expired && !verificationUnavailable && <><section
            aria-labelledby="delivery-preferences-heading"
            className="overflow-hidden rounded-2xl border border-border/80 bg-background"
          >
            <header className="border-b bg-muted/40 px-5 py-4">
              <h2 id="delivery-preferences-heading" className="font-semibold">
                发布偏好
              </h2>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                设置文档位置和通知对象。自动交付需在这台桌面单独确认启用，手动发布仍在详情确认。
              </p>
            </header>
            <section className="flex flex-col gap-3 border-b p-5">
              <h3 className="text-sm font-medium">文档存放位置</h3>
              <FeishuDestinationPicker
                key={JSON.stringify([owner, identityVisit])}
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
            <section className="border-b p-5">
              <FieldGroup>
                <FieldSet disabled={busy || !value.connected || value.expired}>
                  <FieldLegend>机器人通知</FieldLegend>
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
                    仅列出你与机器人共同加入的群。交付前为群授予文档阅读权限，失败时保留文档并提示重试。
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
            <section className="bg-muted/20 p-5">
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
                    ? "仅这台桌面今后成功生成并保存的新个人会议纪要自动交付。历史稿、编辑稿和失败任务不发送；尚未交给服务的任务需要应用运行。"
                    : "当前服务暂不支持经确认的自动交付，可在详情页手动发布。"}
                </FieldDescription>
                <FieldDescription>{!value.notify_self && !value.groups.length && !value.contacts?.length ? '未选择通知对象：自动交付只创建文档，不发送通知。' : '通知所选联系人和群时会授予文档阅读权限。'}</FieldDescription>
                <FieldDescription>
                  当前服务不支持更新已有飞书链接；新修订发布为新文档，历史文档继续保留。
                </FieldDescription>
              </FieldSet>
            </section>
          </section>
          <div
            aria-label="保存发布偏好"
            className="sticky bottom-0 flex items-center justify-between gap-4 rounded-xl border bg-background/95 px-5 py-4 shadow-sm backdrop-blur-sm"
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
        </>
      )}
      <FeishuApplicationSetup key={JSON.stringify([owner, identityVisit])} onChanged={() => void load()} />
      <AlertDialog open={!!consent} onOpenChange={open => { if (!open) setConsent(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{consent?.snapshot.auto_publish ? '确认这台桌面的自动交付' : '确认保存通知联系人预设'}</AlertDialogTitle>
            <AlertDialogDescription>{consent?.snapshot.auto_publish ? '确认后将安装并启用这台桌面的飞书插件。今后在这台桌面成功生成并保存的新个人会议纪要将自动创建飞书文档。未生成或失败的不发，不回溯旧稿，编辑已有纪要不发送。' : '仅保存所选联系人和发布预设，自动交付保持关闭。不会安装或启用飞书插件，也不会创建文档、授予阅读权限或发送通知。'}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="flex flex-col gap-3 text-sm">
            <p>文档位置：{consent?.destinationLabel}</p>
            <p>通知对象：{consent?.recipientLabel}</p>
            <p>{consent?.snapshot.auto_publish ? '通知联系人或群会授予文档阅读权限。断开飞书或关闭自动交付将停止尚未启动的任务；服务接收后可继续，未交给服务的任务需要应用保持运行。' : '当前仅保存预设。将来开启自动交付时需要再次确认目的地、通知对象和阅读权限。'}</p>
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
                      placeholder="搜索机器人已加入的群"
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
                      没有可用群。请将机器人加入目标群，再刷新。
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
