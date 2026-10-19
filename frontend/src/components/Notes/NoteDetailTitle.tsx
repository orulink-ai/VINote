import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

/** Keep the title readable without displacing the actions/player from short viewports. */
export function NoteDetailTitle({ title, zh }: { title: string; zh: boolean }) {
  const heading = useRef<HTMLHeadingElement>(null)
  const [clipped, setClipped] = useState(false)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const node = heading.current
    if (!node) return
    const measure = () => setClipped(node.scrollHeight > node.clientHeight + 1)
    measure()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(node)
    window.addEventListener('resize', measure)
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure) }
  }, [title])
  return <>
    <h1 ref={heading} className="line-clamp-2 min-w-0 text-2xl font-medium [overflow-wrap:anywhere]">{title}</h1>
    {clipped && <Button variant="link" size="sm" className="mt-1 h-auto px-0" onClick={() => setOpen(true)}>{zh ? '查看完整标题' : 'Read full title'}</Button>}
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="min-w-0"><DialogHeader><DialogTitle>{zh ? '完整标题' : 'Full title'}</DialogTitle><DialogDescription className="max-h-[65vh] overflow-auto text-left [overflow-wrap:anywhere]">{title}</DialogDescription></DialogHeader></DialogContent></Dialog>
  </>
}
