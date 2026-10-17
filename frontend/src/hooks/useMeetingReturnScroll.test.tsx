import { useRef, type ReactNode } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const context = vi.hoisted(() => ({
  owner: 'owner-a',
  workspace: { scope: 'personal', teamId: '' },
  location: { pathname: '/meetings', search: '?archived=1', hash: '#history', state: null as null | { returnTo: string } },
}))
vi.mock('react-router-dom', () => ({ useLocation: () => context.location }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: context.owner } }) }))
vi.mock('@/stores/teamStore', () => ({ useTeamStore: (select: (state: unknown) => unknown) => select({ currentWorkspace: context.workspace }) }))
import { useMeetingReturnScroll } from './useMeetingReturnScroll'

const source = '/meetings?archived=1#history'
let frames: Map<number, FrameRequestCallback>
let nextFrame: number
function Harness({ ready = true, showList = true, target = true, row = true, view = 'original-filter' }) {
  const pane = useRef<HTMLElement | null>(null)
  useMeetingReturnScroll(pane)
  return <main ref={pane} data-testid="pane">
    {showList && <section tabIndex={-1} data-testid="list" data-meeting-scroll-view={view} data-meeting-scroll-ready={ready}>
      {row && <div data-meeting-row-ids={JSON.stringify(['personal::note:related-3'])}>
        <details open><summary data-meeting-row-fallback>关联纪要</summary>
          {target && <button data-meeting-return-target="personal::note:related-3">第三条同名纪要</button>}
        </details>
      </div>}
    </section>}
  </main>
}
function geometry(top = 900) {
  const pane = screen.getByTestId('pane')
  Object.defineProperty(pane, 'scrollHeight', { configurable: true, value: 2400 })
  Object.defineProperty(pane, 'clientHeight', { configurable: true, value: 600 })
  Object.defineProperty(pane, 'offsetTop', { configurable: true, value: 0 })
  const target = screen.queryByRole('button', { name: '第三条同名纪要' })
  if (target) Object.defineProperty(target, 'offsetTop', { configurable: true, value: top })
  return pane
}
async function flushFrame() {
  await act(async () => { await Promise.resolve() }) // Let MutationObserver enqueue a frame.
  act(() => {
    const queued = [...frames.values()]
    frames.clear()
    queued.forEach(callback => callback(0))
  })
}
function enterDetail(rerender: (ui: ReactNode) => void) {
  geometry().scrollTop = 700
  fireEvent.click(screen.getByRole('button', { name: '第三条同名纪要' }))
  context.location = { pathname: '/workspace/actual-content-3', search: '', hash: '', state: { returnTo: source } }
  rerender(<Harness showList={false} />)
}
function returnToList(rerender: (ui: ReactNode) => void, props: Parameters<typeof Harness>[0] = {}) {
  context.location = { pathname: '/meetings', search: '?archived=1', hash: '#history', state: null }
  rerender(<Harness {...props} />)
  return geometry(1100)
}
beforeEach(() => {
  context.owner = 'owner-a'
  context.workspace = { scope: 'personal', teamId: '' }
  context.location = { pathname: '/meetings', search: '?archived=1', hash: '#history', state: null }
  frames = new Map(); nextFrame = 0
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.set(++nextFrame, callback); return nextFrame })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => { frames.delete(id) })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('waits through lazy loading and list reads, then restores the exact clicked object offset and focus once', async () => {
  const { rerender } = render(<Harness />)
  enterDetail(rerender)
  context.location = { pathname: '/meetings', search: '?archived=1', hash: '#history', state: null }
  rerender(<Harness showList={false} />)
  const pane = geometry()
  pane.scrollTop = 0
  await flushFrame()
  expect(pane.scrollTop).toBe(0)
  rerender(<Harness ready={false} />); geometry(1100)
  await flushFrame()
  expect(pane.scrollTop).toBe(0)
  rerender(<Harness />); geometry(1100)
  const target = screen.getByRole('button', { name: '第三条同名纪要' })
  const focus = vi.spyOn(target, 'focus')
  await flushFrame()
  expect(pane.scrollTop).toBe(900) // Captured 200px offset, not old absolute 700px.
  expect(target).toHaveFocus()
  expect(focus).toHaveBeenCalledTimes(1)
  expect(focus).toHaveBeenCalledWith({ preventScroll: true })
  pane.scrollTop = 100
  rerender(<Harness ready={false} />)
  rerender(<Harness />); geometry(1400)
  await flushFrame()
  expect(pane.scrollTop).toBe(100)
  expect(focus).toHaveBeenCalledTimes(1)
})

it.each(['wheel', 'touchstart', 'pointerdown', 'keydown', 'input'])('cancels pending restoration on %s instead of pulling the user back', async (event) => {
  const { rerender } = render(<Harness />)
  enterDetail(rerender)
  const pane = returnToList(rerender, { ready: false })
  pane.scrollTop = 40
  fireEvent(window, new Event(event, { bubbles: true }))
  rerender(<Harness />); geometry(1100)
  await flushFrame()
  expect(pane.scrollTop).toBe(40)
  expect(screen.getByRole('button', { name: '第三条同名纪要' })).not.toHaveFocus()
})

it.each(['owner', 'workspace', 'route', 'filter'])('does not reuse a captured position across a changed %s', async (change) => {
  const { rerender } = render(<Harness />)
  enterDetail(rerender)
  if (change === 'owner') context.owner = 'owner-b'
  if (change === 'workspace') context.workspace = { scope: 'team', teamId: 'team-b' }
  const pane = returnToList(rerender, { view: change === 'filter' ? 'another-filter' : 'original-filter' })
  if (change === 'route') {
    context.location = { pathname: '/meetings', search: '?archived=0', hash: '', state: null }
    rerender(<Harness />)
  }
  pane.scrollTop = 50
  await flushFrame()
  expect(pane.scrollTop).toBe(50)
})

it.each([true, false])('uses saved scroll and a safe fallback when the original content disappeared (row exists: %s)', async (row) => {
  const { rerender } = render(<Harness />)
  enterDetail(rerender)
  const pane = returnToList(rerender, { target: false, row })
  pane.scrollTop = 0
  await flushFrame()
  expect(pane.scrollTop).toBe(700)
  expect(row ? screen.getByText('关联纪要') : screen.getByTestId('list')).toHaveFocus()
})

it('does not restore on a direct visit or when detail returnTo does not match the captured source', async () => {
  const { rerender } = render(<Harness />)
  geometry().scrollTop = 55
  await flushFrame()
  expect(geometry().scrollTop).toBe(55)
  fireEvent.click(screen.getByRole('button', { name: '第三条同名纪要' }))
  context.location = { pathname: '/note/other', search: '', hash: '', state: { returnTo: '/notes' } }
  rerender(<Harness showList={false} />)
  const pane = returnToList(rerender)
  pane.scrollTop = 10
  await flushFrame()
  expect(pane.scrollTop).toBe(10)
})

it('drops a pending read on navigation away and does not revive it on a later direct visit', async () => {
  const { rerender } = render(<Harness />)
  enterDetail(rerender)
  returnToList(rerender, { ready: false })
  context.location = { pathname: '/files', search: '', hash: '', state: null }
  rerender(<Harness showList={false} />)
  const pane = returnToList(rerender)
  pane.scrollTop = 30
  await flushFrame()
  expect(pane.scrollTop).toBe(30)
  expect(screen.getByRole('button', { name: '第三条同名纪要' })).not.toHaveFocus()
})
