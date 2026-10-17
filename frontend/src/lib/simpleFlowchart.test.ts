import { describe, expect, it } from 'vitest'
import { parseSimpleFlowchart } from './simpleFlowchart'

describe('bounded flowchart data parser', () => {
  it('lays out a real branching and merging directed graph with edge labels', () => {
    const result = parseSimpleFlowchart('flowchart TD\nA[开始] --> B{检查}\nB -->|通过| C[保存]\nB -- 失败 --> D[重试]\nC --> E[结束]\nD --> E')
    expect(result.ok).toBe(true)
    if (!result.ok) throw new Error(result.reason)
    expect(result.graph.nodes).toHaveLength(5)
    expect(result.graph.edges).toHaveLength(5)
    expect(result.graph.edges.map(edge => edge.label)).toContain('通过')
    expect(result.graph.nodes.find(node => node.id === 'E')!.y).toBeGreaterThan(result.graph.nodes.find(node => node.id === 'C')!.y)
    expect(result.graph.edges.every(edge => edge.points.length >= 2)).toBe(true)
  })

  it('supports horizontal chains and quoted text without evaluation', () => {
    const result = parseSimpleFlowchart('flowchart LR;A["读取原文"] --> B("保存原版本") --> C[完成]')
    expect(result.ok).toBe(true)
    if (result.ok) expect(result.graph.nodes[2].x).toBeGreaterThan(result.graph.nodes[1].x)
  })

  it('routes skipped ranks outside intermediate nodes', () => {
    const result = parseSimpleFlowchart('graph TD\nA --> B --> C\nA --> C')
    expect(result.ok).toBe(true)
    if (result.ok) expect(result.graph.edges[2].points).toHaveLength(6)
  })

  it.each([
    'flowchart TD\nA[<img src=x onerror=alert(1)>]',
    'flowchart TD\nA --> B\nclick A "https://evil.example"',
    '%%{init: {securityLevel: loose}}%%\nflowchart TD\nA --> B',
    'flowchart TD\nA["\\u003cscript\\u003e"]',
    'flowchart TD\nA[https://evil.example/image.svg]',
    'flowchart TD\nA --> B\nstyle A fill:red',
    'flowchart TD\nA --> B\nsubgraph group\nB --> C\nend',
    'sequenceDiagram\nAlice->>Bob: message',
    'flowchart TD\nA --> B\nB --> A',
    'flowchart TD\nA --> A',
    'flowchart TD\nA[x]\nA[different]',
    'flowchart TD\nA --> B trailing words',
    'flowchart TD\nA[[nested unsupported]]',
    'flowchart TD\nA["unterminated]',
  ])('rejects unsafe/unsupported syntax as a whole: %s', source => {
    expect(parseSimpleFlowchart(source).ok).toBe(false)
  })

  it('rejects node and edge limits without silently truncating', () => {
    expect(parseSimpleFlowchart('flowchart TD\n' + Array.from({ length: 21 }, (_, i) => `N${i}[step]`).join('\n')).ok).toBe(false)
    expect(parseSimpleFlowchart('flowchart TD\n' + Array.from({ length: 41 }, () => 'A --> B').join('\n')).ok).toBe(false)
    expect(parseSimpleFlowchart('flowchart TD\nA[' + 'x'.repeat(61) + ']').ok).toBe(false)
    expect(parseSimpleFlowchart('x'.repeat(12001)).ok).toBe(false)
  })
})
