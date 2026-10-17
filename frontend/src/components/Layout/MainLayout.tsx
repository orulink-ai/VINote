import { LoadingState } from '@/components/Feedback/ResourceState'
import { PageReturn } from '@/components/Layout/PageReturn'
import { Suspense, useEffect, useRef, useState, type CSSProperties } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter } from '@/components/ui/alert-dialog'
import { WorkspaceSearchDialog } from './WorkspaceSearchDialog'
import { Sidebar } from './Sidebar'
import { MeetingRecorderDock } from '../MeetingRecorder/MeetingRecorderDock'
import { SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'
import { APP_MODE_EVENT, useAppModeStore } from '../../stores/appModeStore'
import { useAuthStore } from '../../stores/authStore'
import { SourceTaskProgress } from './SourceTaskProgress'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { FadeUp } from '@/components/ui/motion'
import { SessionConnection } from './SessionConnection'
import { loadingPageParent, pageParentLabel } from '@/lib/navigation'
import { useMeetingReturnScroll } from '@/hooks/useMeetingReturnScroll'

export function MainLayout() {
  const mainScroll = useRef<HTMLElement | null>(null)
  useMeetingReturnScroll(mainScroll)
  const location = useLocation()
  const navigate = useNavigate()
  const [leaveRequest, setLeaveRequest] = useState<{ to: string; protectedDraft: boolean } | null>(null)
  useEffect(() => {
    const request = (event: Event) => setLeaveRequest((event as CustomEvent<{ to: string; protectedDraft: boolean }>).detail)
    window.addEventListener('vinote:draft-navigation', request)
    return () => window.removeEventListener('vinote:draft-navigation', request)
  }, [])
  const [searchOpen, setSearchOpen] = useState(false)
  const searchOrigin = useRef<HTMLElement | null>(null)
  const openSearch = () => { searchOrigin.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setSearchOpen(true) }
  const isNoteEditor = location.pathname.startsWith('/note/') || location.pathname.startsWith('/workspace/')
  const loadingParent = loadingPageParent(location.pathname, location.search, (location.state as { returnTo?: unknown } | null)?.returnTo)
  const userId = useAuthStore(state => state.user?.id)
  useEffect(() => {
    if (!userId) return
    // Restore this account's device content once; no polling or upload listeners.
    void useWorkspaceStore.getState().initialize(userId).catch(() => undefined)
    return () => useWorkspaceStore.getState().reset()
  }, [userId])
  useEffect(() => {
    useAppModeStore.getState().reset()
    if (!userId) return
    const sync = () => { void useAppModeStore.getState().load() }
    const onStorage = (event: StorageEvent) => { if (event.key === APP_MODE_EVENT) sync() }
    sync()
    window.addEventListener('focus', sync)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener('focus', sync)
      window.removeEventListener('storage', onStorage)
      useAppModeStore.getState().reset()
    }
  }, [userId])

  return (
    <TooltipProvider delayDuration={150}>
      <SidebarProvider defaultOpen style={{ '--sidebar-width': '14.5rem', '--sidebar-width-icon': '4.5rem' } as CSSProperties} className="workspace-shell relative h-full min-h-0">
        <Sidebar onSearch={openSearch} />
        <WorkspaceSearchDialog searchOpen={searchOpen} setSearchOpen={setSearchOpen} onClosed={() => searchOrigin.current?.focus()} />
        <div className="workspace-canvas flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <SessionConnection />
          <div className="flex h-12 shrink-0 items-center justify-between border-b px-4 md:hidden">
            <SidebarTrigger aria-label="打开导航" />
            <span className="text-sm font-semibold">VINote</span>
            <Button size="icon" variant="ghost" aria-label="搜索资料与页面" onClick={openSearch}><Search /></Button>
          </div>
          {import.meta.env.DEV && <SourceTaskProgress key={userId} />}
          <main ref={mainScroll} className={`app-surface stealth-scroll min-h-0 flex-1 ${isNoteEditor ? 'overflow-hidden' : 'overflow-auto'}`}>
            <FadeUp key={location.pathname} className={isNoteEditor ? 'h-full min-h-0 min-w-0' : 'min-h-full'}>
              <Suspense fallback={<div className="workspace-page">{loadingParent && <PageReturn to={loadingParent} label={pageParentLabel(loadingParent)} contextual={false} />}<LoadingState label="正在打开页面…" /></div>}><Outlet key={userId} /></Suspense>
            </FadeUp>
          </main>
        </div>
        <MeetingRecorderDock />
        <AlertDialog open={!!leaveRequest} onOpenChange={open => { if (!open) setLeaveRequest(null) }}><AlertDialogContent>
          <AlertDialogHeader><AlertDialogTitle>离开当前编辑？</AlertDialogTitle><AlertDialogDescription>{leaveRequest?.protectedDraft ? '未提交的修改已保留在当前账号的本机草稿中。返回这份内容可继续编辑。' : '本机草稿保护失败。请留在当前页面，保存或导出内容后再离开。'}</AlertDialogDescription></AlertDialogHeader>
          <AlertDialogFooter><Button variant="outline" onClick={() => setLeaveRequest(null)}>继续编辑</Button><Button disabled={!leaveRequest?.protectedDraft} onClick={() => { if (leaveRequest?.protectedDraft) { navigate(leaveRequest.to); setLeaveRequest(null) } }}>保留草稿并离开</Button></AlertDialogFooter>
        </AlertDialogContent></AlertDialog>
      </SidebarProvider>
    </TooltipProvider>
  )
}
