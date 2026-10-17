import {
  Bot,
  HardDrive,
  Info,
  Mic2,
  Palette,
  Plug,
  User,
  LayoutGrid,
  Users,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
export type SettingsTab =
  | "overview"
  | "spaces"
  | "profile"
  | "models"
  | "appearance"
  | "recording"
  | "storage"
  | "connections"
  | "about";
const tabs: { key: SettingsTab; label: string; icon: LucideIcon }[] = [
  { key: "overview", label: "设置总览", icon: LayoutGrid },
  { key: "profile", label: "我的账号", icon: User },
  { key: "spaces", label: "空间与协作", icon: Users },
  { key: "models", label: "转写与总结", icon: Bot },
  { key: "recording", label: "录制", icon: Mic2 },
  { key: "appearance", label: "外观与语言", icon: Palette },
  { key: "storage", label: "存储", icon: HardDrive },
  { key: "connections", label: "连接与工具", icon: Plug },
  { key: "about", label: "关于", icon: Info },
];
export function SettingsNav({
  activeTab,
  onChange,
}: {
  activeTab: SettingsTab;
  onChange: (tab: SettingsTab) => void;
}) {
  const groups: { label: string; keys: SettingsTab[] }[] = [
    { label: "账号与协作", keys: ["overview", "profile", "spaces"] },
    { label: "使用偏好", keys: ["appearance"] },
    { label: "当前设备与处理", keys: ["models", "recording", "storage"] },
    { label: "服务", keys: ["about"] },
  ];
  return (
    <nav
      aria-label="设置分类"
      className="flex flex-col gap-5 rounded-2xl border bg-muted/30 p-3"
    >
      {groups.map((group) => (
        <section key={group.label} className="flex flex-col gap-1">
          <h2 className="px-3 pb-1 pt-2 text-[11px] font-medium text-muted-foreground">
            {group.label}
          </h2>
          {group.keys.map((key) => {
            const tab = tabs.find((item) => item.key === key)!;
            return (
              <Button
                key={tab.key}
                aria-current={activeTab === tab.key ? "page" : undefined}
                onClick={() => onChange(tab.key)}
                variant={activeTab === tab.key ? "secondary" : "ghost"}
                className="h-10 w-full justify-start"
              >
                <tab.icon data-icon="inline-start" />
                {tab.label}
              </Button>
            );
          })}
        </section>
      ))}
    </nav>
  );
}
