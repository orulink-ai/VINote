import { useState } from "react";
import { Download } from "lucide-react";
import { portableMarkdown } from "@/lib/workspace";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Field, FieldLabel, FieldDescription } from "@/components/ui/field";
import { ErrorState } from "@/components/Feedback/ResourceState";

export function ExportPanel({
  title,
  content,
  version,
  transcript,
  disabled,
}: {
  title: string;
  content: string;
  version: string;
  transcript?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [includeTranscript, setIncludeTranscript] = useState(false);
  const [error, setError] = useState("");
  const payload = `# ${title}\n\n> ${version}\n\n${portableMarkdown(content)}${includeTranscript && transcript ? `\n\n## 逐字稿\n\n${portableMarkdown(transcript)}` : ""}`;
  const download = () => {
    try {
      const url = URL.createObjectURL(
        new Blob([payload], { type: "text/markdown;charset=utf-8" }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download =
        `${title || "笔记"}-${version}`
          .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
          .slice(0, 140) + ".md";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导出失败，请重试");
    }
  };
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        <Download data-icon="inline-start" />
        导出 Markdown
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] overflow-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>导出与预览</DialogTitle>
            <DialogDescription>
              导出当前已保存内容 · {version}
              。附件以文字说明呈现，原始录音可从文件库导出。
            </DialogDescription>
          </DialogHeader>
          <Field orientation="horizontal">
            <Checkbox
              id="export-transcript"
              checked={includeTranscript}
              disabled={!transcript}
              onCheckedChange={(value) => setIncludeTranscript(value === true)}
            />
            <FieldLabel htmlFor="export-transcript">附带逐字稿</FieldLabel>
          </Field>
          {!transcript && (
            <FieldDescription>这份内容尚无已读取的逐字稿。</FieldDescription>
          )}
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md border p-4 text-sm leading-6">
            {payload}
          </pre>
          {error && (
            <ErrorState
              error={error}
              onRetry={download}
              retryLabel="重试导出"
            />
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              返回
            </Button>
            <Button onClick={download}>下载 Markdown</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
