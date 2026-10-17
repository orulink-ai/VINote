import { useLayoutEffect, useRef, type RefObject } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useTeamStore } from '@/stores/teamStore'

type ReturnPosition = {
  scope: string
  route: string
  view: string
  target: string
  rowIds: string[]
  top: number
  offset: number
  enteredDetail: boolean
}

function identities(value: string | undefined): string[] {
  try {
    const parsed: unknown = JSON.parse(value || '[]')
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : []
  } catch { return [] }
}

// Layout coordinates deliberately exclude FadeUp's temporary transform.
function layoutTop(element: HTMLElement): number {
  let top = 0
  let current: HTMLElement | null = element
  while (current) {
    top += current.offsetTop
    current = current.offsetParent instanceof HTMLElement ? current.offsetParent : null
  }
  return top
}

/** Only a related-minutes click -> content detail -> same meetings view. */
export function useMeetingReturnScroll(paneRef: RefObject<HTMLElement | null>) {
  const location = useLocation()
  const owner = useAuthStore(state => state.user?.id)
  const workspace = useTeamStore(state => state.currentWorkspace)
  const scope = JSON.stringify([owner, workspace.scope, workspace.scope === 'team' ? workspace.teamId : null])
  const route = location.pathname + location.search + location.hash
  const position = useRef<ReturnPosition | null>(null)
  const contextualReturn = (location.state as { returnTo?: unknown } | null)?.returnTo

  useLayoutEffect(() => {
    const pane = paneRef.current
    if (!pane) return
    if (!owner || position.current?.scope !== scope) position.current = null
    if (location.pathname.startsWith('/note/') || location.pathname.startsWith('/workspace/')) {
      const saved = position.current
      if (saved && contextualReturn === saved.route) saved.enteredDetail = true
      else position.current = null
      return
    }
    if (location.pathname !== '/meetings') {
      position.current = null
      return
    }

    let pending = position.current?.enteredDetail && position.current.route === route ? position.current : null
    // A different route/query is not a return to the captured list.
    position.current = null
    let frame: number | undefined
    let observer: MutationObserver | undefined
    let resize: ResizeObserver | undefined
    const stop = () => {
      pending = null
      if (frame !== undefined) cancelAnimationFrame(frame)
      frame = undefined
      observer?.disconnect()
      resize?.disconnect()
    }
    const restore = () => {
      frame = undefined
      if (!pending) return
      const list = pane.querySelector<HTMLElement>('[data-meeting-scroll-view]')
      if (!list || list.dataset.meetingScrollReady !== 'true') return
      const saved = pending
      if (list.dataset.meetingScrollView !== saved.view) { stop(); return }
      const target = Array.from(list.querySelectorAll<HTMLElement>('[data-meeting-return-target]'))
        .find(node => node.dataset.meetingReturnTarget === saved.target)
      // Expand state must be restored before measuring/focusing a related button.
      if (target && target.closest('details')?.open === false) return
      const row = Array.from(list.querySelectorAll<HTMLElement>('[data-meeting-row-ids]'))
        .find(node => identities(node.dataset.meetingRowIds).some(id => saved.rowIds.includes(id)))
      const focus = target || row?.querySelector<HTMLElement>('[data-meeting-row-fallback]') || list
      const desired = target ? layoutTop(target) - layoutTop(pane) - saved.offset : saved.top
      stop() // Consume before focus/scroll or any subsequent refresh/layout change.
      const behavior = pane.style.scrollBehavior
      pane.style.scrollBehavior = 'auto'
      pane.scrollTop = Math.max(0, Math.min(desired, Math.max(0, pane.scrollHeight - pane.clientHeight)))
      focus.focus({ preventScroll: true })
      pane.style.scrollBehavior = behavior
    }
    const schedule = () => {
      if (pending && frame === undefined) frame = requestAnimationFrame(restore)
    }
    if (pending) {
      observer = new MutationObserver(schedule)
      observer.observe(pane, { subtree: true, childList: true, attributes: true })
      if (typeof ResizeObserver !== 'undefined') {
        resize = new ResizeObserver(schedule)
        resize.observe(pane)
      }
      schedule()
    }
    const capture = (event: MouseEvent) => {
      if (!owner || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
      const target = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-meeting-return-target]') : null
      const list = target?.closest<HTMLElement>('[data-meeting-scroll-view]')
      if (!target || !list || !pane.contains(target)) return
      position.current = {
        scope, route, view: list.dataset.meetingScrollView || '',
        target: target.dataset.meetingReturnTarget || '',
        rowIds: identities(target.closest<HTMLElement>('[data-meeting-row-ids]')?.dataset.meetingRowIds),
        top: pane.scrollTop,
        offset: layoutTop(target) - layoutTop(pane) - pane.scrollTop,
        enteredDetail: false,
      }
    }
    // Never pull the user back after they start interacting while data is loading.
    const cancel = () => { stop(); position.current = null }
    const inputEvents = ['wheel', 'touchstart', 'pointerdown', 'keydown', 'input'] as const
    inputEvents.forEach(name => window.addEventListener(name, cancel, { capture: true, passive: true }))
    pane.addEventListener('click', capture, true)
    return () => {
      stop()
      inputEvents.forEach(name => window.removeEventListener(name, cancel, true))
      pane.removeEventListener('click', capture, true)
    }
  }, [paneRef, owner, scope, route, location.pathname, contextualReturn])
}
