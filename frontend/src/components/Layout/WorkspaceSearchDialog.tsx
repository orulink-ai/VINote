import {
  FileText,
  ListTodo,
  Mic2, Folder, Plug,
  Settings2,
  ArrowUpRight,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useNoteLibraryStore } from "@/stores/noteLibraryStore";
import { useTeamStore } from "@/stores/teamStore";
import { useLibraryNotes, libraryNoteUrl } from "@/hooks/useLibraryNotes";
import { notePreview } from "@/lib/notePreview";
import { Button } from "@/components/ui/button";
import { requestPageNavigation } from '@/lib/navigation';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";


const destinations = [
  { path: "/projects", icon: Folder, label: "项目", context: "按项目查看内容" },
  { path: "/connections", icon: Plug, label: "插件", context: "飞书与 MCP 工具" },
  { path: "/files", icon: Folder, label: "文件库", context: "当前设备上的原始文件" },
  {
    path: "/notes",
    icon: FileText,
    label: "笔记",
    context: "笔记、纪要与全部版本",
  },
  { path: "/tasks", icon: ListTodo, label: "任务与恢复", context: "处理进度与失败恢复" },
  { path: "/meetings", icon: Mic2, label: "会议", context: "设备、原件与历史" },
  {
    path: "/settings",
    icon: Settings2,
    label: "设置",
    context: "让 VINote 适合你的工作方式",
  },
];
export function WorkspaceSearchDialog({ searchOpen, setSearchOpen, onClosed }: {
  searchOpen: boolean;
  setSearchOpen: React.Dispatch<React.SetStateAction<boolean>>;
  onClosed?: () => void;
}) {
  const navigate = useNavigate();
  const { loading, error, loadNotes } = useNoteLibraryStore();
  const { currentWorkspace } = useTeamStore();
  const notes = useLibraryNotes();
  const focusOrigin = useRef<HTMLElement | null>(null);
  const [query, setQuery] = useState('');
  useEffect(() => { if (searchOpen) setQuery('') }, [searchOpen]);
  useEffect(() => {
    if (searchOpen) void loadNotes(currentWorkspace);
  }, [searchOpen, currentWorkspace, loadNotes]);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        if (!searchOpen && document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]')) return;
        event.preventDefault();
        setSearchOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [setSearchOpen, searchOpen]);
  const open = (path: string) => {
    setSearchOpen(false);
    requestPageNavigation(path, navigate);
  };
  return (
    <>
      <Dialog open={searchOpen} onOpenChange={setSearchOpen}>
        <DialogContent onOpenAutoFocus={() => { focusOrigin.current = document.activeElement instanceof HTMLElement ? document.activeElement : null }} onCloseAutoFocus={event => { if (focusOrigin.current?.isConnected) { event.preventDefault(); focusOrigin.current.focus() } else if (onClosed) { onClosed() } }} className="workspace-command overflow-hidden p-0 sm:max-w-2xl">
          <DialogTitle className="sr-only">搜索资料与页面</DialogTitle>
          <DialogDescription className="sr-only">
            查找当前空间的笔记与会议，或快速打开功能页面。
          </DialogDescription>
          <Command>
            <div className="workspace-command-heading"><span>快速查找</span><kbd>ESC 关闭</kbd></div>
            <CommandInput value={query} onValueChange={setQuery} aria-label="搜索资料与页面" placeholder="搜索当前空间的内容，或输入页面名称…" />
            <CommandList>
              <CommandEmpty>没有匹配结果，试试其他关键词。</CommandEmpty>
              <CommandGroup heading="页面快捷入口">
                {destinations.map((item) => (
                  <CommandItem key={item.path} onSelect={() => open(item.path)}>
                    <item.icon />
                    <span>{item.label}</span>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {item.context}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
              <CommandSeparator />
              <CommandGroup heading={query.trim() ? '匹配内容 · 当前空间' : '最近内容 · 当前空间'}>
                {(query.trim() ? notes : notes.slice(0, 5)).map((note) => (
                  <CommandItem
                    key={note.id}
                    aria-label={note.title.slice(0, 120)}
                    value={`${note.title} ${notePreview(note.content).slice(0, 200)}`}
                    onSelect={() => open(libraryNoteUrl(note))}
                  >
                    <FileText />
                    <span className="min-w-0 flex-1 truncate">
                      {note.title}
                    </span>
                    <ArrowUpRight />
                  </CommandItem>
                ))}
                {loading && (
                  <p
                    role="status"
                    className="p-4 text-xs text-muted-foreground"
                  >
                    正在更新资料…
                  </p>
                )}
                {error && (
                  <div className="p-4">
                    <p role="alert" className="text-xs text-destructive">
                      {error}
                    </p>
                    <Button
                      variant="outline"
                      onClick={() => void loadNotes(currentWorkspace)}
                    >
                      重新读取本机资料
                    </Button>
                  </div>
                )}
              </CommandGroup>
            </CommandList>
          </Command>
          <div className="workspace-command-footer"><span>↑ ↓ 选择</span><span>↵ 打开</span><span className="ml-auto">当前空间</span></div>
        </DialogContent>
      </Dialog>
    </>
  );
}
