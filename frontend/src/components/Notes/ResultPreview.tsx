import { useEffect, useRef, useState, type ComponentProps } from 'react'
import { MarkdownContent } from '@/components/Markdown/MarkdownContent'
import { Button } from '@/components/ui/button'
import { apiJson, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { buildSummaryHtml, depthLabels, presentationLabels, type SummaryPresentation } from '@/lib/summaryPresentation'

type Props = ComponentProps<typeof MarkdownContent> & { taskId?: string; title?: string; exportContent?: string }

export function ResultPreview({ taskId, title = '会议纪要', ...props }: Props) {
  const owner = useAuthStore(s => s.user?.id)
  return <PresentationPreview key={JSON.stringify([owner, taskId])} taskId={taskId} title={title} {...props} />
}

function PresentationPreview({ taskId, title = '会议纪要', exportContent, ...props }: Props) {
  const [metadata, setMetadata] = useState<SummaryPresentation | null>(null)
  const [html, setHtml] = useState('')
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState(false)
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  useEffect(() => {
    let active = true
    if (taskId) void apiJson<SummaryPresentation>(`/api/task/${encodeURIComponent(taskId)}/summary-presentation`)
      .then(value => {
        if (active && value.protocol === 1 && value.task_id === taskId &&
          Object.prototype.hasOwnProperty.call(depthLabels, value.content_depth) && Object.prototype.hasOwnProperty.call(presentationLabels, value.presentation)) setMetadata(value)
      }).catch(cause => { if (active && !(cause instanceof ApiError && cause.status === 404)) setError('形式信息读取失败，正文仍可阅读。') })
    return () => { active = false }
  }, [taskId])
  useEffect(() => {
    let active = true
    setHtml('')
    if (metadata?.presentation === 'html') void buildSummaryHtml(props.content, title, taskId)
      .then(value => { if (active) setHtml(value) })
      .catch(() => { if (active) setError('HTML 预览准备失败，已保留 Markdown 正文。') })
    return () => { active = false }
  }, [metadata, props.content, title, taskId])
  async function download() {
    if (exporting) return
    setExporting(true)
    try {
      const savedBody = exportContent ?? props.content
      const output = savedBody === props.content && html ? html : await buildSummaryHtml(savedBody, title, taskId)
      if (!live.current) return
      const url = URL.createObjectURL(new Blob([output], { type: 'text/html;charset=utf-8' }))
      const a = document.createElement('a')
      a.href = url; a.download = title.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 120) + '.html'
      a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { if (live.current) setError('HTML 导出失败，请重试。') }
    finally { if (live.current) setExporting(false) }
  }
  return <>
    {metadata && <div className="flex flex-wrap items-center gap-3 px-6 pt-4">
      <p className="text-sm text-muted-foreground">{depthLabels[metadata.content_depth]} · {presentationLabels[metadata.presentation]}</p>
      <Button variant="outline" size="sm" disabled={exporting} onClick={() => void download()}>{exporting ? '正在准备导出…' : '导出 HTML'}</Button>
    </div>}
    {error && <p role="alert" className="px-6 text-sm text-destructive">{error}</p>}
    {metadata?.presentation === 'html' && html ? <iframe title="安全 HTML 纪要预览" sandbox="" referrerPolicy="no-referrer" srcDoc={html} className="min-h-[65vh] w-full border-0" /> : <MarkdownContent {...props} />}
  </>
}
