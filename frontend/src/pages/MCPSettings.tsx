import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter } from '@/components/ui/alert-dialog';
import { useEffect, useRef, useState } from "react";
import { PageReturn } from '@/components/Layout/PageReturn';
import { useLocation, useSearchParams } from "react-router-dom";
import { Plug, Plus, RefreshCw, Wrench } from "lucide-react";
import { apiJson } from "@/lib/api";
import {
  listMCPConnections,
  listMCPRuns,
  mcpBase,
  mcpRunLabel,
  provisionMCPTranslation, isCloudTranslation, cloudTranslationSchema, cloudTranslationTool,
  type MCPConnection,
  type MCPTool,
  type MCPRun,
} from "@/lib/mcpConnections";
import { useAuthStore } from "@/stores/authStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import {
  LoadingState,
  ErrorState,
  EmptyState,
} from "@/components/Feedback/ResourceState";
import { PageHeading } from "@/components/Layout/PageHeading";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

import { MarkdownContent } from '@/components/Markdown/MarkdownContent';
import { resolvePageParent, pageParentLabel } from '@/lib/navigation';
import { type WorkspaceNote } from '@/lib/workspace';
import { savedWorkspaceVersionLabel } from '@/lib/workspaceVersionLabel';
import { getTranslationModels, validatedTranslationModel, queryMCPRequest, readMCPReceipts, writeMCPReceipt, verifyMCPRun, translationArguments, translationFields, translationText, translationSaveBody, type TranslationModels, type MCPReceipt, type TranslationRun } from '@/lib/mcpTranslation';

