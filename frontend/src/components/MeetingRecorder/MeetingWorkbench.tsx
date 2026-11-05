import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { calendarDay, dayLabel } from '@/lib/contentDates';
import { useMeetingDisplay } from '@/hooks/useMeetingDisplay';
import { MeetingDisplayEditor } from './MeetingDisplayEditor';
import '@/pages/content-workspace.css';
import type { MeetingTaskStates } from '@/hooks/useMeetingTaskStates';
import { useMeetingSummaryPresentations } from '@/hooks/useMeetingSummaryPresentations';
import { depthLabels, presentationLabels } from '@/lib/summaryPresentation';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useViewState } from "@/hooks/useViewState";
import {
  ChevronRight,
  FileAudio,
  FileText,
  FileVideo,
  Search,
} from "lucide-react";
import { LocalRecordingPreview } from "./LocalRecordingPreview";
import { notePreview } from "@/lib/notePreview";
import { type LibraryNote as NoteRecord } from "@/hooks/useLibraryNotes";
import { type PendingMeeting } from "@/lib/audioStorage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { buildMeetingRows, meetingNoteState, type MeetingRow } from '@/lib/meetingGroups';
export { buildMeetingRows } from '@/lib/meetingGroups';
import { useAuthStore } from '@/stores/authStore';
import { serverTimestamp } from "@/lib/serverTimestamp";
import { AssociateMeetingDialog } from './AssociateMeetingDialog';
import { Alert, AlertDescription } from '@/components/ui/alert';

function meetingTime(value: string | undefined, serverValue = false) {
  if (!value) return { short: "时间未记录", full: "时间未记录" };
  // A known date is not evidence of a midnight recording or save time.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const date = new Date(`${value}T00:00:00Z`);
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value)
      return { short: "时间不可用", full: "时间不可用" };
    return { short: `${value}（时间未记录）`, full: `${value}（时间未记录）` };
  }
  const date = serverValue ? serverTimestamp(value) : new Date(value);
  if (!Number.isFinite(date.getTime())) return { short: "时间不可用", full: "时间不可用" };
  const options: Intl.DateTimeFormatOptions = {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  };
  return {
    short: new Intl.DateTimeFormat("zh-CN", options).format(date),
    full: new Intl.DateTimeFormat("zh-CN", { ...options, second: "2-digit" }).format(date),
  };
}

function recordingDuration(seconds: number | undefined) {
  return seconds !== undefined && Number.isFinite(seconds) && seconds >= 0
    ? `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`
    : undefined;
}

const processingLabels: Record<string, string> = {
  pending: '等待处理', queued: '等待处理', uploaded: '准备会议文件', preparing: '准备会议文件', preparing_media: '准备会议文件',
  transcribing: '转写中', diarizing: '分析说话人', parallel_analysis: '转写与说话人分析', aligning: '对齐逐字稿',
  analyzing_video: '整理共享画面与发言资料', generating: '生成会议纪要', summarizing: '生成会议纪要',
  screenshots: '整理画面', saving: '保存会议纪要', saving_result: '保存会议纪要',
};

function MeetingProcessingStatus({ row, taskStates }: { row: MeetingRow; taskStates: MeetingTaskStates }) {
  if (row.state !== '处理中') return null;
  const task = taskStates[row.recording?.taskId || row.note?.taskId || ''];
  const live = typeof task === 'object' ? task : undefined;
  const status = live?.status || row.recording?.processingStatus;
  const stage = live?.stage && processingLabels[live.stage] ? live.stage : status;
  const processed = live ? live.processedSeconds : row.recording?.processedSeconds;
  const total = live ? live.totalSeconds : row.recording?.totalSeconds;
  const measured = status === 'transcribing' && typeof processed === 'number' && Number.isFinite(processed) && processed >= 0 &&
    typeof total === 'number' && Number.isFinite(total) && total > 0 && processed <= total;
  const updated = live ? live.updatedAt : row.recording?.processingUpdatedAt;
  const percent = measured ? Math.floor(processed / total * 100) : undefined;
  return <span className="mt-2 block space-y-1 text-xs text-muted-foreground">
    <span className="block">{stage && processingLabels[stage] || '正在读取处理阶段'}</span>
    {measured && <><span className="block tabular-nums">已转写 {Math.round(processed)} / {Math.round(total)} 秒</span>
      <span role="progressbar" aria-label="音频转写进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="block h-1.5 max-w-sm overflow-hidden rounded-full bg-muted">
        <span className="block h-full bg-primary" style={{ width: `${percent}%` }} />
      </span></>}
    {updated && <span className="block tabular-nums">进度更新于 {meetingTime(updated, true).full}</span>}
  </span>;
}

function noteSource(note: NoteRecord) {
  const device = note.sourceDevice || note.generationClient;
  return device === "desktop" ? "桌面端" : device === "mobile" ? "手机" : undefined;
}

