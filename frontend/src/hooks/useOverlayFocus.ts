import { useRef } from 'react'

/** Controlled overlays may be opened without a Radix Trigger. Keep their opener. */
export function useOverlayFocus(onOpen?: (event: Event) => void, onClose?: (event: Event) => void) {
  const opener = useRef<HTMLElement | null>(null)
  return {
    onOpenAutoFocus(event: Event) {
      const active = document.activeElement
      opener.current = active instanceof HTMLElement && active !== document.body ? active : null
      onOpen?.(event)
    },
    onCloseAutoFocus(event: Event) {
      onClose?.(event)
      if (event.defaultPrevented) return
      // Another task has replaced this overlay; let its own focus scope win.
      if (document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]')) {
        event.preventDefault()
        return
      }
      if (opener.current?.isConnected && !opener.current.matches(':disabled')) {
        event.preventDefault()
        opener.current.focus({ preventScroll: true })
      }
    },
  }
}
