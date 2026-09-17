import { type LucideIcon } from 'lucide-react'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
export function PlaceholderSettingsPanel({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string }) { return <Empty className="min-h-72 border border-dashed"><EmptyHeader><EmptyMedia variant="icon"><Icon /></EmptyMedia><EmptyTitle>{title}</EmptyTitle><EmptyDescription>{body}</EmptyDescription></EmptyHeader></Empty> }
