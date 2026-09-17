import { useEffect } from 'react'
import { AudioLines, ChevronUp, FileInput, Home, Library, Mic2, Plus, Settings2, Users } from 'lucide-react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import packageJson from '../../../package.json'
import { useI18n } from '../../lib/i18n'
import { useTeamStore } from '../../stores/teamStore'
import { useAuthStore } from '../../stores/authStore'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Sidebar as ShadcnSidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupAction, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuBadge, SidebarMenuButton, SidebarMenuItem, SidebarRail, SidebarSeparator, useSidebar } from '@/components/ui/sidebar'

export function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { state } = useSidebar()
  const collapsed = state === 'collapsed'
  const { copy, locale } = useI18n()
  const zh = locale.startsWith('zh')
  const user = useAuthStore(state => state.user)
  const { teams, currentWorkspace, loadTeams, initialized, selectPersonalWorkspace, selectTeamWorkspace } = useTeamStore()
  useEffect(() => { if (!initialized) void loadTeams() }, [initialized, loadTeams])
  const navigation = [
    { path: '/', icon: Home, label: copy.sidebar.home },
    { path: '/meetings', icon: Mic2, label: zh ? '会议' : 'Meetings' },
    { path: '/generate', icon: FileInput, label: zh ? '整理' : 'Organize' },
    { path: '/notes', icon: Library, label: zh ? '知识库' : 'Library' },
    { path: '/team', icon: Users, label: zh ? '协作' : 'Team' },
  ]

  return (
    <ShadcnSidebar collapsible="icon" variant="sidebar" className="border-r-0">
      <SidebarHeader className="gap-3 px-3 py-4">
        <SidebarMenu><SidebarMenuItem><SidebarMenuButton size="lg" onClick={() => navigate('/')} tooltip="VINote">
          <span className="flex aspect-square size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm"><AudioLines className="size-5" /></span>
          <span className="grid flex-1 text-left leading-tight"><span className="truncate text-base font-semibold">VINote</span><span className="truncate text-xs text-muted-foreground">{zh ? '会议与知识空间' : 'Meeting knowledge'}</span></span>
          <Badge variant="secondary" className="text-[10px]">Beta</Badge>
        </SidebarMenuButton></SidebarMenuItem></SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup><SidebarGroupLabel>{zh ? '工作' : 'Work'}</SidebarGroupLabel><SidebarGroupContent><SidebarMenu>
          {navigation.map(item => { const active = item.path === '/' ? location.pathname === '/' : location.pathname.startsWith(item.path); return <SidebarMenuItem key={item.path}><SidebarMenuButton asChild isActive={active} tooltip={item.label}><NavLink to={item.path}><item.icon /><span>{item.label}</span></NavLink></SidebarMenuButton></SidebarMenuItem> })}
        </SidebarMenu></SidebarGroupContent></SidebarGroup>
        <SidebarSeparator />
        <SidebarGroup><SidebarGroupLabel>{zh ? '空间' : 'Spaces'}</SidebarGroupLabel><SidebarGroupAction aria-label={zh ? '创建团队' : 'Create team'} onClick={() => navigate('/team')}><Plus /></SidebarGroupAction><SidebarGroupContent><SidebarMenu>
          <SidebarMenuItem><SidebarMenuButton tooltip={zh ? '个人空间' : 'Personal'} isActive={currentWorkspace.scope === 'personal'} onClick={selectPersonalWorkspace}><span className="flex size-5 items-center justify-center rounded-md bg-primary/10 text-[10px] font-semibold text-primary">P</span><span>{zh ? '个人空间' : 'Personal'}</span>{currentWorkspace.scope === 'personal' ? <SidebarMenuBadge>•</SidebarMenuBadge> : null}</SidebarMenuButton></SidebarMenuItem>
          {teams.map(team => <SidebarMenuItem key={team.id}><SidebarMenuButton tooltip={team.name} isActive={currentWorkspace.scope === 'team' && currentWorkspace.teamId === team.id} onClick={() => selectTeamWorkspace(team.id)}><span className="flex size-5 items-center justify-center rounded-md bg-secondary text-[10px] font-semibold">{team.name.slice(0, 1).toUpperCase()}</span><span>{team.name}</span><SidebarMenuBadge>{team.memberCount}</SidebarMenuBadge></SidebarMenuButton></SidebarMenuItem>)}
          {!teams.length && !collapsed ? <SidebarMenuItem><SidebarMenuButton onClick={() => navigate('/team')} className="h-auto border border-dashed py-3 text-muted-foreground"><Plus /><span>{zh ? '创建共享空间' : 'Create shared space'}</span></SidebarMenuButton></SidebarMenuItem> : null}
        </SidebarMenu></SidebarGroupContent></SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="p-3"><SidebarMenu>
        <SidebarMenuItem><SidebarMenuButton asChild isActive={location.pathname.startsWith('/settings')} tooltip={copy.sidebar.settings}><NavLink to="/settings"><Settings2 /><span>{copy.sidebar.settings}</span><span className="ml-auto text-[10px] text-muted-foreground">v{packageJson.version}</span></NavLink></SidebarMenuButton></SidebarMenuItem>
        <SidebarMenuItem><DropdownMenu><DropdownMenuTrigger asChild><SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent"><Avatar className="size-8 rounded-lg"><AvatarFallback className="rounded-lg bg-foreground text-background">{user?.email?.[0]?.toUpperCase() || 'V'}</AvatarFallback></Avatar><span className="grid min-w-0 flex-1 text-left leading-tight"><span className="truncate text-sm font-medium">{user?.email?.split('@')[0]}</span><span className="truncate text-xs text-muted-foreground">{user?.email}</span></span><ChevronUp className="ml-auto size-4" /></SidebarMenuButton></DropdownMenuTrigger><DropdownMenuContent side="right" align="end" className="w-60"><DropdownMenuLabel>{zh ? '当前账号' : 'Account'}</DropdownMenuLabel><DropdownMenuItem onClick={() => navigate('/settings')}><Settings2 />{copy.sidebar.settings}</DropdownMenuItem><DropdownMenuSeparator /><DropdownMenuItem onClick={() => navigate('/team')}><Users />{zh ? '管理团队' : 'Manage team'}</DropdownMenuItem></DropdownMenuContent></DropdownMenu></SidebarMenuItem>
      </SidebarMenu></SidebarFooter>
      <SidebarRail />
    </ShadcnSidebar>
  )
}
