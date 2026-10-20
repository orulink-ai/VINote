import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { resolveContentUrl } from '@/lib/videoLinks'
import { downloadRecording } from '@/lib/recordingDownload'
import { buildSummaryVisualPng, buildSummaryVisualSvg } from '@/lib/summaryVisualExport'
import { visualFramePath, visualTimestamp, type SummaryVisual } from '@/lib/summaryVisual'
import { useAuthStore } from '@/stores/authStore'
import { useSummaryExportScope } from '@/lib/useSummaryExportScope'
import { diagramLayout } from '@/lib/summaryVisualLayout'
import { DiagramGraphic } from './DiagramGraphic'

function BodyReferences({ visual, ids }: { visual: SummaryVisual; ids: string[] }) {
  return <details className="mt-3 min-w-0 text-sm">
    <summary className="cursor-pointer rounded py-2 text-muted-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">查看对应原文</summary>
    <div className="flex flex-col gap-3 pt-2">{ids.map(id => <p key={id} className="whitespace-pre-wrap [overflow-wrap:anywhere]">{visual.blocks.find(block => block.id === id)!.text}</p>)}</div>
  </details>
}

function SourceFrame({ visual, frameId }: { visual: SummaryVisual; frameId: string }) {
  const [failed, setFailed] = useState(false), [attempt, setAttempt] = useState(0)
  const frame = visual.frames.find(frame => frame.id === frameId)!
  return <div className="min-w-0">
    {failed ? <div className="flex min-h-40 flex-col items-start justify-center gap-3 bg-muted p-4">
      <p role="status" className="text-sm text-muted-foreground">此处原始画面暂不可用，说明和正文保留。</p>
      <Button variant="outline" size="sm" onClick={() => { setFailed(false); setAttempt(value => value + 1) }}>重新读取画面</Button>
    </div> : <img key={attempt} src={resolveContentUrl(visualFramePath(visual.task_id, frame.screenshot_index))} alt={frame.grounded_label} className="aspect-video w-full object-contain bg-muted" loading="lazy" onError={() => setFailed(true)} />}
  </div>
}

