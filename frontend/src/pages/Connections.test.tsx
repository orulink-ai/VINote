import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { Connections } from './Connections'
afterEach(cleanup)
function Destination() { const location = useLocation(); return <div>飞书设置{location.search}</div> }
it('opens only Feishu and preserves safe return context without exposing tools', () => {
  localStorage.setItem('vinote:owner:mcp-invocations:v1', 'retained-history')
  render(<MemoryRouter initialEntries={['/connections?returnTo=%2Fmeetings']}><Routes><Route path="/connections" element={<Connections />} /><Route path="/settings/feishu" element={<Destination />} /></Routes></MemoryRouter>)
  expect(screen.getByText('飞书设置?returnTo=%2Fmeetings')).toBeInTheDocument()
  expect(screen.queryByText(/MCP|内容处理插件/)).not.toBeInTheDocument()
  expect(localStorage.getItem('vinote:owner:mcp-invocations:v1')).toBe('retained-history')
})
