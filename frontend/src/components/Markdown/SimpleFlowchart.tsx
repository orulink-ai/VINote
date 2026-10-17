import { useId, useMemo, useState } from 'react'
import { flowLabelLines, parseSimpleFlowchart } from '@/lib/simpleFlowchart'

/** SVG elements are constructed only from our bounded AST, never model SVG. */
export function SimpleFlowchart({ source }: { source: string }) {
  const result = useMemo(() => parseSimpleFlowchart(source), [source])
  const [expanded, setExpanded] = useState(false)
  const id = useId().replace(/:/g, ''), arrow = `${id}-arrow`
  return <section className="my-4 min-w-0 rounded-xl border bg-background p-3" aria-label="流程图">
    {result.ok ? <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-muted-foreground">{result.graph.nodes.length} 个节点 · {result.graph.edges.length} 条有向关系</span>
        <button type="button" className="min-h-11 rounded-md border px-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring" aria-expanded={expanded} aria-controls={`${id}-viewport`} onClick={() => setExpanded(value => !value)}>{expanded ? '收起流程图' : '展开查看'}</button>
      </div>
      <div id={`${id}-viewport`} tabIndex={0} aria-label="流程图，可使用方向键滚动" className="overflow-auto rounded-lg border focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring" style={{ maxHeight: expanded ? '70vh' : 340 }}>
        <svg width={result.graph.width} height={result.graph.height} role="img" aria-labelledby={`${id}-title ${id}-desc`} style={{ display: 'block', maxWidth: 'none', color: 'hsl(var(--foreground))' }}>
          <title id={`${id}-title`}>流程图</title>
          <desc id={`${id}-desc`}>图中包含{result.graph.nodes.length}个节点及{result.graph.edges.length}条有向关系。完整文字替代在图后的“步骤与关系”中。</desc>
          <defs><marker id={arrow} markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" /></marker></defs>
          {result.graph.edges.map((edge, index) => <g key={index}>
            <polyline points={edge.points.map(point => `${point.x},${point.y}`).join(' ')} fill="none" stroke="currentColor" strokeWidth="2" markerEnd={`url(#${arrow})`} />
            {!!edge.label && <g><rect x={edge.labelAt.x - 102} y={edge.labelAt.y - 30} width="204" height="64" rx="4" fill="hsl(var(--background))" />
              <text x={edge.labelAt.x} y={edge.labelAt.y - 10} fontSize="13" textAnchor="middle" fill="currentColor">{flowLabelLines(edge.label).map((line, i) => <tspan key={i} x={edge.labelAt.x} dy={i ? 16 : 0}>{line}</tspan>)}</text></g>}
          </g>)}
          {result.graph.nodes.map(node => {
            const lines = flowLabelLines(node.label)
            return <g key={node.id}>
              <rect x={node.x} y={node.y} width={node.width} height={node.height} rx={node.shape === 'round' ? 28 : 10} fill="hsl(var(--background))" stroke="currentColor" strokeWidth="2" strokeDasharray={node.shape === 'decision' ? '5 3' : undefined} />
              {node.shape === 'decision' && <text x={node.x + 12} y={node.y + 18} fill="currentColor" fontSize="11">判断</text>}
              <text x={node.x + node.width / 2} y={node.y + node.height / 2 - (lines.length - 1) * 9 + 5} textAnchor="middle" fontSize="14" fill="currentColor">{lines.map((line, index) => <tspan key={index} x={node.x + node.width / 2} dy={index ? 18 : 0}>{line}</tspan>)}</text>
            </g>
          })}
        </svg>
      </div>
      <details className="mt-3 text-sm"><summary className="cursor-pointer rounded py-2 focus-visible:outline focus-visible:outline-ring">步骤与关系（文字替代）</summary>
        <ul className="list-disc space-y-1 pl-5">{result.graph.nodes.map(node => <li key={node.id}>{node.id}：{node.label}{node.shape === 'decision' ? '（判断）' : ''}</li>)}</ul>
        <ul className="mt-2 list-disc space-y-1 pl-5">{result.graph.edges.map((edge, index) => <li key={index}>{result.graph.nodes.find(node => node.id === edge.from)!.label} → {result.graph.nodes.find(node => node.id === edge.to)!.label}{edge.label ? `；条件：${edge.label}` : ''}</li>)}</ul>
      </details>
    </> : <p role="status" className="text-sm text-muted-foreground">暂无法显示此流程图：{result.reason}。源码与已有正文保留，不需要重新生成。</p>}
    <details className="mt-2 text-sm"><summary className="cursor-pointer rounded py-2 focus-visible:outline focus-visible:outline-ring">查看源码</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-3"><code>{source}</code></pre></details>
  </section>
}
