import { isMeetingController } from './lib/meetingController'
import { MeetingRecorderController } from './components/MeetingRecorder/MeetingRecorderController'
import { Suspense, lazy, useEffect } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthGuard } from './components/Auth/AuthGuard'
import { MainLayout } from './components/Layout/MainLayout'
import { MeetingRecorderDock } from './components/MeetingRecorder/MeetingRecorderDock'
import { isRecorderWindowRoute } from './lib/desktopRecorderWindow'
import { useAuthStore } from './stores/authStore'
import { useThemeStore } from './stores/themeStore'

const Login = lazy(async () => ({ default: (await import('./pages/Login')).Login }))
const Home = lazy(async () => ({ default: (await import('./pages/Home')).Home }))
const Notes = lazy(async () => ({ default: (await import('./pages/Notes')).Notes }))
const NoteGenerator = lazy(async () => ({ default: (await import('./pages/NoteGenerator')).NoteGenerator }))
const NoteEditor = lazy(async () => ({ default: (await import('./pages/NoteEditor')).NoteEditor }))
const Settings = lazy(async () => ({ default: (await import('./pages/Settings')).Settings }))
const Meetings = lazy(async () => ({ default: (await import('./pages/Meetings')).Meetings }))
const Team = lazy(async () => ({ default: (await import('./pages/Team')).Team }))

function RouteFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="size-8 animate-spin rounded-full border-2 border-muted border-t-primary" />
    </div>
  )
}

function App() {
  const { resolvedTheme } = useThemeStore()
  const { initialize, initialized } = useAuthStore()
  const recorderWindowRoute = isRecorderWindowRoute()

  useEffect(() => {
    void initialize()
  }, [initialize])

  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolvedTheme === 'dark')
  }, [resolvedTheme])

  useEffect(() => {
    document.documentElement.classList.toggle('recorder-window-route', recorderWindowRoute)
    document.body.classList.toggle('recorder-window-route', recorderWindowRoute)
    return () => {
      document.documentElement.classList.remove('recorder-window-route')
      document.body.classList.remove('recorder-window-route')
    }
  }, [recorderWindowRoute])

  if (!initialized) {
    return <RouteFallback />
  }

  if (recorderWindowRoute) {
    return (
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <div className="meeting-recorder-window-route h-screen w-screen overflow-hidden bg-transparent">
          {isMeetingController() ? <MeetingRecorderController /> : <MeetingRecorderDock autoStart />}
        </div>
      </BrowserRouter>
    )
  }

  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={
            <AuthGuard>
              <MainLayout />
            </AuthGuard>
          }>
            <Route index element={<Home />} />
            <Route path="meetings" element={<Meetings />} />
            <Route path="notes" element={<Notes />} />
            <Route path="generate" element={<NoteGenerator />} />
            <Route path="note/:id" element={<NoteEditor />} />
            <Route path="settings" element={<Settings />} />
            <Route path="team" element={<Team />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App
