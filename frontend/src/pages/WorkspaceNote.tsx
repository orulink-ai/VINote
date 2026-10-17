import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel } from '@/components/ui/alert-dialog';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { resolvePageParent, pageParentLabel } from '@/lib/navigation';
import { PageReturn } from '@/components/Layout/PageReturn';
import { ArrowLeft, GitBranch, Save, Wand2, Wrench, MoreHorizontal, Trash2 } from "lucide-react";
import { apiJson, ApiError } from "@/lib/api";
import { readGenerationRecovery, writeGenerationRecovery, clearGenerationRecovery, type SavedGenerationRequest } from '@/lib/workspaceGenerationRecovery';
import {
  workspacePath,
  type WorkspaceNote as SharedNote,
  type WorkspaceWrite,
  type WorkspaceTranscript,
} from "@/lib/workspace";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { SavedContentShare } from '@/components/Notes/SavedContentShare';
import { useAuthStore } from "@/stores/authStore";
import {
  readTextDraft,
  removeTextDraft,
  useProtectedDraft,
} from "@/hooks/useProtectedDraft";
import {
  LoadingState,
  ErrorState,
  EmptyState,
} from "@/components/Feedback/ResourceState";
import { MarkdownContent } from "@/components/Markdown/MarkdownContent";
import { VersionCompare } from "@/components/Notes/VersionCompare";
import { ExportPanel } from "@/components/Notes/ExportPanel";
import { FeishuDelivery } from "@/components/Notes/FeishuDelivery";
import { MeetingConversation } from "@/components/Notes/MeetingConversation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Field, FieldLabel, FieldGroup } from "@/components/ui/field";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";

const versionSnapshot = (version: SharedNote['versions'][number]) => /^__vinote:(current|saved):([1-9]\d*)$/.exec(version.id);
function savedVersionLabel(version: SharedNote['versions'][number]) {
  const snapshot = versionSnapshot(version);
  const meaning = snapshot
    ? `${snapshot[1] === 'current' ? '自动正文快照' : '写入前正文快照'}`
    : version.kind === 'edit' ? '正文编辑'
    : `${version.kind === 'generated' ? '生成版本' : version.kind === 'imported' ? '导入记录' : '其他保存记录'}${version.title ? ` · ${version.title}` : ''}`;
  const time = version.created_at?.trim() ? new Date(version.created_at) : null;
  return `${meaning} · ${time && Number.isFinite(time.getTime()) ? time.toLocaleString() : '时间未记录'}`;
}