function relatedNotePresentation(note: NoteRecord) {
  const type = note.sourceType === "meeting_recording" ? "录音纪要"
    : note.sourceType === "meeting_video" ? "录屏纪要" : undefined;
  const savedTime = meetingTime(note.createdAt, true);
  const updatedTime = meetingTime(note.updatedAt, true);
  const metadata = [type, noteSource(note)].filter(Boolean).join(" · ");
  const text = note.content ? notePreview(note.content.slice(0, 2000)) : "";
  const characters = Array.from(text);
  const preview = note.content
    ? characters.length ? characters.slice(0, 180).join("") + (characters.length > 180 ? "…" : "") : "暂无文字预览"
    : "正文未读取";
  // Compare only what users see, without combining or reordering content objects.
  const signature = JSON.stringify([note.title, note.dateLabel || "保存于", savedTime.full, updatedTime.full, metadata, preview]);
  return { note, savedTime, updatedTime, metadata, preview, signature };
}

function relatedViewIds(row: MeetingRow) {
  // Use the real members so a different representative does not reset the row.
  return [
    ...row.notes.map(note => `${note.scope}:${note.teamId || ""}:note:${note.id}`),
    ...row.recordings.map(recording => `${recording.workspace.scope}:${recording.workspace.scope === "team" ? recording.workspace.teamId : ""}:recording:${recording.id}`),
  ];
}

function associationNoteId(note: NoteRecord) {
  const id = note.localId || note.id;
  return note.scope === 'personal' && note.status === 'done' &&
    ['meeting_recording', 'meeting_video'].includes(note.sourceType || '') &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id) ? id : undefined;
}

function MeetingNoteItems({ notes, onOpenNote, taskStates, onAssociate, locatedNoteId, ownerId, expanded = true }: {
  notes: NoteRecord[];
  onOpenNote: (id: string, edit?: boolean) => void;
  taskStates: MeetingTaskStates;
  onAssociate?: (note: NoteRecord) => void;
  locatedNoteId?: string;
  ownerId?: string;
  expanded?: boolean;
}) {
  const readPresentation = useMeetingSummaryPresentations(notes, ownerId, expanded);
  const presentationId = useId();
  const items = notes.map(relatedNotePresentation);
  const presentations = new Map<string, number>();
  items.forEach(({ signature }) => presentations.set(signature, (presentations.get(signature) || 0) + 1));
  return <ul className="meeting-version-list grid min-w-0 gap-2">
    {items.map(({ note, savedTime, updatedTime, metadata, preview, signature }, index) => <li key={JSON.stringify([note.scope, note.teamId, note.workspaceKey, note.id])} className="min-w-0">
      <Button data-meeting-return-target={`${note.scope}:${note.teamId || ''}:note:${note.id}`} data-meeting-located={note.id === locatedNoteId || undefined}
        aria-describedby={`${presentationId}-${index}`} aria-current={note.id === locatedNoteId ? 'true' : undefined} variant="ghost" className={`meeting-version-row h-auto min-h-11 w-full items-start justify-start whitespace-normal py-3 text-left ${note.id === locatedNoteId ? 'ring-2 ring-ring' : ''}`} onClick={() => onOpenNote(note.id)}>
        <span className="min-w-0">
          <span className="block [overflow-wrap:anywhere]">查看纪要 · {note.title}</span>
          <span className="mt-1 block text-xs leading-5 text-muted-foreground">保存于 <span title={savedTime.full} className="tabular-nums">{savedTime.full}</span>{metadata && ` · ${metadata}`}</span>
          <span className="mt-1 block text-xs leading-5 text-muted-foreground">记录更新于 <span className="tabular-nums">{updatedTime.full}</span> · {meetingNoteState(note, taskStates)}</span>
          <span className="mt-2 line-clamp-2 [overflow-wrap:anywhere] text-xs leading-5 text-muted-foreground">{preview}</span>
        </span>
      </Button>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-1">
      <div id={`${presentationId}-${index}`} role="group" aria-label="生成形式与详略" className="flex min-w-0 flex-wrap items-center gap-2">
        {(() => {
          const summary = readPresentation(note);
          return typeof summary === 'object'
            ? <><span className="text-xs text-muted-foreground">{presentationLabels[summary.presentation]}</span><span aria-hidden="true" className="text-xs text-muted-foreground">·</span><span className="text-xs text-muted-foreground">{depthLabels[summary.depth]}</span></>
            : <span className="text-xs text-muted-foreground">{summary === 'checking' ? '正在读取形式与详略…' : summary === 'missing' ? '形式/详略未记录' : '形式/详略暂未核验'}</span>;
        })()}
      </div>
      <div className="meeting-version-actions ml-auto flex flex-wrap justify-end gap-2">
        {onAssociate && <Button size="sm" variant="outline" className="min-h-11" disabled={!associationNoteId(note)} aria-label={`关联《${note.title}》到会议`} onClick={() => onAssociate(note)}>关联到会议</Button>}
        <Button size="sm" variant="ghost" className="min-h-11" aria-label={`编辑《${note.title}》`} onClick={() => onOpenNote(note.id, true)}>编辑纪要</Button>
      </div>
      </div>
      {onAssociate && !associationNoteId(note) && <p className="text-xs leading-5 text-muted-foreground">此历史内容暂无可关联的设备稿件记录，仍可查看内容和原项目。</p>}
      {(presentations.get(signature) || 0) > 1 && <details className="mt-1 text-xs">
        <summary className="min-h-11 cursor-pointer rounded-md py-3 text-muted-foreground focus-visible:outline focus-visible:outline-ring">记录详情</summary>
        <dl className="pb-3"><dt className="text-muted-foreground">记录标识</dt><dd className="mt-1 select-text break-all">{note.id}</dd></dl>
      </details>}
    </li>)}
  </ul>;
}
export type MeetingArchiveView = 'meetings' | 'pending';
export type MeetingLocator = { requestId: string; ownerId?: string; noteId?: string; taskId?: string; recordingId?: string; focus?: 'meeting'; invalid?: boolean };
const matchesNote = (note: NoteRecord, id: string) => note.id === id || note.localId === id || note.workspaceKey === id || note.sourceIds?.includes(id);

