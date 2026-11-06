import { useTaskCenter, type CenterTask, type TaskWorkspace } from '@/hooks/useTaskCenter';
import { AlertDialog, AlertDialogContent, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '@/components/ui/alert-dialog';
import { TaskProgress } from '@/components/Feedback/TaskProgress';
import { taskDisplayTitle, taskDisplayMessage } from '@/lib/taskDisplay';
import { Input } from '@/components/ui/input';
import { sourceHistoryAction } from '@/lib/taskRecoveryView';
import { isRejectedVersionReceipt, readVersionReceipt, meetingVersionDetails } from '@/lib/meetingVersionRecovery';
import { isMeetingVersionReceipt } from '@/lib/meetingVersion';
import { depthLabels, presentationLabels } from '@/lib/summaryPresentation';
import { deletedMeetingOperation, deletedMeetingTasks, MEETING_TASKS_DELETED } from '@/lib/deletedMeetingTasks';
import { readMeetingVersionHistory, unverifiedVersionHistory, versionHistoryTitle, type VersionHistory } from '@/lib/meetingVersionHistory';
import { useEffect, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { listPendingMeetings, type PendingMeeting } from "@/lib/audioStorage";
import { useAuthStore } from "@/stores/authStore";
import { deliveryStatus, type Delivery } from "@/lib/feishu";
import { useLibraryNotes, libraryNoteUrl } from "@/hooks/useLibraryNotes";
import { useNoteLibraryStore } from "@/stores/noteLibraryStore";
import { useTeamStore } from "@/stores/teamStore";
import { pageParentLabel, resolvePageParent } from '@/lib/navigation';
import { PageReturn } from '@/components/Layout/PageReturn';
import { PageHeading } from "@/components/Layout/PageHeading";
import {
  ErrorState,
  LoadingState,
  EmptyState,
} from "@/components/Feedback/ResourceState";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

const unknownFailureCodes = new Set(['summary_result_unconfirmed', 'unknown_result', 'unknown_error', 'asr_incomplete_result']);
const confirmedFailure = (task?: CenterTask) => !!task?.failed && task.terminal && !task.unavailable && !unknownFailureCodes.has(task.errorCode || '');
type HistoryRemoval = { identity: string; fingerprint: string; receiptKey?: string; receiptRaw?: string; recordingId?: string };
const removalKey = (owner: string, identity: string) => `vinote:task-history-dismissed:${encodeURIComponent(owner)}:${encodeURIComponent(identity)}`;

export function Tasks() {
  const owner = useAuthStore((s) => s.user?.id);
  return <TasksPage key={owner || 'signed-out'} owner={owner} />;
}

function TasksPage({ owner }: { owner?: string }) {
  const [params, setParams] = useSearchParams();
  const historyReturn = `/tasks${params.toString() ? `?${params.toString()}` : ''}`;
  const tab = ["generation", "feishu"].includes(
    params.get("tab") || "",
  )
    ? params.get("tab")!
    : "generation";
  const notes = useLibraryNotes();
  const currentWorkspace = useTeamStore(state => state.currentWorkspace);
  const loadNotes = useNoteLibraryStore(state => state.loadNotes);
  const notesError = useNoteLibraryStore(state => state.error);
  useEffect(() => { if (owner) void loadNotes(currentWorkspace); }, [owner, currentWorkspace, loadNotes]);
  const legacySync = params.get('tab') === 'sync';
  const [recordings, setRecordings] = useState<PendingMeeting[]>([]);
  type SourceImport = { workspace?: TaskWorkspace; sourceTitle?: string; sourceUrl?: string; id?: string; operationId?: string; parentTaskId?: string; meeting: boolean; mode?: string; submissionState?: string; historyReceiptKey?: string; historyReceiptRaw?: string };
  const [imports, setImports] = useState<SourceImport[]>([]);
  const [versionStates, setVersionStates] = useState<Record<string, VersionHistory>>({});
  const [deliveries, setDeliveries] = useState<
    { noteId: string; title: string; url: string; job: Delivery }[]
  >([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [removal, setRemoval] = useState<HistoryRemoval | null>(null);
  const [, setDismissalRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setAttempt(value => value + 1);
    window.addEventListener(MEETING_TASKS_DELETED, refresh);
    return () => window.removeEventListener(MEETING_TASKS_DELETED, refresh);
  }, []);
  useEffect(() => {
    if (legacySync) return;
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setVersionStates({});
    const load = async () => {
      if (tab === "generation") {
        const deletedTasks = owner ? deletedMeetingTasks(owner) : new Set<string>();
        const accepted = new Map<string, SourceImport>();
        const snapshots = new Map<string, { key: string; raw: string }>();
        const keys = owner ? ['note', 'meeting'].map(kind => `vinote:import-receipt:${owner}:${kind}`) : [];
        if (owner) for (let index = 0; index < localStorage.length; index++) {
          const key = localStorage.key(index);
          if (key?.startsWith(`vinote:source-receipt:${owner}:`) || key?.startsWith(`vinote:source-task-receipt:${owner}:`) || key?.startsWith(`vinote:import-draft:${owner}:`)) keys.push(key);
        }
        for (const key of keys) {
          const raw = localStorage.getItem(key);
          if (raw) {
            let saved: SourceImport | null;
            try {
              saved = owner && key.startsWith(`vinote:source-receipt:${owner}:`)
                ? readVersionReceipt(localStorage, owner, key.slice(`vinote:source-receipt:${owner}:`.length)) as SourceImport
                : JSON.parse(raw);
            } catch {
              if (active) setError('部分任务记录无法读取，其他记录仍可查看。');
              continue;
            }
            if (!saved) continue;
            if (saved.id && deletedTasks.has(saved.id)) continue;
            if (owner && saved.operationId && deletedMeetingOperation(owner, saved.operationId)) continue;
            if (owner && isMeetingVersionReceipt(saved, owner) && typeof saved.parentTaskId === 'string' && deletedTasks.has(saved.parentTaskId)) continue;
            if ((typeof saved.id === 'string' && saved.id || typeof saved.operationId === 'string' && /^[A-Za-z0-9_-]{1,160}$/.test(saved.operationId)) && typeof saved.meeting === 'boolean') {
              const identity = saved.operationId || saved.id;
              if (!identity) continue;
              const rank = (item: SourceImport) => item.submissionState === 'accepted' || !item.submissionState && !!item.id ? 3 : item.submissionState === 'unknown' ? 2 : 1;
              const prior = accepted.get(identity);
              if (prior && (rank(prior) > rank(saved) || rank(prior) === rank(saved)
                && prior.historyReceiptKey?.startsWith(`vinote:source-receipt:${owner}:`))) continue;
              accepted.set(identity, { ...saved, historyReceiptKey: key, historyReceiptRaw: raw });
              snapshots.set(identity, { key, raw });
            }
          }
        }
        if (active) setImports([...accepted.values()]);
        const statuses = async () => {
          for (const [identity, item] of accepted) {
            if (!active) return;
            if (!meetingVersionDetails(item, owner) || isRejectedVersionReceipt(item, owner)) continue;
            const snapshot = snapshots.get(identity)!;
            const current = () => active && !!owner && useAuthStore.getState().user?.id === owner && localStorage.getItem(snapshot.key) === snapshot.raw;
            const status = await readMeetingVersionHistory(item, controller.signal, current, owner);
            if (status && current()) setVersionStates(previous => ({ ...previous, [identity]: status }));
          }
        };
        const device = async () => {
          const local = owner ? await listPendingMeetings(owner) : [];
          if (active) setRecordings(local.filter(item => !item.taskId || !deletedTasks.has(item.taskId)));
        };
        const results = await Promise.allSettled([statuses(), device()]);
        const failed = results.find(result => result.status === 'rejected');
        if (failed?.status === 'rejected') throw failed.reason;

      } else if (tab === "feishu") {
        const next: typeof deliveries = [];
        // Serial readback avoids issuing one request per note simultaneously.
        for (const note of notes) {
          if (!active) return;
          const job = await deliveryStatus(note.id);
          if (job)
            next.push({
              noteId: note.id,
              title: note.title,
              url: libraryNoteUrl(note),
              job,
            });
        }
        if (active) setDeliveries(next);
      }
    };
    void load()
      .catch((cause) => {
        if (active) setError(cause.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [owner, tab, attempt, legacySync, historyReturn]);
  const taskStates = useTaskCenter(owner, [
    ...imports.filter(item => !meetingVersionDetails(item, owner) && !isRejectedVersionReceipt(item, owner) && (!item.submissionState || item.submissionState === 'accepted')).flatMap(item => item.id ? [item.id] : []),
    ...recordings.flatMap(item => item.taskId && !item.noteId ? [item.taskId] : []),
  ], tab === 'generation' && !legacySync, attempt, imports.filter(item => !meetingVersionDetails(item, owner) && !isRejectedVersionReceipt(item, owner) && item.operationId && item.submissionState !== 'accepted').map(item => item.operationId!), Object.fromEntries([
    ...imports.flatMap(item => item.workspace ? [
      ...(item.id ? [[item.id, item.workspace] as const] : []),
      ...(item.operationId ? [[`operation:${item.operationId}`, item.workspace] as const] : []),
    ] : []),
    ...recordings.filter(item => item.taskId && item.workspace).map(item => [item.taskId!, item.workspace] as const),
  ]));
  const importRemoval = (item: SourceImport): HistoryRemoval | null => {
    const version = meetingVersionDetails(item, owner);
    const live = (item.id ? taskStates[item.id] : undefined) || (item.operationId ? taskStates[`operation:${item.operationId}`] : undefined);
    const failed = isRejectedVersionReceipt(item, owner) || (version ? versionStates[item.operationId || item.id || '']?.failed : confirmedFailure(live));
    return failed && item.historyReceiptKey && item.historyReceiptRaw ? {
      identity: `import:${item.operationId || item.id}`, fingerprint: item.historyReceiptRaw,
      receiptKey: item.historyReceiptKey, receiptRaw: item.historyReceiptRaw,
    } : null;
  };
  const recordingRemoval = (item: PendingMeeting): HistoryRemoval | null => item.ownerId === owner && item.taskId && !item.noteId && confirmedFailure(taskStates[item.taskId])
    ? { identity: `recording:${item.id}`, recordingId: item.id, fingerprint: JSON.stringify(item) } : null;
  // Display preference only: never remove execution receipts, task artifacts or recordings.
  // Re-read status even for dismissed rows, so running/unknown/recovered tasks remain visible.
  const hidden = (candidate: HistoryRemoval | null) => {
    try { return !!owner && !!candidate && localStorage.getItem(removalKey(owner, candidate.identity)) === candidate.fingerprint; }
    catch { return false; }
  };
  const visibleImports = imports.filter(item => !hidden(importRemoval(item)));
  const visibleRecordings = recordings.filter(item => !hidden(recordingRemoval(item)));
  const deleteHistory = async () => {
    if (!owner || !removal || useAuthStore.getState().user?.id !== owner) return;
    const selected = removal;
    try {
      const candidate = selected.recordingId
        ? (await listPendingMeetings(owner)).filter(item => item.id === selected.recordingId).map(recordingRemoval)[0]
        : imports.map(importRemoval).find(item => item?.identity === selected.identity);
      if (useAuthStore.getState().user?.id !== owner || !candidate || candidate.fingerprint !== selected.fingerprint
          || selected.receiptKey && localStorage.getItem(selected.receiptKey) !== selected.receiptRaw) return;
      localStorage.setItem(removalKey(owner, selected.identity), selected.fingerprint);
      setDismissalRevision(value => value + 1);
    } catch { setError('未能删除处理记录，请重试。'); }
    finally { setRemoval(null); }
  };
  const matches = (...values: (string | undefined)[]) => values.join(' ').toLowerCase().includes(query.trim().toLowerCase());
  const shownImports = visibleImports.filter(item => matches(item.sourceTitle, item.sourceUrl, meetingVersionDetails(item, owner)?.title, item.meeting ? '会议导入任务' : '资料整理任务'));
  const shownRecordings = visibleRecordings.filter(item => matches(item.options.title));
  const shownDeliveries = deliveries.filter(item => matches(item.title));
  // Completed notes outlive transient import receipts. Show only records with a
  // real task identity, and never infer a task from a title or a handwritten note.
  const coveredTaskIds = new Set([
    ...visibleImports.flatMap(item => item.id ? [item.id] : []),
    ...visibleRecordings.flatMap(item => item.taskId ? [item.taskId] : []),
  ]);
  const deletedTasks = owner ? deletedMeetingTasks(owner) : new Set<string>();
  // A legacy receipt can resolve to the same saved note through an older task.
  // Compare verified note identities, never titles, so distinct versions remain visible.
  const coveredNoteIds = new Set([
    ...Object.values(taskStates).flatMap(task => task.noteId ? [task.noteId] : []),
    ...Object.values(versionStates).flatMap(state => state.noteId ? [state.noteId] : []),
    ...visibleRecordings.flatMap(recording => recording.noteId ? [recording.noteId] : []),
  ]);
  const savedTasks = owner ? notes.filter(note => note.status === 'done' && note.taskId
    && !coveredTaskIds.has(note.taskId) && !deletedTasks.has(note.taskId)
    && ![note.id, note.localId, ...(note.sourceIds || [])].some(id => !!id && coveredNoteIds.has(id))) : [];
  const shownSavedTasks = savedTasks.filter(note => matches(note.title));
  const hasRows = tab === 'generation' ? visibleImports.length + visibleRecordings.length + savedTasks.length > 0 : deliveries.length > 0;
  const hasMatches = tab === 'generation' ? shownImports.length + shownRecordings.length + shownSavedTasks.length > 0 : shownDeliveries.length > 0;
  if (legacySync) return <Navigate replace to={'/settings/storage?' + new URLSearchParams({ returnTo: resolvePageParent(params.get('returnTo')) })} />;
  return (
    <div className="workspace-page tasks-page">
      {params.get('returnTo') && <PageReturn to={resolvePageParent(params.get("returnTo"))} label={pageParentLabel(resolvePageParent(params.get("returnTo")))} />}
      <PageHeading
        title="任务"
        description="查看生成进度、打开结果或处理失败任务。"
        actions={
          <Button
            variant="outline"
            disabled={loading}
            onClick={() => { void loadNotes(currentWorkspace); setAttempt((n) => n + 1); }}
          >
            <RefreshCw data-icon="inline-start" />
            刷新状态
          </Button>
        }
      />
      <div className="task-toolbar"><Tabs value={tab} onValueChange={(value) => setParams(previous => {
        const next = new URLSearchParams(previous);
        next.set('tab', value);
        return next;
      })}>
        <TabsList className="line-tabs">
          <TabsTrigger value="generation">内容生成</TabsTrigger>
          <TabsTrigger value="feishu">飞书发布</TabsTrigger>
        </TabsList>
      </Tabs>
      {hasRows && <Input aria-label="搜索处理记录" placeholder="搜索任务或原文件" value={query} onChange={event => setQuery(event.target.value)} className="h-9 max-w-sm" />}</div>
      {hasRows && !hasMatches && <EmptyState title="没有匹配的处理记录" description="换个来源标题，或清除搜索。"><Button variant="outline" onClick={() => setQuery('')}>清除搜索</Button></EmptyState>}
      {notesError && <ErrorState error="已保存的任务记录读取失败，请重试。" onRetry={() => void loadNotes(currentWorkspace)} />}
      {error && (
        <ErrorState
          error={error}
          onRetry={() => setAttempt((n) => n + 1)}
          busy={loading}
        />
      )}
      {loading && <LoadingState rows={1} label="正在更新任务状态…" />}
      {tab === "generation" && (
        <div className="task-list">
          {shownImports.map((item) => {
            const version = meetingVersionDetails(item, owner);
            const rejected = isRejectedVersionReceipt(item, owner);
            const status = version && !rejected ? versionStates[item.operationId || item.id || ''] || unverifiedVersionHistory() : null;
            const live = !version ? (item.id ? taskStates[item.id] : undefined) || (item.operationId ? taskStates[`operation:${item.operationId}`] : undefined) : undefined;
            const operationUrl = `/generate?mode=${item.mode === 'url' ? 'url' : 'file'}${item.meeting ? '&meeting=1' : ''}${item.operationId ? `&operation=${encodeURIComponent(item.operationId)}` : item.id ? `&task=${encodeURIComponent(item.id)}` : ''}`;
            const target = live?.noteId ? `/note/${encodeURIComponent(live.noteId)}` : status?.noteId ? `/note/${encodeURIComponent(status.noteId)}`
              : status?.taskId && !status.saveable && !status.failed ? `/generate?mode=file&meeting=1&task=${encodeURIComponent(status.taskId)}` : operationUrl;
            const originalTitle = version ? version.title : item.sourceTitle || item.sourceUrl;
            const displayTitle = taskDisplayTitle(originalTitle, item.meeting, version ? status?.title : live?.title);
            return <article key={item.operationId || item.id} className="task-row relative grid min-w-0 gap-2 border-b py-4 lg:pr-64">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="min-w-0 flex-1 text-sm font-medium [overflow-wrap:anywhere]">{versionHistoryTitle(displayTitle)}{version ? ' · 新版本' : ''}</h2>
            </div>
            {version && <details className="task-details"><summary>处理详情</summary><dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
              {status?.title && <div><dt className="text-muted-foreground">录制来源</dt><dd>{versionHistoryTitle(version.title)}</dd></div>}
              <div><dt className="text-muted-foreground">本次选择的总结模型</dt><dd className="break-words">{version.model}</dd></div>
              <div><dt className="text-muted-foreground">内容与形式</dt><dd>{depthLabels[version.depth]} · {presentationLabels[version.presentation]}</dd></div>
              <div><dt className="text-muted-foreground">语音识别</dt><dd>{version.reuse ? '复用已有转写' : '重新识别（已确认）'}</dd></div>
              <div><dt className="text-muted-foreground">提交时间</dt><dd><time className="tabular-nums" dateTime={version.createdAt}>{new Date(version.createdAt).toLocaleString('zh-CN', { hour12: false })}</time></dd></div>
            </dl></details>}
            <p className="task-description min-w-0 text-pretty text-sm text-muted-foreground [overflow-wrap:anywhere]">{live ? taskDisplayMessage(live, item.meeting) : rejected ? '本次未受理，未创建任务。失败记录已保留，重新生成需要返回来源再次核验确认。' : status ? status.detail : item.operationId && item.submissionState !== 'accepted' ? item.submissionState === 'reserved' ? '已收到提交，排队状态待确认；请查询原任务。' : '提交状态待确认，原来源已保留，请查询原任务。' : '任务已接收，请查询原结果，避免重复生成。'}</p>
            {status && <span className={`text-xs ${status.failed ? 'text-destructive' : 'text-muted-foreground'}`}>{status.label}</span>}
            {!version && originalTitle && displayTitle !== originalTitle && <details className="task-details"><summary>原文件与来源</summary><p className="mt-2 break-all text-xs">{originalTitle}</p></details>}

            {live && <TaskProgress task={live} />}
            {importRemoval(item) && <Button variant="ghost" size="sm" className="w-fit lg:absolute lg:right-0 lg:top-16" onClick={() => setRemoval(importRemoval(item))}>删除失败记录</Button>}
            <Button variant="outline" className="w-fit max-w-full whitespace-normal lg:absolute lg:right-0 lg:top-4" asChild><Link to={target} state={{ returnTo: historyReturn }}>{live?.noteId ? '打开已保存内容' : live?.complete ? item.operationId ? '打开结果并保存' : '查看处理结果' : live?.failed ? '查看失败原因与恢复' : rejected ? '查看未受理记录' : status?.action || sourceHistoryAction(item)}</Link></Button>
          </article>})}
          {shownRecordings.map((r) => { const live = r.taskId ? taskStates[r.taskId] : undefined; const savedId = live?.noteId || r.noteId; return (
            <article key={r.id} className="task-row relative flex min-w-0 flex-col gap-2 border-b py-4 lg:pr-64">
              <div className="flex justify-between gap-3">
                <h2 className="min-w-0 flex-1 text-sm font-medium [overflow-wrap:anywhere]">{versionHistoryTitle(r.options.title)}</h2>
                {!live && <Badge
                  variant={
                    r.processingStatus === "failed"
                      ? "destructive"
                      : "secondary"
                  }
                >
                  {{
                      idle: "已保存",
                      queued: "排队中",
                      preparing_media: "准备资料",
                      transcribing: "转写",
                      diarizing: "说话人分析",
                      parallel_analysis: "转写与说话人分析",
                      aligning: "对齐",
                      analyzing_video: "视频分析",
                      generating: "生成与核对",
                      saving_result: "保存结果",
                      completed: "完成",
                      failed: "需处理",
                    }[r.processingStatus]
                  }
                </Badge>}
              </div>
              <p className="text-xs text-muted-foreground">
                原录音已保留 · {savedId ? '纪要已保存' : live ? live.complete ? '生成已完成' : live.failed ? '处理未完成' : '进度自动更新' : r.processingStatus === 'completed' ? '生成已完成' : r.processingStatus === 'failed' ? '处理未完成' : r.taskId ? '查看处理记录' : '尚未生成纪要'}
              </p>
              {(live || r.processingError) && (
                <p className="text-sm text-muted-foreground [overflow-wrap:anywhere]">{live ? taskDisplayMessage(live, true) : r.processingError}</p>
              )}
              {live && <TaskProgress task={live} />}
              {recordingRemoval(r) && <Button variant="ghost" size="sm" className="w-fit lg:absolute lg:right-0 lg:top-16" onClick={() => setRemoval(recordingRemoval(r))}>删除失败记录</Button>}
              <Button variant="outline" className="w-fit max-w-full whitespace-normal lg:absolute lg:right-0 lg:top-4" asChild>
                <Link to={savedId ? `/note/${encodeURIComponent(savedId)}` : live?.complete && r.taskId ? `/generate?meeting=1&task=${encodeURIComponent(r.taskId)}` : `/files?${new URLSearchParams({ type: 'all', q: '', file: `recording:${r.id}`, returnTo: historyReturn })}`} state={{ returnTo: historyReturn }}>
                  {(live ? live.failed : r.processingStatus === "failed") && !savedId
                    ? "查看原录音与恢复选项"
                    : savedId ? "查看会议纪要" : live?.complete ? "打开结果" : "查看原录音"}
                </Link>
              </Button>
            </article>
          )})}
          {shownSavedTasks.map(note => <article key={`saved:${note.id}`} className="task-row relative grid min-w-0 gap-2 border-b py-4 lg:pr-64">
            <h2 className="min-w-0 text-sm font-medium [overflow-wrap:anywhere]">{note.title}</h2>
            <p className="task-description text-sm text-muted-foreground">笔记已保存，可直接打开。</p>
            <TaskProgress task={{ label: '已完成', complete: true, failed: false, terminal: true, noteId: note.id }} />
            <Button variant="outline" className="w-fit max-w-full whitespace-normal lg:absolute lg:right-0 lg:top-4" asChild><Link to={note.workspaceKey ? libraryNoteUrl(note) : `/note/${encodeURIComponent(note.id)}`} state={{ returnTo: historyReturn }}>打开已保存内容</Link></Button>
          </article>)}
          {!loading && !error && !visibleRecordings.length && !visibleImports.length && !savedTasks.length && (
            <EmptyState
              title="暂无生成任务"
              description="录制或导入资料，保存后可开始生成。"
            >
              <Button asChild>
                <Link to="/meetings">前往会议</Link>
              </Button>
            </EmptyState>
          )}
        </div>
      )}
      {tab === "feishu" && (
        <>
          {shownDeliveries.map((item) => (
            <div
              key={item.noteId}
              className="relative flex min-w-0 flex-col gap-2 border-b py-4 lg:pr-64"
            >
              <h2 className="min-w-0 [overflow-wrap:anywhere]">{item.title}</h2>
              <p className="text-sm">
                {item.job.status === "completed"
                  ? "已完成交付"
                  : item.job.status === "failed"
                    ? "需处理"
                    : "处理中"}{" "}
                · 飞书集成服务
              </p>
              {item.job.error && (
                <p className="text-sm text-destructive [overflow-wrap:anywhere]">{item.job.error}</p>
              )}
              <Button variant="outline" className="w-fit max-w-full whitespace-normal lg:absolute lg:right-0 lg:top-4" asChild>
                <Link to={item.url}>打开交付记录并恢复失败步骤</Link>
              </Button>
            </div>
          ))}
          {!loading && !error && !deliveries.length && (
            <EmptyState
              title="暂无交付记录"
              description="从已保存内容的详情页发起飞书交付。"
            >
              <Button variant="outline" asChild>
                <Link to="/settings/feishu" state={{ returnTo: historyReturn }}>检查飞书配置</Link>
              </Button>
            </EmptyState>
          )}
        </>
      )}

      <AlertDialog open={!!removal} onOpenChange={open => { if (!open) setRemoval(null); }}>
        <AlertDialogContent>
          <AlertDialogTitle>删除这条失败记录？</AlertDialogTitle>
          <AlertDialogDescription>仅从任务列表移除此失败记录。原文件、已保存内容和提交凭据都会保留，不会重新发起处理。任务状态变化后会重新显示。</AlertDialogDescription>
          <AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => void deleteHistory()}>删除记录</AlertDialogAction></AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
