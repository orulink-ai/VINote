import { feishuVerificationUnavailable, feishuVerificationMessage } from '@/lib/feishuConnectionState'
import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { FeishuDestinationPicker } from "@/components/Settings/FeishuDestinationPicker";
import { apiJson } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";
import {
  feishuGroups,
  feishuStatus,
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

export function FeishuSettings() {
  const owner = useAuthStore((state) => state.user?.id);
  const draftKey = owner ? `vinote:feishu-preferences:${owner}` : "";
  const [value, setValue] = useState<FeishuStatus | null>(null);
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
  const [destinationCheck, setDestinationCheck] =
    useState<DestinationCheck | null>(null);
  const isCurrentOwner = () => useAuthStore.getState().user?.id === owner;
  const load = async () => {
    setBusy(true);
    setError("");
    setSaveFailed(false);
    try {
      const next = await feishuStatus();
      if (!isCurrentOwner()) return false;
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
          draft = parsed;
      } catch {
        /* Browser storage may be unavailable; the visible form still works. */
      }
      if (!draft && dirty && value)
        draft = {
          notify_self: value.notify_self,
          auto_publish: value.auto_publish,
          groups: value.groups,
          destination_config: value.destination_config,
          permission_policy: value.permission_policy,
        };
      setValue({ ...next, ...draft });
      if (next.connected && !next.expired && !feishuVerificationUnavailable(next)) {
        setAuthUrl(''); setAuthorization(null); setAuthExpired(false);
      } else if (authUrl) setMessage(feishuVerificationUnavailable(next) ? feishuVerificationMessage : next.expired ? '需要重新授权，请使用新的授权链接。' : '尚未收到飞书授权，请完成后再次核验。');
      setDirty(!!draft);
      if (draft) setMessage("已恢复未保存的设置，请核对后保存。");
      if (next.connected && !next.expired && !feishuVerificationUnavailable(next)) {
        setGroupError("");
        setGroupsLoading(true);
        try {
          const nextGroups = await feishuGroups();
          if (!isCurrentOwner()) return false;
          setGroups(nextGroups);
          setGroupsLoaded(true);
        } catch (cause) {
          if (!isCurrentOwner()) return false;
          setGroupError(
            cause instanceof Error ? cause.message : "读取群列表失败",
          );
        } finally {
          if (isCurrentOwner()) setGroupsLoading(false);
        }
      } else setGroups([]);
      return true;
    } catch (cause) {
      if (!isCurrentOwner()) return false;
      setError(cause instanceof Error ? cause.message : "读取失败，请重试");
      return false;
    } finally {
      if (isCurrentOwner()) setBusy(false);
    }
  };
  useEffect(() => {
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
    setDisconnect(false);
    void load();
  }, [owner]);
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
    if (value) {
      const next = { ...value, ...patch };
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
            }),
          );
      } catch {
        setError("设置草稿无法保存到本机，请在离开前保存设置");
      }
    }
    setDirty(true);
    setMessage("");
  };
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
                    setBusy(true);
                    setError("");
                    setSaveFailed(false);
                    try {
                      const auth = await apiJson<FeishuAuthorization>(
                        "/api/feishu/authorize",
                        { method: "POST" },
                      );
                      if (!isCurrentOwner()) return;
                      setAuthUrl(auth.url);
                      setAuthorization(auth);
                      setAuthExpired(false);
                    } catch (cause) {
                      if (isCurrentOwner()) setError((cause as Error).message);
                    } finally {
                      if (isCurrentOwner()) setBusy(false);
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
                设置文档位置和通知方式，发布前仍可在详情确认。
              </p>
            </header>
            <section className="flex flex-col gap-3 border-b p-5">
              <h3 className="text-sm font-medium">文档存放位置</h3>
              <FeishuDestinationPicker
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
                    disabled={!value.capabilities?.background_delivery}
                    onCheckedChange={(checked) =>
                      change({ auto_publish: checked })
                    }
                  />
                </Field>
                <FieldDescription>
                  {value.capabilities?.background_delivery
                    ? "首次纪要完成并保存后自动交付。"
                    : "当前服务尚无持续后台交付能力，使用详情页手动发布；不能保证关闭应用后的自动发送。"}
                </FieldDescription>
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
                    : message || "设置按 VINote 账号共享"}
            </span>
            <Button
              disabled={
                busy ||
                !dirty ||
                !value.connected ||
                value.expired ||
                (!!value.destination_config &&
                  !destinationCheck?.can_attempt_create)
              }
              onClick={async () => {
                setBusy(true);
                setError("");
                setSaveFailed(false);
                try {
                  const saved = await apiJson<FeishuStatus>(
                    "/api/feishu/preferences",
                    {
                      method: "PUT",
                      body: JSON.stringify({
                        notify_self: value.notify_self,
                        groups: value.groups,
                        auto_publish: value.auto_publish,
                        destination_config: value.destination_config,
                        permission_policy: value.permission_policy,
                      }),
                    },
                  );
                  if (!isCurrentOwner()) return;
                  setValue(saved);
                  setDirty(false);
                  try {
                    if (draftKey) sessionStorage.removeItem(draftKey);
                  } catch {
                    /* Saved preferences remain authoritative. */
                  }
                  setMessage("设置已保存，将用于下一份纪要。");
                } catch (cause) {
                  if (isCurrentOwner()) {
                    setSaveFailed(true);
                    setError((cause as Error).message);
                  }
                } finally {
                  if (isCurrentOwner()) setBusy(false);
                }
              }}
            >
              {busy ? "处理中…" : saveFailed && dirty ? "重试保存" : "保存设置"}
            </Button>
          </div></>}
        </>
      )}
      <FeishuApplicationSetup key={owner} onChanged={() => void load()} />
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
                    onClick={async () => {
                      if (busy || groupsLoading) return;
                      setBusy(true);
                      setGroupsLoading(true);
                      setGroupError("");
                      try {
                        const nextGroups = await feishuGroups();
                        if (!isCurrentOwner()) return;
                        setGroups(nextGroups);
                        setGroupsLoaded(true);
                        setError("");
                      } catch (cause) {
                        if (isCurrentOwner())
                          setGroupError((cause as Error).message);
                      } finally {
                        if (isCurrentOwner()) { setBusy(false); setGroupsLoading(false); }
                      }
                    }}
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
                setBusy(true);
                try {
                  await apiJson("/api/feishu/connection", { method: "DELETE" });
                  if (!isCurrentOwner()) return;
                  await load();
                } catch (cause) {
                  if (isCurrentOwner()) setError((cause as Error).message);
                } finally {
                  if (isCurrentOwner()) setBusy(false);
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