export function WorkspaceNote() {
  const { key = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const requestedParent = location.state?.returnTo ?? new URLSearchParams(location.search).get('returnTo');
  const returnTo = resolvePageParent(requestedParent);
  const returnLabel = pageParentLabel(returnTo);
  const owner = useAuthStore((s) => s.user?.id);
  const {
    details,
    mappings,
    loadDetail,
    save,
    busy: storeBusy,
    ready,
    owner: workspaceOwner,
    error: workspaceError,
    initialize,
    changeDeleted,
  } = useWorkspaceStore();
  const [baseline, setBaseline] = useState<SharedNote | null>(null);
  const [readContext, setReadContext] = useState({ owner, key });
  const sameRead = readContext.owner === owner && readContext.key === key && workspaceOwner === owner;
  const note = sameRead ? details[key] ?? baseline ?? undefined : undefined;
  const textSource = ['file', 'text', 'document', 'transcript'].includes(note?.source_type || '');
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [readError, setReadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editorPreview, setEditorPreview] = useState(false);
  const [tab, setTab] = useState(() =>
    new URLSearchParams(window.location.search).get("view") === "chat"
      ? "chat"
      : "summary",
  );
  const [versionId, setVersionId] = useState("");
  const [contextOpen, setContextOpen] = useState(false);
  const [compare, setCompare] = useState(false);
  const [generate, setGenerate] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [template, setTemplate] = useState<"minutes" | "summary" | "actions">(
    "minutes",
  );
  const [generation, setGeneration] = useState<SavedGenerationRequest | null>(null);
  const [leave, setLeave] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const deleteReturn = useRef<{ element: HTMLButtonElement; owner: string | undefined; key: string } | null>(null);
  const [historicalTranscript, setHistoricalTranscript] =
    useState<WorkspaceTranscript | null>(null);
  const [evidenceError, setEvidenceError] = useState("");
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const [evidenceAttempt, setEvidenceAttempt] = useState(0);
  const [classificationOpen, setClassificationOpen] = useState(false);
  const [project, setProject] = useState("");
  const [tags, setTags] = useState("");
  const dirty =
    sameRead && !!baseline && (title !== baseline.title || content !== baseline.content);
  const draftStatus = useProtectedDraft(
    `workspace:${key}`,
    title,
    content,
    dirty,
    baseline?.revision,
  );
  const selected = versionId
    ? note?.versions.find((v) => v.id === versionId)
    : undefined;
  const viewedTranscript = selected ? historicalTranscript : baseline?.transcript;
  useEffect(() => {
    let active = true;
    setHistoricalTranscript(null);
    setEvidenceError("");
    setEvidenceBusy(false);
    if (!selected || textSource) return;
    if (selected.evidence_revision == null) {
      setEvidenceError(
        "此历史版本未保存输入原文证据，不能使用当前逐字稿代替。",
      );
      return;
    }
    setEvidenceBusy(true);
    void apiJson<{ transcript: WorkspaceTranscript | null }>(
      `${workspacePath(key)}/evidence/${selected.evidence_revision}`,
    )
      .then((result) => {
        if (active) setHistoricalTranscript(result.transcript);
      })
      .catch((cause) => {
        if (active) setEvidenceError(cause.message);
      })
      .finally(() => {
        if (active) setEvidenceBusy(false);
      });
    return () => {
      active = false;
    };
  }, [key, versionId, selected?.evidence_revision, evidenceAttempt, textSource]);
  const viewedContent = selected?.content ?? content;
  const viewedTitle = selected?.title ?? title;
  const isMeeting = ["meeting_recording", "meeting_video"].includes(note?.source_type || "");
  const previewContent = !editing
    ? viewedContent.replace(/^#[ \t]+([^\r\n]+)(?:\r?\n|$)/, (heading, headingTitle: string) =>
        headingTitle.trim() === viewedTitle.trim() ? "" : heading)
    : viewedContent;
  const toolVersion = selected?.id || note?.versions.find(version =>
    version.content === baseline?.content && version.title === baseline?.title)?.id;
  const detailParams = new URLSearchParams(location.search);
  detailParams.set("returnTo", returnTo);
  if (selected) detailParams.set("version", selected.id);
  else detailParams.delete("version");
  const detailReturnTo = location.pathname + "?" + detailParams.toString() + location.hash;
  const toolsBlocked = dirty || saving || !!note?.deleted || !!readError || loading || !toolVersion;
  const localId = Object.entries(mappings).find(
    ([, value]) => value.key === key,
  )?.[0];
  const restore = (next: SharedNote) => {
    let draft = null;
    try {
      if (owner) draft = readTextDraft(owner, `workspace:${key}`);
    } catch {
      setError("无法读取本机草稿，请检查浏览器存储权限");
    }
    setBaseline(
      draft && typeof draft.baseRevision === "number"
        ? { ...next, revision: draft.baseRevision }
        : next,
    );
    setTitle(draft?.title ?? next.title);
    setContent(draft?.content ?? next.content);
    const requestedVersion = new URLSearchParams(location.search).get('version');
    if (!draft && requestedVersion) {
      if (next.versions.some(version => version.id === requestedVersion)) setVersionId(requestedVersion);
      else setError('返回的历史版本不可用，请在来源与版本中明确重新选择；当前显示最新已保存正文。');
    }
    if (new URLSearchParams(window.location.search).get("classify") === "1") {
      setProject(
        typeof next.metadata.project === "string" ? next.metadata.project : "",
      );
      setTags(
        Array.isArray(next.metadata.tags) ? next.metadata.tags.join("，") : "",
      );
      setContextOpen(false);
                  setClassificationOpen(true);
    }
    if (draft) {
      setEditing(true);
      if (draft.baseRevision !== next.revision)
        setError("本机草稿基于较早保存记录，保存前请核对当前已保存正文。");
    }
    else if (new URLSearchParams(location.search).get('edit') === '1') setEditing(true);
  };
  useEffect(() => {
    if (!ready || !owner || workspaceOwner !== owner) return;
    let active = true;
    const stillCurrent = () => active && useAuthStore.getState().user?.id === owner && useWorkspaceStore.getState().owner === owner;
    setReadContext({ owner, key });
    setError("");
    setReadError("");
    setVersionId("");
    setBaseline(null);
    setEditing(false);
    setGeneration(null);
    if (owner) {
      try {
        const recovery = readGenerationRecovery(owner, key);
        if (recovery) { setGeneration(recovery); setInstructions(recovery.instructions); setTemplate(recovery.template as 'minutes' | 'summary' | 'actions'); }
      } catch (cause) { setError((cause as Error).message); }
    }
    const cached = useWorkspaceStore.getState().details[key];
    if (cached) restore(cached);
    setLoading(true);
    void loadDetail(key, true)
      .then((next) => {
        if (!stillCurrent()) return;
        if (next.key !== key) throw new Error('读取的内容标识不匹配，请重试原链接');
        restore(next);
      })
      .catch((cause) => {
        if (!stillCurrent()) return;
        // loadDetail can publish the fetched note before offline-cache persistence
        // fails. Keep that exact record readable while reporting the failure.
        const fetched = useWorkspaceStore.getState().details[key];
        if (fetched) restore(fetched);
        setReadError(cause instanceof Error ? cause.message : '读取失败，请重试');
      })
      .finally(() => {
        if (stillCurrent()) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [key, owner, workspaceOwner, attempt, loadDetail, ready]);
  useEffect(() => {
    if (!note || !baseline || note.key !== baseline.key || note.revision === baseline.revision || dirty || saving) return;
    setBaseline(note); setTitle(note.title); setContent(note.content);
  }, [note, baseline, dirty, saving]);
  const saved = (next: SharedNote) => {
    setBaseline(next);
    setTitle(next.title);
    setContent(next.content);
    setVersionId("");
    setEditing(false);
    setClassificationOpen(false);
    if (owner) {
      try {
        removeTextDraft(owner, `workspace:${key}`);
      } catch {
        /* The persisted revision is authoritative. */
      }
    }
  };
  const saveDraft = async (patch: Partial<WorkspaceWrite> = {}) => {
    if (!baseline || saving) return;
    setSaving(true);
    setError("");
    try {
      const body: WorkspaceWrite = {
        base_revision: baseline.revision,
        operation_id: crypto.randomUUID(),
        title,
        content,
        source_type: baseline.source_type,
        source_device: baseline.source_device,
        transcript: baseline.transcript,
        metadata: baseline.metadata,
        archived: baseline.archived,
        ...patch,
      };
      const next = await save(key, body);
      if (next) saved(next);
      else
        setError(
          "保存未完成，草稿已保留。请重试保存或导出正文。",
        );
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const generateVersion = async () => {
    if (!baseline || !owner || saving || dirty || generation?.generatedContent) return;
    setSaving(true);
    setError("");
    const request = generation || {
      operation_id: crypto.randomUUID(),
      instructions,
      template,
      base_revision: baseline.revision,
    };
    setGeneration(request);
    try {
      writeGenerationRecovery(owner, key, request);
      const next = await apiJson<SharedNote>(`${workspacePath(key)}/generate`, {
        method: "POST",
        body: JSON.stringify(request),
      });
      if (useAuthStore.getState().user?.id !== owner) return;
      saved(next);
      await loadDetail(key, true);
      clearGenerationRecovery(owner, key);
      setGeneration(null);
      setGenerate(false);
    } catch (cause) {
      if (useAuthStore.getState().user?.id !== owner) return;
      const detail = cause instanceof ApiError ? cause.detail as { generated_content?: string } : null;
      const recovery = { ...request, error: (cause as Error).message, ...(detail?.generated_content ? { generatedContent: detail.generated_content } : {}) };
      setGeneration(recovery);
      try { writeGenerationRecovery(owner, key, recovery); } catch { setError(`${(cause as Error).message}；恢复记录未保存，请保留此页。`); return; }
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  };
  if ((!ready || workspaceOwner !== owner) && workspaceError)
    return (
      <div className="workspace-page">
        <PageReturn to={returnTo} label={returnLabel} />
        <ErrorState error={workspaceError} onRetry={() => { if (owner) void initialize(owner).catch(() => undefined); }} retryLabel="重新读取" />
      </div>
    );
  if (!ready || !sameRead || ((!note || !baseline) && loading))
    return (
      <div className="workspace-page">
        <PageReturn to={returnTo} label={returnLabel} />
        <LoadingState label="正在读取内容及版本…" />
      </div>
    );
  if (!note || !baseline)
    return (
      <div className="workspace-page">
        <ErrorState
          error={readError || error || "未能读取这份内容，请重试原链接"}
          onRetry={() => setAttempt((v) => v + 1)}
          busy={loading}
          retryLabel="重新读取"
        />
        <Button asChild variant="outline">
          <Link to={returnTo}>{returnLabel}</Link>
        </Button>
      </div>
    );
  const versionLabel = selected
    ? savedVersionLabel(selected)
    : '当前已保存正文';
  const generatedVersions = note.versions.filter(version => !versionSnapshot(version) && version.kind === 'generated');
  const otherVersions = note.versions.filter(version => versionSnapshot(version) || version.kind !== 'generated');
  const defaultVersionId = typeof note.metadata.default_version_id === 'string' ? note.metadata.default_version_id : '';
  const defaultLoaded = note.versions.some(version => version.id === defaultVersionId);
  const selectedSnapshot = selected ? versionSnapshot(selected) : null;
  const recordExplanation = !selected
    ? '当前已保存正文。'
    : selectedSnapshot?.[1] === 'current'
      ? '这是当时保存的自动正文快照，不代表此刻的最新正文，也不是一次新的生成。'
      : selectedSnapshot?.[1] === 'saved'
        ? '这是后续写入前保留的正文快照，不是一次新的生成。'
        : selected.kind === 'generated' ? '这是一次生成保存的正文版本。'
        : selected.kind === 'edit' ? '这是正文编辑保存的记录；时间相同不代表它与快照是同一记录。'
        : selected.kind === 'imported' ? '这是导入时保存的正文记录，不是正文编辑或生成记录。'
        : '这是已保存记录，未记录具体类型。';
  return (
    <div className="detail-page flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 flex-col gap-3 border-b bg-background px-6 py-4">
        <Button
          variant="ghost"
          className="w-fit"
          onClick={() => (dirty ? setLeave(true) : navigate(returnTo))}
        >
          <ArrowLeft />
          {returnLabel}
        </Button>
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0 flex-1">
            <p className="mb-2 text-xs text-muted-foreground">{isMeeting ? "会议纪要" : "笔记"}</p>
            {editing ? (
              <div className="grid gap-2">
                <Label htmlFor="workspace-note-title">{isMeeting ? "会议名称" : "笔记标题"}</Label>
                <Input id="workspace-note-title" value={title} onChange={(e) => setTitle(e.target.value)} disabled={saving} />
              </div>
            ) : (
              <h1 className="break-words text-2xl font-medium">{viewedTitle}</h1>
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              {note.source_device === "desktop" ? "桌面端" : note.source_device === "mobile" ? "手机" : note.source_device || "来源设备"} ·{" "}
              {typeof note.metadata.source_created_at === "string"
                ? `保存于 ${new Date(note.metadata.source_created_at).toLocaleString()}`
                : `记录于 ${new Date(note.created_at).toLocaleString()}`}
            </p>
          </div>
          <div role="group" aria-label="主要内容操作" className="flex flex-wrap items-start gap-2">
            {dirty ? (
              <Button size="sm" disabled={saving || storeBusy || !title.trim()} onClick={() => void saveDraft()}>
                <Save />{saving ? "保存中…" : "保存"}
              </Button>
            ) : (
              <Button size="sm" variant="outline" disabled={saving || !!selected || note.deleted}
                onClick={() => { setTab("summary"); setEditing(!editing); }}>
                {editing ? "返回阅读" : "编辑"}
              </Button>
            )}
            <ExportPanel title={viewedTitle} content={selected?.content ?? baseline.content} version={versionLabel} transcript={viewedTranscript?.full_text} disabled={dirty || saving || note.deleted} />
            <SavedContentShare title={viewedTitle} content={selected?.content ?? baseline.content} disabled={dirty || saving || note.deleted} />
            <Button size="sm" variant="ghost" className="text-destructive" disabled={dirty || saving || storeBusy || note.deleted} onClick={event => { deleteReturn.current = { element: event.currentTarget, owner, key }; setContextOpen(false); setDeleteOpen(true); }}><Trash2 />删除</Button>
            <FeishuDelivery noteId={key} title={viewedTitle} content={selected?.content ?? baseline.content}
              disabled={dirty || saving || note.deleted}
              versionId={selected?.id || note.versions.find(v => v.content === baseline.content && v.title === baseline.title)?.id}
              revisionId={String(baseline.revision)} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {dirty && <Badge variant="secondary">{draftStatus}</Badge>}
          <span className="text-xs text-muted-foreground">
            当前查看：{selected ? "历史版本" : "最新正文"} · 默认版本：
            {note.metadata.default_version_id ? "已指定" : "最新正文"}
          </span>

        </div>
        <details className="rounded-xl border bg-muted/20">
          <summary role="button" className="flex min-h-10 cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-ring [&::-webkit-details-marker]:hidden">
            <MoreHorizontal className="size-4" aria-hidden="true" />内容操作
          </summary>
          <div className="grid max-h-[40vh] gap-4 overflow-auto border-t p-3 md:grid-cols-2 xl:grid-cols-3">
            <section aria-label="版本与来源" className="grid content-start gap-2">
              <h2 className="text-xs font-medium text-muted-foreground">版本与来源</h2>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => setContextOpen(true)}><GitBranch />来源与版本</Button>
              </div>
              <p className="text-xs leading-5 text-muted-foreground">查看历史正文、输入证据和来源文件；查看不会修改当前内容。</p>
            </section>
            <section aria-label="内容工具" className="grid content-start gap-2">
              <h2 className="text-xs font-medium text-muted-foreground">内容工具</h2>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" asChild>
                  <Link to={`/settings/mcp?mode=translation&note=${encodeURIComponent(key)}${toolVersion ? '&version=' + encodeURIComponent(toolVersion) : ''}`}
                    state={{ returnTo: detailReturnTo }} aria-disabled={toolsBlocked || undefined} tabIndex={toolsBlocked ? -1 : undefined}
                    className={toolsBlocked ? "pointer-events-none opacity-50" : undefined}
                    onClick={event => { if (toolsBlocked) event.preventDefault(); }}><Wrench />全文翻译 · MCP</Link>
                </Button>
                <Button size="sm" variant="ghost" asChild>
                  <Link to={toolVersion ? `/connections?note=${encodeURIComponent(key)}&version=${encodeURIComponent(toolVersion)}` : "/connections"} state={{ returnTo: detailReturnTo }}>流程图整理（选择已保存内容）</Link>
                </Button>
              </div>
              <p className="text-xs leading-5 text-muted-foreground">{toolsBlocked ? "请先保存修改并读取完整正文版本，再在工具页确认发送范围；不发送草稿。" : "翻译使用当前查看的已保存版本，目标语言仅中文或英文；在工具页核对并授权。"}</p>
            </section>
            <section aria-label="分类与归档" className="grid content-start gap-2">
              <h2 className="text-xs font-medium text-muted-foreground">分类与归档</h2>
              <div className="flex flex-col items-start gap-2">
              <Button
                variant="outline"
                disabled={saving || dirty}
                onClick={() => {
                  setProject(
                    typeof note.metadata.project === "string"
                      ? note.metadata.project
                      : "",
                  );
                  setTags(
                    Array.isArray(note.metadata.tags)
                      ? note.metadata.tags.join("，")
                      : "",
                  );
                  setContextOpen(false);
                  setClassificationOpen(true);
                }}
              >
                项目与标签
              </Button>
              <Button
                variant="ghost"
                disabled={dirty || saving || note.deleted}
                onClick={() => void saveDraft({ archived: !note.archived })}
              >
                {note.archived ? "移出归档" : "归档内容"}
              </Button>


              </div>
            </section>
          </div>
        </details>
        {readError && (
          <ErrorState error={readError} onRetry={() => setAttempt((v) => v + 1)} busy={loading || saving} retryLabel="重新读取" />
        )}
        {error && (
          <ErrorState
            error={error}
            onRetry={
              dirty ? () => void saveDraft() : () => setAttempt((v) => v + 1)
            }
            busy={saving || loading}
            retryLabel={dirty ? "重试保存" : "重新读取"}
          />
        )}
        {note.deleted && (
          <Alert>
            <AlertDescription>
              内容已进入回收站，可在存储页恢复。原文件未删除。
            </AlertDescription>
          </Alert>
        )}
        {baseline.revision !== note.revision && dirty && (
          <Alert>
            <AlertDescription>
              已保存正文发生变化，草稿仍保留。保存前请核对。
              <Button variant="outline" onClick={() => { setContextOpen(false); setCompare(true) }}>
                比较已保存正文
              </Button>
            </AlertDescription>
          </Alert>
        )}
      </header>
      <div className="flex min-h-0 flex-1 flex-col bg-background lg:flex-row">

        <section
          aria-label={isMeeting ? "纪要阅读与编辑" : "笔记阅读与编辑"}
          className="flex min-h-0 min-w-0 flex-1 flex-col"
        >
          <Tabs
            value={tab}
            onValueChange={setTab}
            className="shrink-0 border-b px-6"
          >
            <TabsList className="line-tabs">
              <TabsTrigger value="summary">{isMeeting ? "纪要" : "正文"}</TabsTrigger>
              {!textSource && (note.transcript || selected) && (
                <TabsTrigger value="transcript">逐字稿</TabsTrigger>
              )}
              <TabsTrigger value="chat">对话</TabsTrigger>
            </TabsList>
          </Tabs>
          {tab === "chat" ? (
            <MeetingConversation
              document={textSource}
              key={`${key}:${versionId}`}
              noteId={key}
              workspace
              versionId={versionId || undefined}
            />
          ) : (
            <div className="min-h-0 flex-1 overflow-auto px-6 py-8 lg:px-10">
              {tab === "transcript" ? (
                evidenceBusy ? (
                  <LoadingState label="正在读取此版本的原文证据…" />
                ) : evidenceError ? (
                  <ErrorState
                    error={evidenceError}
                    onRetry={
                      selected?.evidence_revision != null
                        ? () => setEvidenceAttempt((v) => v + 1)
                        : undefined
                    }
                  />
                ) : viewedTranscript?.segments.length ? (
                  viewedTranscript.segments.map((s, i) => (
                    <p
                      key={i}
                      className="mb-4 text-sm leading-7"
                      style={{
                        contentVisibility: "auto",
                        containIntrinsicSize: "auto 80px",
                      }}
                    >
                      <span className="mr-3 text-muted-foreground">
                        {Math.floor(s.start / 60)}:
                        {String(Math.floor(s.start % 60)).padStart(2, "0")} ·{" "}
                        {s.speaker_label || s.speaker_id || "未知说话人"}
                      </span>
                      {s.text}
                    </p>
                  ))
                ) : (
                  <EmptyState
                    title="没有逐字稿"
                    description="这份内容未保存逐字稿。"
                  />
                )
              ) : editing ? (
                <div className="flex min-h-full flex-col gap-4">
                  <Label className="flex items-center gap-2" htmlFor="workspace-editor-preview">
                    <Checkbox id="workspace-editor-preview" checked={editorPreview} onCheckedChange={value => setEditorPreview(value === true)} />显示 Markdown 预览
                  </Label>
                  <div className={editorPreview ? "grid gap-6 xl:grid-cols-2" : "grid gap-6"}>
                  <Textarea
                    aria-label={isMeeting ? "纪要正文" : "笔记正文"}
                    className="min-h-96 resize-y font-mono leading-7"
                    value={content}
                    disabled={saving}
                    onChange={(e) => setContent(e.target.value)}
                  />
                  {editorPreview && <MarkdownContent content={content} className="prose max-w-none break-words dark:prose-invert" />}
                  </div>
                </div>
              ) : (
                <MarkdownContent
                  content={previewContent}
                  className="prose mx-auto max-w-4xl break-words dark:prose-invert"
                />
              )}
            </div>
          )}
        </section>
      </div>
      <Dialog
        open={classificationOpen}
        onOpenChange={(value) => {
          if (!saving) setClassificationOpen(value);
        }}
      >
        <DialogContent closeLabel="关闭">
          <DialogHeader>
            <DialogTitle>项目与标签</DialogTitle>
            <DialogDescription>
              保存项目与标签，原正文和历史版本保留。
            </DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="note-project">项目</FieldLabel>
              <Input
                id="note-project"
                value={project}
                maxLength={120}
                onChange={(e) => setProject(e.target.value)}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="note-tags">
                标签（用逗号分隔，最多 30 个）
              </FieldLabel>
              <Input
                id="note-tags"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
              />
            </Field>
          </FieldGroup>
          {error && <ErrorState error={error} />}
          <DialogFooter>
            <Button variant="outline" disabled={saving} onClick={() => setClassificationOpen(false)}>取消</Button>
            <Button
              disabled={saving || storeBusy}
              onClick={async () => {
                const values = Array.from(
                  new Set(
                    tags
                      .split(/[,，]/)
                      .map((t) => t.trim())
                      .filter(Boolean),
                  ),
                );
                if (values.length > 30 || values.some((t) => t.length > 80)) {
                  setError("标签最多 30 个，每个不超过 80 字");
                  return;
                }
                await saveDraft({
                  metadata: {
                    ...baseline.metadata,
                    project: project.trim(),
                    tags: values,
                  },
                });
              }}
            >
              保存分类
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
<Sheet open={contextOpen} onOpenChange={setContextOpen}><SheetContent className="w-full overflow-y-auto sm:max-w-md"><SheetHeader><SheetTitle>来源与版本</SheetTitle><SheetDescription>查看原件、证据与版本记录。正文保持在阅读区。</SheetDescription></SheetHeader>        <div
          aria-label="来源与版本"
          className="flex min-w-0 flex-col gap-5 pt-6"
        >
          <section
            aria-labelledby="source-heading"
            className="flex flex-col gap-3 rounded-xl border border-border/70 bg-background p-4"
          >
            <h2
              id="source-heading"
              className="text-xs font-semibold text-muted-foreground"
            >
              原始资料
            </h2>
            <p className="text-sm text-muted-foreground">
              {note.source_type === 'text'
                ? '直接创建的笔记，正文与版本可在此设备使用。'
                : `原始文件默认保存在${note.source_device === 'desktop' ? '桌面端' : note.source_device === 'mobile' ? '手机' : note.source_device || '来源设备'}，正文与版本可在此设备使用。`}
            </p>
            {localId ? (
              <Button variant="outline" asChild>
                <Link to={`/files?${new URLSearchParams({ note: localId, type: 'all', q: '', returnTo: detailReturnTo }).toString()}`} state={{ returnTo: detailReturnTo }} onClick={() => setContextOpen(false)}>
                  查看原始资料
                </Link>
              </Button>
            ) : note.source_type !== 'text' ? (
              <p className="text-xs text-muted-foreground">
                此设备未关联原文件；需要重新处理时，请在来源设备打开。
              </p>
            ) : null}
          </section>
          <section
            aria-label="版本与修订"
            className="flex flex-col gap-3 rounded-xl border border-border/70 bg-background p-4"
          >
            <Field>
              <FieldLabel htmlFor="workspace-version">
                <GitBranch className="inline size-4" /> 已保存版本
              </FieldLabel>
              <NativeSelect
                id="workspace-version"
                aria-describedby="workspace-version-help workspace-version-selection"
                value={versionId}
                disabled={dirty || saving}
                onChange={(e) => {
                  setVersionId(e.target.value);
                  setEditing(false);
                }}
              >
                <optgroup label="当前正文">
                  <NativeSelectOption value="">最新正文 · 修订 {note.revision}</NativeSelectOption>
                </optgroup>
                {generatedVersions.length > 0 && <optgroup label="生成版本">
                  {generatedVersions.map(version => <NativeSelectOption key={version.id} value={version.id}>{savedVersionLabel(version)}{version.id === defaultVersionId ? ' · 默认展示' : ''}</NativeSelectOption>)}
                </optgroup>}
                {otherVersions.length > 0 && <optgroup label="编辑、保存与其他记录">
                  {otherVersions.map(version => <NativeSelectOption key={version.id} value={version.id}>{savedVersionLabel(version)}{version.id === defaultVersionId ? ' · 默认展示' : ''}</NativeSelectOption>)}
                </optgroup>}
              </NativeSelect>
              <p id="workspace-version-help" className="text-xs leading-5 text-muted-foreground">生成版本与保存过程分组列出；快照、编辑、导入等记录全部保留，同一时间不代表多次生成。选择只阅读，不会保存或生成。</p>
              <div id="workspace-version-selection" className="grid gap-1 text-xs leading-5 text-muted-foreground">
                <p>{recordExplanation}</p>
                {selected && <p>{versionLabel}</p>}
                {selected && selected.content === note.content && <p>正文与当前正文完全相同，仍是独立记录。</p>}
                <p>{!defaultVersionId ? '默认展示：未指定。' : !defaultLoaded ? '默认展示记录尚未载入。' : selected?.id === defaultVersionId ? '此记录为默认展示。' : '默认展示已在对应记录标注。'}</p>
                {dirty && <p>另有本机未保存草稿；草稿尚未成为已保存正文。</p>}
              </div>
            </Field>
            <Button
              variant="outline"
              disabled={!selected && !dirty}
              onClick={() => { setContextOpen(false); setCompare(true) }}
            >
              比较当前与所选版本
            </Button>
            {selected && (
              <>
                <Button
                  variant="outline"
                  disabled={saving || dirty}
                  onClick={() =>
                    void saveDraft({
                      content: selected.content,
                      title: selected.title,
                    })
                  }
                >
                  恢复为新修订
                </Button>
                <Button
                  variant="ghost"
                  disabled={saving || dirty}
                  onClick={() =>
                    void saveDraft({
                      metadata: {
                        ...baseline.metadata,
                        default_version_id: selected.id,
                      },
                    })
                  }
                >
                  设为默认展示
                </Button>
              </>
            )}
            <Button
              variant="outline"
              disabled={saving || (!generation && (dirty || !!selected || note.deleted))}
              onClick={() => { setContextOpen(false); setGenerate(true) }}
            >
              <Wand2 />
              {generation ? "查看与恢复原生成请求" : "生成新版本"}
            </Button>
            <p className="text-xs leading-5 text-muted-foreground">{generation ? "已有请求与结果保留，查看不会创建新任务。" : selected ? "正在查看历史版本。返回最新正文后，可基于已保存输入生成新版本。" : "依据当前已保存输入生成新版本，原正文和历史保留。"}</p>
          </section>

        </div></SheetContent></Sheet>
      <Dialog open={compare} onOpenChange={setCompare}>
        <DialogContent closeLabel="关闭" className="max-h-[85vh] overflow-auto sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle>版本比较</DialogTitle>
            <DialogDescription>
              逐段查看差异；恢复历史将保存一个新的修订，原版本继续保留。
            </DialogDescription>
          </DialogHeader>
          <VersionCompare
            left={selected?.content ?? note.content}
            right={content}
            leftLabel={selected ? versionLabel : "已保存正文"}
            rightLabel={dirty ? "本机草稿" : "当前正文"}
          />
          <DialogFooter><Button variant="outline" onClick={() => setCompare(false)}>关闭比较</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={generate}
        onOpenChange={(value) => {
          if (!saving) setGenerate(value);
        }}
      >
        <DialogContent closeLabel="关闭">
          <DialogHeader>
            <DialogTitle>生成新版本</DialogTitle>
            <DialogDescription>
              使用所选文字资料进行总结与核对，成功后保存独立版本。原有正文和版本继续保留。
            </DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="generate-template">整理目标</FieldLabel>
              <NativeSelect
                id="generate-template"
                value={template}
                disabled={saving || !!generation}
                onChange={(e) => setTemplate(e.target.value as typeof template)}
              >
                <NativeSelectOption value="minutes">
                  {isMeeting ? "完整会议纪要" : "完整结构化笔记"}
                </NativeSelectOption>
                <NativeSelectOption value="summary">
                  简短总结
                </NativeSelectOption>
                <NativeSelectOption value="actions">
                  行动事项
                </NativeSelectOption>
              </NativeSelect>
            </Field>
            <Field>
              <FieldLabel htmlFor="generate-instructions">补充要求</FieldLabel>
              <Textarea
                id="generate-instructions"
                value={instructions}
                disabled={saving || !!generation}
                onChange={(e) => setInstructions(e.target.value)}
              />
            </Field>
          </FieldGroup>
          {error && <ErrorState error={error} />}
          {generation && (
            <p className="text-sm text-muted-foreground">
              保留此次请求标识，重试不会主动创建第二个生成任务。
            </p>
          )}
          {generation?.generatedContent && <div className="flex min-h-0 flex-col gap-3"><p className="text-sm">生成已完成，保存发生冲突。原正文和生成结果均保留。</p><Textarea aria-label="保留的生成正文" readOnly value={generation.generatedContent} className="h-36" /><Button variant="outline" disabled={saving} onClick={async () => { if (!owner) return; setSaving(true); try { const copy = await save(`generated-${generation.operation_id}`, { base_revision: 0, operation_id: generation.operation_id, title: `${baseline.title}（冲突保留）`, content: generation.generatedContent!, source_type: 'text', source_device: baseline.source_device }); if (!copy) throw new Error('另存未完成，生成结果保留，请重试保存。'); clearGenerationRecovery(owner, key); setGeneration(null); setGenerate(false); navigate(`/workspace/${encodeURIComponent(copy.key)}`, { state: { returnTo } }); } catch (cause) { setError((cause as Error).message); } finally { setSaving(false); } }}>将生成结果另存为笔记</Button></div>}
          <DialogFooter>
            <Button variant="outline" disabled={saving} onClick={() => setGenerate(false)}>
              {generation ? '关闭（保留原请求）' : '取消'}
            </Button>
            <Button disabled={saving || !!generation?.generatedContent} onClick={() => void generateVersion()}>
              {saving
                ? "生成与核对中…"
                : generation
                  ? "重试原生成请求"
                  : "生成并保存新版本"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <AlertDialog
        open={deleteOpen}
        onOpenChange={(next) => {
          if (!saving) setDeleteOpen(next);
        }}
      >
        <AlertDialogContent onCloseAutoFocus={event => {
          event.preventDefault();
          const trigger = deleteReturn.current;
          if (trigger?.element.isConnected && trigger.key === key && trigger.owner === useAuthStore.getState().user?.id) trigger.element.focus();
        }} onEscapeKeyDown={event => { if (saving) event.preventDefault(); }}>
          <AlertDialogHeader>
            <AlertDialogTitle>将这份内容移入回收站？</AlertDialogTitle>
            <AlertDialogDescription>
              正文与版本移入回收站，可在存储页恢复。原文件与已发布飞书文档保留。
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && <ErrorState error={error} />}
          <AlertDialogFooter>
            <AlertDialogCancel asChild><Button
              variant="outline"
              disabled={saving}
            >
              保留
            </Button></AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={saving || storeBusy}
              onClick={async () => {
                if (saving || storeBusy) return;
                setSaving(true);
                try {
                  const result = await changeDeleted(key, true);
                  if (result?.deleted) navigate(returnTo);
                  else
                    setError('移入回收站未完成，正文与原文件保留，请重试。');
                } catch (cause) {
                  setError((cause as Error).message);
                } finally {
                  setSaving(false);
                }
              }}
            >
              移入回收站
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Dialog open={leave} onOpenChange={setLeave}>
        <DialogContent closeLabel="关闭">
          <DialogHeader>
            <DialogTitle>离开编辑？</DialogTitle>
            <DialogDescription>
              {draftStatus}。草稿仅在当前账号的本机可见。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLeave(false)}>
              继续编辑
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                if (owner) removeTextDraft(owner, `workspace:${key}`);
                navigate(returnTo);
              }}
            >
              放弃草稿并离开
            </Button>
            <Button onClick={() => navigate(returnTo)}>保留草稿并离开</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
