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
import { resolveBackendOrigin } from '@/lib/runtimeConfig'

type Props = ComponentProps<typeof MarkdownContent> & { taskId?: string; title?: string; exportContent?: string }

export function ResultPreview({ taskId, title = '会议纪要', ...props }: Props) {
  const owner = useAuthStore(s => s.user?.id)
  return <PresentationPreview key={JSON.stringify([owner, taskId, props.exportContent ?? props.content, resolveBackendOrigin()])} taskId={taskId} title={title} {...props} />
}

function PresentationPreview({ taskId, title = '会议纪要', exportContent, ...props }: Props) {
  const [metadata, setMetadata] = useState<SummaryPresentation | null>(null)
  const [html, setHtml] = useState('')
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportStatus, setExportStatus] = useState('')
  const [visualState, setVisualState] = useState<{ body: string; visual: SummaryVisual } | null>(null)
  const [visualNotice, setVisualNotice] = useState('')
  const [readError, setReadError] = useState('')
  const [canReadAgain, setCanReadAgain] = useState(false)
  const [reading, setReading] = useState(false)
  const [readRevision, setReadRevision] = useState(0)
  const readClaim = useRef(false)
  const savedBody = exportContent ?? props.content
  const origin = resolveBackendOrigin()
  const visual = visualState?.body === savedBody ? visualState.visual : undefined
  const exportClaim = useRef(false)
  const captureExportScope = useSummaryExportScope([savedBody, title, taskId, origin])
  const captureReadScope = useSummaryExportScope([savedBody, taskId, origin])
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  useEffect(() => {
    let active = true
    const scoped = captureReadScope()
    const current = () => active && scoped() && resolveBackendOrigin() === origin
    setMetadata(null); setReadError(''); setCanReadAgain(false)
    setVisualState(null); setVisualNotice('')
    if (!taskId) return () => { active = false }
    readClaim.current = true; setReading(true)
    // Explicit recovery only re-reads these artifacts. It never submits or
    // resumes generation; missing historical metadata remains a silent 404.
    void (async () => {
      try {
        const metadata = await apiJson<SummaryPresentation>(`/api/task/${encodeURIComponent(taskId)}/summary-presentation`)
        if (!current()) return
        if (!metadata || metadata.protocol !== 1 || metadata.task_id !== taskId ||
          !Object.prototype.hasOwnProperty.call(depthLabels, metadata.content_depth) || !Object.prototype.hasOwnProperty.call(presentationLabels, metadata.presentation)) {
          setReadError('形式信息无法核验，正文仍可阅读。'); setCanReadAgain(true); return
        }
        setMetadata(metadata)
        if (metadata.presentation !== 'comic' && metadata.presentation !== 'infographic') return
        setVisualNotice('正在读取图形与正文依据…')
        try {
          const raw = await apiJson<unknown>(`/api/task/${encodeURIComponent(taskId)}/summary-visual`)
          if (!current()) return
          const value = await validateSummaryVisual(raw, taskId, metadata.presentation, savedBody)
          if (!current()) return
          if (value.ok) { setVisualState({ body: savedBody, visual: value.value }); setVisualNotice('') }
          else { setVisualNotice(value.reason); setCanReadAgain(true) }
        } catch (cause) {
          if (!current()) return
          const missing = cause instanceof ApiError && cause.status === 404
          setVisualNotice(missing ? '此版本尚无可核验图形，已保留正文。' : '图形读取失败，已保留正文。')
          setCanReadAgain(!missing)
        }
      } catch (cause) {
        if (current() && !(cause instanceof ApiError && cause.status === 404)) {
          setReadError('形式信息读取失败，正文仍可阅读。'); setCanReadAgain(true)
        }
      } finally {
        if (active) {
          readClaim.current = false; setReading(false)
          // A→B→A between React renders invalidates the request as well. Offer
          // a fresh explicit read instead of accepting the old account result.
          if (!current()) { setReadError('账号或来源已变化，请重新读取形式信息。'); setCanReadAgain(true) }
        }
      }
    })()
    return () => { active = false }
  }, [taskId, savedBody, origin, readRevision])
  useEffect(() => {
    let active = true
    const scoped = captureExportScope()
    const current = () => active && scoped() && resolveBackendOrigin() === origin
    setHtml('')
    if (metadata?.presentation === 'html') void buildSummaryHtml(props.content, title, taskId)
      .then(value => { if (current()) setHtml(value) })
      .catch(() => { if (current()) setError('HTML 预览准备失败，已保留 Markdown 正文。') })
    return () => { active = false }
  }, [metadata, props.content, title, taskId, origin])
  function reread() {
    if (readClaim.current) return
    readClaim.current = true
    setReadRevision(value => value + 1)
  }
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
    {readError && <p role="alert" className="px-6 text-sm text-destructive">{readError}</p>}
    {(canReadAgain || (reading && readRevision > 0)) && <div className="px-6 py-2">
      <Button type="button" variant="outline" size="sm" disabled={reading} onClick={reread}>{reading ? '正在重新读取…' : '重新读取形式与图形'}</Button>
    </div>}
    {exportStatus && <p role="status" className="px-6 text-sm text-muted-foreground">{exportStatus}</p>}
    {visualNotice && <p role="status" className="px-6 py-3 text-sm text-muted-foreground">{visualNotice}</p>}
    {visual && <SummaryVisualPanel key={JSON.stringify([visual.body_sha256, savedBody])} visual={visual} savedBody={savedBody} title={title} onVideoJump={props.onVideoJump} />}
    {metadata?.presentation === 'html' && html ? <iframe title="安全 HTML 纪要预览" sandbox="" referrerPolicy="no-referrer" srcDoc={html} className="min-h-[65vh] w-full border-0" /> : <MarkdownContent {...props} />}
  </>
}
