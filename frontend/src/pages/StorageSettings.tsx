import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { useAuthStore } from '@/stores/authStore';
import { listPendingMeetings, type PendingMeeting } from '@/lib/audioStorage';
import { PageReturn } from '@/components/Layout/PageReturn';
import { PageHeading } from '@/components/Layout/PageHeading';
import { ErrorState, LoadingState } from '@/components/Feedback/ResourceState';
import { Button } from '@/components/ui/button';

export function StorageSettings() {
  const { items, details, ready, error, busy, initialize, changeDeleted } = useWorkspaceStore();
  const owner = useAuthStore(s => s.user?.id);
  const location = useLocation();
  const [recordings, setRecordings] = useState<PendingMeeting[]>([]);
  const [recordingsReady, setRecordingsReady] = useState(false);
  const [localError, setLocalError] = useState('');
  const [restoreError, setRestoreError] = useState('');
  const [restoring, setRestoring] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const deleted = items.filter(note => note.deleted);
  const returnTo = location.pathname + location.search + location.hash;
  useEffect(() => {
    let active = true;
    setRecordingsReady(false);
    setRecordings([]);
    setLocalError('');
    if (owner) void listPendingMeetings(owner)
      .then(next => { if (active) { setRecordings(next); setRecordingsReady(true); } })
      .catch(cause => { if (active) setLocalError(cause instanceof Error ? cause.message : '录制记录读取失败'); });
    return () => { active = false; };
  }, [owner, attempt]);
  useEffect(() => {
    if (location.hash === '#trash' && ready) {
      heading.current?.scrollIntoView({ block: 'start' });
      heading.current?.focus({ preventScroll: true });
    }
  }, [location.hash, ready]);
  const reload = () => {
    setAttempt(value => value + 1);
    if (owner) void initialize(owner).catch(() => undefined);
  };
  return <div className="workspace-page max-w-3xl">
    <PageReturn to="/settings?tab=storage" label="返回存储设置" />
    <PageHeading title="存储" description="管理当前设备的内容、原文件与回收站。" />
    {error && <ErrorState error={error} onRetry={reload} busy={busy} retryLabel="重新读取" />}
    {!ready && !error && <LoadingState label="正在读取保存内容…" />}
    <section className="grid gap-3 border-b pb-6" aria-label="保存内容">
      <h2 className="font-medium">正文与版本</h2>
      <p className="text-sm text-muted-foreground">笔记、会议纪要和已保存版本保留在此设备；移入回收站后可恢复。</p>
      {ready && <dl className="grid grid-cols-2 gap-3 text-sm">
        <dt>内容</dt><dd>{items.filter(note => !note.deleted).length} 份</dd>
        <dt>已读取历史版本</dt><dd>{Object.values(details).reduce((sum, note) => sum + note.versions.length, 0)} 份</dd>
      </dl>}
      <Button variant="outline" className="w-fit" asChild><Link to="/notes">查看笔记</Link></Button>
    </section>
    <section className="grid gap-3 border-b pb-6" aria-label="原文件">
      <h2 className="font-medium">原文件</h2>
      <p className="text-sm text-muted-foreground">录制和导入的原文件在文件库管理。移除正文不会删除原文件或已发布的飞书文档。</p>
      {localError && <ErrorState error={localError} onRetry={reload} retryLabel="重新读取" />}
      <p className="text-sm text-muted-foreground">{recordingsReady ? `${recordings.length} 条录制记录` : localError ? '录制记录数量暂不可用' : '正在读取录制记录…'}</p>
      <Button variant="outline" className="w-fit" asChild><Link to={'/files?' + new URLSearchParams({ type: 'all', returnTo })} state={{ returnTo }}>打开原文件目录</Link></Button>
    </section>
    <section className="grid gap-3" aria-label="内容回收站">
      <h2 id="trash" ref={heading} tabIndex={-1} className="scroll-mt-6 font-medium">内容回收站</h2>
      <p className="text-sm text-muted-foreground">恢复正文及其已保存版本，原文件不受影响。</p>
      {restoreError && <p role="alert" className="text-sm text-destructive">{restoreError}</p>}
      {ready && deleted.map(note => <div key={note.key} className="flex items-center justify-between gap-3 border-b py-3">
        <span className="min-w-0 break-words">{note.title}</span>
        <Button variant="outline" disabled={busy || !!restoring} onClick={async () => {
          if (!owner) return;
          const expectedOwner = owner;
          setRestoring(note.key); setRestoreError('');
          try {
            const restored = await changeDeleted(note.key, false);
            if (useAuthStore.getState().user?.id !== expectedOwner) return;
            if (!restored || restored.deleted) throw new Error('恢复未完成，内容仍保留在回收站，请重试。');
          } catch (cause) {
            if (useAuthStore.getState().user?.id === expectedOwner) setRestoreError(cause instanceof Error ? cause.message : '恢复失败，请重试。');
          } finally { setRestoring(null); }
        }}>{restoring === note.key ? '恢复中…' : '恢复内容'}</Button>
      </div>)}
      {ready && !deleted.length && <p className="text-sm text-muted-foreground">回收站为空。</p>}
    </section>
  </div>;
}