export function MeetingWorkbench({
  recordings,
  notes,
  importedSourceCount = 0,
  importedSources,
  loading,
  onOpenNote,
  onDeleted,
  onDeleteMeeting,
  canDeleteMeeting,
  actions,
  taskStates = {},
  view,
  onViewChange,
  associationContextKey = '',
  onAssociated,
  locator,
  locateError,
  onLocateRetry,
  onClearLocator,
}: {
  recordings: PendingMeeting[];
  notes: NoteRecord[];
  importedSourceCount?: number;
  importedSources?: (query: string, filter: string, date: string) => ReactNode;
  loading: boolean;
  onOpenNote: (id: string, edit?: boolean) => void;
  onDeleted: (id: string) => void;
  onDeleteMeeting?: (row: MeetingRow) => Promise<void>;
  canDeleteMeeting?: (row: MeetingRow) => boolean;
  actions?: ReactNode;
  taskStates?: MeetingTaskStates;
  view?: MeetingArchiveView;
  onViewChange?: (view: MeetingArchiveView) => void;
  associationContextKey?: string;
  onAssociated?: () => Promise<void> | void;
  locator?: MeetingLocator;
  locateError?: string;
  onLocateRetry?: () => void;
  onClearLocator?: () => void;
}) {
  const ownerId = useAuthStore(state => state.user?.id);
  const display = useMeetingDisplay(ownerId);
  const [selectedDate, setSelectedDate] = useViewState('meetings-calendar-date', '');
  const viewId = useId();
  const [previewOpen, setPreviewOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [previewRecordingId, setPreviewRecordingId] = useState<string | null>(null);
  const [associating, setAssociating] = useState<{ note: NoteRecord; ownerId: string; context: string }>();
  const [associationFeedback, setAssociationFeedback] = useState('');
  const [deletingRow, setDeletingRow] = useState<MeetingRow>();
  const [deleteError, setDeleteError] = useState('');
  const [deleteBusy, setDeleteBusy] = useState(false);
  const deleteLock = useRef(false);
  const pendingTab = useRef<HTMLButtonElement>(null);
  const mounted = useRef(false);
  const listRef = useRef<HTMLElement>(null);
  const [dismissedLocator, setDismissedLocator] = useState('');
  const expandedLocator = useRef('');
  const focusedLocator = useRef('');
  const [query, setQuery] = useViewState("recordings-query", "");
  const [filter, setFilter] = useViewState("recordings-filter", "全部");
  const [selectedKey, setSelectedKey] = useViewState<string | null>(
    "recordings-selected",
    null,
  );
  const [expandedRows, setExpandedRows] = useViewState<string[]>("recordings-expanded", []);
  const [storedView, setStoredView] = useViewState<MeetingArchiveView>('meeting-dossier-view', 'meetings');
  const allRows = buildMeetingRows(recordings.filter(row => !ownerId || row.ownerId === ownerId),
    notes.filter(note => !ownerId || !note.meetingSource || note.meetingSource.ownerId === ownerId), taskStates, ownerId).map(row => {
      const canonical = row.notes.find(note => note.meetingSource)?.meetingSource?.canonicalTaskId || row.recording?.taskId;
      const displayKey = canonical ? `task:${canonical}` : undefined;
      const metadata = displayKey ? display[displayKey] : undefined;
      const topic = (row.note?.title || '').replace(/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?\s*[|｜]\s*/, '').trim();
      const readableTopic = /^(待生成纪要|录制时间未记录|未命名会议|未命名录制)$/.test(topic) || /\.(?:wav|mp3|m4a|webm|mp4|ogg|flac)$/i.test(topic) ? '' : topic;
      return { ...row, displayKey,
        title: (metadata ? metadata.title : row.recording?.displayTitle || (row.recording?.titleEdited ? row.recording.options.title : '')) || readableTopic || row.title,
        displayDate: (metadata ? metadata.meeting_date : row.recording?.displayDate) || calendarDay(row.date),
      };
    }).sort((a, b) => b.displayDate.localeCompare(a.displayDate) || a.key.localeCompare(b.key));
  const locating = !!locator && locator.requestId !== dismissedLocator;
  const invalidLocator = locator?.invalid || locator?.focus !== undefined && locator.focus !== 'meeting' || !!locator?.ownerId && locator.ownerId !== ownerId ||
    !!locator && ![locator.noteId, locator.taskId, locator.recordingId].some(Boolean) ||
    [locator?.noteId, locator?.taskId, locator?.recordingId].some(id => id !== undefined && !/^[A-Za-z0-9_-]{1,160}$/.test(id));
  const candidates = locating && !invalidLocator && !loading && !locateError ? allRows.filter(row =>
    (!locator.noteId || row.notes.some(note => matchesNote(note, locator.noteId!))) &&
    (!locator.taskId || row.notes.some(note => note.taskId === locator.taskId || note.meetingSource?.canonicalTaskId === locator.taskId) ||
      row.recordings.some(recording => recording.taskId === locator.taskId || recording.id === locator.taskId)) &&
    (!locator.recordingId || row.recordings.some(recording => recording.id === locator.recordingId))) : [];
  const locatedRow = candidates.length === 1 ? candidates[0] : undefined;
  const locatedNote = locator?.noteId && locatedRow ? locatedRow.notes.find(note => note.id === locator.noteId) ||
    locatedRow.notes.find(note => matchesNote(note, locator.noteId!)) : undefined;
  const focusMeeting = locator?.focus === 'meeting' && locatedRow?.kind === 'meeting';
  const focusedNote = focusMeeting ? undefined : locatedNote;
  const activeView = locatedRow ? locatedRow.kind === 'meeting' ? 'meetings' : 'pending'
    : view || (storedView === 'pending' ? 'pending' : 'meetings');
  const pendingView = activeView === 'pending';
  const actionContext = JSON.stringify([ownerId, associationContextKey, activeView]);
  const currentContext = useRef(actionContext);
  currentContext.current = actionContext;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { setAssociationFeedback(''); }, [actionContext]);
  useEffect(() => { setDeletingRow(undefined); setDeleteError(''); }, [actionContext]);
  useEffect(() => {
    if (!associationFeedback) return;
    const frame = requestAnimationFrame(() => {
      if (!document.querySelector('[role="dialog"][data-state="open"]')) pendingTab.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [associationFeedback]);
  const associationCompleted = async () => {
    await onAssociated?.();
    if (!mounted.current || currentContext.current !== actionContext) return;
    setAssociating(undefined);
    setAssociationFeedback('关联已确认，可在全部会议中查看对应档案。');
  };
  const changeView = (next: MeetingArchiveView) => { setDismissedLocator(locator?.requestId || ''); setStoredView(next); onViewChange?.(next); };
  const expandedIds = Array.isArray(expandedRows) ? expandedRows : [];
  // Group stable identities before filtering: retained history is not a new row.
  // Source association defines a dossier. Historical personal archive flags
  // remain on the content but cannot hide a meeting or split its versions.
  const rows = allRows.filter(row => row.kind === 'meeting');
  const visible = pendingView ? [] : rows.filter(row => !selectedDate || selectedDate === row.displayDate || locating && row.key === locatedRow?.key).filter(
    (row) =>
      (row.key === locatedRow?.key || (
        row.title +
        row.notes.map(note => note.title + ' ' + notePreview(note.content || '')).join(' ') +
        row.recordings.map(recording => recording.options.title || '').join(' ')
      )
        .toLowerCase()
        .includes(query.trim().toLowerCase()) &&
      (filter === "全部" || row.state === filter || filter === "需处理" && ["状态未核验", "纪要待保存"].includes(row.state))),
  );
  const matchesQuery = (note: NoteRecord) => (note.title + ' ' + notePreview(note.content || '')).toLowerCase().includes(query.trim().toLowerCase());
  const unlinked = allRows.filter(row => row.kind === 'unlinked').flatMap(row => row.notes)
    .filter(note => note.id === locatedNote?.id || matchesQuery(note))
    .sort((a, b) => serverTimestamp(b.createdAt).getTime() - serverTimestamp(a.createdAt).getTime());
  useEffect(() => {
    if (associating && (!pendingView || associating.ownerId !== ownerId || associating.context !== associationContextKey ||
      !unlinked.some(note => note.id === associating.note.id))) setAssociating(undefined);
  }, [pendingView, ownerId, associationContextKey, associating, unlinked]);
  const setRowExpanded = (viewIds: string[], open: boolean) => setExpandedRows(current => {
    const ids = Array.isArray(current) ? current.filter(id => typeof id === 'string') : [];
    if (viewIds.some(id => ids.includes(id)) === open) return ids;
    return open ? [...new Set([...ids, ...viewIds])] : ids.filter(id => !viewIds.includes(id));
  });
  const locatorContext = JSON.stringify([ownerId, locator?.requestId, associationContextKey, locator?.focus]);
  useEffect(() => {
    if (!locatedRow || loading || expandedLocator.current === locatorContext) return;
    expandedLocator.current = locatorContext;
    if (locatedRow.kind === 'meeting') setRowExpanded(relatedViewIds(locatedRow), true);
  }, [locatorContext, locatedRow?.key, loading]);
  useEffect(() => {
    if (!locatedRow || loading || focusedLocator.current === locatorContext) return;
    const element = focusedNote
      ? listRef.current?.querySelector<HTMLElement>('[data-meeting-located="true"]')
      : Array.from(listRef.current?.querySelectorAll<HTMLElement>('[data-meeting-row-key]') || [])
        .find(node => node.dataset.meetingRowKey === locatedRow.key)?.querySelector<HTMLElement>('button');
    if (!element || element.closest('details')?.open === false) return;
    const frame = requestAnimationFrame(() => {
      if (!element.isConnected) return;
      focusedLocator.current = locatorContext;
      element.scrollIntoView?.({ block: 'center', behavior: 'auto' });
      element.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [locatorContext, locatedRow?.key, focusedNote?.id, expandedRows, loading]);
  const selected = pendingView ? undefined : rows.find((row) => row.key === selectedKey && row.recording);
  const previewRecording = selected?.recordings.find(row => row.id === previewRecordingId) || selected?.recording;
  const selectedRecordingTime = meetingTime(previewRecording?.startedAt);
  const selectedRecordingDuration = recordingDuration(previewRecording?.elapsedSeconds);
  useEffect(() => { if (!selected) setPreviewOpen(false) }, [selected]);
  return (
    <section ref={listRef} aria-label="会议列表" tabIndex={-1} data-meeting-scroll-view={JSON.stringify([activeView, query, filter])} data-meeting-scroll-ready={!loading} className="meeting-workspace flex min-w-0 flex-col gap-4">
      <div className="min-w-0">
        <div
          aria-label="记录列表"
          className="min-w-0"
        >
          {(allRows.length > 0 || !!importedSourceCount || query || selectedDate || filter !== '全部') && <div className="mb-2 flex flex-wrap items-center gap-3 border-b pb-3">
            <div className="relative min-w-0 flex-1 sm:max-w-sm"><Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" aria-hidden="true" /><Input aria-label="搜索记录" placeholder="搜索标题或会议内容" value={query} onChange={event => setQuery(event.target.value)} className="h-9 pl-9" /></div>
            <Tabs className="min-w-0" value={activeView} onValueChange={value => changeView(value === 'pending' ? 'pending' : 'meetings')}><TabsList aria-label="会议档案视图" className="line-tabs h-9"><TabsTrigger value="meetings">按日期浏览</TabsTrigger><TabsTrigger ref={pendingTab} value="pending">未关联原录制</TabsTrigger></TabsList></Tabs>
            {!pendingView && <Button variant="outline" className="h-9" onClick={() => setFiltersOpen(true)}>筛选会议{(selectedDate || filter !== '全部') ? ' · 已筛选' : ''}</Button>}
          </div>}
          <Dialog open={filtersOpen} onOpenChange={setFiltersOpen}><DialogContent className="max-w-md"><DialogHeader><DialogTitle>筛选会议</DialogTitle><DialogDescription>按会议日期与处理状态查找，关闭后保留选择。</DialogDescription></DialogHeader><div className="grid gap-5">
              {!pendingView && <label className="flex items-center gap-2 text-xs text-muted-foreground">会议日期<Input type="date" aria-label="按会议日期筛选" value={selectedDate} onChange={event => setSelectedDate(event.target.value)} className="w-auto" />{selectedDate && <Button variant="ghost" size="sm" onClick={() => setSelectedDate('')}>全部日期</Button>}</label>}
              {!pendingView && <Tabs className="min-w-0 max-w-full" value={filter} onValueChange={setFilter}>
                <TabsList aria-label="记录筛选" className="h-auto max-w-full flex-wrap">
                  {["全部", "未生成", "处理中", "已完成", "需处理"].map((label) => (
                    <TabsTrigger
                      key={label}
                      value={label}
                      className="px-2.5 py-1"
                    >
                      {label}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>}
            <Button onClick={() => setFiltersOpen(false)}>完成筛选</Button></div></DialogContent></Dialog>
          <div>
            {pendingView && unlinked.length > 0 && <p className="text-xs leading-5 text-muted-foreground">选择“关联到会议”，并入对应的录音或录屏档案。</p>}
          </div>
          {associationFeedback && <p role="status" className="text-sm leading-6">{associationFeedback}</p>}
          {locating && <Alert variant={!loading && !locatedRow ? 'destructive' : 'default'}>
            <AlertDescription className="grid gap-2">
              <p role={loading || locatedRow ? 'status' : 'alert'}>{loading ? '正在读取并定位关联会议…' : locatedRow
                ? locatedRow.kind === 'unlinked' ? '此纪要尚未关联到会议，已定位未关联原录制内容。原筛选已保留。'
                  : focusedNote ? '已定位原会议档案和关联纪要。原筛选已保留。' : '已定位原会议档案。原筛选已保留。'
                : invalidLocator ? '定位标识无效或账号已变化，请返回文件库重新选择。'
                  : '当前空间未找到唯一的会议关联，请重新读取记录或返回文件库。原文件和纪要均保留。'}</p>
              <div className="flex flex-wrap gap-2">
                {!loading && !locatedRow && onLocateRetry && <Button variant="outline" size="sm" onClick={onLocateRetry}>重新读取关联</Button>}
                <Button variant="ghost" size="sm" onClick={() => { setDismissedLocator(locator?.requestId || ''); onClearLocator?.(); }}>结束定位</Button>
              </div>
            </AlertDescription>
          </Alert>}
          {loading && !(pendingView ? unlinked.length : visible.length) && <Skeleton className="h-20 w-full" />}
          {!loading && <p className="pb-1 text-xs tabular-nums text-muted-foreground">{pendingView ? `${unlinked.length} 条未关联原录制内容` : `${visible.length + importedSourceCount} 场会议`}</p>}
          {visible.map((row, index) => {
            const viewIds = relatedViewIds(row);
            const expanded = viewIds.some(id => expandedIds.includes(id));
            const panelId = `${viewId}-meeting-${encodeURIComponent(row.key)}`;
            const isRecordingDate = row.dateKind === 'recording';
            const time = meetingTime(row.date);
            const duration = recordingDuration(row.recording?.elapsedSeconds);
            // Server-retained originals remain reachable after local capture
            // history has gone. Open the authorized note; detail verifies media.
            const retainedSource = !row.recordings.length
              ? row.notes.find(note => note.meetingSource && note.meetingSource.canonicalTaskId === note.taskId) ||
                row.notes.find(note => note.meetingSource)
              : undefined;
            const hasOriginal = row.recordings.length > 0 || !!retainedSource;
            const hasRelated = row.notes.length > 0 || hasOriginal;
            const relatedLabel = row.notes.length
              ? `关联纪要（${row.notes.length}条）${hasOriginal ? "与原录制" : ""}`
              : "查看原录制";
            const Icon = row.recording
              ? row.recording.options.screen ||
                row.recording.options.meetingType === "video"
                ? FileVideo
                : FileAudio
              : row.note?.sourceType === "meeting_video"
                ? FileVideo
                : row.note?.sourceType === "meeting_recording"
                  ? FileAudio
                  : FileText;
            return (
              <div key={row.key} data-meeting-row-key={row.key} data-meeting-row-ids={JSON.stringify(viewIds)} className="border-b">
              {(index === 0 || visible[index - 1].displayDate !== row.displayDate) && <h2 className="border-b bg-background px-3 pb-2 pt-6 text-sm font-medium">{dayLabel(row.displayDate, '录制日期未记录')}</h2>}
              <button
                key={row.key}
                type="button"
                aria-label={`${row.title.slice(0, 120)} · ${row.state}`}
                data-meeting-located={focusMeeting && row.key === locatedRow?.key || undefined}
                aria-current={focusMeeting && row.key === locatedRow?.key ? 'true' : undefined}
                aria-expanded={expanded}
                aria-controls={panelId}
                onClick={() => setRowExpanded(viewIds, !expanded)}
                className={`meeting-source-row flex w-full items-start gap-3 px-2 py-4 text-left transition-colors motion-reduce:transition-none hover:bg-muted/60 focus-visible:outline focus-visible:outline-ring ${expanded ? "bg-muted/50" : ""}`}
              >
                <span className="grid size-9 shrink-0 place-items-center rounded-md bg-muted/40 text-muted-foreground">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block break-words text-sm font-medium tabular-nums">
                    {row.title}
                  </span>
                  <span className="meeting-source-meta mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    {isRecordingDate && <span title={time.full} className="tabular-nums">录制于 {time.full}</span>}
                    {duration && <span className="tabular-nums">{duration}</span>}
                    {row.notes.length > 0 && <span>{row.notes.length} 份纪要</span>}
                    <span
                      className={row.state === "需处理" ? "text-destructive" : row.state === "已完成" ? "text-emerald-700 dark:text-emerald-300" : undefined}
                    >
                      {row.state === "已完成" ? "纪要已完成" : row.state}
                    </span>
                  </span>
                  <MeetingProcessingStatus row={row} taskStates={taskStates} />
                  {row.recording?.processingError && (
                    <span className="mt-2 block break-words text-xs text-destructive">
                      {row.recording.processingError} · 原录音已保留
                    </span>
                  )}
                </span>
                <ChevronRight aria-hidden="true" className={`mt-1 size-4 shrink-0 text-muted-foreground ${expanded ? 'rotate-90' : ''}`} />
              </button>
              {hasRelated && <details id={panelId} className="meeting-source-contents min-w-0 text-sm [overflow-wrap:anywhere]" open={expanded} onToggle={event => setRowExpanded(viewIds, event.currentTarget.open)}>
                <summary hidden data-meeting-row-fallback aria-label={`${row.title} · ${relatedLabel}`} className="min-h-11 cursor-pointer break-words rounded-md py-3 text-muted-foreground focus-visible:outline focus-visible:outline-ring">{relatedLabel}</summary>
                <div className="grid min-w-0 gap-4 pb-3">
                  <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs text-muted-foreground">{row.displayDate ? `会议日期 · ${row.displayDate}` : '可补填会议日期'}</span><MeetingDisplayEditor sourceKey={row.displayKey} recording={row.recording} title={(display[row.displayKey || ''] ? display[row.displayKey || ''].title : row.recording?.displayTitle || (row.recording?.titleEdited ? row.recording.options.title : '')) || ''} date={row.displayDate} onSaved={() => { void onAssociated?.(); }} /></div>
                  {onDeleteMeeting && (!canDeleteMeeting || canDeleteMeeting(row)) && <Button variant="ghost" className="w-fit text-destructive" onClick={() => { setDeleteError(''); setDeletingRow(row); }}>删除整场会议</Button>}
                  {row.notes.length > 0 && <section aria-label="关联纪要" className="grid gap-2">
                    <h3 className="text-xs font-medium text-muted-foreground">纪要版本</h3>

                    <MeetingNoteItems notes={row.notes} onOpenNote={onOpenNote} taskStates={taskStates} locatedNoteId={focusedNote?.id} ownerId={ownerId} expanded={expanded} />
                  </section>}
                  {row.recordings.length > 0 && <section aria-label="关联原录制" className="grid gap-2">
                    <h3 className="text-xs font-medium text-muted-foreground">原录制</h3>
                    {row.recordings.map(recording => {
                      const recordedTime = meetingTime(recording.startedAt);
                      const originalDuration = recordingDuration(recording.elapsedSeconds);
                      return <Button key={recording.id} variant="ghost" className="h-auto min-h-11 w-full items-start justify-start whitespace-normal py-3 text-left" onClick={() => { setSelectedKey(row.key); setPreviewRecordingId(recording.id); setPreviewOpen(true) }}>
                        <span className="min-w-0">
                          <span className="block break-words">查看原录制 · {recording.options.title || "未命名录制"}</span>
                          <span className="mt-1 block text-xs leading-5 text-muted-foreground">录制于 <span className="tabular-nums">{recordedTime.full}</span>{originalDuration && ` · ${originalDuration}`}</span>
                        </span>
                      </Button>;
                    })}
                  </section>}
                  {retainedSource && <section aria-label="关联原录制" className="grid gap-2">
                    <h3 className="text-xs font-medium text-muted-foreground">原录制</h3>
                    <p className="text-xs leading-5 text-muted-foreground">打开关联纪要查看来源，原录制是否可用以详情核验为准。纪要和旧稿始终保留。</p>
                    <Button variant="ghost" className="h-auto min-h-11 w-full justify-start whitespace-normal py-3 text-left" onClick={() => onOpenNote(retainedSource.id)}>
                      查看原录制 · {retainedSource.title}
                    </Button>
                  </section>}
                </div>
              </details>}
              </div>
            );
          })}
          {pendingView && unlinked.length > 0 && <section aria-label="未关联原录制内容" className="grid min-w-0 gap-3 py-3">
            <MeetingNoteItems notes={unlinked} onOpenNote={onOpenNote} taskStates={taskStates} locatedNoteId={focusedNote?.id} ownerId={ownerId}
              onAssociate={ownerId && onAssociated ? note => setAssociating({ note, ownerId, context: associationContextKey }) : undefined} />
          </section>}
          {!pendingView && unlinked.length > 0 && <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
            <p>另有 {unlinked.length} 条内容待关联到会议档案。</p>
            <Button variant="ghost" className="min-h-11" onClick={() => changeView('pending')}>查看未关联原录制</Button>
          </div>}
          {!pendingView && importedSources?.(query, filter, selectedDate)}
          {!loading && !(pendingView ? unlinked.length : visible.length) && (pendingView || !importedSourceCount) && (
            <Empty className="border-0 py-10">
              <FileAudio className="size-7 text-muted-foreground" aria-hidden="true" />
              <EmptyHeader>
                <EmptyTitle>
                  {pendingView ? query ? '没有匹配的未关联原录制内容' : '暂无未关联原录制内容' : query || selectedDate || filter !== '全部' ? '没有匹配会议' : '还没有会议档案'}
                </EmptyTitle>
                <EmptyDescription>
                  {pendingView ? query ? '换个关键词试试。' : '已关联的纪要位于对应会议档案中。' : query || selectedDate || filter !== '全部'
                    ? '换个关键词或筛选条件试试。'
                    : '录制或导入一场会议后，档案会出现在这里。'}
                </EmptyDescription>
              </EmptyHeader>
              {!pendingView && !query && !selectedDate && filter === '全部' && actions}
              {(query || selectedDate || !pendingView && filter !== "全部") && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery(""); setSelectedDate('');
                    if (!pendingView) setFilter("全部");
                  }}
                >
                  清除筛选
                </Button>
              )}
            </Empty>
          )}
        </div>
        {associating && pendingView && associating.ownerId === ownerId && associating.context === associationContextKey &&
          unlinked.some(note => note.id === associating.note.id) && associationNoteId(associating.note) && onAssociated &&
          <AssociateMeetingDialog key={JSON.stringify([ownerId, associationContextKey, associating.note.id])}
            noteId={associationNoteId(associating.note)!} noteTitle={associating.note.title} ownerId={ownerId}
            onClose={() => setAssociating(undefined)} onAssociated={associationCompleted} />}
        <Sheet open={previewOpen} onOpenChange={setPreviewOpen}><SheetContent className="w-full sm:max-w-md"><SheetHeader><SheetTitle>录制详情</SheetTitle><SheetDescription>回放录制、导出文件，或继续生成会议纪要。</SheetDescription></SheetHeader><div className="flex min-w-0 flex-col gap-4 pt-6">
          {selected ? (
            <>
              <div>
                <p className="text-xs text-muted-foreground">选中记录</p>
                <h2 className="mt-3 line-clamp-3 break-words text-lg font-semibold tracking-[-0.015em]">
                  {previewRecording?.options.title || selected.title}
                </h2>
                <p className="mt-2 text-xs text-muted-foreground">
                  录制于 <span className="tabular-nums">{selectedRecordingTime.full}</span>
                  {selectedRecordingDuration && ` · ${selectedRecordingDuration}`}
                </p>
              </div>
              {previewRecording && (
                <LocalRecordingPreview
                  key={previewRecording.id}
                  recording={previewRecording}
                  onOpenNote={id => onOpenNote(selected.notes.find(note => note.id === id || note.localId === id || note.sourceIds?.includes(id))?.id || id)}
                  onDeleted={() => onDeleted(previewRecording.id)}
                />
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              选择记录，查看纪要、播放原声或重试处理。
            </p>
          )}
        </div></SheetContent></Sheet>
      </div>
      <Dialog open={!!deletingRow} onOpenChange={open => { if (!open && !deleteBusy) setDeletingRow(undefined); }}><DialogContent><DialogHeader><DialogTitle>删除整场会议？</DialogTitle><DialogDescription>将删除此会议及其关联内容和原录制，删除后无法恢复。已发布的飞书文档不会删除。</DialogDescription></DialogHeader>
        {deleteError && <p role="alert" className="text-sm text-destructive">{deleteError}</p>}
        <div className="flex justify-end gap-2"><Button variant="outline" disabled={deleteBusy} onClick={() => setDeletingRow(undefined)}>取消</Button><Button variant="destructive" disabled={deleteBusy} onClick={() => {
          if (!deletingRow || !onDeleteMeeting || deleteLock.current) return;
          const context = actionContext;
          deleteLock.current = true; setDeleteBusy(true); setDeleteError('');
          void onDeleteMeeting(deletingRow).then(() => { if (mounted.current && currentContext.current === context) setDeletingRow(undefined); }).catch(error => { if (mounted.current && currentContext.current === context) setDeleteError(error instanceof Error ? error.message : '删除未完成，请重试。'); }).finally(() => { deleteLock.current = false; if (mounted.current) setDeleteBusy(false); });
        }}>确认删除会议</Button></div>
      </DialogContent></Dialog>
    </section>
  );
}
