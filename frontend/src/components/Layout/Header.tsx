import { FileText, LogOut, Mic2, Search, Settings2, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useI18n } from '../../lib/i18n'
import { useAuthStore } from '../../stores/authStore'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from '@/components/ui/command'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const destinations = [
  { path: '/', icon: FileText, zh: '动态', en: 'Activity' },
  { path: '/meetings', icon: Mic2, zh: '会议', en: 'Meetings' },
  { path: '/generate', icon: FileText, zh: '链接与文件', en: 'Links & files' },
  { path: '/notes', icon: FileText, zh: '笔记库', en: 'Notes' },
  { path: '/team', icon: Users, zh: '成员与共享', en: 'Members & sharing' },
  { path: '/settings', icon: Settings2, zh: '设置', en: 'Settings' },
]

export function Header() {
  const { user, signOut } = useAuthStore()
  const { copy, locale } = useI18n()
  const navigate = useNavigate()
  const location = useLocation()
  const zh = locale.startsWith('zh')
  const [searchOpen, setSearchOpen] = useState(false)
  const current = location.pathname.startsWith('/note/')
    ? { zh: '笔记', en: 'Note' }
    : destinations.find(item => item.path === '/' ? location.pathname === '/' : location.pathname.startsWith(item.path))

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setSearchOpen(value => !value)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const open = (path: string) => { setSearchOpen(false); navigate(path) }

  return <>
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <SidebarTrigger className="-ml-1 text-muted-foreground transition-transform duration-200 hover:scale-105 hover:text-foreground" />
      <div className="min-w-0 animate-in fade-in slide-in-from-left-1 duration-300">
        <p className="truncate text-sm font-medium">{zh ? current?.zh : current?.en}</p>
        <p className="hidden text-[11px] text-muted-foreground sm:block">VINote</p>
      </div>
      <Button variant="ghost" className="mx-auto hidden h-9 w-full max-w-md justify-start border bg-muted/35 text-muted-foreground shadow-none transition-all duration-200 hover:-translate-y-px hover:border-foreground/20 hover:bg-muted lg:flex" onClick={() => setSearchOpen(true)}>
        <Search data-icon="inline-start" /><span className="flex-1 text-left">{zh ? '搜索笔记、会议和页面' : copy.header.searchPlaceholder}</span><kbd className="rounded border bg-background px-1.5 py-0.5 text-[10px]">Ctrl K</kbd>
      </Button>
      <div className="ml-auto flex items-center gap-1">
        <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon" onClick={() => setSearchOpen(true)} className="transition-transform duration-200 hover:scale-105 lg:hidden"><Search /></Button></TooltipTrigger><TooltipContent>{zh ? '搜索' : 'Search'}</TooltipContent></Tooltip>
        <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="rounded-full transition-transform duration-200 hover:scale-105"><Avatar className="size-8"><AvatarFallback className="bg-foreground text-xs font-semibold text-background">{user?.email?.[0]?.toUpperCase() || 'V'}</AvatarFallback></Avatar></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="w-60"><DropdownMenuLabel className="truncate">{user?.email}</DropdownMenuLabel><DropdownMenuSeparator /><DropdownMenuGroup><DropdownMenuItem onClick={() => navigate('/settings')}><Settings2 />{copy.sidebar.settings}</DropdownMenuItem><DropdownMenuItem onClick={() => navigate('/team')}><Users />{zh ? '成员与共享' : 'Members & sharing'}</DropdownMenuItem></DropdownMenuGroup><DropdownMenuSeparator /><DropdownMenuGroup><DropdownMenuItem onClick={async () => { await signOut(); navigate('/login') }}><LogOut />{copy.header.signOut}</DropdownMenuItem></DropdownMenuGroup></DropdownMenuContent></DropdownMenu>
      </div>
    </header>
    <Dialog open={searchOpen} onOpenChange={setSearchOpen}><DialogContent className="overflow-hidden p-0 sm:max-w-xl" aria-describedby={undefined}><DialogTitle className="sr-only">{zh ? '全局搜索' : 'Global search'}</DialogTitle><Command><CommandInput placeholder={zh ? '搜索笔记、会议或前往页面…' : 'Search notes, meetings, or pages…'} /><CommandList><CommandEmpty>{zh ? '没有找到结果' : 'No results found'}</CommandEmpty><CommandGroup heading={zh ? '前往' : 'Go to'}>{destinations.map(item => <CommandItem key={item.path} onSelect={() => open(item.path)}><item.icon /><span>{zh ? item.zh : item.en}</span></CommandItem>)}</CommandGroup><CommandSeparator /><CommandGroup heading={zh ? '快捷操作' : 'Shortcuts'}><CommandItem onSelect={() => open('/meetings')}><Mic2 /><span>{zh ? '打开会议录制' : 'Open meeting capture'}</span></CommandItem><CommandItem onSelect={() => open('/generate')}><FileText /><span>{zh ? '打开资料收件箱' : 'Open material inbox'}</span></CommandItem></CommandGroup></CommandList></Command></DialogContent></Dialog>
  </>
}
