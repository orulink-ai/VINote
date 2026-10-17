import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronDown, ChevronsUpDown, Search, FileText, ListTodo, LogOut, Mic2, Settings2, Folder, Plug, Send, Wrench } from 'lucide-react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import packageJson from '../../../package.json'
import { useI18n } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useMeetingRecorderStore } from '@/stores/meetingRecorderStore'
import { useTeamStore } from '@/stores/teamStore'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { AlertDialog as Dialog, AlertDialogContent as DialogContent, AlertDialogDescription as DialogDescription, AlertDialogFooter as DialogFooter, AlertDialogHeader as DialogHeader, AlertDialogTitle as DialogTitle } from '@/components/ui/alert-dialog'
import { requestPageNavigation, settingsMenuParent } from '@/lib/navigation'
import { ErrorState } from '@/components/Feedback/ResourceState'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Sidebar as SidebarFrame, SidebarContent, SidebarFooter, SidebarHeader, useSidebar } from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

export function Sidebar({ onSearch }: { onSearch: () => void }) {
  const navigate = useNavigate()
  const location = useLocation()
  const settingsParent = settingsMenuParent(location.pathname, location.search, location.hash, location.state?.returnTo)
  const settingsParams = new URLSearchParams()
  if (settingsParent) settingsParams.set('returnTo', settingsParent)
  const settingsPath = '/settings' + (settingsParent ? '?' + settingsParams.toString() : '')
  const accountSettingsParams = new URLSearchParams(settingsParams)
  accountSettingsParams.set('tab', 'profile')
  const accountSettingsPath = '/settings?' + accountSettingsParams.toString()
  const { state, isMobile, setOpenMobile, toggleSidebar } = useSidebar()
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const { user, signOut } = useAuthStore()
  const recorder = useMeetingRecorderStore()
  const { teams, currentWorkspace, loadTeams, selectPersonalWorkspace, selectTeamWorkspace } = useTeamStore()
  useEffect(() => { void loadTeams() }, [loadTeams])
  const [logout, setLogout] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const collapsed = state === 'collapsed' && !isMobile
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null)
  const closeMobile = () => { if (isMobile) setOpenMobile(false) }
  const captureRisk = ['requesting', 'recording', 'paused', 'stopping'].includes(recorder.phase)
    || recorder.hasRecoverableRecording && !recorder.localRecordingSaved
  const returnTo = String(location.state?.returnTo || '')
  const meetingContext = location.pathname === '/meetings'
    || location.pathname === '/generate' && new URLSearchParams(location.search).get('meeting') === '1'
    || /^\/note\//.test(location.pathname) && returnTo.startsWith('/meetings')
  const navigation = [
    { id: 'meetings', path: '/meetings', icon: Mic2, label: zh ? '会议' : 'Meetings', active: meetingContext, children: [] },
    { id: 'notes', path: '/notes', icon: FileText, label: zh ? '笔记' : 'Notes', active: !meetingContext && (location.pathname === '/' || /^\/(notes|note|workspace|generate|write|archive|projects)(\/|$)/.test(location.pathname)), children: [] },
    { id: 'files', path: '/files?type=all', icon: Folder, label: zh ? '文件库' : 'Files', active: location.pathname === '/files', children: [] },
    { id: 'plugins', path: '/connections', icon: Plug, label: zh ? '插件' : 'Plugins', active: location.pathname === '/connections' || /^\/settings\/(feishu|mcp)/.test(location.pathname), children: [
      { path: '/settings/feishu', label: '飞书', icon: Send }, { path: '/settings/mcp', label: 'MCP 工具', icon: Wrench },
    ] },
  ]
  const selected = (path: string) => path.includes('?')
    ? location.pathname === path.split('?')[0] && (new URLSearchParams(location.search).get('type') || 'all') === new URLSearchParams(path.split('?')[1]).get('type')
    : location.pathname === path
  useEffect(() => {
    const group = location.pathname === '/files' ? 'files'
      : location.pathname === '/connections' || /^\/settings\/(feishu|mcp)/.test(location.pathname) ? 'plugins'
        : null
    setExpandedGroup(group)
  }, [location.pathname])

  return <>
    <SidebarFrame collapsible="icon" className="workspace-navigation" aria-label={zh ? '应用导航' : 'Application navigation'}>
      <SidebarHeader className="workspace-brand-region">
        <div className="workspace-brand-row">
          {!collapsed && <NavLink to="/meetings" onClick={closeMobile} className="workspace-brand" aria-label={zh ? 'VINote，返回会议' : 'VINote, meetings'}>
            <img src="/app-icon.png" alt="" className="size-8 shrink-0 rounded-lg" />
            <span className="workspace-brand-copy"><strong>VINote</strong></span>
          </NavLink>}
          <Tooltip><TooltipTrigger asChild><button type="button" className="workspace-collapse" onClick={toggleSidebar} aria-label={collapsed ? '展开导航' : '收起导航'} aria-expanded={!collapsed}>
            <ChevronLeft aria-hidden="true" />
          </button></TooltipTrigger><TooltipContent side="right">{collapsed ? '展开导航' : '收起导航'} · Ctrl B</TooltipContent></Tooltip>
        </div>
        <Tooltip><TooltipTrigger asChild><button type="button" className="workspace-search-launcher" onClick={() => { closeMobile(); onSearch() }} aria-label="搜索资料与页面（Ctrl K）">
          <Search aria-hidden="true" />{!collapsed && <><span>快速查找</span><kbd>Ctrl K</kbd></>}
        </button></TooltipTrigger>{collapsed && <TooltipContent side="right">搜索资料与页面 · Ctrl K</TooltipContent>}</Tooltip>
        {!collapsed && teams.length > 0 && <NativeSelect aria-label="当前资料空间" value={currentWorkspace.scope === 'team' ? currentWorkspace.teamId : 'personal'} onChange={e => e.target.value === 'personal' ? selectPersonalWorkspace() : selectTeamWorkspace(e.target.value)}>
          <NativeSelectOption value="personal">个人空间</NativeSelectOption>
          {teams.map(team => <NativeSelectOption key={team.id} value={team.id}>{team.name}</NativeSelectOption>)}
        </NativeSelect>}
      </SidebarHeader>
      <SidebarContent className="workspace-navigation-body">
        <nav aria-label={zh ? '主要功能' : 'Main navigation'}><ul className="workspace-navigation-list">
          {navigation.map(item => <li key={item.id} className="workspace-nav-group">
            <div className={cn('workspace-nav-parent', item.active && 'is-active')}>
              <Tooltip><TooltipTrigger asChild><Link to={item.path} onClick={() => { setExpandedGroup(item.id); closeMobile() }} className="workspace-nav-parent-link" aria-label={item.label} aria-current={item.active && item.children.length === 0 ? 'page' : undefined}>
                <item.icon aria-hidden="true" className="size-4 shrink-0" />{!collapsed && <span className="truncate">{item.label}</span>}
              </Link></TooltipTrigger>{collapsed && <TooltipContent side="right">{item.label}</TooltipContent>}</Tooltip>
              {!collapsed && item.children.length > 0 && <button type="button" className="workspace-nav-disclosure" aria-label={`${expandedGroup === item.id ? '收起' : '展开'}${item.label}`} aria-expanded={expandedGroup === item.id} aria-controls={`nav-${item.id}`} onClick={() => setExpandedGroup(current => current === item.id ? null : item.id)}><ChevronDown aria-hidden="true" className={cn('size-4 transition-transform motion-reduce:transition-none', expandedGroup !== item.id && '-rotate-90')} /></button>}
            </div>
            {!collapsed && <ul id={`nav-${item.id}`} hidden={expandedGroup !== item.id} className="workspace-nav-children">{item.children.map(child => <li key={child.path}><Link to={child.path} onClick={closeMobile} className={cn('workspace-nav-child', selected(child.path) && 'is-selected')} aria-current={selected(child.path) ? 'page' : undefined}>{child.label}</Link></li>)}</ul>}
          </li>)}
        </ul></nav>
      </SidebarContent>
      <SidebarFooter className="workspace-account-region">

        <Tooltip><TooltipTrigger asChild>
          <NavLink to={settingsPath} onClick={closeMobile} aria-label={zh ? '设置' : 'Settings'}
            className={cn('workspace-nav-item workspace-settings-link', (location.pathname === '/settings' || /^\/settings\/(storage|sync)/.test(location.pathname) || location.pathname === '/team') && 'is-selected')}>
            <span className="workspace-nav-icon"><Settings2 aria-hidden="true" /></span>
            {!collapsed && <span className="workspace-nav-copy"><span>{zh ? '设置' : 'Settings'}</span><small>{zh ? '模型、录制与数据' : 'Preferences & data'}</small></span>}
          </NavLink>
        </TooltipTrigger>{collapsed && <TooltipContent side="right">{zh ? '设置' : 'Settings'}</TooltipContent>}</Tooltip>
        <DropdownMenu><DropdownMenuTrigger asChild>
          <Button variant="ghost" className="workspace-account" aria-label="账号菜单">
            <Avatar className="size-8 shrink-0"><AvatarFallback>{user?.email?.[0]?.toUpperCase() || 'V'}</AvatarFallback></Avatar>
            {!collapsed && <><span className="workspace-account-copy"><span>{user?.email?.split('@')[0] || 'VINote'}</span><small>{zh ? '我的账号' : 'My account'}</small></span><ChevronsUpDown /></>}
          </Button>
        </DropdownMenuTrigger><DropdownMenuContent side="right" align="end" className="w-60">
          <DropdownMenuLabel className="truncate">{user?.email}</DropdownMenuLabel>
          <DropdownMenuGroup>
            <DropdownMenuItem onClick={() => { closeMobile(); requestPageNavigation(accountSettingsPath, navigate) }}><Settings2 />账号与个人资料</DropdownMenuItem>
            <DropdownMenuItem onClick={() => { closeMobile(); requestPageNavigation(`/tasks?returnTo=${encodeURIComponent(location.pathname + location.search)}`, navigate) }}><ListTodo />处理历史与恢复</DropdownMenuItem>
            <DropdownMenuItem onClick={() => { setError(''); setLogout(true) }}><LogOut />退出此设备</DropdownMenuItem>
          </DropdownMenuGroup><DropdownMenuSeparator /><DropdownMenuLabel className="text-xs font-normal text-muted-foreground">VINote v{packageJson.version}</DropdownMenuLabel>
        </DropdownMenuContent></DropdownMenu>
      </SidebarFooter>
    </SidebarFrame>
    <Dialog open={logout} onOpenChange={value => { if (!busy) setLogout(value) }}><DialogContent>
      <DialogHeader><DialogTitle>退出此设备？</DialogTitle><DialogDescription>{captureRisk
        ? '录制或原始文件尚未保存。请先返回记录完成保存，再退出账号。'
        : '此设备的内容与草稿保留，重新登录同一账号后可继续。'}</DialogDescription></DialogHeader>
      {error && <ErrorState error={error} />}
      <DialogFooter><Button variant="outline" disabled={busy} onClick={() => { setLogout(false); if (captureRisk) navigate('/meetings') }}>{captureRisk ? '返回录制' : '继续使用'}</Button>
        <Button disabled={busy || captureRisk} aria-busy={busy} onClick={async () => {
          setBusy(true)
          try { await signOut(); navigate('/login') } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
        }}>{busy ? '退出中…' : '退出此设备'}</Button></DialogFooter>
    </DialogContent></Dialog>
  </>
}
