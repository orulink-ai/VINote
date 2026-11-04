import { calendarDay, dayLabel } from '@/lib/contentDates';
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronRight,
  FileText,
  Mic2,
  Search,
  PenLine,
  Edit3,
  Trash2,
  FileUp,
  Link2,
  SlidersHorizontal,
} from "lucide-react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useLibraryNotes, libraryNoteUrl, type LibraryNote } from "@/hooks/useLibraryNotes";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { useI18n } from "@/lib/i18n";
import { noteOrigin } from "@/lib/noteOrigin";
import { notePreview } from "@/lib/notePreview";
import { groupNoteDossiers } from '@/lib/noteDossiers';
import { serverTimestamp } from '@/lib/serverTimestamp';
import { useNoteLibraryStore } from "@/stores/noteLibraryStore";
import { useTeamStore } from "@/stores/teamStore";
import { PageHeading } from "@/components/Layout/PageHeading";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover';
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";
import { cn } from "@/lib/utils";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import { useViewState } from "@/hooks/useViewState";
import { PageReturn } from '@/components/Layout/PageReturn';
import { resolvePageParent } from '@/lib/navigation';
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '@/components/ui/alert-dialog';

type Filter = "all" | "meeting" | "media" | "text";
export function Notes() {
  const navigate = useNavigate();
  const location = useLocation();
  const returnTo = resolvePageParent(location.pathname + location.search + location.hash);
  const { locale, formatDate } = useI18n();
  const { loading, error, loadNotes } = useNoteLibraryStore();
  const notes = useLibraryNotes();
  const [params, setParams] = useSearchParams();
  const archived = params.get("archived") === "1";
  const selectedDate = params.get("date") || "";
  const setDate = (value: string) => setParams(previous => { const next = new URLSearchParams(previous); value ? next.set("date", value) : next.delete("date"); return next; });
  const contentError = useWorkspaceStore((s) => s.error);
  const workspaceBusy = useWorkspaceStore((s) => s.busy);
  const [deleteTarget, setDeleteTarget] = useState<LibraryNote | null>(null);
  const deleteReference = deleteTarget?.workspaceKey || deleteTarget?.localId || deleteTarget?.id;
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [expandedReadError, setExpandedReadError] = useState('');
  const deleteLock = useRef(false);
  const { currentWorkspace } = useTeamStore();
  const [query, setQuery] = useViewState("notes-query", "");
  const [filter, setFilter] = useViewState<Filter>("notes-filter", "all");
  const project = params.get("project") || "all";
  const setProject = (value: string) => { const next = new URLSearchParams(params); value === "all" ? next.delete("project") : next.set("project", value); setParams(next); };
  const projects = Array.from(
    new Set(notes.map((note) => note.project).filter((p): p is string => !!p)),
  ).sort();
  const zh = locale.startsWith("zh");
  const hasCache = notes.length > 0;
  const hasFilters = !!(query || selectedDate || archived || project !== 'all' || filter !== 'all');
  const showFilters = hasCache || hasFilters;
  const readErrorIdentity = JSON.stringify([error, contentError]);
  const hasReadError = !!(error || contentError);
  const readErrorsExpanded = hasReadError && expandedReadError === readErrorIdentity;
  const updateLabel = hasReadError ? '列表读取未完成' : loading || workspaceBusy ? '正在读取内容' : '';
  const savedTimes = useMemo(() => {
    const counts = new Map<string, number>();
    for (const note of notes) counts.set(note.title, (counts.get(note.title) || 0) + 1);
    const result = new Map<string, Date>();
    for (const note of notes) {
      // Remote creation/last-read time is not evidence of when the source was saved.
      if ((counts.get(note.title) || 0) < 2 || note.recordingStartedAt || note.dateLabel === '同步于' || !/T\d{2}:\d{2}:\d{2}/.test(note.createdAt)) continue;
      const saved = serverTimestamp(note.createdAt);
      if (Number.isFinite(saved.getTime())) result.set(note.id, saved);
    }
    return result;
  }, [notes]);
  const savedTimeFormat = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  useEffect(() => {
    void loadNotes(currentWorkspace);
  }, [currentWorkspace, loadNotes]);
  const filtered = useMemo(
    () =>
      groupNoteDossiers(notes.filter((note) => {
        const source = note.sourceType || "";
        const meeting = source.startsWith("meeting");
        const media = ["video", "audio"].some((type) => source.includes(type));
        const matchesType =
          filter === "all" ||
          (filter === "meeting" && meeting) ||
          (filter === "media" && media && !meeting) ||
          (filter === "text" && !meeting && !media);
        return (
          (project !== 'all' || !meeting) && (!archived || Boolean(note.archived)) &&
          (project === "all" || note.project === project) &&
          matchesType
        );
      })).filter(group => group.versions.some(note =>
        `${note.title} ${note.tags?.join(' ') || ''} ${notePreview(note.content)}`
          .toLowerCase().includes(query.trim().toLowerCase())))
      .map(group => ({ ...group, savedDate: group.versions.map(note => calendarDay(note.createdAt)).sort().reverse()[0] || '' }))
      .filter(group => !selectedDate || group.savedDate === selectedDate)
      .sort((a, b) => b.savedDate.localeCompare(a.savedDate) || a.id.localeCompare(b.id)),
    [filter, notes, query, archived, project, selectedDate],
  );
  const deletingGroupedVersion = !!deleteTarget?.originalSource && notes.some(note =>
    note.id !== deleteTarget.id && note.scope === deleteTarget.scope && note.teamId === deleteTarget.teamId &&
    note.originalSource?.ownerId === deleteTarget.originalSource?.ownerId &&
    note.originalSource?.originalId === deleteTarget.originalSource?.originalId);
  const filters: Array<[Filter, string]> = [
    ["all", zh ? "全部" : "All"],
    ["media", zh ? "音视频" : "Media"],
    ["text", zh ? "文档与文字" : "Documents & text"],
  ];
  const open = (id: string, edit = false) => {
    const note = notes.find((n) => n.id === id);
    if (note) {
      const target = new URL(libraryNoteUrl(note), 'https://vinote.invalid');
      if (edit) target.searchParams.set('edit', '1');
      navigate(target.pathname + target.search, { state: { returnTo } });
    }
  };
  const remove = async () => {
    const reference = deleteReference;
    if (!reference || deleteLock.current || workspaceBusy) return;
    deleteLock.current = true;
    setDeleting(true);
    setDeleteError('');
    const owner = useWorkspaceStore.getState().owner;
    try {
      if (useWorkspaceStore.getState().owner !== owner) throw new Error('账号已切换，请重新打开内容');
      const receipt = await useWorkspaceStore.getState().changeDeleted(reference, true);
      if (!receipt?.deleted) throw new Error('移入回收站未完成，正文与原文件保留，请重试。');
      setDeleteTarget(null);
    } catch (cause) {
      setDeleteError(cause instanceof Error ? cause.message : '删除失败，内容已保留，请重试');
    } finally {
      deleteLock.current = false;
      setDeleting(false);
    }
  };
  return (
    <div className="workspace-page notes-page">
      {project !== "all" && <PageReturn to="/projects" label="返回项目" />}
      <PageHeading
        title={archived ? '归档内容' : project !== "all" ? project : zh ? "笔记" : "Content"}
        description={
          archived ? "已归档的笔记与纪要，保留全部版本。" : "把资料整理成值得回看的知识。"
        }
        actions={
          <><Button variant="ghost" asChild><Link to={'/notes/files?' + new URLSearchParams({ returnTo })} state={{ returnTo }}>笔记原文件</Link></Button><Button asChild><Link to="/write" state={{ returnTo }}><PenLine data-icon="inline-start" />写笔记</Link></Button></>
        }
      />
      {!archived && <section aria-label="生成总结笔记" className="notes-intake">
        <span className="text-xs text-muted-foreground">添加资料</span>
        {[
          { mode: 'url', icon: Link2, title: '粘贴链接', description: 'B 站等公开视频、普通网页或公开文档 → 总结笔记' },
          { mode: 'file', icon: FileUp, title: '导入文件', description: 'PDF、Word、音视频或文字文件 → 总结笔记' },
        ].map(({ mode, icon: Icon, title, description }) => <Link key={mode} to={`/generate?mode=${mode}&intent=import`} onClick={event => { if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate(`/generate?mode=${mode}&intent=import&draft=${crypto.randomUUID()}`, { state: { returnTo } }); }} state={{ returnTo }} title={description} className="inline-flex min-h-10 items-center gap-2 rounded-md px-3 text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Icon aria-hidden="true" className="size-4 text-muted-foreground" />
          <span>{title}</span><span className="sr-only">{description}</span>
        </Link>)}
      </section>}
      {!hasCache && error && (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>{error}</span>
            <Button
              variant="outline"
              disabled={loading}
              onClick={() => void loadNotes(currentWorkspace)}
            >
              {zh ? "重新加载" : "Reload"}
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {!hasCache && contentError && (
        <Alert>
          <AlertDescription className="flex items-center justify-between gap-3">
            <span>保存内容读取失败：{contentError}</span>
            <Button
              variant="outline"
              onClick={() => { const state = useWorkspaceStore.getState(); if (state.owner) void state.initialize(state.owner).catch(() => undefined); }}
            >
              重新读取
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <section aria-label="内容浏览" className="notes-workspace min-w-0">
        <div
          aria-label="笔记列表"
          className="notes-list min-w-0"
        >
          {showFilters && <div className="notes-filters flex flex-wrap items-center gap-2 border-b pb-2">
            <div className="relative min-w-60 flex-1">
              <Search
                className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                aria-label="搜索笔记"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索标题或正文"
                className="min-h-11 pl-9"
              />
            </div>
            <div className="flex max-w-full flex-wrap items-center gap-2">
              <Tabs
                value={filter}
                onValueChange={(value) => setFilter(value as Filter)}
              >
                <TabsList
                  className="h-auto flex-wrap justify-start gap-0 rounded-md bg-transparent p-0"
                  aria-label="内容类型"
                >
                  {filters.map(([value, label]) => (
                    <TabsTrigger
                      key={value}
                      value={value}
                      className="min-h-10 rounded-md px-3 py-1.5 text-xs shadow-none data-[state=active]:bg-muted data-[state=active]:shadow-none"
                      title={value === 'text' ? '文档与文字：网页文章、PDF、Word、文字与字幕笔记' : undefined}
                    >
                      {label}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
              {projects.length > 0 && (
                <div className="ml-auto max-w-40">
                  <NativeSelect
                    aria-label="项目筛选"
                    className="min-h-11"
                    value={project}
                    onChange={(e) => setProject(e.target.value)}
                  >
                    <NativeSelectOption value="all">
                      全部项目
                    </NativeSelectOption>
                    {projects.map((name) => (
                      <NativeSelectOption key={name} value={name}>
                        {name}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                </div>
              )}
            </div>
            <Popover><PopoverTrigger asChild><Button variant="outline" size="sm"><SlidersHorizontal />筛选{(selectedDate || archived) ? ' · 已启用' : ''}</Button></PopoverTrigger><PopoverContent align="end" className="grid gap-4">
              <p className="text-sm font-medium">筛选笔记</p>
              <label className="grid gap-2 text-xs text-muted-foreground">保存日期<Input type="date" aria-label="按保存日期筛选" value={selectedDate} onChange={event => setDate(event.target.value)} /></label>
              <label className="grid gap-2 text-xs text-muted-foreground">归档状态<NativeSelect aria-label="归档筛选" value={archived ? 'archived' : 'all'} onChange={event => setParams(previous => { const next = new URLSearchParams(previous); event.target.value === 'archived' ? next.set('archived', '1') : next.delete('archived'); return next; })}><NativeSelectOption value="all">全部内容</NativeSelectOption><NativeSelectOption value="archived">仅已归档</NativeSelectOption></NativeSelect></label>
              {(selectedDate || archived) && <Button variant="ghost" size="sm" onClick={() => { setParams(previous => { const next = new URLSearchParams(previous); next.delete('date'); next.delete('archived'); return next; }); }}>清除日期与归档筛选</Button>}
            </PopoverContent></Popover>
            {selectedDate && <Button variant="secondary" size="sm" aria-label="全部日期" title="清除日期筛选" onClick={() => setDate('')}>{selectedDate} ×</Button>}
          </div>}
          <div aria-label="列表数量与读取状态" className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 text-xs text-muted-foreground">
            <p>{!hasCache && (hasReadError || loading) ? (zh ? '数量待核验' : 'Count not verified') : zh ? `${filtered.length} 篇笔记` : `${filtered.length} notes`}</p>
            <div className="flex min-h-11 min-w-0 flex-1 flex-wrap items-center justify-end gap-x-2">
              <span className="grid min-w-0">
                <span aria-hidden="true" className="invisible col-start-1 row-start-1">{zh ? '列表读取未完成' : 'Content could not be read'}</span>
                <span aria-live="polite" role={hasCache && updateLabel ? 'status' : undefined} aria-label={hasCache && updateLabel ? '笔记列表读取状态' : undefined} className="col-start-1 row-start-1">{hasCache ? updateLabel || '\u00a0' : '\u00a0'}</span>
              </span>
              <Button variant="ghost" className={cn('min-h-11', (!hasCache || !error) && 'invisible')} aria-hidden={!hasCache || !error} tabIndex={hasCache && error ? 0 : -1} disabled={!hasCache || !error || loading} onClick={() => void loadNotes(currentWorkspace)}>{zh ? '重新加载' : 'Reload'}</Button>
              <Button variant="ghost" className={cn('min-h-11', (!hasCache || !hasReadError) && 'invisible')} aria-hidden={!hasCache || !hasReadError} tabIndex={hasCache && hasReadError ? 0 : -1} disabled={!hasCache || !hasReadError} aria-expanded={readErrorsExpanded} aria-controls="notes-read-error-details" onClick={() => setExpandedReadError(readErrorsExpanded ? '' : readErrorIdentity)}>{readErrorsExpanded ? '收起原因' : '查看原因'}</Button>
            </div>
            <Link to={'/settings/storage?' + new URLSearchParams({ returnTo }) + '#trash'} state={{ returnTo }} className="inline-flex min-h-11 shrink-0 items-center rounded-sm px-2 underline underline-offset-4 hover:text-foreground focus-visible:outline focus-visible:outline-ring">{zh ? '回收站' : 'Trash'}</Link>
          </div>
          {hasCache && readErrorsExpanded && <div id="notes-read-error-details" className="mb-2 grid gap-2 rounded-lg border p-3 text-sm break-words">
            {error && <p><span className="font-medium">列表读取未完成：</span>{error}</p>}
            {contentError && <p><span className="font-medium">保存内容读取未完成：</span>{contentError}</p>}
            <p className="text-muted-foreground">已读取的内容仍可阅读。</p>
          </div>}
          {loading && !notes.length
            ? [1, 2, 3].map((i) => <Skeleton key={i} className="mb-3 h-20" />)
            : filtered.map(({ id, representative: note, versions, savedDate }, index) => (
                <div key={id} className="border-b" data-note-row={note.id}>
                {(index === 0 || filtered[index - 1].savedDate !== savedDate) && <h2 className="border-b bg-background px-3 pb-2 pt-6 text-sm font-medium">{dayLabel(savedDate, '保存日期未记录')}</h2>}
                <div className="flex items-center">
                <button
                  type="button"
                  aria-label={`${note.title.slice(0, 120)} · ${note.status === "failed" ? "需处理" : note.status === "done" ? "已保存" : "处理中"}`}
                  onClick={() => open(note.id)}
                  className={cn(
                    "flex min-w-0 flex-1 items-center gap-4 px-3 py-4 text-left hover:bg-muted/50 focus-visible:outline focus-visible:outline-ring",
                  )}
                >
                  <span className="grid size-9 shrink-0 place-items-center rounded-md bg-muted/50">
                    {note.sourceType?.startsWith("meeting") ? (
                      <Mic2 className="size-4" />
                    ) : (
                      <FileText className="size-4" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px] font-medium">
                      {note.title}
                    </span>
                    <span className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                      {notePreview(note.content).slice(0, 200) ||
                        (zh ? "暂无正文" : "No content")}
                    </span>
                    <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                      <span>
                      {`${note.dateLabel === '同步于' ? '记录于' : note.dateLabel || "保存于"} `}
                      {formatDate(savedTimes.get(note.id)?.toISOString() || note.createdAt)}{savedTimes.has(note.id) ? ` ${savedTimeFormat.format(savedTimes.get(note.id)!)}` : ''} ·{" "}
                      {note.sourceDevice === 'desktop' ? (zh ? '桌面端' : 'Desktop') : note.sourceDevice === 'mobile' ? (zh ? '手机' : 'Mobile') : note.sourceDevice === 'web' ? (zh ? '网页端' : 'Web') : note.sourceDevice || noteOrigin(note.generationClient, zh)}
                      {note.teamName ? ` · ${note.teamName}` : ""}
                      </span>
                    </span>
                  </span>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                </button>
                <div className="notes-row-actions flex shrink-0 items-center gap-1 pr-2">
                  <Button variant="ghost" size="icon" title={versions.length > 1 ? '编辑当前版本' : '编辑笔记'} aria-label={`编辑${versions.length > 1 ? '当前版本' : ''}《${note.title}》`} disabled={workspaceBusy || deleting} onClick={() => open(note.id, true)}><Edit3 aria-hidden="true" className="size-4" /></Button>
                  <Button variant="ghost" size="icon" title={versions.length > 1 ? '仅将当前版本移入回收站' : '移入回收站'} aria-label={`删除${versions.length > 1 ? '当前版本' : ''}《${note.title}》`} disabled={workspaceBusy || deleting} onClick={() => { setDeleteError(''); setDeleteTarget(note); }}><Trash2 aria-hidden="true" className="size-4" /></Button>
                </div>
                </div>
                {versions.length > 1 && <details className="px-3 pb-3 pl-16 text-sm">
                  <summary className="w-fit cursor-pointer rounded-sm py-1 text-xs text-muted-foreground hover:text-foreground focus-visible:outline focus-visible:outline-ring">{versions.length} 个总结版本</summary>
                  <ul className="mt-1 grid gap-1 border-l pl-3">
                    {versions.map((version, index) => <li key={version.id}>
                      <Link to={libraryNoteUrl(version)} state={{ returnTo }} className="flex min-h-9 flex-wrap items-center justify-between gap-x-3 rounded-sm px-2 py-1 hover:bg-muted focus-visible:outline focus-visible:outline-ring">
                        <span className="min-w-0 break-words">{version.title}{index === 0 && <span className="ml-2 text-xs text-muted-foreground">最新</span>}</span>
                        <span className="text-xs text-muted-foreground">{formatDate(version.updatedAt || version.createdAt)}</span>
                      </Link>
                    </li>)}
                  </ul>
                </details>}
                </div>
              ))}
          {!loading && !filtered.length && !error && !contentError && (
            <Empty className="notes-empty">
              <span className="grid size-12 place-items-center rounded-xl border bg-background text-muted-foreground"><FileText className="size-6" aria-hidden="true" /></span>
              <EmptyHeader>
                <EmptyTitle>
                  {zh
                    ? query || selectedDate || filter !== "all" || project !== "all"
                      ? "没有匹配的笔记"
                      : archived ? "没有归档内容" : "还没有保存的笔记"
                    : "No notes found"}
                </EmptyTitle>
                <EmptyDescription>
                  {zh
                    ? archived ? "归档的内容会显示在这里；选择全部内容可继续按日期浏览。" : "导入一份资料，或写下第一篇笔记。"
                    : "Summarize a video link or a local file, or write a note."}
                </EmptyDescription>
              </EmptyHeader>
              {query || selectedDate || filter !== "all" || project !== "all" ? (
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery("");
                    setFilter("all");
                    setParams(previous => { const next = new URLSearchParams(previous); next.delete("project"); next.delete("date"); return next; });
                  }}
                >
                  {zh ? "清除筛选" : "Clear filters"}
                </Button>
              ) : !archived ? <Button onClick={() => navigate(`/generate?mode=url&intent=import&draft=${crypto.randomUUID()}`, { state: { returnTo } })}><Link2 />从链接生成第一篇笔记</Button> : null}
            </Empty>
          )}
        </div>

      </section>
      <AlertDialog open={!!deleteTarget} onOpenChange={open => { if (!open && !deleting) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>将《{deleteTarget?.title}》移入回收站？</AlertDialogTitle>
            <AlertDialogDescription>{deletingGroupedVersion ? '仅此总结版本及其编辑历史移入回收站，其他总结版本不受影响。' : '正文与版本移入回收站，可在存储页恢复。'}原文件与已发布飞书文档保留。</AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError && <p role="alert" className="text-sm text-destructive">{deleteError}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>保留笔记</AlertDialogCancel>
            <AlertDialogAction disabled={deleting || workspaceBusy} onClick={event => { event.preventDefault(); void remove(); }}>{deleting ? '正在移入…' : deleteError ? '重试移入回收站' : '移入回收站'}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
