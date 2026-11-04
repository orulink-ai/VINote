import { useMeetingDisplay } from '@/hooks/useMeetingDisplay';
import { MeetingDisplayEditor } from './MeetingDisplayEditor';
import { dayLabel } from '@/lib/contentDates';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import { FileAudio, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';

type Source = { id: string; task_id?: string; note_id?: string; purpose?: string; title?: string; filename: string; processing_status?: string; error_code?: string };
const processingStatuses = new Set(['processing', 'pending', 'running', 'uploaded', 'preparing', 'preparing_media', 'downloading', 'transcribing', 'diarizing', 'parallel_analysis', 'aligning', 'analyzing_video', 'summarizing', 'screenshots', 'saving', 'saving_result']);
export function ImportedMeetingSources({ owner, coveredTasks, returnTo, onSourceCount, query = '', filter = '全部', date = '' }: { owner?: string; coveredTasks: string[]; returnTo: string; onSourceCount?: (count: number) => void; query?: string; filter?: string; date?: string }) {
  const display = useMeetingDisplay(owner);
  const [items, setItems] = useState<Source[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const epoch = useRef(0);
  useEffect(() => {
    const run = ++epoch.current;
    setItems([]); setFailed(false); setLoading(!!owner);
    if (!owner) return;
    const unsubscribe = useAuthStore.subscribe?.((state, previous) => {
      if (state.user?.id !== previous.user?.id) {
        epoch.current++; setItems([]); setLoading(false);
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
  const sources = items.filter(item => (!date || info(item)?.meeting_date === date) && `${info(item)?.title || ''} ${item.title || ''} ${item.filename}`.toLowerCase().includes(query.trim().toLowerCase()) && (filter === '全部' || filter === '未生成' && !item.task_id || filter === '需处理' && ['failed', 'error'].includes(item.processing_status || '') || filter === '处理中' && processingStatuses.has(item.processing_status || '')) && item.purpose === 'meeting' && !item.note_id && (!item.task_id || !coveredTasks.includes(item.task_id))).sort((a, b) => (info(b)?.meeting_date || '').localeCompare(info(a)?.meeting_date || ''));
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
          <span className="mt-1 block text-xs text-muted-foreground">{['unknown_result', 'unknown_error', 'asr_incomplete_result'].includes(item.error_code || '') ? '处理结果尚未确认，原文件已保留。' : item.processing_status === 'failed' ? '处理未完成，原文件已保留。' : item.task_id ? '原文件已保留，有处理记录。' : '原文件已保存，尚未生成纪要。'}</span>
        </span>
        <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </Link>
      <div className="pb-2 pl-12"><MeetingDisplayEditor sourceKey={key(item)} title={info(item)?.title || ''} date={info(item)?.meeting_date || ''} /></div>
    </article>)}
  </section>;
}
