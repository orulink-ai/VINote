import type { SummaryVisual } from '@/lib/summaryVisual'
import { visualTimestamp } from '@/lib/summaryVisual'
import { diagramLayout, diagramTextLines, visualTextLines } from '@/lib/summaryVisualLayout'
import { DiagramGraphic, exportPalette } from './DiagramGraphic'

/** Standalone export made entirely of owned SVG elements and embedded JPEGs. */
export function SummaryVisualSvg({ visual, title, images }: { visual: SummaryVisual; title: string; images: Map<string, string> }) {
  const titleLines = visualTextLines(title, 78), top = 62 + titleLines.length * 28
  const margin = 32, columnWidth = 508
  const diagram = visual.diagram
  const nodes = diagram?.nodes.map(node => ({ id: node.id, label: node.grounded_label })) || []
  const edges = diagram?.edges.map(edge => ({ from: edge.from, to: edge.to, label: edge.grounded_label })) || []
  const layout = diagram ? diagramLayout(nodes, edges, diagram.kind === 'flow') : null
  // Keep the entire diagram viewport (including routed reference circles)
  // inside the standalone export instead of centering it beyond fixed bounds.
  const width = Math.max(1104, (layout?.width || 0) + margin * 2)
  const panels = visual.scenes.map((scene, index) => {
    const frame = visual.frames.find(frame => frame.id === scene.frame_id)!
    return { scene, frame, lines: visualTextLines(scene.grounded_label, 52), index }
  })
  const panelHeight = 330 + Math.max(0, ...panels.map(panel => panel.lines.length * 22))
  let legendY = top + (layout?.height || 0) + 16
  const legend = edges.map((edge, index) => {
    const lines = diagramTextLines(`${index + 1}. ${nodes.find(node => node.id === edge.from)!.label} → ${nodes.find(node => node.id === edge.to)!.label} · ${edge.label}`, width - margin * 2)
    const entry = { lines, y: legendY }; legendY += lines.length * 22 + 16
    return entry
  })
  const height = diagram ? legendY + margin : top + Math.ceil(panels.length / 2) * (panelHeight + 24) + margin
  return <svg xmlns="http://www.w3.org/2000/svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
    <title>{title}</title>
    <desc>{visual.presentation === 'comic' ? '画面分镜：原始录屏截图及已保存正文说明。' : '信息图：已保存正文中的对象和有据关系。'}{visual.body_sha256}</desc>
    <rect width="100%" height="100%" fill={exportPalette.background} />
    <g fontFamily="system-ui, sans-serif" fill={exportPalette.foreground}>
      <text x={margin} y="30" fontSize="13" fill={exportPalette.muted}>{visual.presentation === 'comic' ? '画面分镜 · 原始录屏画面' : '信息图 · 已保存正文'}</text>
      <text x={margin} y="64" fontSize="24" fontWeight="600">{titleLines.map((line, index) => <tspan key={index} x={margin} dy={index ? 28 : 0}>{line}</tspan>)}</text>
      {diagram ? <>
        <g transform={`translate(${(width - layout!.width) / 2},${top})`}><DiagramGraphic nodes={nodes} edges={edges} flow={diagram.kind === 'flow'} palette={exportPalette} /></g>
        {legend.map((entry, index) => <text key={index} x={margin} y={entry.y} fontSize="16" fontWeight="400">{entry.lines.map((line, lineIndex) => <tspan key={lineIndex} x={margin} dy={lineIndex ? 22 : 0}>{line}</tspan>)}</text>)}
      </> : panels.map(({ scene, frame, lines, index }) => {
        const x = margin + index % 2 * (columnWidth + 24), y = top + Math.floor(index / 2) * (panelHeight + 24)
        return <g key={scene.id}>
          <rect x={x} y={y} width={columnWidth} height={panelHeight} rx="12" fill={exportPalette.background} stroke={exportPalette.border} />
          <image href={images.get(frame.id)} x={x + 12} y={y + 12} width={columnWidth - 24} height="272" preserveAspectRatio="xMidYMid meet" />
          <text x={x + 16} y={y + 308} fontSize="13" fill={exportPalette.muted}>{String(index + 1).padStart(2, '0')} · {visualTimestamp(frame.timestamp_seconds)}</text>
          <text x={x + 16} y={y + 336} fontSize="16">{lines.map((line, lineIndex) => <tspan key={lineIndex} x={x + 16} dy={lineIndex ? 22 : 0}>{line}</tspan>)}</text>
        </g>
      })}
    </g>
  </svg>
}
