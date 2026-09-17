import { useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { Header } from './Header'
import { Sidebar } from './Sidebar'
import { MeetingRecorderDock } from '../MeetingRecorder/MeetingRecorderDock'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { APP_MODE_EVENT, useAppModeStore } from '../../stores/appModeStore'
import { useAuthStore } from '../../stores/authStore'

export function MainLayout() {
  const userId = useAuthStore(state => state.user?.id)
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
      <SidebarProvider defaultOpen>
        <Sidebar />
        <SidebarInset className="h-svh min-w-0 overflow-hidden bg-background">
          <Header />
          <main className="app-surface stealth-scroll min-h-0 flex-1 overflow-auto"><Outlet /></main>
        </SidebarInset>
        <MeetingRecorderDock />
      </SidebarProvider>
    </TooltipProvider>
  )
}
