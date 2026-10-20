import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { NoteDetailTitle } from './NoteDetailTitle'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('makes the complete clipped title keyboard reachable without replacing the reading page', async () => {
  let measure!: () => void
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { measure = callback }
    observe() {}
    disconnect() {}
  })
  const title = 'Synthetic long title '.repeat(50)
  render(<NoteDetailTitle title={title} zh={false} />)
  const heading = screen.getByRole('heading', { level: 1 })
  Object.defineProperties(heading, { clientHeight: { value: 64 }, scrollHeight: { value: 640 } })
  act(() => measure())
  const trigger = screen.getByRole('button', { name: 'Read full title' })
  trigger.focus()
  fireEvent.click(trigger)
  const dialog = screen.getByRole('dialog', { name: 'Full title' })
  expect(dialog).toHaveTextContent(title.trim())
  fireEvent.keyDown(dialog, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByRole('heading', { level: 1 })).toBe(heading)
});