export function MCPSettings() {
  const owner = useAuthStore((s) => s.user?.id);
  const [params, setParams] = useSearchParams();
  const workspace = useWorkspaceStore();
  const location = useLocation();
  const translationMode = params.get('mode') === 'translation';
  const returnTo = resolvePageParent(location.state?.returnTo, params.get('note') ? `/workspace/${encodeURIComponent(params.get('note')!)}` : '/connections');
  const [selectedNote, setSelectedNote] = useState<WorkspaceNote | null>(null);
  const [versionId, setVersionId] = useState('');
  const [sourceError, setSourceError] = useState('');
  const [providerError, setProviderError] = useState('');
  const [provisionUnknown, setProvisionUnknown] = useState(false);
  const [textField, setTextField] = useState(''), [languageField, setLanguageField] = useState('');
  const [targetLanguage, setTargetLanguage] = useState<'en' | 'zh'>('en');
  const [modelCatalog, setModelCatalog] = useState<TranslationModels | null>(null);
  const [translationModel, setTranslationModel] = useState('');
  const [modelLoading, setModelLoading] = useState(false), [modelError, setModelError] = useState('');
  const modelEpoch = useRef(0);
  const [receipts, setReceipts] = useState<MCPReceipt[]>([]);
  const [recoveryError, setRecoveryError] = useState('');
  const [comparison, setComparison] = useState<'source' | 'result'>('result');
  const sourceVersion = selectedNote?.versions.find(version => version.id === versionId);
  const [connections, setConnections] = useState<MCPConnection[]>([]);
  const [selected, setSelected] = useState("");
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [runs, setRuns] = useState<MCPRun[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toolLoading, setToolLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [toolError, setToolError] = useState("");
  const [adding, setAdding] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [editingId, setEditingId] = useState("");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [authType, setAuthType] = useState<"none" | "token">("none");
  const [token, setToken] = useState("");
  const [tool, setTool] = useState<MCPTool | null>(null);
  const [argumentsText, setArgumentsText] = useState("{}");
  const [scopeField, setScopeField] = useState("");
  const [run, setRun] = useState<TranslationRun | null>(null);
  const [invocation, setInvocation] = useState<MCPReceipt | null>(null);
  const [remove, setRemove] = useState<MCPConnection | null>(null);
  const activeOwner = useRef({ owner, epoch: 0 });
  if (activeOwner.current.owner !== owner) activeOwner.current = { owner, epoch: activeOwner.current.epoch + 1 };
  const ownerEpoch = activeOwner.current.epoch;
  const dialogEpoch = useRef(0);
  const actionLock = useRef(false), sourceEpoch = useRef(0), selectedRef = useRef(selected);
  selectedRef.current = selected;
  useEffect(() => useAuthStore.subscribe((state, previous) => { if (state.user?.id !== previous.user?.id) activeOwner.current.epoch++; }), []);
  const connection = connections.find((c) => c.id === selected);
  const path = `${mcpBase}/${encodeURIComponent(selected)}`;
  const official = connections.find(isCloudTranslation);
  const managed = !!connection?.managed || connection?.authType === 'vinote-session';
  const officialTool = !!tool && isCloudTranslation(connection) && cloudTranslationSchema(tool);
  const loadModels = async (reset = false) => {
    const epoch = ++modelEpoch.current, visibleEpoch = dialogEpoch.current, selectedConnection = selected;
    setModelLoading(true); setModelError(''); setModelCatalog(null);
    if (reset) setTranslationModel('');
    try {
      const catalog = await getTranslationModels();
      if (!validOwner() || epoch !== modelEpoch.current || visibleEpoch !== dialogEpoch.current || selectedRef.current !== selectedConnection) return;
      setModelCatalog(catalog);
      if (reset) setTranslationModel(catalog.defaultModel || '');
    } catch (cause) {
      if (validOwner() && epoch === modelEpoch.current && visibleEpoch === dialogEpoch.current) setModelError((cause as Error).message);
    } finally {
      if (validOwner() && epoch === modelEpoch.current && visibleEpoch === dialogEpoch.current) setModelLoading(false);
    }
  };
  const validOwner = () =>
    activeOwner.current.epoch === ownerEpoch && activeOwner.current.owner === owner && useAuthStore.getState().user?.id === owner;
  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const capability = await apiJson<{ transport: string }>(
        `${mcpBase}/capabilities`,
      );
      if (capability.transport !== "streamable-http")
        throw new Error("当前服务不支持所需的 MCP 传输协议");
      const list = await listMCPConnections();
      const history = await listMCPRuns();
      if (!validOwner()) return;
      setConnections(list.connections);
      if (translationMode) setSelected(current => current || list.connections.find(isCloudTranslation)?.id || '');
      setRuns(history.runs);
      setOffset(history.runs.length);
      setHasMore(history.runs.length === 50);
      setLoaded(true);
    } catch (cause) {
      if (validOwner()) setError((cause as Error).message);
    } finally {
      if (validOwner()) setLoading(false);
    }
  };
  const loadTools = async () => {
    if (!selected) return;
    const requestedConnection = selected;
    setToolLoading(true);
    setToolError("");
    try {
      const result = await apiJson<{ tools: MCPTool[] }>(`${path}/tools`);
      if (validOwner() && selectedRef.current === requestedConnection) setTools(result.tools);
    } catch (cause) {
      if (validOwner() && selectedRef.current === requestedConnection) setToolError((cause as Error).message);
    } finally {
      if (validOwner() && selectedRef.current === requestedConnection) setToolLoading(false);
    }
  };
  useEffect(() => {
    setConnections([]);
    setSelected("");
    setTools([]);
    setRuns([]);
    setToken("");
    setLoaded(false);
    setRun(null);
    setInvocation(null);
    dialogEpoch.current++; setTool(null); setSelectedNote(null); setVersionId(''); setSourceError(''); setConfigOpen(false); setAdding(false); setProviderError(''); setProvisionUnknown(false); setReceipts([]); setRecoveryError(''); setBusy(false); actionLock.current = false;
    void refresh();
    if (owner) try { const saved = readMCPReceipts(owner); setReceipts(saved); } catch (cause) { setRecoveryError((cause as Error).message); }
  }, [owner]);
  useEffect(() => {
    const id = ++sourceEpoch.current;
    setSelectedNote(null); setVersionId(''); setSourceError('');
    if (params.get('note') && workspace.owner === owner) void workspace.loadDetail(params.get('note')!, true).then(note => {
      if (!validOwner() || id !== sourceEpoch.current) return;
      if (note.key !== params.get('note')) { setSourceError('读取的内容标识不匹配，请返回原链接。'); return; }
      setSelectedNote(note);
      const requested = params.get('version');
      if (requested && !note.versions.some(version => version.id === requested)) {
        setVersionId(''); setSourceError('指定的历史版本不可用。不会换成最新正文，请明确选择另一个已保存版本。');
      } else setVersionId(requested || String(note.metadata.default_version_id || note.versions[0]?.id || ''));
    }).catch(cause => { if (validOwner() && id === sourceEpoch.current) setError((cause as Error).message); });
  }, [owner, workspace.owner, params.get('note'), params.get('version')]);
  useEffect(() => {
    setTools([]);
    void loadTools();
  }, [selected]);
  useEffect(() => { if (invocation && invocation.connectionId === selected) setTool(tools.find(item => item.name === invocation.toolName) || null); }, [tools, selected, invocation?.requestId]);
  useEffect(() => {
    if (!translationMode || invocation || toolLoading || toolError) return;
    const current = tools.find(item => item.name === tool?.name);
    if (tool && current !== tool) { setTool(current || null); return; }
    if (!tool && isCloudTranslation(connection)) {
      const ready = tools.find(item => item.enabled && cloudTranslationSchema(item));
      if (ready) { setTool(ready); setTextField('text'); setLanguageField('target_language'); }
    }
  }, [translationMode, invocation, tools, tool, toolLoading, toolError, selected, connection]);
  useEffect(() => {
    modelEpoch.current++; setModelCatalog(null); setTranslationModel(''); setModelError(''); setModelLoading(false);
    if (officialTool && !invocation) void loadModels(true);
  }, [officialTool, tool?.definitionHash, selected, owner]);
  const action = async (work: () => Promise<void>) => {
    if (actionLock.current || !validOwner()) return;
    actionLock.current = true;
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (cause) {
      if (validOwner()) setError((cause as Error).message);
    } finally {
      if (validOwner()) { actionLock.current = false; setBusy(false); }
    }
  };
  const checkProvision = async () => {
    const list = await listMCPConnections();
    if (!validOwner()) return;
    setConnections(list.connections);
    const found = list.connections.find(isCloudTranslation);
    if (found) { setSelected(found.id); setProvisionUnknown(false); setProviderError(''); }
    else { setProvisionUnknown(true); setProviderError('尚未核验到官方连接。请继续查询原连接；不会自动重新提交或执行翻译。'); }
  };
  const connectOfficial = async () => action(async () => {
    setProviderError('');
    try {
      const result = await provisionMCPTranslation();
      if (!validOwner()) return;
      if (!isCloudTranslation(result.connection) || result.provider.id !== 'vinote-cloud-translation'
        || result.provider.toolName !== cloudTranslationTool || result.provider.textParameter !== 'text'
        || result.provider.languageParameter !== 'target_language') throw new Error('官方连接返回信息无法核验，请查询原连接。');
      setConnections(list => [result.connection, ...list.filter(item => item.id !== result.connection.id)]);
      setSelected(result.connection.id); setProvisionUnknown(false);
      if (!result.provider.configured) setProviderError('VINote 云模型服务尚未配置，请等待服务配置完成。');
    } catch (cause) {
      if (!validOwner()) return;
      const status = (cause as { status?: number }).status;
      if (status === 404 || status === 405) { setProviderError('当前服务暂不支持第一方云翻译，请等待服务升级。'); return; }
      if (status === 503) { setProviderError('VINote 云模型服务尚未配置，请等待服务配置完成。'); return; }
      if (status) throw cause;
      setProvisionUnknown(true);
      try { await checkProvision(); } catch { if (validOwner()) setProviderError('连接提交结果未知，请查询原连接。不会自动重新提交或执行翻译。'); }
    }
  });
  const persist = (receipt: MCPReceipt, visibleEpoch = dialogEpoch.current) => {
    if (!owner || !validOwner()) throw new Error('账号已变化，请核验当前账号的请求。');
    writeMCPReceipt(owner, receipt); setReceipts(readMCPReceipts(owner)); if (visibleEpoch === dialogEpoch.current) setInvocation(receipt);
  };
  const acceptRun = (receipt: MCPReceipt, result: TranslationRun, visibleEpoch = dialogEpoch.current) => { const updated = verifyMCPRun(receipt, result); persist(updated, visibleEpoch); if (visibleEpoch === dialogEpoch.current) setRun(result); setRuns(old => [result, ...old.filter(item => item.id !== result.id)]); };
  const query = async (receipt: MCPReceipt) => {
    const visibleEpoch = dialogEpoch.current;
    const result = await queryMCPRequest(receipt.requestId);
    if (!validOwner()) return;
    let updated = verifyMCPRun(receipt, result);
    if (receipt.saving && receipt.source && receipt.saveBody) {
      const note = await workspace.loadDetail(receipt.source.note_key, true);
      if (!validOwner()) return;
      const savedVersion = receipt.saveBody.versions?.[0];
      if (savedVersion && note.versions.some(version => version.id === savedVersion.id && version.content === savedVersion.content)) updated = { ...updated, saving: false, saved: true };
    }
    persist(updated, visibleEpoch); if (visibleEpoch === dialogEpoch.current) setRun(result); setRuns(old => [result, ...old.filter(item => item.id !== result.id)]);
  };
  const recover = (receipt: MCPReceipt) => {
    setConfigOpen(false); setAdding(false);
    dialogEpoch.current++; setSelected(receipt.connectionId); setTool(tools.find(item => item.name === receipt.toolName && receipt.connectionId === selected) || null); setRun(null); setInvocation(receipt); setArgumentsText(JSON.stringify(receipt.arguments, null, 2)); setComparison('result');
    void action(() => query(receipt));
  };
  const invoke = async (confirmed = false) => action(async () => {
    if (!connection || !tool || !owner) return;
    if (managed && !translationMode) throw new Error("请从已保存内容详情进入全文翻译，再核对源版本。");
    const visibleEpoch = dialogEpoch.current;
    let request = invocation;
    if (request && !confirmed) { await query(request); return; }
    if (request && (request.connectionId !== connection.id || request.toolName !== tool.name)) throw new Error('原请求已绑定其他服务或工具，请查询原请求。');
    if (!request) {
      const pending = readMCPReceipts(owner).find(item => !item.status || ['awaiting_confirmation', 'running', 'unknown'].includes(item.status));
      if (pending) { recover(pending); throw new Error('已有未确认的请求，请先查询原请求，不会重复调用。'); }
      let args: Record<string, unknown>;
      let source: MCPReceipt['source'], mapping: MCPReceipt['mapping'];
      if (translationMode) {
        if (sourceError || !selectedNote || !sourceVersion || selectedNote.deleted || workspace.owner !== owner) throw new Error('请先选择完整的已保存版本。');
        source = { note_key: selectedNote.key, source_version_id: sourceVersion.id, base_revision: selectedNote.revision, content: sourceVersion.content };
        mapping = { text_parameter: textField, language_parameter: languageField, target_language: targetLanguage };
        if (managed && !officialTool) throw new Error('官方工具定义无法核验，请重新发现工具；不会执行。');
        if (officialTool) mapping = { ...mapping, model_parameter: 'model', model: validatedTranslationModel(modelCatalog, translationModel) };
        args = translationArguments(tool, source, mapping);
      } else {
        const parsed: unknown = JSON.parse(argumentsText);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('参数必须是 JSON 对象');
        args = parsed as Record<string, unknown>;
      }
      request = { connectionId: connection.id, requestId: crypto.randomUUID(), toolName: tool.name, arguments: args, ...(source ? { source, mapping } : {}) };
      persist(request); // Durable before the first POST; tokens are never persisted.
    }
    if (confirmed && (run?.status !== 'awaiting_confirmation' || !run.confirmationToken || run.requestId !== request.requestId)) throw new Error('请先查询原请求并重新核对授权。');
    if (confirmed) { request = { ...request, status: 'running' }; persist(request, visibleEpoch); setRun(null); }
    const result = await apiJson<TranslationRun>(`${mcpBase}/${encodeURIComponent(request.connectionId)}/invoke`, { method: 'POST', body: JSON.stringify({ requestId: request.requestId, toolName: request.toolName, arguments: request.arguments, ...(confirmed ? { confirmed: true, confirmationToken: run!.confirmationToken } : {}) }) });
    if (validOwner()) acceptRun(request, result, visibleEpoch);
  });
  const output = run ? translationText(run) : null;
  const awaitingExecution = run?.status === 'awaiting_confirmation';
  const readingOriginalRequest = !!invocation && busy && !run;
  const fields = tool ? translationFields(tool) : [];
  const previewSource = invocation?.source?.content ?? sourceVersion?.content;
  const recoverable = receipts.filter(item => !item.saved && (!!item.source || !item.status || ['awaiting_confirmation', 'running', 'unknown'].includes(item.status)));
  let mappingError = '';
  if (translationMode && tool && sourceVersion && selectedNote && !invocation) try { translationArguments(tool, { note_key: selectedNote.key, source_version_id: sourceVersion.id, base_revision: selectedNote.revision, content: sourceVersion.content }, { text_parameter: textField, language_parameter: languageField, target_language: targetLanguage, ...(officialTool ? { model_parameter: 'model' as const, model: validatedTranslationModel(modelCatalog, translationModel) } : {}) }); } catch (cause) { mappingError = (cause as Error).message; }
  const readyTool = !!tool && tools.some(item => item === tool && item.enabled);
  const unresolvedRequest = receipts.some(item => !item.status || ['awaiting_confirmation', 'running', 'unknown'].includes(item.status) || item.saving);
  const prepareDisabled = busy || !loaded || !!recoveryError || !!invocation || unresolvedRequest || !connection?.enabled
    || connection.status !== 'connected' || toolLoading || !!toolError || !readyTool
    || !!sourceError || !selectedNote || !sourceVersion || selectedNote.deleted || workspace.owner !== owner
    || !!mappingError || !textField || !languageField
    || (managed && !officialTool);
  const serviceStatus = !loaded ? loading ? '正在读取连接状态…' : '连接状态尚未确认'
    : !connection ? '尚未选择服务' : !connection.enabled ? '连接已禁用'
    : connection.status === 'error' ? '连接需处理，请在连接与授权中核验'
    : connection.status !== 'connected' ? '连接已保存，待发现工具'
    : toolLoading ? '正在核对工具与授权…' : toolError ? '工具与授权状态尚未确认'
    : managed && !tools.some(cloudTranslationSchema) ? '工具定义尚未核验，请重新发现'
    : !readyTool ? '请选择兼容工具并明确授权' : '工具已授权；执行前仍需确认';
  const translationControls = <div className="grid gap-4"><Field><FieldLabel htmlFor="mcp-target-language">目标语言</FieldLabel><NativeSelect id="mcp-target-language" value={targetLanguage} disabled={busy} onChange={event => setTargetLanguage(event.target.value as 'en' | 'zh')}><NativeSelectOption value="en">英语（en）</NativeSelectOption><NativeSelectOption value="zh">中文（zh）</NativeSelectOption></NativeSelect></Field>{officialTool && <Field>
            <FieldLabel htmlFor="mcp-translation-model">翻译模型</FieldLabel>
            <NativeSelect id="mcp-translation-model" value={translationModel} disabled={busy || modelLoading || !modelCatalog} aria-describedby="mcp-model-help" onChange={event => setTranslationModel(event.target.value)}>
              <NativeSelectOption value="">明确选择翻译模型</NativeSelectOption>
              {translationModel && modelCatalog && !modelCatalog.models.some(item => item.id === translationModel) && <NativeSelectOption value={translationModel} disabled>{translationModel}（不可用，请重选）</NativeSelectOption>}
              {modelCatalog?.models.map(item => <NativeSelectOption key={item.id} value={item.id}>{item.id}</NativeSelectOption>)}
            </NativeSelect>
            <FieldDescription id="mcp-model-help">{modelLoading ? '正在读取当前账号可用模型…' : modelError || (!modelCatalog ? '模型列表尚未核验，不能准备调用。' : !modelCatalog.models.length ? '当前账号没有可用模型，不能准备调用。' : modelCatalog.defaultModel ? '仅预选服务核验的默认模型；可以明确更换。本机偏好不视为云端同步。' : '服务没有默认模型，请选择。不会自动使用列表首项或本机偏好。')}</FieldDescription>
            <Button variant="outline" disabled={busy || modelLoading} onClick={() => void loadModels()}>重新读取翻译模型</Button>
          </Field>}{mappingError && <p role="status" className="text-sm text-muted-foreground">{mappingError}</p>}</div>;
  const management = <div className="grid gap-5">
      <section aria-label="官方云翻译连接" className="grid gap-3 rounded-xl border p-4">
        <h2 className="text-sm font-medium">VINote 云翻译 · 第一方 MCP</h2>
        <p className="text-sm text-muted-foreground">使用当前云账号和 VINote 云模型服务，无需粘贴地址或令牌。连接本身不执行翻译；发现工具后还需逐项授权、预览并确认。</p>
        {/* Reserve status and recovery slots: async responses must not move nearby targets. */}
        <div role="region" aria-label="官方连接状态与帮助" tabIndex={0} className="min-h-12 break-words text-sm leading-6 focus-visible:outline focus-visible:outline-ring">
          <p role="status">{!loaded ? loading ? '正在读取连接状态…' : '连接状态尚未确认' : !official ? provisionUnknown ? '连接结果待核验' : '尚未连接' : !official.enabled ? '连接已禁用' : official.status !== 'connected' ? '连接已保存，待发现工具' : selected !== official.id ? '已发现工具，选择官方连接核对授权' : toolLoading ? '正在核对工具与授权…' : toolError ? '工具与授权状态尚未确认' : !tools.some(cloudTranslationSchema) ? '尚未发现兼容的翻译工具，请重新发现' : !tools.some(item => item.enabled && cloudTranslationSchema(item)) ? '已发现工具，待授权翻译工具' : '工具已授权，可准备调用；尚未执行翻译'}</p>
          {providerError && <p role="alert" className="text-destructive">{providerError}</p>}
        </div>
        <div aria-label="官方连接操作" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {official ? <Button className="h-10 w-full" variant="outline" disabled={busy} onClick={() => setSelected(official.id)}>查看官方连接与授权</Button> : <Button className="h-10 w-full" disabled={busy || !loaded || provisionUnknown} onClick={() => void connectOfficial()}>连接官方云翻译</Button>}
          <div className="h-10 min-w-0">
            {provisionUnknown && <Button className="h-10 w-full" variant="outline" disabled={busy} onClick={() => void action(checkProvision)}>查询原官方连接</Button>}
          </div>
        </div>
      </section>
      <details className="rounded-xl border p-4">
      <summary className="cursor-pointer text-sm font-medium">可连接哪些工具？</summary>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">接入你实际使用的翻译、术语检索或业务系统 HTTPS MCP 服务。添加连接后先发现工具，逐项启用，再从纪要详情选择内容调用。这里只管理远程服务；不把尚未接入的产品列成已安装插件。</p>
      </details>
      {error && (
        <ErrorState
          error={error}
          onRetry={() => void refresh()}
          busy={busy || loading}
          retryLabel="重新读取服务状态"
        />
      )}
      {!loaded && loading && <LoadingState label="正在读取 MCP 服务…" />}
      {!loaded && !loading && (
        <Alert>
          <AlertDescription>
            工具服务暂不可用。请检查共享集成服务的部署与登录状态；恢复后可重新读取。
          </AlertDescription>
        </Alert>
      )}
      {connections.length > 0 ? <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside
          aria-label="MCP 连接列表"
          className="flex min-w-0 flex-col gap-2 rounded-2xl border border-border/70 bg-muted/40 p-3"
        >
          <h2 className="px-3 py-2 text-xs font-semibold text-muted-foreground">
            已保存连接
          </h2>
          {connections.map((item) => (
            <Button
              key={item.id}
              aria-pressed={selected === item.id}
              aria-label={`${item.name.slice(0, 120)} · ${item.enabled ? "已启用" : "已禁用"}`}
              variant={selected === item.id ? "secondary" : "ghost"}
              className="h-auto justify-start py-3"
              onClick={() => { dialogEpoch.current++; setTool(null); setRun(null); setInvocation(null); setSelected(item.id); }}
              disabled={busy || (translationMode && !!invocation)}
            >
              <Plug />
              <span className="min-w-0 text-left">
                <span className="block truncate">{item.name}</span>
                <span className="block text-xs text-muted-foreground">
                  {!item.enabled
                    ? "已禁用"
                    : item.status === "connected"
                      ? "已发现工具"
                      : item.status === "error"
                        ? "连接需处理"
                        : "待验证"}
                </span>
              </span>
            </Button>
          ))}
          {loaded && !connections.length && (
            <EmptyState
              title="尚未连接工具"
              description="添加一个远程 HTTPS MCP 地址，再发现并选择工具。"
            />
          )}
        </aside>
        <section
          aria-label="选中连接与工具"
          className="flex min-w-0 flex-col gap-5 rounded-2xl border border-border/80 bg-background p-5"
        >
          {connection ? (
            <>
              <section
                aria-label="连接管理"
                className="flex flex-col gap-4 rounded-xl border border-border/60 bg-muted/30 p-4"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="font-medium">{connection.name}</h2>
                    <p className="break-all text-xs text-muted-foreground">
                      {managed ? "当前云账号 · VINote 云模型服务" : connection.url}
                    </p>
                  </div>
                  <Field orientation="horizontal">
                    <FieldLabel htmlFor="mcp-enabled">启用连接</FieldLabel>
                    <Switch
                      id="mcp-enabled"
                      checked={connection.enabled}
                      disabled={busy || (translationMode && !!invocation)}
                      onCheckedChange={(enabled) =>
                        void action(async () => {
                          const updated = await apiJson<MCPConnection>(path, {
                            method: "PATCH",
                            body: JSON.stringify({ enabled }),
                          });
                          if (!validOwner()) return;
                          setConnections((list) =>
                            list.map((c) =>
                              c.id === updated.id ? updated : c,
                            ),
                          );
                        })
                      }
                    />
                  </Field>
                </div>
                {connection.lastError && (
                  <ErrorState error={connection.lastError} />
                )}
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    disabled={busy || !connection.enabled || (translationMode && !!invocation)}
                    onClick={() =>
                      void action(async () => {
                        const result = await apiJson<{
                          connection: MCPConnection;
                          tools: MCPTool[];
                        }>(`${path}/discover`, { method: "POST" });
                        if (!validOwner()) return;
                        setTools(result.tools);
                        setConnections((list) =>
                          list.map((c) =>
                            c.id === result.connection.id
                              ? result.connection
                              : c,
                          ),
                        );
                        setToolError("");
                      })
                    }
                  >
                    <RefreshCw />
                    {busy ? "处理中…" : "连接并发现工具"}
                  </Button>
                  {!managed && <Button
                    variant="ghost"
                    disabled={busy || (translationMode && !!invocation)}
                    onClick={() => {
                      setEditingId(connection.id);
                      setName(connection.name);
                      setUrl(connection.url);
                      setAuthType(connection.authType === "token" ? "token" : "none");
                      setToken("");
                      setConfigOpen(false); setAdding(true);
                    }}
                  >
                    更新连接或凭证
                  </Button>}
                  <Button
                    variant="ghost"
                    disabled={busy || (translationMode && !!invocation)}
                    onClick={() => { setConfigOpen(false); setRemove(connection); }}
                  >
                    移除连接
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  {managed ? "官方地址与云账号由服务管理，不能编辑地址或凭证。启用连接不等于授权工具；新增或变化的工具需重新授权。" : "发现工具不会执行工具。自定义连接使用无认证或访问令牌，新增或变化的工具需重新启用。"}
                </p>
              </section>
              <section
                aria-labelledby="available-tools-heading"
                className="min-w-0"
              >
                <h2
                  id="available-tools-heading"
                  className="pb-3 text-sm font-semibold"
                >
                  可用工具
                </h2>
                {toolError && (
                  <ErrorState
                    error={toolError}
                    onRetry={() => void loadTools()}
                    busy={toolLoading}
                  />
                )}
                {toolLoading && <LoadingState rows={2} label="正在读取工具…" />}
                {tools.map((item) => (
                  <article
                    key={item.name}
                    className="flex flex-col gap-3 border-t py-4"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="break-all font-medium">{item.name}</h3>
                      <Switch
                        aria-label={`启用 ${item.name}`}
                        checked={item.enabled}
                        disabled={busy || !connection.enabled || (translationMode && !!invocation)}
                        onCheckedChange={(enabled) =>
                          void action(async () => {
                            const updated = await apiJson<MCPTool>(
                              `${path}/tools`,
                              {
                                method: "PATCH",
                                body: JSON.stringify({
                                  name: item.name,
                                  enabled,
                                }),
                              },
                            );
                            if (!validOwner()) return;
                            setTools((list) =>
                              list.map((t) =>
                                t.name === updated.name ? updated : t,
                              ),
                            );
                          })
                        }
                      />
                    </div>
                    <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                      {item.description}
                    </p>
                    {managed && <p className="text-xs text-muted-foreground">{cloudTranslationSchema(item) ? "官方正文、目标语言与模型参数已核验。请从笔记详情选择源版本；定义变化须重新发现并授权。" : "官方工具定义不匹配，不能执行。请重新发现工具并重新授权。"}</p>}
                    <Badge variant="outline" className="w-fit">
                      每次执行前确认
                    </Badge>
                    <Button
                      variant="outline"
                      className="w-fit"
                      disabled={!item.enabled || !connection.enabled || busy || (translationMode && !!invocation) || (managed && (connection.status !== "connected" || !cloudTranslationSchema(item)))}
                      onClick={() => {
                        if (owner) try { const pending = readMCPReceipts(owner).find(receipt => !receipt.status || ['awaiting_confirmation', 'running', 'unknown'].includes(receipt.status)); if (pending) { recover(pending); return; } } catch (cause) { setRecoveryError((cause as Error).message); return; }
                        if (managed && !translationMode) {
                          const next = new URLSearchParams(params); next.set('mode', 'translation');
                          setParams(next, { replace: true, state: location.state });
                        }
                        if (translationMode && isCloudTranslation(connection)) setConfigOpen(false);
                        if (!translationMode) dialogEpoch.current++;
                        setTool(item);
                        setArgumentsText("{}");
                        setRun(null);
                        setInvocation(null);
                        setScopeField(""); setTextField(isCloudTranslation(connection) && cloudTranslationSchema(item) ? "text" : ""); setLanguageField(isCloudTranslation(connection) && cloudTranslationSchema(item) ? "target_language" : ""); setTargetLanguage("en");
                        setError("");
                      }}
                    >
                      <Wrench />
                      {translationMode ? managed ? "准备官方云翻译" : "选择此工具翻译（高级）" : managed ? "准备官方云翻译" : "选择参数并预览调用"}
                    </Button>
                  </article>
                ))}
                {!toolLoading && !toolError && !tools.length && (
                  <EmptyState
                    title="暂无已发现工具"
                    description="点击连接并发现工具。服务返回空列表时可检查服务配置后再次发现。"
                  />
                )}
              </section>
            </>
          ) : loaded && connections.length > 0 ? (
            <EmptyState
              title="选择一个服务"
              description="查看工具、管理授权或执行本次调用。"
            />
          ) : null}
        </section>
      </div> : loaded ? <section className="rounded-2xl border">
        <EmptyState title={translationMode ? "没有远程翻译工具" : "尚未连接工具"} description="连接真实 HTTPS MCP 服务后，发现并启用兼容工具。连接本身不会执行任何操作。">
          <Button disabled={busy || (translationMode && !!invocation)} onClick={() => { setEditingId(''); setName(''); setUrl(''); setToken(''); setAuthType('none'); setAdding(true) }}><Plus data-icon="inline-start" />{translationMode ? "添加自定义翻译服务（高级）" : "添加自定义连接（高级）"}</Button>
        </EmptyState>
      </section> : null}
      <section
        aria-labelledby="tool-runs-heading"
        className="flex flex-col gap-3 rounded-2xl border border-border/80 bg-background p-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="tool-runs-heading" className="font-semibold">
            工具运行记录
          </h2>
          <Button
            variant="outline"
            size="sm"
            disabled={loading || busy}
            onClick={() => void refresh()}
          >
            刷新运行状态
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          运行位置：集成服务。结果未知时先检查外部结果，不自动重放；取消不能回滚远端副作用。
        </p>
        {runs.map((item) => (
          <details key={item.id} className="border-b py-4 last:border-b-0">
            <summary className="cursor-pointer text-sm">
              {item.toolName} · {mcpRunLabel[item.status]} ·{" "}
              {new Date(item.createdAt).toLocaleString()}
            </summary>
            <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs">
              {JSON.stringify(
                {
                  arguments: item.arguments,
                  result: item.result,
                  error: item.error,
                },
                null,
                2,
              )}
            </pre>
            {item.status === "awaiting_confirmation" && (
              <Button
                variant="outline"
                disabled={busy || (translationMode && !!invocation)}
                onClick={() =>
                  void action(async () => {
                    const updated = await apiJson<MCPRun>(
                      `${mcpBase}/runs/${encodeURIComponent(item.id)}/cancel`,
                      { method: "POST" },
                    );
                    if (!validOwner()) return;
                    setRuns((list) =>
                      list.map((r) => (r.id === updated.id ? updated : r)),
                    );
                  })
                }
              >
                取消待执行请求
              </Button>
            )}
          </details>
        ))}
        {loaded && !runs.length && (
          <EmptyState
            title="还没有调用记录"
            description="执行结果将保存在这里，离开页面后仍可查看。"
          />
        )}
        {hasMore && (
          <Button
            variant="outline"
            disabled={busy || (translationMode && !!invocation)}
            onClick={() =>
              void action(async () => {
                const next = await listMCPRuns(offset);
                if (!validOwner()) return;
                setRuns((old) => [
                  ...old,
                  ...next.runs.filter((r) => !old.some((i) => i.id === r.id)),
                ]);
                setOffset(offset + next.runs.length);
                setHasMore(next.runs.length === 50);
              })
            }
          >
            读取更早记录
          </Button>
        )}
      </section>

    {translationMode && tool && !invocation && <section aria-label="高级翻译参数映射" className="grid gap-3">{!officialTool && <><p className="text-sm">工具 schema 中的两个字符串字段由你明确选择；其他必填字段或复杂结构不兼容。</p>{[['mcp-text-field', '正文参数', textField, setTextField], ['mcp-language-field', '目标语言参数', languageField, setLanguageField]].map(([id, label, value, change]) => <Field key={id as string}><FieldLabel htmlFor={id as string}>{label as string}</FieldLabel><NativeSelect id={id as string} value={value as string} disabled={busy} onChange={event => (change as (value: string) => void)(event.target.value)}><NativeSelectOption value="">明确选择 schema 字段</NativeSelectOption>{fields.map(field => <NativeSelectOption key={field} value={field}>{field}</NativeSelectOption>)}</NativeSelect></Field>)}</>}</section>}
  </div>;
  return (
    <div className="workspace-page max-w-5xl">
      <PageReturn to={returnTo} label={pageParentLabel(returnTo)} />
      <PageHeading
        title={translationMode ? "全文翻译" : "MCP 工具"}
        description={translationMode ? "选择已保存源版本，预览后确认执行；结果核对后另存新版本。" : "连接远程 HTTPS 服务，只发送本次明确选择的参数。"}
        actions={!translationMode && connections.length > 0 &&
          <Button
            disabled={!loaded || busy}
            onClick={() => {
              setEditingId("");
              setName("");
              setUrl("");
              setToken("");
              setAuthType('none');
              setConfigOpen(false); setAdding(true);
            }}
          >
            <Plus />
            添加自定义连接（高级）
          </Button>
        }
      />
      {translationMode && <section aria-label="翻译来源" className="grid gap-3 rounded-xl border p-4 text-sm"><h2 className="font-medium">{selectedNote?.title || '翻译来源'}</h2><p>选择完整已保存正文，译文核对后另存新版本。原件和附件不会发送。</p>{selectedNote && (!invocation?.source || invocation.source.note_key === selectedNote.key) ? <Field><FieldLabel htmlFor="mcp-source-version">源版本</FieldLabel><NativeSelect id="mcp-source-version" value={invocation?.source?.source_version_id || versionId} disabled={busy || !!invocation} onChange={event => { setVersionId(event.target.value); setSourceError(''); }}><NativeSelectOption value="">明确选择已保存版本</NativeSelectOption>{selectedNote.versions.map(version => <NativeSelectOption key={version.id} value={version.id}>{savedWorkspaceVersionLabel(version)}</NativeSelectOption>)}</NativeSelect><FieldDescription>保留这份源版本作为原文；保存译文前仍会核验当前内容是否变化。</FieldDescription></Field> : <p role="status">{invocation?.source ? '恢复的是原请求固定源版本，正文在调用预览中；不会替换成当前打开内容。' : '尚未读取完整已保存版本，请返回内容详情选择版本；不会使用缓存正文代替。'}</p>}{sourceVersion && !invocation && <details><summary className="cursor-pointer">查看源正文</summary><MarkdownContent content={sourceVersion.content} remoteImagePolicy="confirm" /></details>}</section>}
      {sourceError && <p role="alert" className="text-sm text-destructive">{sourceError}</p>}
      {recoveryError && <ErrorState error={recoveryError} />}
      {recoverable.length > 0 && <section aria-label="MCP 请求恢复" className="grid gap-2 rounded-xl border p-4"><h2 className="text-sm font-medium">继续原请求</h2><p className="text-sm text-muted-foreground">关闭后原请求保留。恢复只查询，不会重新调用远程工具。</p>{recoverable.map(receipt => <Button key={receipt.requestId} variant="outline" disabled={busy} onClick={() => recover(receipt)}>{receipt.toolName} · 查询原请求</Button>)}</section>}
      {translationMode ? <>
        <section aria-label="翻译服务" className="grid gap-3 rounded-xl border p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-medium">{connection?.name || '选择真实 MCP 翻译服务'}</h2>
            <Button variant="outline" disabled={busy} onClick={() => setConfigOpen(true)}>连接与授权</Button>
          </div>
          <p role="status" className="min-h-6 text-sm text-muted-foreground">{serviceStatus}</p>
          {providerError && <p role="alert" className="text-sm text-destructive">{providerError}</p>}
        </section>
        {!invocation && <section aria-label="本次翻译" className="grid gap-4 rounded-xl border p-4">
          {translationControls}
          <Button disabled={prepareDisabled} onClick={() => void invoke()}>预览本次翻译</Button>
          {unresolvedRequest && <p role="status" className="text-sm text-muted-foreground">原请求尚待确认或恢复，请继续查询原请求；不会创建新的调用。</p>}
          {!readyTool && <p className="text-sm text-muted-foreground">请在连接与授权中核对工具；自定义工具需明确映射正文和语言字段。</p>}
        </section>}
        {error && !invocation && <ErrorState error={error} onRetry={() => void refresh()} busy={busy || loading} retryLabel="重新读取服务状态" />}
        <Dialog open={configOpen && !adding && !invocation} onOpenChange={setConfigOpen}>
          <DialogContent className="max-h-[85vh] overflow-auto sm:max-w-4xl">
            <DialogHeader><DialogTitle>连接与授权</DialogTitle><DialogDescription>连接、发现和授权不执行翻译。自定义服务与参数映射在此配置。</DialogDescription></DialogHeader>
            {management}
            <DialogFooter>
              {connections.length > 0 && <Button variant="ghost" disabled={busy} onClick={() => { setEditingId(''); setName(''); setUrl(''); setToken(''); setAuthType('none'); setConfigOpen(false); setAdding(true); }}>添加自定义翻译服务（高级）</Button>}
              <Button variant="outline" onClick={() => setConfigOpen(false)}>返回全文翻译</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </> : management}
      <Dialog
        open={adding}
        onOpenChange={(next) => {
          if (!busy) {
            setAdding(next);
            if (!next && translationMode) setConfigOpen(true);
            if (!next) {
              setToken("");
              setName("");
              setUrl("");
            }
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingId ? "更新连接" : "添加 MCP 连接"}
            </DialogTitle>
            <DialogDescription>
              首版支持公网 HTTPS Streamable HTTP
              地址。令牌保存在服务端，其他设备仅显示是否已配置。
            </DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="mcp-name">服务名称</FieldLabel>
              <Input
                id="mcp-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={120}
                disabled={busy}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="mcp-url">服务地址</FieldLabel>
              <Input
                id="mcp-url"
                type="url"
                placeholder="https://example.com/mcp"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={busy}
              />
              <FieldDescription>
                地址中不能包含凭证、查询参数或片段。
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="mcp-auth">认证方式</FieldLabel>
              <NativeSelect
                id="mcp-auth"
                value={authType}
                onChange={(e) => setAuthType(e.target.value as typeof authType)}
                disabled={busy}
              >
                <NativeSelectOption value="none">无认证</NativeSelectOption>
                <NativeSelectOption value="token">访问令牌</NativeSelectOption>
              </NativeSelect>
            </Field>
            {authType === "token" && (
              <Field>
                <FieldLabel htmlFor="mcp-token">访问令牌</FieldLabel>
                <Input
                  id="mcp-token"
                  type="password"
                  autoComplete="new-password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  disabled={busy}
                />
              </Field>
            )}
          </FieldGroup>
          {error && <ErrorState error={error} />}
          <DialogFooter>
            <Button
              disabled={
                busy ||
                !name.trim() ||
                !url.trim() ||
                (authType === "token" && !token.trim())
              }
              onClick={() =>
                void action(async () => {
                  const parsed = new URL(url);
                  if (
                    parsed.protocol !== "https:" ||
                    parsed.username ||
                    parsed.password ||
                    parsed.search ||
                    parsed.hash
                  )
                    throw new Error("请输入不含凭证、查询或片段的 HTTPS 地址");
                  const editingConnection = !!editingId;
                  const saved = await apiJson<MCPConnection>(
                    editingConnection
                      ? `${mcpBase}/${encodeURIComponent(editingId)}`
                      : mcpBase,
                    {
                      method: editingConnection ? "PATCH" : "POST",
                      body: JSON.stringify({
                        name: name.trim(),
                        url: url.trim(),
                        authType,
                        ...(authType === "token" ? { token } : {}),
                      }),
                    },
                  );
                  if (!validOwner()) return;
                  setConnections((list) => [
                    saved,
                    ...list.filter((c) => c.id !== saved.id),
                  ]);
                  setSelected(saved.id);
                  setAdding(false);
                  if (translationMode) setConfigOpen(true);
                  setName("");
                  setUrl("");
                  setToken("");
                })
              }
            >
              {busy ? "保存中…" : "保存连接"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!invocation || (!translationMode && !!tool)}
        onOpenChange={(next) => {
          if (!next) {
            dialogEpoch.current++; if (!translationMode) setTool(null);
            setInvocation(null);
            setRun(null);
          }
        }}
      >
        <DialogContent className="max-h-[85vh] overflow-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{tool?.name || invocation?.toolName} · {invocation?.source || translationMode ? "全文翻译" : "调用预览"}</DialogTitle>
            <DialogDescription>
              目标：{managed ? "VINote 云模型服务 · 当前云账号" : connections.find(item => item.id === invocation?.connectionId)?.url || connection?.url}
              。工具结果仅作为数据；本次只发送下面明确填写的参数。
            </DialogDescription>
          </DialogHeader>
          <details>
            <summary className="cursor-pointer text-sm">查看参数结构（高级）</summary>
            <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-all text-xs">
              {JSON.stringify(tool?.inputSchema, null, 2)}
            </pre>
          </details>
          {!translationMode && !invocation?.source && !managed && <Field>
            <FieldLabel htmlFor="tool-args">本次参数（JSON）</FieldLabel>
            <Textarea
              id="tool-args"
              value={argumentsText}
              onChange={(e) => setArgumentsText(e.target.value)}
              disabled={busy || !!invocation}
              className="min-h-40 font-mono"
            />
          </Field>}
          {selectedNote && !invocation && !translationMode && (
            <Field>
              <FieldLabel htmlFor="tool-scope-field">
                显式附加所选笔记正文到参数字段
              </FieldLabel>
              <Input
                id="tool-scope-field"
                value={scopeField}
                onChange={(e) => setScopeField(e.target.value)}
                placeholder="填写工具接受的字符串字段名称"
              />
              <FieldDescription>
                {selectedNote.title} · r{selectedNote.revision}
                。仅附加正文，不包含原始录音。
              </FieldDescription>
              <Button
                variant="outline"
                disabled={!scopeField.trim()}
                onClick={() => {
                  try {
                    const args = JSON.parse(argumentsText);
                    if (
                      !args ||
                      typeof args !== "object" ||
                      Array.isArray(args)
                    )
                      throw new Error("参数必须为对象");
                    setArgumentsText(
                      JSON.stringify(
                        { ...args, [scopeField.trim()]: selectedNote.content },
                        null,
                        2,
                      ),
                    );
                  } catch (cause) {
                    setError((cause as Error).message);
                  }
                }}
              >
                附加这份正文
              </Button>
            </Field>
          )}
          {sourceError && <p role="alert" className="text-sm text-destructive">{sourceError} 关闭预览后，在源版本中明确重选。</p>}
          {translationMode && !invocation && !sourceVersion && !sourceError && <p role="status" className="text-sm">尚未选择完整已保存正文，请关闭预览并从内容详情选择源版本。</p>}
          {error && <ErrorState error={error} />}
          {run && (
            <>
              <Badge
                variant={
                  run.status === "failed" || run.status === "unknown"
                    ? "destructive"
                    : "secondary"
                }
              >
                {mcpRunLabel[run.status]}
              </Badge>
              {run.error && <ErrorState error={run.error.message} />}
              {run.status === "unknown" && (
                <Alert>
                  <AlertDescription>
                    远端可能已执行，请先在外部服务核验结果。本次请求不会自动重新执行。
                  </AlertDescription>
                </Alert>
              )}
              {!invocation?.source && run.result != null && (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-md border p-3 text-xs">
                  {JSON.stringify(run.result, null, 2)}
                </pre>
              )}
            </>
          )}
          {invocation?.source && <div className="grid gap-4"><p className="text-sm text-muted-foreground">目标语言：{invocation.mapping?.target_language === 'zh' ? '中文' : '英语'}。本次只发送下列完整源正文、目标语言{invocation.mapping?.model ? `及模型 ${invocation.mapping.model}` : "（原请求未显式指定模型）"}；{readingOriginalRequest ? '正在核验原请求，读取完成前不推断执行或取消状态。' : awaitingExecution ? '确认后才会执行翻译；关闭预览保留待确认请求。' : '关闭预览不撤销已执行的调用。'}</p><div className="flex gap-2 md:hidden" role="group" aria-label={readingOriginalRequest ? '核对原文与原请求' : awaitingExecution ? '核对原文与执行说明' : '核对原文与译文'}><Button aria-pressed={comparison === 'source'} variant="outline" onClick={() => setComparison('source')}>原文</Button><Button aria-pressed={comparison === 'result'} variant="outline" onClick={() => setComparison('result')}>{readingOriginalRequest ? '请求状态' : awaitingExecution ? '执行说明' : '译文'}</Button></div><div className="grid gap-4 md:grid-cols-2"><section aria-label="翻译源原文" className={`min-w-0 rounded-xl border p-3 ${comparison === 'source' ? '' : 'hidden md:block'}`}><h3 className="mb-2 text-sm font-medium">原文（固定源版本）</h3><div className="max-h-80 overflow-auto"><MarkdownContent content={previewSource || ''} /></div></section><section aria-label={readingOriginalRequest ? '原请求核验' : awaitingExecution ? '翻译执行说明' : 'MCP 译文预览'} className={`min-w-0 rounded-xl border p-3 ${comparison === 'result' ? '' : 'hidden md:block'}`}><h3 className="mb-2 text-sm font-medium">{readingOriginalRequest ? '正在核验原请求' : awaitingExecution ? '等待执行确认' : '译文预览'}</h3><div className="max-h-80 overflow-auto">{output ? <MarkdownContent content={output} remoteImagePolicy="confirm" imageSessionKey={`${owner}:${invocation.requestId}`} /> : <p className="text-sm text-muted-foreground">{readingOriginalRequest ? '读取完成前不推断执行、取消或译文状态；原文与原请求保留。' : awaitingExecution ? '确认后才会执行翻译。本次原请求尚待确认；核验原请求只读取状态，不执行工具。' : run?.status === 'succeeded' ? '工具没有返回完整可保存的纯文本结果；原文保留。' : run?.status === 'cancelled' ? '本次请求已取消；原文保留。' : '尚无已确认译文，请查询原请求。'}</p>}</div></section></div>
            {output && <><p className="text-sm text-muted-foreground">核对后按普通编辑保存为当前新版本，原文版本保留；不会自动发布到飞书。保存不代表后台校验翻译事实。</p><Button disabled={busy || invocation.saving || invocation.saved || !!recoveryError || workspace.owner !== owner} onClick={() => void action(async () => {
              if (!run || !invocation.source || !owner) return;
              const visibleEpoch = dialogEpoch.current;
              const note = await workspace.loadDetail(invocation.source.note_key, true);
              if (!validOwner()) return;
              const body = invocation.saveBody || translationSaveBody(note, invocation, run);
              const saving = { ...invocation, saving: true, saveBody: body }; persist(saving, visibleEpoch);
              const saved = await workspace.save(note.key, body);
              if (!validOwner()) return;
              const version = body.versions?.[0];
              if (!saved || !version || saved.revision <= body.base_revision || !saved.versions.some(item => item.id === version.id && item.content === version.content)) throw new Error('保存尚未确认；译文和原请求已保留，请检查版本后重试。');
              persist({ ...saving, saving: false, saved: true }, visibleEpoch);
            })}>{invocation.saved ? '新版本已保存' : invocation.saving ? '保存待核验' : '核对无误，保存为新版本'}</Button>{invocation.saving && <p role="status" className="text-sm">保存结果待核验，请检查笔记版本。译文与原文保留，不会再次调用工具。</p>}</>}
          </div>}
          <DialogFooter>
            {invocation && <Button variant="outline" disabled={busy} onClick={() => void action(() => query(invocation))}>{readingOriginalRequest ? '正在核验原请求' : awaitingExecution ? '核验原请求（不会执行）' : '查询原请求状态'}</Button>}
            {run?.status === 'awaiting_confirmation' && invocation ? <><Button variant="outline" disabled={busy} onClick={() => void action(async () => { const visibleEpoch = dialogEpoch.current; const updated = await apiJson<TranslationRun>(`${mcpBase}/runs/${encodeURIComponent(run.id)}/cancel`, { method: 'POST' }); if (validOwner()) acceptRun(invocation, updated, visibleEpoch); })}>取消待执行请求</Button><Button disabled={busy || !tool || !connection?.enabled || !tool.enabled || !run.confirmationToken || invocation.connectionId !== selected} onClick={() => void invoke(true)}>确认服务、正文与参数，执行工具</Button></> : !invocation && <Button disabled={busy || !!recoveryError || !tool || !connection?.enabled || !tool.enabled || (translationMode && (!!sourceError || !selectedNote || !sourceVersion || !!mappingError || !textField || !languageField || (managed && !officialTool)))} onClick={() => void invoke()}>准备调用并检查授权</Button>}
          </DialogFooter>
          <Button variant="ghost" onClick={() => { dialogEpoch.current++; if (!translationMode) setTool(null); setInvocation(null); setRun(null); }}>关闭预览（保留原请求）</Button>

        </DialogContent>
      </Dialog>
      <AlertDialog
        open={!!remove}
        onOpenChange={(next) => {
          if (!busy && !next) setRemove(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>移除 {remove?.name}？</AlertDialogTitle>
            <AlertDialogDescription>
              清除凭证并阻止新调用。笔记与运行记录保留；已执行的远端动作无法回滚。
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && <ErrorState error={error} />}
          <AlertDialogFooter>
            <Button
              variant="outline"
              onClick={() => setRemove(null)}
              disabled={busy}
            >
              保留连接
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  if (!remove) return;
                  await apiJson(`${mcpBase}/${remove.id}`, {
                    method: "DELETE",
                  });
                  if (!validOwner()) return;
                  setConnections((list) =>
                    list.filter((c) => c.id !== remove.id),
                  );
                  setRemove(null);
                  setSelected("");
                })
              }
            >
              确认移除
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
