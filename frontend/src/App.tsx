import { isMeetingController } from "./lib/meetingController";
import { MeetingRecorderController } from "./components/MeetingRecorder/MeetingRecorderController";
import { Suspense, lazy, useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { LoadingState, EmptyState } from "./components/Feedback/ResourceState";
import { AuthGuard } from "./components/Auth/AuthGuard";
import { MainLayout } from "./components/Layout/MainLayout";
import { MeetingRecorderDock } from "./components/MeetingRecorder/MeetingRecorderDock";
import { DesktopTitleBar } from "./components/Layout/DesktopTitleBar";
import { isRecorderWindowRoute } from "./lib/desktopRecorderWindow";
import { useAuthStore } from "./stores/authStore";
import { useThemeStore } from "./stores/themeStore";

const Login = lazy(async () => ({
  default: (await import("./pages/Login")).Login,
}));
const Tasks = lazy(async () => ({
  default: (await import("./pages/Tasks")).Tasks,
}));
const StorageSettings = lazy(async () => ({
  default: (await import("./pages/StorageSettings")).StorageSettings,
}));
const MCPSettings = lazy(async () => ({
  default: (await import("./pages/MCPSettings")).MCPSettings,
}));
const WorkspaceNote = lazy(async () => ({
  default: (await import("./pages/WorkspaceNote")).WorkspaceNote,
}));
const Projects = lazy(() => import('./pages/Projects').then(m => ({ default: m.Projects })));
const Connections = lazy(() => import('./pages/Connections').then(m => ({ default: m.Connections })));
const FileLibrary = lazy(() => import('./pages/FileLibrary').then(m => ({ default: m.FileLibrary })));
const Notes = lazy(async () => ({
  default: (await import("./pages/Notes")).Notes,
}));
const WriteNote = lazy(async () => ({ default: (await import('./pages/WriteNote')).WriteNote }));
const NoteGenerator = lazy(async () => ({
  default: (await import("./pages/NoteGenerator")).NoteGenerator,
}));
const NoteEditor = lazy(async () => ({
  default: (await import("./pages/NoteEditor")).NoteEditor,
}));
const Settings = lazy(async () => ({
  default: (await import("./pages/Settings")).Settings,
}));
const Meetings = lazy(async () => ({
  default: (await import("./pages/Meetings")).Meetings,
}));
const FeishuSettings = lazy(async () => ({
  default: (await import("./pages/FeishuSettings")).FeishuSettings,
}));
const Team = lazy(async () => ({
  default: (await import("./pages/Team")).Team,
}));

function RouteFallback() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background">
      <LoadingState rows={0} label="正在打开页面…" />
    </div>
  );
}

function App() {
  const { resolvedTheme, theme, setTheme, reduceMotion, fontScale } =
    useThemeStore();
  const { initialize, initialized } = useAuthStore();
  const recorderWindowRoute = isRecorderWindowRoute();

  useEffect(() => {
    const updateVisibility = () => {
      document.documentElement.dataset.documentHidden = String(document.hidden);
    };
    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    return () =>
      document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolvedTheme === "dark");
  }, [resolvedTheme]);
  useEffect(() => {
    document.documentElement.dataset.reduceMotion = String(reduceMotion);
    document.documentElement.style.fontSize =
      fontScale === "large" ? "18px" : "16px";
  }, [reduceMotion, fontScale]);
  useEffect(() => {
    const preference = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => {
      if (theme === "system") setTheme("system");
    };
    update();
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, [theme, setTheme]);

  useEffect(() => {
    document.documentElement.classList.toggle(
      "recorder-window-route",
      recorderWindowRoute,
    );
    document.body.classList.toggle(
      "recorder-window-route",
      recorderWindowRoute,
    );
    return () => {
      document.documentElement.classList.remove("recorder-window-route");
      document.body.classList.remove("recorder-window-route");
    };
  }, [recorderWindowRoute]);

  if (!initialized) {
    return <RouteFallback />;
  }

  if (recorderWindowRoute) {
    return (
      <BrowserRouter
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <div className="meeting-recorder-window-route h-dvh w-screen overflow-hidden bg-transparent">
          {isMeetingController() ? (
            <MeetingRecorderController />
          ) : (
            <MeetingRecorderDock autoStart />
          )}
        </div>
      </BrowserRouter>
    );
  }

  return (
    <div className="flex h-dvh min-h-0 flex-col overflow-hidden bg-background">
      <DesktopTitleBar />
      <div className="min-h-0 flex-1">
        <BrowserRouter
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route
                element={
                  <AuthGuard>
                    <MainLayout />
                  </AuthGuard>
                }
              >
                <Route index element={<Navigate to="/meetings" replace />} />
                <Route path="write" element={<WriteNote />} />
                <Route path="assistant" element={<Navigate to="/notes" replace />} />
                <Route
                  path="activity"
                  element={<Navigate to="/tasks" replace />}
                />
                <Route path="tasks" element={<Tasks />} />
                <Route path="meetings" element={<Meetings />} />
                <Route path="notes" element={<Notes />} />
                <Route path="projects" element={<Projects />} />
                <Route path="connections" element={<Connections />} />
                <Route path="files" element={<FileLibrary />} />
                <Route path="generate" element={<NoteGenerator />} />
                <Route path="note/:id" element={<NoteEditor />} />
                <Route path="workspace/:key" element={<WorkspaceNote />} />
                <Route
                  path="archive"
                  element={<Navigate to="/notes?archived=1" replace />}
                />
                <Route path="settings" element={<Settings />} />
                <Route path="settings/feishu" element={<FeishuSettings />} />
                <Route path="settings/mcp" element={<MCPSettings />} />
                <Route path="settings/storage" element={<StorageSettings />} />
                <Route path="settings/sync" element={<StorageSettings />} />
                <Route path="team" element={<Team />} />
                <Route
                  path="*"
                  element={
                    <EmptyState
                      title="找不到这个页面"
                      description="请从左侧导航返回记录、笔记或设置。"
                    />
                  }
                />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
      </div>
    </div>
  );
}

export default App;
