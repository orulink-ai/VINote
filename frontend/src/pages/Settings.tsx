import { useSearchParams, useLocation, Link, Navigate } from "react-router-dom";
import { pageParentLabel, settingsPageParent } from '@/lib/navigation';
import {
  ChevronRight,
  ArrowLeft,
  Mic2,
  Plug,
  HardDrive,
  Users,
  ListTodo,
  Bell,
} from "lucide-react";
import { DesktopUpdatePanel } from "@/components/Settings/DesktopUpdatePanel";
import { NotificationSettingsPanel } from "@/components/Settings/NotificationSettingsPanel";
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
      className="group -mx-3 flex items-center gap-3 rounded-lg px-3 py-3 transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="grid size-8 shrink-0 place-items-center text-muted-foreground">
        <Icon aria-hidden="true" className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{title}</span>
        <span className="mt-1 block text-xs leading-5 text-muted-foreground">
          {description}
        </span>
      </span>
      <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground group-hover:text-foreground" />
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
    "notifications",
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
      {(activeTab !== 'overview' || hasContext) && <div className="page-return"><Button asChild variant="ghost" size="sm"><Link to={activeTab === 'overview' ? parent : overviewPath}><ArrowLeft data-icon="inline-start" />{activeTab === 'overview' ? pageParentLabel(parent) : '返回设置总览'}</Link></Button></div>}
      <PageHeading
        title="设置"
        description="管理当前设备、内容处理和外部服务。"
      />
      <div className="grid items-start gap-5 lg:grid-cols-[180px_minmax(0,1fr)]">
        <SettingsNav
          activeTab={activeTab}
          onChange={(tab) => setParams(current => { const next = new URLSearchParams(current); next.set('tab', tab); if (hasContext) next.set('returnTo', parent); else next.delete('returnTo'); return next; }, { state: hasContext ? { returnTo: parent } : undefined })}
        />
        <section
          key={activeTab}
          aria-label="设置内容"
          className="min-w-0 bg-background py-1 lg:border-l lg:pl-6"
        >
          {activeTab === 'overview' && <div className="flex flex-col">
            <h2 className="mb-2 text-base font-medium">设置总览</h2>
            <SettingLink parent={parent} to="/settings?tab=profile" title="我的账号" description="当前登录身份。" icon={Users} />
            <SettingLink parent={parent} to="/settings?tab=spaces" title="空间与协作" description="选择个人或团队空间，管理成员。" icon={Users} />
            <SettingLink parent={parent} to="/settings?tab=models" title="转写与总结" description="选择下次处理使用的模型与服务。" icon={Plug} />
            <SettingLink parent={parent} to="/settings?tab=storage" title="存储" description="查看当前设备的内容、原文件与回收站。" icon={HardDrive} />
            <SettingLink parent={parent} to="/settings?tab=notifications" title="任务通知" description="完成或失败时提醒，后台可使用系统通知。" icon={Bell} />
            <SettingLink parent={sectionPath} to="/settings/feishu" title="飞书" description="发布内容与发送通知。" icon={Plug} />
          </div>}
          {activeTab === "profile" && (
            <div className="flex flex-col gap-6">
              <h2 className="text-base font-medium">我的账号</h2>
              <ProfileSettingsPanel email={user?.email} />
            </div>
          )}
          {activeTab === 'spaces' && <div className="flex flex-col gap-4">
              <h2 className="text-base font-medium">空间与协作</h2>
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
          {activeTab === "notifications" && <NotificationSettingsPanel />}
          {activeTab === "recording" && (
            <div className="flex flex-col gap-5">
              <h2 className="text-base font-medium">录制</h2>
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
              <h2 className="text-base font-medium">存储</h2>
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
              <h2 className="text-base font-medium">VINote</h2>
              <DesktopUpdatePanel />
              <p className="text-sm leading-7 text-muted-foreground">
                把讨论与资料整理成可回溯、可继续使用的笔记。
              </p>
              <Button variant="outline" className="w-fit" asChild>
                <Link to={'/tasks?' + new URLSearchParams({ returnTo: sectionPath }).toString()} state={{ returnTo: sectionPath }}>任务与诊断</Link>
              </Button>
              <div className="mt-4 border-t pt-4 text-xs leading-6 text-muted-foreground">
                <p>界面细节参考并适配了 <a className="underline underline-offset-4 hover:text-foreground focus-visible:outline-ring" href="https://github.com/heydamir/unslop" target="_blank" rel="noreferrer">unslop</a>，作者 Damir Sokolovsky（@heydamir）。</p>
                <p>采用 <a className="underline underline-offset-4 hover:text-foreground focus-visible:outline-ring" href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a> 许可；已针对 VINote 的录制、设置与逐字稿界面调整。</p>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
