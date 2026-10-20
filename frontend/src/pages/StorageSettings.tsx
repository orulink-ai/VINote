import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { useAuthStore } from '@/stores/authStore';
import { listPendingMeetings, type PendingMeeting } from '@/lib/audioStorage';
import { PageReturn } from '@/components/Layout/PageReturn';
import { PageHeading } from '@/components/Layout/PageHeading';
import { ErrorState, LoadingState } from '@/components/Feedback/ResourceState';
import { Button, buttonVariants } from '@/components/ui/button';
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription,
  AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '@/components/ui/alert-dialog';

type TrashSelection = { owner: string; entries: { key: string; title: string; revision: number }[]; completed: number };

export function StorageSettings() {
  const { items, details, owner: cacheOwner, ready, error, busy, initialize, changeDeleted, purgeDeleted } = useWorkspaceStore();
  const owner = useAuthStore(s => s.user?.id);
  const location = useLocation();
  const [recordings, setRecordings] = useState<PendingMeeting[]>([]);
  const [recordingsReady, setRecordingsReady] = useState(false);
  const [localError, setLocalError] = useState('');
  const [restoreError, setRestoreError] = useState('');
  const [restoring, setRestoring] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selection, setSelection] = useState<TrashSelection | null>(null);
  const [purging, setPurging] = useState(false);
  const [purgeError, setPurgeError] = useState('');
  const [notice, setNotice] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const trigger = useRef<{ button: HTMLButtonElement; owner: string; generation: number } | null>(null);
  const purgeRun = useRef<number | null>(null);
  const view = useRef({ key: '', generation: 0 });
  const viewKey = `${owner}\0${location.key}\0${location.pathname}${location.search}${location.hash}`;
  if (view.current.key !== viewKey) view.current = { key: viewKey, generation: view.current.generation + 1 };
  const deleted = items.filter(note => note.deleted);
  const canPurge = ready && !!owner && cacheOwner === owner && !busy && !restoring && !purging;
  const returnTo = location.pathname + location.search + location.hash;
  useEffect(() => {
    setSelection(null); setPurging(false); setPurgeError(''); setNotice(''); setRestoreError(''); setRestoring(null);
  }, [viewKey]);
  useEffect(() => () => { view.current.generation++; }, []);
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
  const selectTrash = (entries: TrashSelection['entries'], button: HTMLButtonElement) => {
    if (!canPurge || !owner) return;
    trigger.current = { button, owner, generation: view.current.generation };
    setNotice(''); setPurgeError(''); setSelection({ owner, entries: entries.map(({ key, title, revision }) => ({ key, title, revision })), completed: 0 });
  };
  const confirmPurge = async () => {
    if (!selection || purging) return;
    const generation = view.current.generation;
    if (purgeRun.current === generation) return;
    const current = () => view.current.generation === generation && useAuthStore.getState().user?.id === selection.owner;
    if (!current()) return;
    purgeRun.current = generation;
    setPurging(true); setPurgeError('');
    const failed: TrashSelection['entries'] = [];
    let completed = selection.completed;
    let failure = '';
    try {
      for (const entry of selection.entries) {
        if (!current()) return;
        try { await purgeDeleted(entry.key, selection.owner, entry.revision); completed++; }
        catch (cause) {
          failed.push(entry);
          failure ||= cause instanceof Error ? cause.message : '清理未完成，请重试。';
        }
        if (!current()) return;
      }
      if (failed.length) {
        setSelection({ ...selection, entries: failed, completed });
        setPurgeError(`已清理 ${completed} 份，${failed.length} 份未完成：${failure}`);
      } else {
        setSelection(null); setNotice(`已永久清理 ${completed} 份内容，原文件已保留。`);
      }
    } finally {
      if (purgeRun.current === generation) purgeRun.current = null;
      if (current()) setPurging(false);
    }
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
      {notice && <p role="status" className="text-sm text-muted-foreground">{notice}</p>}
      {ready && deleted.length > 0 && <Button variant="outline" className="w-fit" disabled={!canPurge}
        onClick={event => selectTrash(deleted, event.currentTarget)}>清空回收站</Button>}
      {ready && deleted.map(note => <div key={note.key} className="flex items-center justify-between gap-3 border-b py-3">
        <span className="min-w-0 break-words">{note.title}</span>
        <div className="flex shrink-0 gap-2">
        <Button variant="outline" disabled={busy || !!restoring || purging} onClick={async () => {
          if (!owner) return;
          const expectedOwner = owner;
          const generation = view.current.generation;
          const current = () => view.current.generation === generation && useAuthStore.getState().user?.id === expectedOwner;
          setRestoring(note.key); setRestoreError('');
          try {
            const restored = await changeDeleted(note.key, false);
            if (!current()) return;
            if (!restored || restored.deleted) throw new Error('恢复未完成，内容仍保留在回收站，请重试。');
          } catch (cause) {
            if (current()) setRestoreError(cause instanceof Error ? cause.message : '恢复失败，请重试。');
          } finally { if (current()) setRestoring(null); }
        }}>{restoring === note.key ? '恢复中…' : '恢复内容'}</Button>
        <Button variant="destructive" disabled={!canPurge} aria-label={`永久删除${note.title}`}
          onClick={event => selectTrash([note], event.currentTarget)}>永久删除</Button>
        </div>
      </div>)}
      {ready && !deleted.length && <p className="text-sm text-muted-foreground">回收站为空。</p>}
    </section>
    <AlertDialog open={!!selection} onOpenChange={open => { if (!open && !purging) setSelection(null); }}>
      <AlertDialogContent onCloseAutoFocus={event => {
        event.preventDefault();
        const origin = trigger.current;
        if (!origin || origin.owner !== useAuthStore.getState().user?.id || origin.generation !== view.current.generation) return;
        if (origin.button.isConnected && !origin.button.disabled) origin.button.focus();
        else heading.current?.focus({ preventScroll: true });
      }}>
        <AlertDialogHeader>
          <AlertDialogTitle>永久清理回收站内容？</AlertDialogTitle>
          <AlertDialogDescription>
            {selection?.entries.length === 1 ? `“${selection.entries[0].title}”` : `所选 ${selection?.entries.length || 0} 份内容`}的正文及已保存版本将永久删除，无法恢复。原始音视频、导入文件和已发布的飞书文档不受影响。
          </AlertDialogDescription>
        </AlertDialogHeader>
        {purgeError && <p role="alert" className="text-sm text-destructive">{purgeError}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={purging}>取消</AlertDialogCancel>
          <AlertDialogAction disabled={purging} className={buttonVariants({ variant: 'destructive' })}
            onClick={event => { event.preventDefault(); void confirmPurge(); }}>
            {purging ? '清理中…' : purgeError ? '重试清理' : '确认永久删除'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>;
}
