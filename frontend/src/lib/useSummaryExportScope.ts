import { useEffect, useRef } from 'react'
import { useAuthStore } from '@/stores/authStore'

/** Immediate store subscription also invalidates A→B→A between React renders. */
export function useSummaryExportScope(scope: unknown[]) {
  const latest = useRef(scope), epoch = useRef(0), live = useRef(true)
  const renderOwner = useAuthStore(state => state.user?.id)
  const renderedEpoch = epoch.current
  latest.current = scope
  useEffect(() => {
    live.current = true
    let observed = useAuthStore.getState().user?.id
    const unsubscribe = useAuthStore.subscribe(state => {
      if (state.user?.id !== observed) { epoch.current++; observed = state.user?.id }
    })
    return () => { live.current = false; unsubscribe() }
  }, [])
  return () => {
    const frozen = scope
    return () => live.current && epoch.current === renderedEpoch && useAuthStore.getState().user?.id === renderOwner && frozen.length === latest.current.length && frozen.every((value, index) => value === latest.current[index])
  }
}
