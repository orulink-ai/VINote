import { useEffect, useRef, useState } from "react";
import { useAuthStore } from '@/stores/authStore';
import { publishScope } from '@/lib/feishuPublishReceipt';
import { apiJson } from "@/lib/api";
import type { DestinationCheck, FeishuDestination } from "@/lib/feishu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ErrorState, EmptyState } from "@/components/Feedback/ResourceState";

type Item = {
  kind: "folder" | "wiki";
  folder_token?: string;
  space_id?: string;
  node_token?: string;
  name: string;
  has_child?: boolean;
};
export function FeishuDestinationPicker({
  value,
  onChange,
  capabilities,
  disabled,
  onChecked,
  autoCheck = false,
}: {
  value: FeishuDestination;
  onChange: (value: FeishuDestination) => void;
  capabilities?: Record<string, boolean>;
  disabled?: boolean;
  onChecked?: (value: DestinationCheck | null) => void;
  autoCheck?: boolean;
}) {
  const owner = useAuthStore(state => state.user?.id);
  const [advanced, setAdvanced] = useState(false);
  const [selected, setSelected] = useState<{ key: string; name: string } | null>(null);
  const identity = (target: FeishuDestination) => target.kind === "personal" ? "personal" : target.kind === "folder" ? `folder:${target.folder_token}` : `wiki:${target.space_id}:${target.node_token}`;
  const requestSequence = useRef(0);
  const current = useRef({ target: identity(value), disabled, owner });
  current.current = { target: identity(value), disabled, owner };
  const checkedCallback = useRef(onChecked);
  checkedCallback.current = onChecked;
  const [items, setItems] = useState<Item[]>([]);
  const [check, setCheck] = useState<DestinationCheck | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [pageToken, setPageToken] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [history, setHistory] = useState<Record<string, string>[]>([]);
  const [parent, setParent] = useState<Record<string, string>>({});
  const update = (next: FeishuDestination, name?: string) => {
    requestSequence.current++;
    setSelected(name ? { key: identity(next), name } : null);
    onChange(next);
    setCheck(null);
    onChecked?.(null);
  };
  const browse = async (scope: Record<string, string> = {}, append = false, remember = true) => {
    if (value.kind === "personal") return;
    const request = ++requestSequence.current, target = identity(value);
    setBusy(true);
    setError("");
    try {
      if (!owner) throw new Error('请先登录，再选择文档位置');
      const guard = publishScope(owner);
      const params = new URLSearchParams({
        kind: value.kind,
        ...scope,
        ...(append ? { page_token: pageToken } : {}),
      });
      const next = await apiJson<{
        items: Item[];
        has_more: boolean;
        page_token: string;
      }>(`/api/feishu/destinations?${params}`);
      guard();
      if (request !== requestSequence.current || current.current.target !== target || current.current.disabled || current.current.owner !== owner) return false;
      if (!append && remember && JSON.stringify(scope) !== JSON.stringify(parent)) setHistory(old => [...old, parent]);
      setItems((old) => (append ? [...old, ...next.items] : next.items));
      setLoaded(true);
      setParent(scope);
      setPageToken(next.page_token);
      setHasMore(next.has_more);
      return true;
    } catch (cause) {
      if (request === requestSequence.current) setError((cause as Error).message);
      return false;
    } finally {
      if (request === requestSequence.current) setBusy(false);
    }
  };
  const verify = async () => {
    const request = ++requestSequence.current, target = identity(value);
    setBusy(true);
    setError("");
    setCheck(null);
    onChecked?.(null);
    try {
      if (!owner) throw new Error('请先登录，再核验文档位置');
      const guard = publishScope(owner);
      const next = await apiJson<DestinationCheck>(
        "/api/feishu/destinations/check",
        { method: "POST", body: JSON.stringify(value) },
      );
      guard();
      if (request !== requestSequence.current || current.current.target !== target || current.current.disabled || current.current.owner !== owner) return;
      if (identity(next) !== target) throw new Error('位置核验响应与所选位置不符，请重新核验');
      setCheck(next);
      checkedCallback.current?.(next);
    } catch (cause) {
      if (request === requestSequence.current) setError((cause as Error).message);
    } finally {
      if (request === requestSequence.current) setBusy(false);
    }
  };
  const target = identity(value);
  const previousTarget = useRef<{ target: string; owner: string | undefined }>();
  useEffect(() => {
    requestSequence.current++;
    setBusy(false);
    const changed = previousTarget.current?.target !== target || previousTarget.current?.owner !== owner;
    previousTarget.current = { target, owner };
    if (autoCheck || changed) { setCheck(null); setError(''); checkedCallback.current?.(null); }
    const complete = value.kind === 'personal' || (value.kind === 'folder' ? !!value.folder_token : !!value.space_id && !!value.node_token);
    if (autoCheck && !disabled && complete) void verify();
    return () => { requestSequence.current++ };
  }, [target, disabled, autoCheck, owner]);
  return (
    <FieldGroup>
      <Field>
        <FieldLabel>文档位置</FieldLabel>
        <NativeSelect
          aria-label="文档位置类型"
          value={value.kind}
          disabled={disabled || busy}
          onChange={(e) => {
            const kind = e.target.value;
            update(
              kind === "folder"
                ? { kind, folder_token: "" }
                : kind === "wiki"
                  ? { kind, space_id: "", node_token: "" }
                  : { kind: "personal" },
            );
            setAdvanced(false);
            setItems([]);
            setLoaded(false);
            setParent({});
            setHistory([]);
            setHasMore(false);
          }}
        >
          <NativeSelectOption value="personal">个人云文档</NativeSelectOption>
          <NativeSelectOption
            value="folder"
            disabled={capabilities?.folder === false}
          >
            个人 / 组织共享文件夹
          </NativeSelectOption>
          <NativeSelectOption
            value="wiki"
            disabled={capabilities?.wiki === false}
          >
            知识库节点
          </NativeSelectOption>
        </NativeSelect>
        <FieldDescription>
          组织位置沿用目标权限；不自动扩大到全组织公开。
        </FieldDescription>
        {(capabilities?.folder === false || capabilities?.wiki === false) && <FieldDescription>
          当前飞书应用尚未开放{[capabilities?.folder === false ? '共享文件夹' : '', capabilities?.wiki === false ? '知识库' : ''].filter(Boolean).join('、')}访问。可先发布到个人云文档；需使用组织位置时，请在飞书连接中核对应用权限并重新授权。
        </FieldDescription>}
      </Field>
      {value.kind !== "personal" && (
        <>
          <div role="region" aria-label="已选文档位置" className="rounded-lg border border-border bg-muted/40 p-3 text-sm">
            <p className="font-medium">已选位置</p>
            <p className="mt-1 break-words">{check && identity(check) === identity(value) && check.name
              ? check.path.join(" / ") || check.name
              : selected?.key === identity(value) ? selected.name
              : value.kind === "folder" && value.folder_token || value.kind === "wiki" && value.space_id && value.node_token
                ? "已保留文档位置，请核验以读取名称。"
                : "尚未选择，请浏览可见位置。"}</p>
            <p className="mt-1 text-xs text-muted-foreground">{autoCheck ? '选择后自动核验创建权限。' : '浏览可见不代表可写；选择后请核验位置与权限。'}</p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              disabled={disabled || busy}
              onClick={() => void browse()}
            >
              浏览可见位置
            </Button>
            {loaded && (
              <Button
                variant="ghost"
                disabled={disabled || busy}
                onClick={() => void browse(parent)}
              >
                刷新当前目录
              </Button>
            )}
          </div>
          {history.length > 0 && <Button variant="ghost" disabled={disabled || busy} onClick={async () => { if (await browse(history[history.length - 1], false, false)) setHistory(old => old.slice(0, -1)); }}>返回上一级位置</Button>}
          {items.map((item) => (
            <div
              key={`${item.folder_token}:${item.space_id}:${item.node_token}`}
              className="flex items-center justify-between gap-2 border-b py-2"
            >
              <span className="min-w-0 truncate text-sm">{item.name}</span>
              <div className="flex gap-2">
                {(item.kind === "folder" || item.node_token) && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={disabled || busy}
                    onClick={() =>
                      update(
                        item.kind === "folder"
                          ? { kind: "folder", folder_token: item.folder_token! }
                          : {
                              kind: "wiki",
                              space_id: item.space_id!,
                              node_token: item.node_token!,
                            },
                        item.name,
                      )
                    }
                  >
                    选择
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={disabled || busy}
                  onClick={() =>
                    void browse(
                      item.kind === "folder"
                        ? { folder_token: item.folder_token! }
                        : {
                            space_id: item.space_id!,
                            ...(item.node_token
                              ? { parent_node_token: item.node_token }
                              : {}),
                          },
                    )
                  }
                >
                  进入
                </Button>
              </div>
            </div>
          ))}
          {hasMore && (
            <Button
              variant="outline"
              disabled={disabled || busy}
              onClick={() => void browse(parent, true)}
            >
              加载更多位置
            </Button>
          )}
          {loaded && !items.length && !hasMore && !error && (
            <EmptyState
              title="此处没有可见位置"
              description="可返回上级浏览；已有目标标识时可展开高级设置。"
            />
          )}
        </>
      )}
      {value.kind !== "personal" && <details open={advanced} onToggle={event => setAdvanced(event.currentTarget.open)} className="rounded-lg border border-border p-3">
        <summary className="cursor-pointer text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">高级设置 · 手填位置标识</summary>
        {advanced && <div className="mt-4 grid gap-4">
          <p className="text-sm text-muted-foreground">已知目标标识时可手动填写，修改后需要重新核验位置与权限。</p>
      {value.kind === "folder" && (
        <Field>
          <FieldLabel htmlFor="feishu-folder-token">文件夹标识</FieldLabel>
          <Input
            id="feishu-folder-token"
            value={value.folder_token}
            disabled={disabled || busy}
            onChange={(e) =>
              update({ kind: "folder", folder_token: e.target.value.trim() })
            }
          />
          <FieldDescription>
            可直接填写共享文件夹 token，不填写完整网址。
          </FieldDescription>
        </Field>
      )}
      {value.kind === "wiki" && (
        <>
          <Field>
            <FieldLabel htmlFor="feishu-space-token">知识空间标识</FieldLabel>
            <Input
              id="feishu-space-token"
              value={value.space_id}
              disabled={disabled || busy}
              onChange={(e) =>
                update({ ...value, space_id: e.target.value.trim() })
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="feishu-node-token">父节点标识</FieldLabel>
            <Input
              id="feishu-node-token"
              value={value.node_token}
              disabled={disabled || busy}
              onChange={(e) =>
                update({ ...value, node_token: e.target.value.trim() })
              }
            />
          </Field>
        </>
      )}
        </div>}
      </details>}
      {error && <ErrorState error={error} />}
      {(!autoCheck || !!error || !!check && !check.can_attempt_create) && <Button
        variant="outline"
        disabled={
          disabled ||
          busy ||
          (value.kind === "folder" && !value.folder_token) ||
          (value.kind === "wiki" && (!value.space_id || !value.node_token))
        }
        onClick={() => void verify()}
      >
        {busy ? "读取并核验中…" : "核验位置与权限"}
      </Button>}
      {autoCheck && busy && <p role="status" className="text-sm text-muted-foreground">正在核验文档位置…</p>}
      {check && (!autoCheck || !check.can_attempt_create) && (
        <Alert variant={check.can_attempt_create ? "default" : "destructive"}>
          <AlertDescription>
            <p>
              {check.path_complete ? "完整路径：" : "已核验路径片段："}
              {check.path.join(" / ") || check.name || "尚未确认"}
            </p>
            <p className="mt-1">
              {check.can_create
                ? "已具备创建条件，提交时仍由飞书核验。"
                : check.can_attempt_create
                  ? "目录可读，创建权限将在提交时核验。"
                  : "当前目标不能提交创建。"}
            </p>
            {check.reason && (
              <p className="mt-1">
                {typeof check.reason === "string"
                  ? check.reason
                  : "目标权限未通过检查"}
              </p>
            )}
          </AlertDescription>
        </Alert>
      )}
    </FieldGroup>
  );
}
