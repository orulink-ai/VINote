import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { SimpleFlowchart } from './SimpleFlowchart'

afterEach(cleanup)

it('renders actual SVG nodes and directed edges, with an accessible expand control', () => {
  const { container } = render(<SimpleFlowchart source={'flowchart TD\nA[来源] -->|确认| B[保存]'} />)
  expect(container.querySelectorAll('svg rect').length).toBeGreaterThanOrEqual(2)
  expect(container.querySelector('svg polyline')).toHaveAttribute('marker-end')
  expect(screen.getByRole('img', { name: /流程图/ })).toBeInTheDocument()
  const expand = screen.getByRole('button', { name: '展开查看' })
  expect(expand).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(expand)
  expect(screen.getByRole('button', { name: '收起流程图' })).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByText(/条件：确认/)).toBeInTheDocument()
})

it('renders malicious source only as text, retaining a safe fallback without SVG', () => {
  const source = 'flowchart TD\nA[<img src=x onerror=alert(1)>]\nclick A "javascript:alert(1)"'
  const { container } = render(<SimpleFlowchart source={source} />)
  expect(screen.getByRole('status')).toHaveTextContent('暂无法显示此流程图')
  expect(container.querySelector('svg')).toBeNull()
  expect(container.querySelector('img')).toBeNull()
  expect(container.querySelector('script')).toBeNull()
  expect(container.querySelector('code')).toHaveTextContent('onerror=alert(1)')
})
