import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ArrowLeft, Check, FileText } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { readTextDraft, removeTextDraft, useProtectedDraft } from '@/hooks/useProtectedDraft'
import { PageHeading } from '@/components/Layout/PageHeading'
import { ErrorState } from '@/components/Feedback/ResourceState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Field, FieldLabel } from '@/components/ui/field'
import { resolvePageParent } from '@/lib/navigation'
import { formatMeetingTitle } from '@/lib/meetingTitle'

export function WriteNote() {
  const navigate = useNavigate()
  const location = useLocation()
  const parent = resolvePageParent(new URLSearchParams(location.search).get('returnTo') ?? location.state?.returnTo)
  const detailPath = (noteKey: string) => `/workspace/${encodeURIComponent(noteKey)}?${new URLSearchParams({ returnTo: parent })}`
  const recoveryPath = '/tasks?' + new URLSearchParams({ returnTo: parent }).toString()
  const owner = useAuthStore(s => s.user?.id)
  const [initial] = useState(() => {
    try { return owner ? readTextDraft(owner, 'write-note') : null } catch { return null }
  })
  const [key] = useState(() => typeof initial?.baseRevision === 'string' ? initial.baseRevision : `text-${crypto.randomUUID()}`)
  const [title, setTitle] = useState(initial?.title || '')
  const [content, setContent] = useState(initial?.content || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const operation = useWorkspaceStore(s => s.pending.find(item => item.key === key))
  const pending = !!operation && !operation.locallyQueued
  const savedNote = useWorkspaceStore(s => s.details[key])
  const ready = useWorkspaceStore(s => s.ready)
  const storeBusy = useWorkspaceStore(s => s.busy)
  const protection = useProtectedDraft('write-note', title, content, !savedNote && !!(title || content), key)
  useEffect(() => {
    if (!owner || !savedNote || pending || operation?.locallyQueued || saving) return
    setError('')
    try { removeTextDraft(owner, 'write-note') } catch { /* Do not overwrite the confirmed receipt. */ }
  }, [owner, savedNote, pending, operation?.locallyQueued, saving])
  const leave = () => {
    if (!owner || saving) return
    if (savedNote && !pending) { navigate(parent); return }
    try {
      localStorage.setItem(`vinote:draft:${owner}:write-note`, JSON.stringify({ title, content, baseRevision: key, updatedAt: new Date().toISOString() }))
      navigate(parent)
    } catch { setError('草稿未保存，请复制或导出正文后再离开。') }
  }
  const save = async () => {
    if (!owner || saving || pending || !content.trim()) return
    setSaving(true); setError('')
    try {
      const savedAt = new Date().toISOString()
      const saved = await useWorkspaceStore.getState().save(key, {
        base_revision: 0, operation_id: crypto.randomUUID(),
        title: title.trim() || formatMeetingTitle(savedAt, '待整理'), content, source_type: 'text', source_device: 'desktop',
        metadata: { source_created_at: savedAt },
      })
      if (!saved) { setError('保存请求尚未确认，草稿和原请求已保留。请到处理记录核验或重试，不会另建一份笔记。'); return }
      try { removeTextDraft(owner, 'write-note') } catch { /* Server receipt is authoritative. */ }
      navigate(detailPath(saved.key))
    } catch (cause) { setError(cause instanceof Error ? cause.message : '保存未完成，草稿已保留。') }
    finally { setSaving(false) }
  }
  return <div className="workspace-page max-w-4xl">
    <Button variant="ghost" className="self-start" disabled={saving} onClick={leave}><ArrowLeft data-icon="inline-start" />保存草稿并返回</Button>
    <PageHeading title="写笔记" description="直接写作或粘贴 Markdown，保存后继续编辑、导出或分享。" />
    <section aria-label="笔记编辑" className="flex flex-col gap-5 rounded-2xl border bg-card p-6">
      <Field><FieldLabel htmlFor="new-note-title">标题</FieldLabel><Input id="new-note-title" value={title} maxLength={120} disabled={saving || pending || !!savedNote} onChange={e => setTitle(e.target.value)} placeholder="给这份内容一个容易找回的名字" /></Field>
      <Field><FieldLabel htmlFor="new-note-content">正文</FieldLabel><Textarea id="new-note-content" value={content} maxLength={100000} disabled={saving || pending || !!savedNote} onChange={e => setContent(e.target.value)} className="min-h-72" placeholder="从一句想法开始，也可以粘贴已有文字…" /></Field>
      {error && <ErrorState error={error} />}
      <div className="flex flex-wrap items-center justify-between gap-3"><p role="status" className="text-xs text-muted-foreground">{savedNote && !pending ? '笔记已保存。后续修改从详情继续，保留历史版本。' : protection || '原始输入保存在当前账号的本机草稿中'}</p>
        {pending ? <Button variant="outline" onClick={() => navigate(recoveryPath)}>查看保存结果与重试</Button> : savedNote ? <Button onClick={() => navigate(detailPath(savedNote.key))}>打开已保存笔记</Button> : <Button disabled={saving || storeBusy || !ready || !content.trim()} aria-busy={saving} onClick={() => void save()}>{saving ? <FileText data-icon="inline-start" /> : <Check data-icon="inline-start" />}{saving ? '正在保存…' : storeBusy ? '正在保存，请稍候' : '保存笔记'}</Button>}
      </div>
    </section>
  </div>
}