/** A verified sidecar adds a reading surface; saved body and originals stay intact. */
export function SummaryVisualPanel({ visual, savedBody, title, onVideoJump }: {
  visual: SummaryVisual; savedBody: string; title: string; onVideoJump?: (seconds: number) => void
}) {
  const owner = useAuthStore(state => state.user?.id)
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('')
  const claim = useRef(false), alive = useRef(true)
  const captureExportScope = useSummaryExportScope([visual, savedBody, title, owner])
  const id = useId(), diagram = visual.diagram
  const graph = diagram && diagramLayout(diagram.nodes.map(node => ({ id: node.id, label: node.grounded_label })), diagram.edges.map(edge => ({ from: edge.from, to: edge.to, label: edge.grounded_label })), diagram.kind === 'flow')
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  async function download(format: 'svg' | 'png') {
    if (claim.current) return
    claim.current = true; setBusy(true); setMessage(''); setError('')
    const current = captureExportScope()
    try {
      const filename = `${title.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 120) || '会议图形'}.${format}`
      if (!current()) return
      const result = await downloadRecording(async () => {
        if (!current()) throw new Error('纪要或账号已变化')
        const blob = format === 'png' ? await buildSummaryVisualPng(visual, savedBody, title) : new Blob([await buildSummaryVisualSvg(visual, savedBody, title)], { type: 'image/svg+xml;charset=utf-8' })
        if (!current()) throw new Error('纪要或账号已变化')
        return blob
      }, title, filename, current)
      if (current()) setMessage(result === 'saved' ? '图形已保存到所选位置。' : result === 'cancelled' ? '已取消图形导出。' : '图形已交给浏览器下载，请在下载列表查看。')
    } catch (cause) { if (current()) setError(cause instanceof Error ? cause.message : '图形导出失败，请重试。') }
    finally { claim.current = false; if (alive.current) setBusy(false) }
  }
  return <section aria-labelledby={`${id}-title`} className="mx-3 my-4 min-w-0 rounded-xl border bg-background p-3 sm:mx-6 sm:p-5">
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 id={`${id}-title`} className="font-medium">{visual.presentation === 'comic' ? '画面分镜' : '信息图'}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{visual.presentation === 'comic' ? '原始录屏画面与模型说明，依据当前已保存正文。' : '依据当前已保存正文绘制；对象和关系可逐项查看原文。'}</p>
      </div>
      <div className="flex flex-wrap gap-2" aria-busy={busy}>
        <Button variant="outline" size="sm" disabled={busy} onClick={() => void download('svg')}>导出 SVG</Button>
        <Button variant="outline" size="sm" disabled={busy} onClick={() => void download('png')}>导出 PNG</Button>
      </div>
    </div>
    {busy && <p role="status" className="mb-3 text-sm text-muted-foreground">正在准备图形导出…</p>}
    {message && <p role="status" className="mb-3 text-sm text-muted-foreground">{message}</p>}
    {error && <p role="alert" className="mb-3 text-sm text-destructive">{error}</p>}
    {visual.presentation === 'comic' ? <ol className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
      {visual.scenes.map((scene, index) => {
        const frame = visual.frames.find(frame => frame.id === scene.frame_id)!
        return <li key={scene.id} className="min-w-0 overflow-hidden rounded-lg border">
          <figure>
            <SourceFrame key={frame.id} visual={visual} frameId={frame.id} />
            <figcaption className="p-4">
              <div className="mb-2 flex items-center gap-3 text-sm text-muted-foreground">
                <span>{String(index + 1).padStart(2, '0')}</span>
                {onVideoJump ? <Button variant="link" size="sm" onClick={() => onVideoJump(frame.timestamp_seconds)} aria-label={`播放 ${visualTimestamp(frame.timestamp_seconds)} 的原录屏`}>{visualTimestamp(frame.timestamp_seconds)}</Button> : <span>{visualTimestamp(frame.timestamp_seconds)}</span>}
              </div>
              <p className="leading-relaxed [overflow-wrap:anywhere]">{scene.grounded_label}</p>
              <BodyReferences visual={visual} ids={scene.block_ids} />
            </figcaption>
          </figure>
        </li>
      })}
    </ol> : diagram && <>
      <div tabIndex={0} role="region" aria-label="信息图，可横向滚动查看" className="overflow-x-auto rounded-lg border focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
        <div className="flex justify-center" style={{ minWidth: graph && graph.width > 640 ? 640 : undefined }}><DiagramGraphic nodes={diagram.nodes.map(node => ({ id: node.id, label: node.grounded_label }))} edges={diagram.edges.map(edge => ({ from: edge.from, to: edge.to, label: edge.grounded_label }))} flow={diagram.kind === 'flow'} /></div>
      </div>
      <ol className="mt-4 grid min-w-0 gap-3 sm:grid-cols-2">{diagram.nodes.map((node, index) => <li key={node.id} className="min-w-0 rounded-lg border p-3">
        <p className="text-sm [overflow-wrap:anywhere]">{String(index + 1).padStart(2, '0')} · {node.grounded_label}</p>
        <BodyReferences visual={visual} ids={node.block_ids} />
      </li>)}</ol>
      {!!diagram.edges.length && <ol className="mt-4 flex min-w-0 flex-col gap-3" aria-label="图中关系与原文依据">{diagram.edges.map((edge, index) => <li key={edge.id} className="min-w-0 border-t pt-3 text-sm">
        <p className="[overflow-wrap:anywhere]">{index + 1} · {diagram.nodes.find(node => node.id === edge.from)!.grounded_label} → {diagram.nodes.find(node => node.id === edge.to)!.grounded_label}</p>
        <p className="mt-1 [overflow-wrap:anywhere]">{edge.grounded_label}</p>
        <BodyReferences visual={visual} ids={edge.block_ids} />
      </li>)}</ol>}
    </>}
  </section>
}
