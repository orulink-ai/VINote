import type { MeetingTaskStates } from '@/hooks/useMeetingTaskStates';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { useEffect, useState, type ReactNode } from "react";
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
import { libraryNoteIdentities, type LibraryNote as NoteRecord } from "@/hooks/useLibraryNotes";
import { type PendingMeeting } from "@/lib/audioStorage";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { serverTimestamp } from "@/lib/serverTimestamp";

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

type Row = {
  key: string;
  title: string;
  date: string;
  state: string;
  recording?: PendingMeeting;
  note?: NoteRecord;
  notes: NoteRecord[];
  recordings: PendingMeeting[];
};

function relatedViewIds(row: Row) {
  // Use the real members so a different representative does not reset the row.
  return [
    ...row.notes.map(note => `${note.scope}:${note.teamId || ""}:note:${note.id}`),
    ...row.recordings.map(recording => `${recording.workspace.scope}:${recording.workspace.scope === "team" ? recording.workspace.teamId : ""}:recording:${recording.id}`),
  ];
}
/** A projection only: every content object and retained original stays reachable. */
export function buildMeetingRows(recordings: PendingMeeting[], notes: NoteRecord[], taskStates: MeetingTaskStates = {}): Row[] {
  const retainedNotes = [...new Map(notes.flatMap(note => [note, ...(note.localSources || [])])
    .map(note => [`${note.scope}:${note.teamId || ''}:${note.workspaceKey || ''}:${note.id}`, note] as const)).values()];
  const nodes = [
    ...recordings.map(recording => {
      const scope = `${recording.workspace.scope}:${recording.workspace.scope === 'team' ? recording.workspace.teamId : ''}:`;
      return { recording, note: undefined as NoteRecord | undefined, identities: [
        `${scope}task:${recording.id}`, ...(recording.taskId ? [`${scope}task:${recording.taskId}`] : []),
        ...[recording.noteId, recording.draftNoteId].filter(Boolean).map(id => `${scope}note:${id}`),
      ] };
    }),
    ...retainedNotes.map(note => ({ note, recording: undefined as PendingMeeting | undefined, identities: libraryNoteIdentities(note) })),
  ];
  const parents = nodes.map((_, index) => index);
  const root = (index: number): number => parents[index] === index ? index : (parents[index] = root(parents[index]));
  const owners = new Map<string, number>();
  nodes.forEach((node, index) => node.identities.forEach(identity => {
    const previous = owners.get(identity);
    if (previous !== undefined) parents[root(index)] = root(previous);
    owners.set(identity, index);
  }));
  const groups = new Map<number, typeof nodes>();
  nodes.forEach((node, index) => { const key = root(index); groups.set(key, [...(groups.get(key) || []), node]); });
  return [...groups.values()].map(group => {
    const content = group.flatMap(node => node.note ? [node.note] : [])
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt) || Number(!!b.workspaceKey) - Number(!!a.workspaceKey));
    const originals = group.flatMap(node => node.recording ? [node.recording] : []);
    const recording = originals.find(row => row.processingStatus !== 'completed') || originals[0];
    const note = content[0];
    let state = recording ? recording.processingStatus === 'failed' ? '需处理'
      : recording.processingStatus === 'idle' ? '未生成' : recording.processingStatus === 'completed' ? '已完成' : '处理中' : note.status === 'failed' || note.status === 'transcribing_failed' || note.status === 'generation_failed' ? '需处理' : note.status === 'done' ? '已完成' : '状态未核验';
    const taskState = taskStates[recording?.taskId || note?.taskId || ''];
    if (taskState === 'failed') state = '需处理';
    else if (taskState === 'processing') state = '处理中';
    else if (taskState === 'checking') state = '状态核验中';
    else if (taskState === 'unverified') state = '状态未核验';
    else if (taskState === 'complete') state = note?.status === 'done' && (!recording || recording.processingStatus === 'completed' || recording.noteId === note.id) ? '已完成' : '纪要待保存';
    return {
      key: recording ? `recording:${recording.id}` : `note:${note.id}`,
      title: recording?.options.title || note.title,
      date: recording?.startedAt || note.recordingStartedAt || note.createdAt,
      state, recording, note, notes: content, recordings: originals,
    };
  }).sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
}
export function MeetingWorkbench({
  recordings,
  notes,
  loading,
  onOpenNote,
  onDeleted,
  actions,
  taskStates = {},
  archived = false,
  onArchiveChange,
}: {
  recordings: PendingMeeting[];
  notes: NoteRecord[];
  loading: boolean;
  onOpenNote: (id: string, edit?: boolean) => void;
  onDeleted: (id: string) => void;
  actions?: ReactNode;
  taskStates?: MeetingTaskStates;
  archived?: boolean;
  onArchiveChange?: (archived: boolean) => void;
}) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewRecordingId, setPreviewRecordingId] = useState<string | null>(null);
  const [query, setQuery] = useViewState("recordings-query", "");
  const [filter, setFilter] = useViewState("recordings-filter", "全部");
  const [selectedKey, setSelectedKey] = useViewState<string | null>(
    "recordings-selected",
    null,
  );
  const [expandedRows, setExpandedRows] = useViewState<string[]>("recordings-expanded", []);
  const expandedIds = Array.isArray(expandedRows) ? expandedRows : [];
  // Group stable identities before filtering: retained history is not a new row.
  const rows = buildMeetingRows(recordings, notes, taskStates)
    .filter(row => Boolean(row.note?.archived) === archived &&
      (!archived || ["meeting_recording", "meeting_video"].includes(row.note?.sourceType || '')))
    .map(row => archived && row.note ? {
      ...row, title: row.note.title,
      date: row.note.recordingStartedAt || row.note.createdAt,
      recording: undefined, recordings: [],
    } : row);
  const visible = rows.filter(
    (row) =>
      (
        row.title +
        (row.note?.title || "") +
        notePreview(row.note?.content || "")
      )
        .toLowerCase()
        .includes(query.trim().toLowerCase()) &&
      (archived || filter === "全部" || row.state === filter || filter === "需处理" && ["状态未核验", "纪要待保存"].includes(row.state)),
  );
  const selected = rows.find((row) => row.key === selectedKey && row.recording);
  const previewRecording = selected?.recordings.find(row => row.id === previewRecordingId) || selected?.recording;
  const selectedRecordingTime = meetingTime(previewRecording?.startedAt);
  const selectedRecordingDuration = recordingDuration(previewRecording?.elapsedSeconds);
  useEffect(() => { if (!selected) setPreviewOpen(false) }, [selected]);
  return (
    <section aria-label="会议列表" tabIndex={-1} data-meeting-scroll-view={JSON.stringify([archived, query, filter])} data-meeting-scroll-ready={!loading} className="flex min-w-0 flex-col gap-4">
      <div className="min-w-0">
        <div
          aria-label="记录列表"
          className="min-w-0"
        >
          <div className="mb-3 flex flex-col gap-3 border-b pb-4">
            <div className="flex flex-wrap items-center gap-2">
              {!archived && actions}
              <div className="relative min-w-48 flex-1">
                <Search
                  className="absolute left-3 top-3 size-4 text-muted-foreground"
                  aria-hidden="true"
                />
                <Input
                  aria-label="搜索记录"
                  placeholder="搜索标题或会议内容"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="pl-9"
                />
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              {onArchiveChange && <Tabs value={archived ? 'archived' : 'active'} onValueChange={value => onArchiveChange(value === 'archived')}>
                <TabsList aria-label="会议归档筛选">
                  <TabsTrigger value="active">未归档</TabsTrigger>
                  <TabsTrigger value="archived">已归档</TabsTrigger>
                </TabsList>
              </Tabs>}
              {!archived && <Tabs value={filter} onValueChange={setFilter}>
                <TabsList
                  aria-label="记录筛选"
                  className="h-auto flex-wrap gap-1 rounded-full border border-border/60 bg-muted p-1"
                >
                  {["全部", "未生成", "处理中", "已完成", "需处理"].map((label) => (
                    <TabsTrigger
                      key={label}
                      value={label}
                      className="rounded-full px-3 py-1.5 transition-colors duration-200 motion-reduce:transition-none"
                    >
                      {label}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>}
            </div>
            {archived && <p className="text-xs leading-5 text-muted-foreground">仅显示已归档的会议纪要，来源与全部历史内容保留。原始录制仍在文件库管理。</p>}
          </div>
          {loading && !visible.length && <Skeleton className="h-20 w-full" />}
          {visible.map((row) => {
            const viewIds = relatedViewIds(row);
            const relatedNotes = row.notes.map(relatedNotePresentation);
            const presentations = new Map<string, number>();
            relatedNotes.forEach(({ signature }) => presentations.set(signature, (presentations.get(signature) || 0) + 1));
            const isRecordingDate = !!(row.recording?.startedAt || row.note?.recordingStartedAt);
            const time = meetingTime(row.date, !isRecordingDate);
            const duration = recordingDuration(row.recording?.elapsedSeconds);
            const hasRelated = row.notes.length > 1 || row.recordings.length > 0;
            const relatedLabel = row.notes.length
              ? `关联纪要（${row.notes.length}条）${row.recordings.length ? "与原录制" : ""}`
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
              <div key={row.key} data-meeting-row-ids={JSON.stringify(viewIds)} className="border-b">
              <button
                key={row.key}
                type="button"
                aria-label={`${row.title.slice(0, 120)} · ${row.state}`}
                aria-pressed={row.recording ? previewOpen && selected?.key === row.key : undefined}
                onClick={() => { if (row.note && (!row.recording || row.state === '已完成')) onOpenNote(row.note.id); else { setSelectedKey(row.key); setPreviewRecordingId(row.recording?.id || null); setPreviewOpen(true) } }}
                className={`flex w-full items-start gap-3 px-3 py-5 text-left transition-colors motion-reduce:transition-none hover:bg-muted/60 ${previewOpen && selected?.key === row.key ? "bg-muted/50" : ""}`}
              >
                <span className="grid size-9 shrink-0 place-items-center rounded-md bg-muted/40 text-muted-foreground">
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {row.title}
                  </span>
                  <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {isRecordingDate ? "录制于 " : "纪要保存于 "}
                    <span title={time.full} className="tabular-nums">{time.short}</span>
                    {duration && ` · ${duration}`}
                    <Badge
                      variant="secondary"
                      className={`rounded px-1.5 py-0 text-[10px] ${row.state === "已完成" ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" : row.state === "需处理" ? "bg-destructive/10 text-destructive" : ""}`}
                    >
                      · {archived ? "已归档" : row.state === "已完成" ? "纪要已完成" : row.state}
                    </Badge>
                  </span>
                  {row.recording?.processingError && (
                    <span className="mt-2 block break-words text-xs text-destructive">
                      {row.recording.processingError} · 原录音已保留
                    </span>
                  )}
                </span>
                <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground" />
              </button>
              {row.note && <div className="flex justify-end px-3 pb-2"><Button size="sm" variant="ghost" className="min-h-11" aria-label={`编辑《${row.note.title}》`} onClick={() => onOpenNote(row.note!.id, true)}>编辑纪要</Button></div>}
              {hasRelated && <details className="px-3 text-sm" open={viewIds.some(id => expandedIds.includes(id))} onToggle={event => {
                const open = event.currentTarget.open;
                setExpandedRows(current => {
                  const ids = Array.isArray(current) ? current.filter(id => typeof id === "string") : [];
                  if (viewIds.some(id => ids.includes(id)) === open) return ids;
                  return open ? [...new Set([...ids, ...viewIds])] : ids.filter(id => !viewIds.includes(id));
                });
              }}>
                <summary data-meeting-row-fallback aria-label={`${row.title} · ${relatedLabel}`} className="min-h-11 cursor-pointer break-words rounded-md py-3 text-muted-foreground focus-visible:outline focus-visible:outline-ring">{relatedLabel}</summary>
                <div className="grid gap-4 pb-3">
                  {row.notes.length > 0 && <section aria-label="关联纪要" className="grid gap-2">
                    <h3 className="font-medium">纪要</h3>
                    <p className="text-xs leading-5 text-muted-foreground">关联纪要分别保留自己的保存版本。</p>
                    {relatedNotes.map(({ note, savedTime, updatedTime, metadata, preview, signature }) => <div key={note.id} className="min-w-0">
                      <Button data-meeting-return-target={`${note.scope}:${note.teamId || ''}:note:${note.id}`} variant="outline" className="h-auto min-h-11 w-full items-start justify-start whitespace-normal py-3 text-left" onClick={() => onOpenNote(note.id)}>
                        <span className="min-w-0">
                          <span className="block break-words">查看纪要 · {note.title}</span>
                          <span className="mt-1 block text-xs leading-5 text-muted-foreground">保存于 <span title={savedTime.full} className="tabular-nums">{savedTime.full}</span>{metadata && ` · ${metadata}`}</span>
                          <span className="mt-1 block text-xs leading-5 text-muted-foreground">记录更新于 <span className="tabular-nums">{updatedTime.full}</span></span>
                          <span className="mt-2 line-clamp-2 break-words text-xs leading-5 text-muted-foreground">{preview}</span>
                        </span>
                      </Button>
                      {(presentations.get(signature) || 0) > 1 && <details className="mt-1 text-xs">
                        <summary className="min-h-11 cursor-pointer rounded-md py-3 text-muted-foreground focus-visible:outline focus-visible:outline-ring">记录详情</summary>
                        <dl className="pb-3"><dt className="text-muted-foreground">记录标识</dt><dd className="mt-1 select-text break-all">{note.id}</dd></dl>
                      </details>}
                    </div>)}
                  </section>}
                  {row.recordings.length > 0 && <section aria-label="关联原录制" className="grid gap-2">
                    <h3 className="font-medium">原录制</h3>
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
                </div>
              </details>}
              </div>
            );
          })}
          {!loading && !visible.length && (
            <Empty>
              <EmptyHeader>
                <EmptyTitle>
                  {archived ? query ? "没有匹配的归档会议纪要" : "还没有归档会议纪要" : query || filter !== "全部" ? "没有匹配会议" : "还没有会议"}
                </EmptyTitle>
                <EmptyDescription>
                  {archived ? query ? "调整搜索关键词，已归档内容和版本不会删除。" : "在会议内容详情的内容操作中归档纪要。原始录制仍在文件库管理。" : query || filter !== "全部"
                    ? "调整筛选或搜索关键词。"
                    : "录制或导入会议后在这里查看纪要。原始文件在文件库管理。"}
                </EmptyDescription>
              </EmptyHeader>
              {(query || !archived && filter !== "全部") && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery("");
                    if (!archived) setFilter("全部");
                  }}
                >
                  清除筛选
                </Button>
              )}
            </Empty>
          )}
        </div>
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
    </section>
  );
}
