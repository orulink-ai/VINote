import { useEffect, useRef, useState, type ComponentProps } from 'react'
import { MarkdownContent } from '@/components/Markdown/MarkdownContent'
import { Button } from '@/components/ui/button'
import { apiJson, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { buildSummaryHtml, depthLabels, presentationLabels, type SummaryPresentation } from '@/lib/summaryPresentation'
import { validateSummaryVisual, type SummaryVisual } from '@/lib/summaryVisual'
import { SummaryVisualPanel } from './visual/SummaryVisualPanel'
import { downloadRecording } from '@/lib/recordingDownload'
import { useSummaryExportScope } from '@/lib/useSummaryExportScope'

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
  const [exportStatus, setExportStatus] = useState('')
  const [visualState, setVisualState] = useState<{ body: string; visual: SummaryVisual } | null>(null)
  const [visualNotice, setVisualNotice] = useState('')
  const savedBody = exportContent ?? props.content
  const visual = visualState?.body === savedBody ? visualState.visual : undefined
  const exportClaim = useRef(false)
  const captureExportScope = useSummaryExportScope([savedBody, title, taskId])
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
    setVisualState(null); setVisualNotice('')
    if (!taskId || !metadata || (metadata.presentation !== 'comic' && metadata.presentation !== 'infographic')) return
    const presentation = metadata.presentation
    setVisualNotice('正在读取图形与正文依据…')
    void apiJson<unknown>(`/api/task/${encodeURIComponent(taskId)}/summary-visual`)
      .then(value => validateSummaryVisual(value, taskId, presentation, savedBody))
      .then(value => {
        if (!active) return
        if (value.ok) { setVisualState({ body: savedBody, visual: value.value }); setVisualNotice('') }
        else setVisualNotice(value.reason)
      }).catch(cause => {
        if (active) setVisualNotice(cause instanceof ApiError && cause.status === 404 ? '此版本尚无可核验图形，已保留正文。' : '图形读取失败，已保留正文。')
      })
    return () => { active = false }
  }, [taskId, metadata, savedBody])
  useEffect(() => {
    let active = true
    setHtml('')
    if (metadata?.presentation === 'html') void buildSummaryHtml(props.content, title, taskId)
      .then(value => { if (active) setHtml(value) })
      .catch(() => { if (active) setError('HTML 预览准备失败，已保留 Markdown 正文。') })
    return () => { active = false }
  }, [metadata, props.content, title, taskId])
  async function download() {
    if (exportClaim.current) return
    exportClaim.current = true; setExporting(true); setExportStatus('')
    const current = captureExportScope()
    try {
      const filename = title.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 120) + '.html'
      if (!current()) return
      const result = await downloadRecording(async () => {
        if (!current()) throw new Error('纪要或账号已变化')
        const output = savedBody === props.content && html ? html : await buildSummaryHtml(savedBody, title, taskId, undefined, visual)
        if (!current()) throw new Error('纪要或账号已变化')
        return new Blob([output], { type: 'text/html;charset=utf-8' })
      }, title, filename, current)
      if (current()) setExportStatus(result === 'saved' ? 'HTML 纪要已保存到所选位置。' : result === 'cancelled' ? '已取消 HTML 导出。' : 'HTML 纪要已交给浏览器下载，请在下载列表查看。')
    } catch { if (current()) setError('HTML 导出失败，请重试。') }
    finally { exportClaim.current = false; if (live.current) setExporting(false) }
  }
  return <>
    {metadata && <div className="flex flex-wrap items-center gap-3 px-6 pt-4">
      <p className="text-sm text-muted-foreground">{depthLabels[metadata.content_depth]} · {presentationLabels[metadata.presentation]}</p>
      <Button variant="outline" size="sm" disabled={exporting} onClick={() => void download()}>{exporting ? '正在准备导出…' : '导出 HTML'}</Button>
    </div>}
    {error && <p role="alert" className="px-6 text-sm text-destructive">{error}</p>}
    {exportStatus && <p role="status" className="px-6 text-sm text-muted-foreground">{exportStatus}</p>}
    {visualNotice && <p role="status" className="px-6 py-3 text-sm text-muted-foreground">{visualNotice}</p>}
    {visual && <SummaryVisualPanel key={JSON.stringify([visual.body_sha256, savedBody])} visual={visual} savedBody={savedBody} title={title} onVideoJump={props.onVideoJump} />}
    {metadata?.presentation === 'html' && html ? <iframe title="安全 HTML 纪要预览" sandbox="" referrerPolicy="no-referrer" srcDoc={html} className="min-h-[65vh] w-full border-0" /> : <MarkdownContent {...props} />}
  </>
}
