import { useSearchParams, useLocation, Link, Navigate } from "react-router-dom";
import { pageParentLabel, settingsPageParent } from '@/lib/navigation';
import {
  ArrowUpRight,
  ArrowLeft,
  Mic2,
  Plug,
  HardDrive,
  Users,
  ListTodo,
} from "lucide-react";
import packageJson from "../../package.json";
import { ModelSourcePanel } from "@/components/Settings/ModelSourcePanel";
import { PageHeading } from "@/components/Layout/PageHeading";
import { AppearanceSettingsPanel } from "@/components/Settings/AppearanceSettingsPanel";
import { ProfileSettingsPanel } from "@/components/Settings/ProfileSettingsPanel";
import {
  SettingsNav,
  type SettingsTab,
} from "@/components/Settings/SettingsNav";
import { useI18n } from "@/lib/i18n";
import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";
import { Button } from "@/components/ui/button";

function SettingLink({
  to,
  title,
  description,
  icon: Icon,
  parent,
}: {
  to: string;
  title: string;
  description: string;
  icon: typeof Plug;
  parent: string;
}) {
  const target = new URL(to, 'https://vinote.invalid');
  if (parent) target.searchParams.set('returnTo', parent);
  return (
    <Link
      to={target.pathname + target.search + target.hash}
      state={parent ? { returnTo: parent } : undefined}
      className="group flex items-center gap-4 border-b py-5 last:border-b-0 focus-visible:rounded-lg focus-visible:outline focus-visible:outline-ring"
    >
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-muted">
        <Icon className="size-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{title}</span>
        <span className="mt-1 block text-xs leading-5 text-muted-foreground">
          {description}
        </span>
      </span>
      <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 motion-reduce:transform-none" />
    </Link>
  );
}
export function Settings() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const parent = settingsPageParent(location.search, location.state?.returnTo) || '';
  const hasContext = !!parent;
  const overviewPath = hasContext ? '/settings?' + new URLSearchParams({ returnTo: parent }).toString() : '/settings';
  const requested = params.get("tab");
  const activeTab: SettingsTab = [
    "overview",
    "spaces",
    "profile",
    "models",
    "appearance",
    "recording",
    "storage",
    "connections",
    "about",
  ].includes(requested || "")
    ? (requested as SettingsTab)
    : "overview";
  // A child flow returns to this settings section. The section retains the
  // original workspace context for the next step back to the overview.
  const sectionParams = new URLSearchParams({ tab: activeTab });
  if (hasContext) sectionParams.set('returnTo', parent);
  const sectionPath = '/settings?' + sectionParams.toString();
  const { user } = useAuthStore();
  const { theme, setTheme } = useThemeStore();
  const { language, setLanguage } = useI18n();
  if (activeTab === 'connections') return <Navigate to={parent ? '/connections?' + new URLSearchParams({ returnTo: parent }).toString() : '/connections'} state={parent ? { returnTo: parent } : undefined} replace />;
  return (
    <div className="workspace-page max-w-5xl">
      {(activeTab !== 'overview' || hasContext) && <div><Button asChild variant="ghost" size="sm"><Link to={activeTab === 'overview' ? parent : overviewPath}><ArrowLeft data-icon="inline-start" />{activeTab === 'overview' ? pageParentLabel(parent) : '返回设置总览'}</Link></Button></div>}
      <PageHeading
        title="设置"
        description="管理当前设备、内容处理和外部服务。"
      />
      <div className="grid items-start gap-6 lg:grid-cols-[190px_minmax(0,1fr)]">
        <SettingsNav
          activeTab={activeTab}
          onChange={(tab) => setParams(current => { const next = new URLSearchParams(current); next.set('tab', tab); if (hasContext) next.set('returnTo', parent); else next.delete('returnTo'); return next; }, { state: hasContext ? { returnTo: parent } : undefined })}
        />
        <section
          key={activeTab}
          aria-label="设置内容"
          className="min-w-0 rounded-2xl border bg-background p-6 sm:p-8"
        >
          {activeTab === 'overview' && <div className="flex flex-col gap-4">
            <h2 className="text-lg font-medium">你想调整什么？</h2>
            <SettingLink parent={parent} to="/settings?tab=profile" title="我的账号" description="当前登录身份。" icon={Users} />
            <SettingLink parent={parent} to="/settings?tab=spaces" title="空间与协作" description="选择个人或团队空间，管理成员。" icon={Users} />
            <SettingLink parent={parent} to="/settings?tab=models" title="转写与总结" description="选择下次处理使用的模型与服务。" icon={Plug} />
            <SettingLink parent={parent} to="/settings?tab=storage" title="存储" description="查看当前设备的内容、原文件与回收站。" icon={HardDrive} />
            <SettingLink parent={sectionPath} to="/connections" title="连接与工具" description="飞书发布与通知，以及可选 MCP 工具。" icon={Plug} />
          </div>}
          {activeTab === "profile" && (
            <div className="flex flex-col gap-6">
              <h2 className="text-lg font-medium">我的账号</h2>
              <ProfileSettingsPanel email={user?.email} />
            </div>
          )}
          {activeTab === 'spaces' && <div className="flex flex-col gap-4">
              <h2 className="text-lg font-medium">空间与协作</h2>
              <SettingLink
                parent={sectionPath}
                to="/team"
                title="空间与成员"
                description="管理已有团队、成员及共享内容访问权限。"
                icon={Users}
              />
            </div>}
          {activeTab === "models" && <ModelSourcePanel />}
          {activeTab === "appearance" && (
            <AppearanceSettingsPanel
              theme={theme}
              language={language}
              onThemeChange={setTheme}
              onLanguageChange={setLanguage}
            />
          )}
          {activeTab === "recording" && (
            <div className="flex flex-col gap-5">
              <h2 className="text-lg font-medium">录制</h2>
              <p className="text-sm leading-7 text-muted-foreground">
                麦克风与权限在当前设备上选择。开始会议后选择是否录屏，结束后先保存完整媒体，再决定是否生成纪要。
              </p>
              <SettingLink
                parent={sectionPath}
                to="/meetings"
                title="麦克风与录制准备"
                description="选择设备、检查权限并开始会议。"
                icon={Mic2}
              />
              <p className="text-xs text-muted-foreground">
                屏幕录制不代表已采集系统声音。录制过程不会调用转写或总结。
              </p>
            </div>
          )}
          {activeTab === "storage" && (
            <div className="flex flex-col gap-5">
              <h2 className="text-lg font-medium">存储</h2>
              <SettingLink
                parent={sectionPath}
                to="/settings/storage"
                title="内容与回收站"
                description="查看当前设备保存的正文与版本，恢复移入回收站的内容。"
                icon={HardDrive}
              />
              <SettingLink
                parent={sectionPath}
                to="/tasks"
                title="任务与恢复"
                description="查看实际运行位置，从失败步骤继续。"
                icon={ListTodo}
              />
            </div>
          )}
          {activeTab === "about" && (
            <div className="flex flex-col gap-4">
              <h2 className="text-lg font-medium">VINote</h2>
              <p className="text-sm text-muted-foreground">
                版本 {packageJson.version}
              </p>
              <p className="text-sm leading-7 text-muted-foreground">
                把讨论与资料整理成可回溯、可继续使用的笔记。
              </p>
              <Button variant="outline" className="w-fit" asChild>
                <Link to={'/tasks?' + new URLSearchParams({ returnTo: sectionPath }).toString()} state={{ returnTo: sectionPath }}>任务与诊断</Link>
              </Button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
