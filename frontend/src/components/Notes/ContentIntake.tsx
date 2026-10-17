import { Link, useLocation } from 'react-router-dom'
import { ArrowUpRight, FileUp, Link2 } from 'lucide-react'

// Note sources belong to Notes. Meeting capture has its own entry in Meetings.
export function ContentIntake() {
  const location = useLocation()
  const state = { returnTo: location.pathname + location.search }
  return <section aria-label="生成总结笔记" className="grid gap-3 sm:grid-cols-2">
    {[
      { mode: 'url', icon: Link2, title: '粘贴链接', description: 'B 站等公开视频、普通网页或在线文档 → 总结笔记' },
      { mode: 'file', icon: FileUp, title: '导入文件', description: 'PDF、Word、音视频或文字文件 → 总结笔记' },
    ].map(({ mode, icon: Icon, title, description }) => <Link key={mode} to={`/generate?mode=${mode}`} state={state} className="group flex min-w-0 items-center gap-4 rounded-2xl border bg-card p-5 transition-[background-color,border-color,transform] duration-150 hover:border-foreground/20 hover:bg-muted/40 active:scale-[.99] motion-reduce:transition-none motion-reduce:active:scale-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted"><Icon className="size-5" /></span>
      <div className="min-w-0 flex-1"><h2 className="text-sm font-medium">{title}</h2><p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p></div>
      <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 motion-reduce:transform-none" />
    </Link>)}
  </section>
}
