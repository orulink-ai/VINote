import { useState } from 'react';
import { Share2 } from 'lucide-react';
import { portableMarkdown } from '@/lib/workspace';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';

/** Sharing is an explicit user action; no account upload or public link is created. */
export function SavedContentShare({ title, content, disabled }: { title: string; content: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const text = `# ${title}\n\n${portableMarkdown(content)}`;
  const share = async () => {
    setBusy(true); setMessage('');
    try {
      await navigator.share({ title, text });
      setOpen(false);
    } catch (cause) {
      if (!(cause instanceof Error && cause.name === 'AbortError')) setMessage('分享未完成，正文保留；可复制后自行发送。');
    } finally { setBusy(false); }
  };
  const copy = async () => {
    setBusy(true); setMessage('');
    try { await navigator.clipboard.writeText(text); setMessage('正文已复制，可粘贴分享。'); }
    catch { setMessage('无法复制，请从下方选择正文后手动复制。'); }
    finally { setBusy(false); }
  };
  return <>
    <Button size="sm" variant="outline" disabled={disabled} onClick={() => { setMessage(''); setOpen(true); }}><Share2 />分享</Button>
    <Dialog open={open} onOpenChange={next => { if (!busy) setOpen(next); }}>
      <DialogContent closeLabel="关闭" className="sm:max-w-2xl">
        <DialogHeader><DialogTitle>分享正文</DialogTitle><DialogDescription>分享当前已保存正文，不包含原始音视频或文件。不会自动创建公开链接。</DialogDescription></DialogHeader>
        <Textarea aria-label="待分享正文" readOnly value={text} className="h-60 resize-none" />
        {message && <p role="status" className="text-sm">{message}</p>}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>取消</Button>
          <Button variant="outline" disabled={busy} onClick={() => void copy()}>复制正文</Button>
          {typeof navigator.share === 'function' && <Button disabled={busy} onClick={() => void share()}>{busy ? '分享中…' : '选择分享方式'}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}
