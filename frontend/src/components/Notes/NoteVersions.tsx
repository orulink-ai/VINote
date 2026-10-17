import { useEffect, useState } from "react";
import { GitBranch } from "lucide-react";
import { apiJson } from "@/lib/api";
import { MarkdownContent } from "@/components/Markdown/MarkdownContent";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { VersionCompare } from "./VersionCompare";
import { LoadingState, EmptyState } from "@/components/Feedback/ResourceState";

type Version = {
  id: string;
  title: string;
  content: string;
  created_at: string;
};
export function NoteVersions({
  noteId,
  revision,
  currentContent = "",
  onRestore,
}: {
  noteId: string;
  revision?: string;
  currentContent?: string;
  onRestore?: (title: string, content: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Version[]>([]);
  const [selected, setSelected] = useState<Version | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [compare, setCompare] = useState(false);
  useEffect(() => {
    let active = true;
    setLoaded(false);
    setItems([]);
    if (open)
      void apiJson<Version[]>(`/api/notes/${noteId}/versions`)
        .then((next) => {
          if (active && Array.isArray(next)) {
            setItems(next);
            setLoaded(true);
          }
        })
        .catch((cause) => {
          if (active) setError(cause.message);
        });
    return () => {
      active = false;
    };
  }, [noteId, revision, open]);
  const load = async () => {
    setBusy(true);
    setError("");
    try {
      const next = await apiJson<Version[]>(`/api/notes/${noteId}/versions`);
      if (!Array.isArray(next)) throw new Error("版本列表格式无效，请重新加载");
      setItems(next);
      setLoaded(true);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        className="h-7 px-0 text-xs text-muted-foreground"
        aria-label="历史版本"
        onClick={() => {
          setOpen(true);
          setSelected(null);
          setCompare(false);
        }}
      >
        <GitBranch data-icon="inline-start" />
        {loaded ? `${items.length} 次历史修订` : "版本与修订"}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="flex max-h-[85vh] flex-col gap-4 overflow-auto sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle>历史版本</DialogTitle>
            <DialogDescription>
              每次保存正文修改会保留之前内容。查看版本不覆盖当前纪要。
            </DialogDescription>
          </DialogHeader>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
              <Button variant="outline" onClick={() => void load()}>
                重试加载
              </Button>
            </Alert>
          )}
          {busy ? (
            <LoadingState label="正在读取历史修订…" />
          ) : selected ? (
            <>
              <Button variant="ghost" onClick={() => setSelected(null)}>
                返回列表
              </Button>
              <h2>{selected.title}</h2>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => setCompare(!compare)}>
                  {compare ? "阅读此版本" : "与当前正文比较"}
                </Button>
                {onRestore && (
                  <Button
                    onClick={() => {
                      onRestore(selected.title, selected.content);
                      setOpen(false);
                    }}
                  >
                    恢复到草稿，保存为新修订
                  </Button>
                )}
              </div>
              {compare ? (
                <VersionCompare
                  left={selected.content}
                  right={currentContent}
                />
              ) : (
                <MarkdownContent
                  content={selected.content}
                  className="prose break-words dark:prose-invert"
                />
              )}
            </>
          ) : items.length ? (
            items.map((version, index) => (
              <Button
                key={version.id}
                variant="outline"
                onClick={() => setSelected(version)}
              >
                {items.length - index} ·{" "}
                {new Date(version.created_at).toLocaleString()}
              </Button>
            ))
          ) : (
            !error && (
              <EmptyState
                title="尚无历史修订"
                description="修改并保存后，之前的正文会保留在这里。生成版本可在共享内容详情查看。"
              />
            )
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
