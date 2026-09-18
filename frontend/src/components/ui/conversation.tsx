import * as React from 'react'
import { ArrowDown } from 'lucide-react'
import { StickToBottom, useStickToBottomContext } from 'use-stick-to-bottom'
import { Avatar, AvatarFallback } from './avatar'
import { Badge } from './badge'
import { Button } from './button'
import { cn } from '@/lib/utils'

export function Conversation({ className, ...props }: React.ComponentProps<typeof StickToBottom>) {
  return <StickToBottom className={cn('relative flex min-h-0 flex-1 flex-col overflow-hidden bg-background', className)} resize="smooth" initial="smooth" {...props} />
}
export function ConversationContent({ className, ...props }: React.ComponentProps<typeof StickToBottom.Content>) {
  return <StickToBottom.Content className={cn('flex flex-col gap-3 p-5 sm:p-6', className)} {...props} />
}

export function ConversationEmptyState({ title, description, icon }: { title: string; description?: string; icon?: React.ReactNode }) {
  return <div className="flex flex-1 animate-in flex-col items-center justify-center gap-4 px-6 py-16 text-center fade-in zoom-in-95 duration-300"><div className="flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground">{icon}</div><div><p className="font-medium">{title}</p>{description ? <p className="mt-1 max-w-sm text-sm leading-6 text-muted-foreground">{description}</p> : null}</div></div>
}

export function ConversationScrollButton() {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext()
  if (isAtBottom) return null
  return <Button variant="secondary" size="icon" className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full shadow-lg animate-in fade-in zoom-in-95" onClick={() => scrollToBottom()} aria-label="Scroll to latest"><ArrowDown /></Button>
}

export function ConversationMessage({ speaker, time, children, active }: { speaker: string; time?: string; children: React.ReactNode; active?: boolean }) {
  return <article aria-current={active ? 'true' : undefined} className={cn('group flex animate-in gap-4 rounded-2xl border border-transparent px-4 py-4 fade-in slide-in-from-bottom-2 duration-300 transition-all hover:border-border hover:bg-muted/35', active && 'border-border bg-muted/60 shadow-sm')}><Avatar className="size-9 shrink-0"><AvatarFallback className="text-xs font-semibold">{speaker.slice(0, 2)}</AvatarFallback></Avatar><div className="min-w-0 flex-1"><div className="mb-1.5 flex items-center gap-2"><span className="text-sm font-semibold">{speaker}</span>{time ? <span className="text-xs tabular-nums text-muted-foreground">{time}</span> : null}{active ? <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">Live</Badge> : null}</div><div className="text-sm leading-6 text-foreground/90">{children}</div></div></article>
}
