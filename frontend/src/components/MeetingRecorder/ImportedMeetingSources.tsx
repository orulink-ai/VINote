import { useMeetingDisplay } from '@/hooks/useMeetingDisplay';
import { MeetingDisplayEditor } from './MeetingDisplayEditor';
import { dayLabel } from '@/lib/contentDates';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import { FileAudio, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';

type Source = { id: string; task_id?: string; canonical_task_id?: string; deletion_pending?: boolean; note_id?: string; purpose?: string; title?: string; filename: string; processing_status?: string; error_code?: string };
const processingStatuses = new Set(['processing', 'pending', 'running', 'uploaded', 'preparing', 'preparing_media', 'downloading', 'transcribing', 'diarizing', 'parallel_analysis', 'aligning', 'analyzing_video', 'summarizing', 'screenshots', 'saving', 'saving_result']);
export function ImportedMeetingSources({ owner, coveredTasks, returnTo, onSourceCount, onDeleteTask, query = '', filter = '全部', date = '' }: { owner?: string; coveredTasks: string[]; returnTo: string; onSourceCount?: (count: number) => void; onDeleteTask?: (canonical: string) => Promise<void>; query?: string; filter?: string; date?: string }) {
  const display = useMeetingDisplay(owner);
  const [items, setItems] = useState<Source[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const epoch = useRef(0);
  const [deleting, setDeleting] = useState<Source>();
  const [deleteError, setDeleteError] = useState('');
  const [deleteBusy, setDeleteBusy] = useState(false);
  const deleteLock = useRef(false);
  useEffect(() => {
    const run = ++epoch.current;
    setItems([]); setFailed(false); setLoading(!!owner); setDeleting(undefined); setDeleteError('');
    if (!owner) return;
    const unsubscribe = useAuthStore.subscribe?.((state, previous) => {
      if (state.user?.id !== previous.user?.id) {
        epoch.current++; setItems([]); setLoading(false); setDeleting(undefined); setDeleteError('');
      }
    });
    const current = () => run === epoch.current && useAuthStore.getState().user?.id === owner;
    void apiJson<{ items: Source[] }>('/api/files').then(result => {
      if (!Array.isArray(result?.items)) throw new Error('invalid source list');
      if (current()) setItems(result.items);
    }).catch(() => { if (current()) setFailed(true); })
      .finally(() => { if (current()) setLoading(false); });
    return () => { epoch.current++; unsubscribe?.(); };
  }, [owner, attempt]);
  const key = (item: Source) => item.id.startsWith('task:') ? item.id : item.task_id ? `task:${item.task_id}` : `file:${item.id}`;
  const info = (item: Source) => display[key(item)] || display[`file:${item.id}`];
  const sources = items.filter(item => (!date || info(item)?.meeting_date === date) && `${info(item)?.title || ''} ${item.title || ''} ${item.filename}`.toLowerCase().includes(query.trim().toLowerCase()) && (filter === '全部' || filter === '未生成' && !item.task_id || filter === '需处理' && (item.deletion_pending || ['failed', 'error'].includes(item.processing_status || '')) || filter === '处理中' && processingStatuses.has(item.processing_status || '')) && item.purpose === 'meeting' && (item.deletion_pending || !item.note_id && (!item.task_id || !coveredTasks.includes(item.task_id)))).sort((a, b) => (info(b)?.meeting_date || '').localeCompare(info(a)?.meeting_date || ''));
  const canonical = (item: Source) => item.canonical_task_id && /^[A-Za-z0-9_-]+$/.test(item.canonical_task_id) ? item.canonical_task_id : /^task:[A-Za-z0-9_-]+$/.test(item.id) ? item.id.slice(5) : undefined;
  useEffect(() => {
    onSourceCount?.(sources.length);
    return () => onSourceCount?.(0);
  }, [onSourceCount, sources.length]);
  if (!loading && !failed && !sources.length) return null;
  return <section aria-label="会议资料" className="grid">
    <h2 className="sr-only text-balance">待生成纪要的会议</h2>

    {loading && <p role="status">正在读取会议资料…</p>}
    {failed && <div role="alert"><p>会议资料暂未读取成功，请重新读取。</p><Button variant="outline" disabled={loading} onClick={() => setAttempt(value => value + 1)}>重新读取会议资料</Button></div>}
    {sources.map((item, index) => <article key={item.id} className="border-b">
      {(index === 0 || info(sources[index - 1])?.meeting_date !== info(item)?.meeting_date) && <h2 className="px-3 pb-2 pt-6 text-sm font-medium">{dayLabel(info(item)?.meeting_date || '', '录制日期未记录')}</h2>}
      <Link to={'/meetings/files?' + new URLSearchParams({ purpose: 'meeting', file: item.id })} state={{ returnTo }} aria-label="查看资料与处理记录" className="flex items-start gap-3 px-2 py-4 transition-colors hover:bg-muted/50 focus-visible:outline focus-visible:outline-ring">
        <span className="grid size-9 shrink-0 place-items-center rounded-md bg-muted/40 text-muted-foreground"><FileAudio className="size-4" aria-hidden="true" /></span>
        <span className="min-w-0 flex-1">
          <h3 className="text-balance break-words text-sm font-medium">{info(item)?.title || '未命名会议'}</h3>
          <span className="mt-1 block text-xs text-muted-foreground">{item.deletion_pending ? '会议删除尚未完成，请继续删除。' : ['unknown_result', 'unknown_error', 'asr_incomplete_result'].includes(item.error_code || '') ? '处理结果尚未确认，原文件已保留。' : item.processing_status === 'failed' ? '处理未完成，原文件已保留。' : item.task_id ? '原文件已保留，有处理记录。' : '原文件已保存，尚未生成纪要。'}</span>
        </span>
        <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </Link>
      <div className="flex gap-2 pb-2 pl-12"><MeetingDisplayEditor sourceKey={key(item)} title={info(item)?.title || ''} date={info(item)?.meeting_date || ''} />{(!item.task_id && !item.id.startsWith('task:') || !!onDeleteTask && !!canonical(item)) && <Button variant="ghost" className="text-destructive" onClick={() => { setDeleteError(''); setDeleting(item); }}>{item.deletion_pending ? '继续删除会议' : '删除整场会议'}</Button>}</div>
    </article>)}
    <Dialog open={!!deleting} onOpenChange={open => { if (!open && !deleteBusy) setDeleting(undefined); }}><DialogContent><DialogHeader><DialogTitle>删除整场会议？</DialogTitle><DialogDescription>将删除原文件及关联的处理记录和纪要，删除后无法恢复。已发布的飞书文档不会删除。</DialogDescription></DialogHeader>
      {deleteError && <p role="alert" className="text-sm text-destructive">{deleteError}</p>}
      <div className="flex justify-end gap-2"><Button variant="outline" disabled={deleteBusy} onClick={() => setDeleting(undefined)}>取消</Button><Button variant="destructive" disabled={deleteBusy} onClick={() => {
        if (!deleting || !owner || deleteLock.current || useAuthStore.getState().user?.id !== owner) return;
        const item = deleting, run = epoch.current;
        deleteLock.current = true; setDeleteBusy(true); setDeleteError('');
        const sourceCanonical = canonical(item);
        const request = sourceCanonical && onDeleteTask
          ? onDeleteTask(sourceCanonical).then(() => ({ deleted: true }))
          : apiJson<{ deleted: boolean }>(`/api/files/${encodeURIComponent(item.id)}/orphan-meeting`, { method: 'DELETE' });
        void request.then(result => {
          if (run !== epoch.current || useAuthStore.getState().user?.id !== owner) return;
          if (result?.deleted !== true) throw new Error('删除结果未确认，请重新读取会议资料。');
          setItems(current => current.filter(source => source.id !== item.id)); setDeleting(undefined);
        }).catch(error => { if (run === epoch.current && useAuthStore.getState().user?.id === owner) setDeleteError(error instanceof Error ? error.message : '删除未完成，请重新读取会议资料。'); }).finally(() => { deleteLock.current = false; setDeleteBusy(false); });
      }}>确认删除会议</Button></div>
    </DialogContent></Dialog>
  </section>;
}
