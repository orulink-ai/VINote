import { useState } from "react";
import { apiJson } from "@/lib/api";
import {
  Conversation,
  ConversationContent,
  ConversationMessage,
  ConversationScrollButton,
} from "@/components/ui/conversation";
import { MarkdownContent } from "@/components/Markdown/MarkdownContent";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ArrowUp, Loader2, RotateCcw } from "lucide-react";

export function MeetingConversation({
  noteId,
  workspace = false,
  versionId,
  document = false,
}: {
  noteId: string;
  workspace?: boolean;
  versionId?: string;
  document?: boolean;
}) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<
    { question: string; answer: string }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ask = async () => {
    if (busy || !question.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await apiJson<{ answer: string }>(
        workspace
          ? `/api/workspace/notes/${encodeURIComponent(noteId)}/ask`
          : `/api/notes/${encodeURIComponent(noteId)}/ask`,
        {
          method: "POST",
          body: JSON.stringify({
            question,
            ...(workspace && versionId ? { version_id: versionId } : {}),
          }),
        },
      );
      const answer =
        typeof result?.answer === "string" ? result.answer.trim() : "";
      if (!answer) throw new Error("没有收到完整回答，请重试。");
      setMessages((current) => [...current, { question, answer }]);
      setQuestion("");
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col">
      <Conversation>
        <ConversationContent>
          {!messages.length && (
            <div className="mx-auto flex max-w-xl flex-col items-center gap-5 py-12 text-center">
              <div>
                <h2 className="text-lg font-medium">{document ? '读懂这份内容' : '从这次会议继续'}</h2>
                <p className="mt-2 text-sm text-muted-foreground">
                  {document ? '针对这份内容提问，回答依据当前已保存的正文。' : '围绕这次会议提问，回答依据已保存纪要。'}
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {(document ? ['概括核心观点', '解释重点段落', '整理关键要点'] : [
                  "梳理已确认的决定",
                  "整理明确的行动项",
                  "哪些内容仍待确认？",
                ]).map((prompt) => (
                  <Button
                    key={prompt}
                    variant="outline"
                    disabled={busy}
                    className="h-auto min-h-10 rounded-full px-4 py-2 font-normal"
                    onClick={() => setQuestion(prompt)}
                  >
                    {prompt}
                  </Button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message, index) => (
            <div key={index}>
              <ConversationMessage speaker="你">
                {message.question}
              </ConversationMessage>
              <ConversationMessage speaker="VINote">
                <MarkdownContent content={message.answer} />
              </ConversationMessage>
            </div>
          ))}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>
      <div className="flex flex-col gap-3 px-4 pb-4 pt-3">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="rounded-2xl border bg-background p-2 shadow-sm focus-within:ring-1 focus-within:ring-ring">
          <Textarea
            aria-label={document ? '关于这份内容的问题' : '会议问题'}
            placeholder={document ? '这份内容有哪些核心观点？' : '这次会议确认了哪些行动？'}
            value={question}
            maxLength={5000}
            disabled={busy}
            className="max-h-40 min-h-14 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                void ask();
              }
            }}
          />
          <div className="flex items-center justify-between gap-3 pl-2">
            <span className="text-xs text-muted-foreground">
              {busy ? "正在回答…" : "Enter 发送 · Shift + Enter 换行"}
            </span>
            <Button
              size="icon"
              className="size-10 shrink-0 rounded-full"
              aria-label={busy ? "正在回答…" : error ? "重试提问" : "发送"}
              disabled={busy || !question.trim()}
              onClick={() => void ask()}
            >
              {busy ? (
                <Loader2 className="animate-spin" />
              ) : error ? (
                <RotateCcw />
              ) : (
                <ArrowUp />
              )}
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
