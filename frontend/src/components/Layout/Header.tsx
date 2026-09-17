import { Bell, FileUp, Link, LogOut, Mic2, Moon, Plus, Search, Settings2, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useI18n } from '../../lib/i18n'
import { useAuthStore } from '../../stores/authStore'
import { useThemeStore } from '../../stores/themeStore'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from '@/components/ui/command'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

export function Header() {
  const { user, signOut } = useAuthStore()
  const { resolvedTheme, setTheme } = useThemeStore()
  const { copy, locale } = useI18n()
  const navigate = useNavigate()
  const location = useLocation()
  const zh = locale.startsWith('zh')
  const [searchOpen, setSearchOpen] = useState(false)
  const titles: Array<[string, string, string]> = [['/meetings', '会议工作台', 'Meeting studio'], ['/generate', '资料整理', 'Organize'], ['/notes', '知识库', 'Library'], ['/team', '团队协作', 'Team'], ['/settings', '偏好设置', 'Settings'], ['/note/', '笔记详情', 'Note'], ['/', '工作台', 'Workspace']]
  const current = titles.find(([path]) => path === '/' ? location.pathname === '/' : location.pathname.startsWith(path))
  useEffect(() => { const onKeyDown = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setSearchOpen(value => !value) } }; window.addEventListener('keydown', onKeyDown); return () => window.removeEventListener('keydown', onKeyDown) }, [])
  const open = (path: string) => { setSearchOpen(false); navigate(path) }
  const actions = [
    { path: '/meetings', icon: Mic2, label: zh ? '开始会议' : 'Start meeting', hint: zh ? '录音、录屏，会后生成转写与纪要' : 'Record now, process after the meeting' },
    { path: '/generate?mode=url', icon: Link, label: zh ? '整理链接' : 'Organize link', hint: zh ? '网页、文章和公开视频' : 'Websites, articles and public videos' },
    { path: '/generate?mode=file', icon: FileUp, label: zh ? '导入文件' : 'Import file', hint: zh ? '音频、视频、字幕和文本' : 'Audio, video, transcripts and text' },
  ]
  return <>
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur-xl">
      <SidebarTrigger className="-ml-1" /><div className="h-4 w-px bg-border" />
      <div className="min-w-0"><p className="truncate text-sm font-semibold">{zh ? current?.[1] : current?.[2]}</p><p className="hidden truncate text-xs text-muted-foreground sm:block">{zh ? '把讨论与资料沉淀为团队知识' : 'Turn conversations and sources into knowledge'}</p></div>
      <Button variant="outline" className="mx-auto hidden w-full max-w-sm justify-start text-muted-foreground lg:flex" onClick={() => setSearchOpen(true)}><Search className="size-4" /><span className="flex-1 text-left">{copy.header.searchPlaceholder}</span><kbd className="rounded border bg-muted px-1.5 py-0.5 text-[10px]">Ctrl K</kbd></Button>
      <div className="ml-auto flex items-center gap-1">
        <DropdownMenu><DropdownMenuTrigger asChild><Button size="sm"><Plus />{copy.header.newButton}</Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="w-72"><DropdownMenuLabel>{zh ? '新建工作' : 'New work'}</DropdownMenuLabel>{actions.map(item => <DropdownMenuItem key={item.path} onClick={() => navigate(item.path)} className="items-start gap-3 py-3"><item.icon className="mt-0.5 size-4" /><span><span className="block font-medium">{item.label}</span><span className="block text-xs text-muted-foreground">{item.hint}</span></span></DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>
        <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon" onClick={() => setSearchOpen(true)} className="lg:hidden"><Search /></Button></TooltipTrigger><TooltipContent>{zh ? '搜索' : 'Search'}</TooltipContent></Tooltip>
        <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon" aria-label={zh ? '通知' : 'Notifications'}><Bell /></Button></TooltipTrigger><TooltipContent>{zh ? '通知' : 'Notifications'}</TooltipContent></Tooltip>
        <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon" onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}>{resolvedTheme === 'dark' ? <Sun /> : <Moon />}</Button></TooltipTrigger><TooltipContent>{zh ? '切换主题' : 'Toggle theme'}</TooltipContent></Tooltip>
        <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="rounded-full"><Avatar className="size-8"><AvatarFallback className="bg-foreground text-xs font-semibold text-background">{user?.email?.[0]?.toUpperCase() || 'V'}</AvatarFallback></Avatar></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="w-60"><DropdownMenuLabel className="truncate">{user?.email}</DropdownMenuLabel><DropdownMenuSeparator /><DropdownMenuItem onClick={() => navigate('/settings')}><Settings2 />{copy.sidebar.settings}</DropdownMenuItem><DropdownMenuItem onClick={async () => { await signOut(); navigate('/login') }}><LogOut />{copy.header.signOut}</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
      </div>
    </header>
    <Dialog open={searchOpen} onOpenChange={setSearchOpen}><DialogContent className="overflow-hidden p-0 sm:max-w-xl" aria-describedby={undefined}><Command><CommandInput placeholder={zh ? '搜索功能或前往页面…' : 'Search actions or pages…'} /><CommandList><CommandEmpty>{zh ? '没有找到结果' : 'No results found'}</CommandEmpty><CommandGroup heading={zh ? '创建' : 'Create'}>{actions.map(item => <CommandItem key={item.path} onSelect={() => open(item.path)}><item.icon /><span>{item.label}</span></CommandItem>)}</CommandGroup><CommandSeparator /><CommandGroup heading={zh ? '前往' : 'Go to'}><CommandItem onSelect={() => open('/notes')}><Search /><span>{zh ? '搜索知识库' : 'Search library'}</span></CommandItem><CommandItem onSelect={() => open('/settings')}><Settings2 /><span>{copy.sidebar.settings}</span></CommandItem></CommandGroup></CommandList></Command></DialogContent></Dialog>
  </>
}
