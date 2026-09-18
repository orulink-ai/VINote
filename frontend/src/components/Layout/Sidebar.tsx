import { useEffect } from 'react'
import { ChevronUp, FileInput, Library, LogOut, Mic2, Settings2, Sparkles, Users } from 'lucide-react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import packageJson from '../../../package.json'
import { useI18n } from '../../lib/i18n'
import { useTeamStore } from '../../stores/teamStore'
import { useAuthStore } from '../../stores/authStore'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Sidebar as ShadcnSidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuBadge, SidebarMenuButton, SidebarMenuItem, SidebarRail, SidebarSeparator, useSidebar } from '@/components/ui/sidebar'

export function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { state } = useSidebar()
  const collapsed = state === 'collapsed'
  const { copy, locale } = useI18n()
  const zh = locale.startsWith('zh')
  const { user, signOut } = useAuthStore()
  const { teams, currentWorkspace, loadTeams, initialized, selectPersonalWorkspace, selectTeamWorkspace } = useTeamStore()
  useEffect(() => { if (!initialized) void loadTeams() }, [initialized, loadTeams])
  const captureNavigation = [{ path: '/', icon: Sparkles, label: zh ? '动态' : 'Activity' }, { path: '/meetings', icon: Mic2, label: zh ? '会议' : 'Meetings' }, { path: '/generate', icon: FileInput, label: zh ? '链接与文件' : 'Links & files' }]
  const libraryNavigation = [{ path: '/notes', icon: Library, label: zh ? '笔记库' : 'Note library' }]
  const renderNavigation = (items: typeof captureNavigation) => items.map(item => {
    const active = item.path === '/' ? location.pathname === '/' : location.pathname.startsWith(item.path)
    return <SidebarMenuItem key={item.path}><SidebarMenuButton asChild isActive={active} tooltip={item.label} className="group/nav relative overflow-hidden transition-all duration-200 hover:translate-x-0.5 data-[active=true]:bg-sidebar-accent data-[active=true]:font-medium before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:origin-center before:scale-y-0 before:rounded-full before:bg-foreground before:transition-transform before:duration-200 data-[active=true]:before:scale-y-100"><NavLink to={item.path}><item.icon className="transition-transform duration-200 group-hover/nav:scale-105" /><span>{item.label}</span></NavLink></SidebarMenuButton></SidebarMenuItem>
  })
  return <ShadcnSidebar collapsible="icon" variant="sidebar" className="border-r-0">
    <SidebarHeader className="border-b px-3 py-3"><SidebarMenu><SidebarMenuItem><SidebarMenuButton size="lg" onClick={() => navigate('/')} tooltip={zh ? '工作空间' : 'Workspace'} className="transition-colors duration-200"><span className="grid flex-1 text-left leading-tight"><span className="truncate text-sm font-semibold">{zh ? '工作空间' : 'Workspace'}</span><span className="truncate text-xs text-muted-foreground">{zh ? '会议与知识' : 'Meetings and knowledge'}</span></span></SidebarMenuButton></SidebarMenuItem></SidebarMenu></SidebarHeader>
    <SidebarContent>
      <SidebarGroup><SidebarGroupLabel>{zh ? '采集' : 'Capture'}</SidebarGroupLabel><SidebarGroupContent><SidebarMenu>{renderNavigation(captureNavigation)}</SidebarMenu></SidebarGroupContent></SidebarGroup>
      <SidebarGroup><SidebarGroupLabel>{zh ? '沉淀' : 'Library'}</SidebarGroupLabel><SidebarGroupContent><SidebarMenu>{renderNavigation(libraryNavigation)}</SidebarMenu></SidebarGroupContent></SidebarGroup>
      <SidebarSeparator />
      <SidebarGroup><SidebarGroupLabel>{zh ? '空间' : 'Spaces'}</SidebarGroupLabel><SidebarGroupContent><SidebarMenu>
        <SidebarMenuItem><SidebarMenuButton tooltip={zh ? '个人空间' : 'Personal'} isActive={currentWorkspace.scope === 'personal'} onClick={selectPersonalWorkspace} className="transition-all duration-200 hover:translate-x-0.5"><span className="flex size-5 items-center justify-center rounded-full bg-foreground text-[9px] font-semibold text-background">P</span><span>{zh ? '个人空间' : 'Personal'}</span>{currentWorkspace.scope === 'personal' ? <SidebarMenuBadge>•</SidebarMenuBadge> : null}</SidebarMenuButton></SidebarMenuItem>
        {teams.map(team => <SidebarMenuItem key={team.id}><SidebarMenuButton tooltip={team.name} isActive={currentWorkspace.scope === 'team' && currentWorkspace.teamId === team.id} onClick={() => selectTeamWorkspace(team.id)} className="transition-all duration-200 hover:translate-x-0.5"><span className="flex size-5 items-center justify-center rounded-full bg-secondary text-[9px] font-semibold">{team.name.slice(0, 1).toUpperCase()}</span><span>{team.name}</span><SidebarMenuBadge>{team.memberCount}</SidebarMenuBadge></SidebarMenuButton></SidebarMenuItem>)}
        <SidebarMenuItem><SidebarMenuButton asChild isActive={location.pathname.startsWith('/team')} tooltip={zh ? '成员与共享' : 'Members & sharing'} className="transition-all duration-200 hover:translate-x-0.5"><NavLink to="/team"><Users /><span>{zh ? '成员与共享' : 'Members & sharing'}</span></NavLink></SidebarMenuButton></SidebarMenuItem>
      </SidebarMenu></SidebarGroupContent></SidebarGroup>
    </SidebarContent>
    <SidebarFooter className="p-3"><SidebarMenu><SidebarMenuItem><SidebarMenuButton asChild isActive={location.pathname.startsWith('/settings')} tooltip={copy.sidebar.settings} className="transition-all duration-200 hover:translate-x-0.5"><NavLink to="/settings"><Settings2 /><span>{copy.sidebar.settings}</span>{!collapsed ? <span className="ml-auto text-[10px] text-muted-foreground">v{packageJson.version}</span> : null}</NavLink></SidebarMenuButton></SidebarMenuItem><SidebarMenuItem><DropdownMenu><DropdownMenuTrigger asChild><SidebarMenuButton size="lg" className="transition-colors duration-200 data-[state=open]:bg-sidebar-accent"><Avatar className="size-8 rounded-lg"><AvatarFallback className="rounded-lg bg-foreground text-background">{user?.email?.[0]?.toUpperCase() || 'V'}</AvatarFallback></Avatar><span className="grid min-w-0 flex-1 text-left leading-tight"><span className="truncate text-sm font-medium">{user?.email?.split('@')[0]}</span><span className="truncate text-xs text-muted-foreground">{user?.email}</span></span><ChevronUp className="ml-auto size-4" /></SidebarMenuButton></DropdownMenuTrigger><DropdownMenuContent side="right" align="end" className="w-60"><DropdownMenuLabel className="truncate">{user?.email}</DropdownMenuLabel><DropdownMenuSeparator /><DropdownMenuGroup><DropdownMenuItem onClick={() => navigate('/settings')}><Settings2 />{copy.sidebar.settings}</DropdownMenuItem><DropdownMenuItem onClick={() => navigate('/team')}><Users />{zh ? '成员与共享' : 'Members & sharing'}</DropdownMenuItem></DropdownMenuGroup><DropdownMenuSeparator /><DropdownMenuItem onClick={async () => { await signOut(); navigate('/login') }}><LogOut />{copy.header.signOut}</DropdownMenuItem></DropdownMenuContent></DropdownMenu></SidebarMenuItem></SidebarMenu></SidebarFooter>
    <SidebarRail />
  </ShadcnSidebar>
}
