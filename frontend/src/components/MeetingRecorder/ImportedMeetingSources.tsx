import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import { Button } from '@/components/ui/button';

type Source = { id: string; task_id?: string; note_id?: string; purpose?: string; title?: string; filename: string; processing_status?: string; error_code?: string };
export function ImportedMeetingSources({ owner, coveredTasks, returnTo }: { owner?: string; coveredTasks: string[]; returnTo: string }) {
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
  const sources = items.filter(item => item.purpose === 'meeting' && !item.note_id && (!item.task_id || !coveredTasks.includes(item.task_id)));
  if (!loading && !failed && !sources.length) return null;
  return <section aria-label="会议资料" className="mt-6 grid gap-3 border-t pt-5">
    <h2 className="text-balance text-base font-medium">会议资料</h2>
    <p className="text-pretty text-sm text-muted-foreground">录音、视频与逐字稿分别保留，可查看原文件和处理记录。</p>
    {loading && <p role="status">正在读取会议资料…</p>}
    {failed && <div role="alert"><p>会议资料暂未读取成功，请重新读取。</p><Button variant="outline" disabled={loading} onClick={() => setAttempt(value => value + 1)}>重新读取会议资料</Button></div>}
    {sources.map(item => <article key={item.id} className="grid gap-2 border-b pb-3">
      <h3 className="text-balance font-medium">{item.title || item.filename}</h3>
      <p className="text-sm text-muted-foreground">{['unknown_result', 'unknown_error', 'asr_incomplete_result'].includes(item.error_code || '') ? '处理结果尚未确认，原文件已保留。' : item.processing_status === 'failed' ? '处理未完成，原文件已保留。' : item.task_id ? '原文件已保留，有处理记录。' : '原文件已保存，尚未生成纪要。'}</p>
      <Button variant="outline" className="w-fit" asChild><Link to={'/files?' + new URLSearchParams({ purpose: 'meeting', file: item.id })} state={{ returnTo }}>查看资料与处理记录</Link></Button>
    </article>)}
  </section>;
}
