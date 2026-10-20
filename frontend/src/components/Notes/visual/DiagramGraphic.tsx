import { useId } from 'react'
import { diagramLayout, type DiagramItem, type DiagramLink } from '@/lib/summaryVisualLayout'

export type VisualPalette = { background: string; foreground: string; muted: string; border: string; accent: string }
export const exportPalette: VisualPalette = { background: '#ffffff', foreground: '#18181b', muted: '#52525b', border: '#d4d4d8', accent: '#f4f4f5' }
const screenPalette: VisualPalette = { background: 'hsl(var(--background))', foreground: 'hsl(var(--foreground))', muted: 'hsl(var(--muted-foreground))', border: 'hsl(var(--border))', accent: 'hsl(var(--muted))' }

/** Only typed text and renderer-owned geometry become SVG elements. */
export function DiagramGraphic({ nodes, edges, flow, palette = screenPalette }: {
  nodes: DiagramItem[]; edges: DiagramLink[]; flow: boolean; palette?: VisualPalette
}) {
  const id = `visual-${useId().replace(/[^A-Za-z0-9_-]/g, '')}`
  const layout = diagramLayout(nodes, edges, flow)
  return <svg xmlns="http://www.w3.org/2000/svg" width={layout.width} height={layout.height} viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-labelledby={`${id}-title ${id}-desc`} style={{ display: 'block', maxWidth: '100%', height: 'auto' }}>
    <title id={`${id}-title`}>{flow ? '流程与关系' : '内容图解'}</title>
    <desc id={`${id}-desc`}>{nodes.map(node => node.label).join('；')}。{edges.map((edge, index) => `${index + 1}：${nodes.find(node => node.id === edge.from)?.label} → ${nodes.find(node => node.id === edge.to)?.label}，${edge.label}`).join('；')}</desc>
    <rect width="100%" height="100%" fill={palette.background} />
    <defs><marker id={`${id}-arrow`} markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 10 5 L 0 10 z" fill={palette.foreground} /></marker></defs>
    {layout.edges.map((edge, index) => <g key={index}>
      <path d={edge.path} stroke={palette.foreground} strokeWidth="1.5" fill="none" markerEnd={`url(#${id}-arrow)`} />
      <circle cx={edge.labelX} cy={edge.labelY} r="13" fill={palette.background} stroke={palette.border} />
      <text x={edge.labelX} y={edge.labelY + 4} textAnchor="middle" fontFamily="system-ui, sans-serif" fontSize="12" fill={palette.foreground}>{edge.number}</text>
    </g>)}
    {layout.nodes.map((node, index) => <g key={node.id}>
      <rect x={node.x} y={node.y} width={node.width} height={node.height} rx="12" fill={palette.accent} stroke={palette.border} />
      <text x={node.x + 18} y={node.y + 25} fontFamily="system-ui, sans-serif" fontSize="12" fill={palette.muted}>{String(index + 1).padStart(2, '0')}</text>
      <text x={node.x + 18} y={node.y + 54} fontFamily="system-ui, sans-serif" fontSize="16" fill={palette.foreground}>{node.lines.map((line, lineIndex) => <tspan key={lineIndex} x={node.x + 18} dy={lineIndex ? 22 : 0}>{line}</tspan>)}</text>
    </g>)}
  </svg>
}
