import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { Minus, Square, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function DesktopTitleBar() {
  if (!isTauri()) return null

  const appWindow = getCurrentWindow()

  return (
    <header
      data-tauri-drag-region
      className="flex h-9 shrink-0 select-none items-center justify-end border-b bg-background"
    >
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-9 w-11 rounded-none text-muted-foreground hover:bg-muted hover:text-foreground"
        aria-label="最小化"
        onClick={() => void appWindow.minimize()}
      >
        <Minus className="size-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-9 w-11 rounded-none text-muted-foreground hover:bg-muted hover:text-foreground"
        aria-label="最大化或还原"
        onClick={() => void appWindow.toggleMaximize()}
      >
        <Square className="size-3.5" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-9 w-11 rounded-none text-muted-foreground hover:bg-destructive hover:text-destructive-foreground"
        aria-label="关闭"
        onClick={() => void appWindow.close()}
      >
        <X className="size-4" />
      </Button>
    </header>
  )
}
