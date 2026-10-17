import { resolvePageParent, pageParentLabel } from '@/lib/navigation';
import { noteOrigin } from "@/lib/noteOrigin";
import { FeishuDelivery } from "@/components/Notes/FeishuDelivery";
import { FeishuDocumentFooter } from "@/components/Notes/FeishuDocumentFooter";
import { RecordingWaveform } from "@/components/Notes/RecordingWaveform";
import { MeetingConversation } from "@/components/Notes/MeetingConversation";
import { NoteVersions } from "@/components/Notes/NoteVersions";
import { ExportPanel } from "@/components/Notes/ExportPanel";
import { LoadingState } from "@/components/Feedback/ResourceState";
import { useAuthStore } from "@/stores/authStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import {
  readTextDraft,
  removeTextDraft,
  useProtectedDraft,
} from "@/hooks/useProtectedDraft";
import { Label } from "../components/ui/label";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Copy,
  Edit3,
  Eye,
  Trash2,
  Save,
  Share2,
  Maximize2,
  Minimize2,
  ListVideo,
  MoreHorizontal,
} from "lucide-react";
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { MarkdownContent } from "../components/Markdown/MarkdownContent";
import { KeyMomentsRail } from "../components/Notes/KeyMomentsRail";
import { VideoReferencePanel } from "../components/Notes/VideoReferencePanel";
import { SavedRecordingActions } from "../components/Notes/SavedRecordingActions";
import { RecordingRetryBar } from "../components/Notes/RecordingRetryBar";
import { TranscriptEvidencePanel } from "../components/Notes/TranscriptEvidencePanel";
import { apiJson } from "../lib/api";
import { findActiveKeyMoment, type KeyMoment } from "../lib/markdownKeyMoments";
import {
  renderTranscriptMarkdown,
  type TranscriptEvidence,
  type TranscriptTextMode,
} from "../lib/noteTranscript";
import { useI18n } from "../lib/i18n";
import { resolveContentUrl } from "../lib/videoLinks";
import {
  type NoteRecord,
  type NoteShareRecord,
  useNoteLibraryStore,
} from "../stores/noteLibraryStore";
import { Button } from "../components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { Alert, AlertDescription } from "../components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../components/ui/alert-dialog";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "../components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "../components/ui/resizable";


type WorkspaceMode = "write" | "split" | "preview";
type NoteView = "summary" | "transcript" | "chat";

const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const TIMESTAMP_LINK_RE = /\[(\d{1,2}:\d{2})(?:-\d{1,2}:\d{2})?\]\(([^)]+)\)/;
const IMAGE_RE = /!\[[^\]]*]\(([^)\s]+)(?:\s+"[^"]*")?\)/;

function deriveKeyMoments(content: string): KeyMoment[] {
  const lines = content.split(/\r?\n/);
  const sections: Array<{ level: number; heading: string; body: string[] }> =
    [];
  let current: { level: number; heading: string; body: string[] } | null = null;

  for (const line of lines) {
    const headingMatch = line.match(HEADING_RE);
    if (headingMatch) {
      if (current) {
        sections.push(current);
      }
      current = {
        level: headingMatch[1].length,
        heading: headingMatch[2],
        body: [],
      };
      continue;
    }

    if (current) {
      current.body.push(line);
    }
  }

  if (current) {
    sections.push(current);
  }

  return sections.flatMap((section) => {
    if (section.level < 2) {
      return [];
    }

    const timestampMatch = findTimestamp(section.heading, section.body);
    if (!timestampMatch) {
      return [];
    }

    const plainHeading = stripMarkdown(section.heading);
    return [
      {
        anchorId: slugifyHeading(plainHeading),
        title: plainHeading.replace(timestampMatch.label, "").trim(),
        timestampLabel: timestampMatch.label,
        seconds: timestampMatch.seconds,
        imageUrl: findImage(section.body),
        excerpt: findExcerpt(section.body),
        level: section.level,
      },
    ];
  });
}
function findTimestamp(heading: string, body: string[]) {
  const headingMatch = heading.match(TIMESTAMP_LINK_RE);
  if (headingMatch) {
    return {
      label: headingMatch[1],
      seconds: parseSeconds(headingMatch[1], headingMatch[2]),
    };
  }

  for (const line of body) {
    const lineMatch = line.match(TIMESTAMP_LINK_RE);
    if (lineMatch) {
      return {
        label: lineMatch[1],
        seconds: parseSeconds(lineMatch[1], lineMatch[2]),
      };
    }
  }

  return null;
}
function findImage(lines: string[]) {
  for (const line of lines) {
    const imageMatch = line.match(IMAGE_RE);
    if (imageMatch) {
      return resolveContentUrl(imageMatch[1]);
    }
  }

  return undefined;
}

function findExcerpt(lines: string[]) {
  for (const line of lines) {
    if (!line.trim() || IMAGE_RE.test(line)) {
      continue;
    }

    const excerpt = stripMarkdown(line);
    if (excerpt) {
      return excerpt.length > 140 ? `${excerpt.slice(0, 137)}...` : excerpt;
    }
  }

  return undefined;
}

function parseSeconds(label: string, href: string) {
  const queryMatch = href.match(/[?&](?:t|start|time_continue)=(\d+)/);
  if (queryMatch) {
    return Number.parseInt(queryMatch[1], 10);
  }

  const [minutes, seconds] = label
    .split(":")
    .map((value) => Number.parseInt(value, 10));
  return minutes * 60 + seconds;
}

function stripMarkdown(text: string) {
  return text
    .replace(TIMESTAMP_LINK_RE, "$1")
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/[*_`>#]/g, " ")
    .replace(/!\[[^\]]*]\([^)]+\)/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function slugifyHeading(text: string) {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-");
}

export function NoteEditor() {
  const { id } = useParams();
  const owner = useAuthStore((state) => state.user?.id);
  const sharedKey = useWorkspaceStore((state) =>
    id ? (state.mappings[id]?.revision > 0 ? state.mappings[id].key : state.items.find(note => note.key === `desktop-${id}` && note.revision > 0)?.key) : undefined,
  );
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const origin = (location.state as { returnTo?: unknown } | null)?.returnTo ?? searchParams.get("returnTo");
  const returnTo = resolvePageParent(origin);
  const { copy, locale } = useI18n();
  const {
    loadNoteById,
    updateNote,
    createShareLink,
    getShareLink,
    disableShareLink,
  } = useNoteLibraryStore();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deliveryRevision, setDeliveryRevision] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const deleteButtonRef = useRef<HTMLButtonElement>(null);
  const zh = locale.startsWith("zh");
  const previewRef = useRef<HTMLDivElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [momentsOpen, setMomentsOpen] = useState(false);
  const [videoExpanded, setVideoExpanded] = useState(false);
  const editRequested = searchParams.get('edit') === '1';
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>(editRequested ? "write" : "preview");
  useEffect(() => setWorkspaceMode(editRequested ? "write" : "preview"), [id, editRequested]);
  const [localTitle, setLocalTitle] = useState("");
  const [content, setContent] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [taskId, setTaskId] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [generationClient, setGenerationClient] = useState<
    string | undefined
  >();
  const [noteScope, setNoteScope] = useState<"personal" | "team">("personal");
  const [noteWorkspaceName, setNoteWorkspaceName] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [shareLoading, setShareLoading] = useState(false);
  const [shareState, setShareState] = useState<NoteShareRecord | null>(null);
  const [shareMessage, setShareMessage] = useState("");
  const [shareError, setShareError] = useState("");
  const [sharePanelOpen, setSharePanelOpen] = useState(false);
  const [error, setError] = useState("");
  const [currentNote, setCurrentNote] = useState<NoteRecord | null>(null);
  const isMeetingContent = !!currentNote?.sourceType?.startsWith('meeting_');
  const hasMediaTranscript = !!taskId && !['file', 'text', 'document', 'transcript'].includes(currentNote?.sourceType || '');
  const hasUnsavedChanges =
    !!currentNote &&
    (localTitle !== currentNote.title || content !== currentNote.content);
  const draftStatus = useProtectedDraft(
    id ? `local:${id}` : "",
    localTitle,
    content,
    hasUnsavedChanges && currentNote?.id === id,
    currentNote?.updatedAt,
  );
  const [leaveOpen, setLeaveOpen] = useState(false);
  const [mediaError, setMediaError] = useState("");
  const [mediaAttempt, setMediaAttempt] = useState(0);
  const [currentTimestamp, setCurrentTimestamp] = useState(0);
  const [jumpRequestId, setJumpRequestId] = useState(0);
  const [keyMoments, setKeyMoments] = useState<KeyMoment[]>([]);
  const [transcriptEvidence, setTranscriptEvidence] =
    useState<TranscriptEvidence | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [transcriptError, setTranscriptError] = useState("");
  const [transcriptAttempt, setTranscriptAttempt] = useState(0);
  const [transcriptTextMode, setTranscriptTextMode] =
    useState<TranscriptTextMode>("clean");

  const noteView: NoteView =
    searchParams.get("view") === "transcript"
      ? "transcript"
      : searchParams.get("view") === "chat"
        ? "chat"
        : "summary";
  const detailParams = new URLSearchParams(searchParams);
  detailParams.set("returnTo", returnTo);
  const detailReturnTo = location.pathname + "?" + detailParams.toString() + location.hash;
  const sourceFilesPath = id ? `/files?${new URLSearchParams({ note: id, returnTo: detailReturnTo }).toString()}` : '';
  // Merge only an exactly matching first H1 while reading. Saved/exported text is unchanged.
  const previewContent = workspaceMode === "preview"
    ? content.replace(/^#[ \t]+([^\r\n]+)(?:\r?\n|$)/, (heading, title: string) =>
        title.trim() === localTitle.trim() ? "" : heading)
    : content;
  const activeMoment = findActiveKeyMoment(keyMoments, currentTimestamp);
  const [recordingDeleted, setRecordingDeleted] = useState(false);
  useEffect(() => setRecordingDeleted(false), [id]);
  const localMediaUrl =
    id && taskId && !recordingDeleted ? `/api/notes/${id}/media` : undefined;
  const isAudioNote =
    Boolean(localMediaUrl) &&
    ["audio", "meeting_recording"].includes(sourceType);
  const isVideoNote =
    Boolean(localMediaUrl) && ["video", "meeting_video"].includes(sourceType);
  const splitLabel = locale.startsWith("zh") ? "对照" : "Split";
  const workspaceBadge =
    noteScope === "team"
      ? noteWorkspaceName ||
        (zh ? isMeetingContent ? "团队纪要" : "团队笔记" : isMeetingContent ? "Team meeting notes" : "Team note")
      : zh
        ? isMeetingContent ? "个人纪要" : "个人笔记"
        : isMeetingContent ? "Personal meeting notes" : "Personal note";
  const shareUrl = shareState?.shareEnabled ? shareState.shareUrl : undefined;
  const shareCopy = {
    title: locale.startsWith("zh") ? "分享链接" : "Share link",
    description: locale.startsWith("zh")
      ? "生成一个后端托管的公开链接，局域网内的其他设备可以直接打开。"
      : "Create a backend-hosted public link that other devices on your LAN can open directly.",
    create: locale.startsWith("zh") ? "创建链接" : "Create link",
    copy: locale.startsWith("zh") ? "复制链接" : "Copy link",
    disable: locale.startsWith("zh") ? "停用分享" : "Disable sharing",
    disabled: locale.startsWith("zh")
      ? "尚未创建分享链接。"
      : "Sharing is currently disabled.",
    created: locale.startsWith("zh") ? "分享链接已创建" : "Share link created",
    copied: locale.startsWith("zh")
      ? "分享链接已复制到剪贴板"
      : "Share link copied to clipboard",
    copyBlocked: locale.startsWith("zh")
      ? "浏览器阻止了剪贴板访问，请手动复制下方链接。"
      : "Clipboard access is blocked in this browser. Copy the link below manually.",
    createFailed: locale.startsWith("zh")
      ? "创建分享链接失败"
      : "Failed to create share link",
    disableFailed: locale.startsWith("zh")
      ? "停用分享失败，请重试"
      : "Failed to disable sharing",
    disabledSuccess: locale.startsWith("zh")
      ? "分享已停用，原链接不再可用。"
      : "Sharing disabled. The old link is no longer accessible.",
  };

  useEffect(() => {
    let active = true;

    async function loadNote() {
      setLoading(true);
      setError("");
      if (!id) {
        setError(copy.noteEditor.missingId);
        setLoading(false);
        return;
      }

      const note = await loadNoteById(id);
      if (!active) {
        return;
      }

      if (!note) {
        setError(copy.noteEditor.notFound);
        setLoading(false);
        return;
      }

      let draft = null;
      try {
        if (owner) draft = readTextDraft(owner, `local:${note.id}`);
      } catch {
        /* The saved content remains readable. */
      }
      setLocalTitle(draft?.title ?? note.title);
      setContent(draft?.content ?? note.content);
      if (draft) setWorkspaceMode("write");
      setVideoUrl(note.videoUrl || "");
      setTaskId(note.taskId || "");
      setSourceType(note.sourceType || "");
      setGenerationClient(note.generationClient);
      setNoteScope(note.scope);
      setNoteWorkspaceName(note.teamName || "");
      setCurrentNote(note);
      setError("");
      setLoading(false);

      const existingShare = await getShareLink(note.id);
      if (!active || !existingShare) {
        return;
      }

      setShareState(existingShare);
    }

    void loadNote().catch((cause) => {
      if (active) {
        setError(
          cause instanceof Error ? cause.message : copy.noteEditor.notFound,
        );
        setLoading(false);
      }
    });

    return () => {
      active = false;
    };
  }, [
    copy.noteEditor.missingId,
    copy.noteEditor.notFound,
    getShareLink,
    id,
    loadNoteById,
    loadAttempt,
  ]);

  useEffect(() => {
    setKeyMoments(deriveKeyMoments(content));
  }, [content]);

  useEffect(() => {
    let active = true;

    async function loadTranscript() {
      if (!id || !hasMediaTranscript) {
        setTranscriptEvidence(null);
        return;
      }
      setTranscriptLoading(true);
      setTranscriptError("");
      try {
        const evidence = await apiJson<TranscriptEvidence>(
          `/api/notes/${id}/transcript`,
        );
        if (active) setTranscriptEvidence(evidence);
      } catch (cause) {
        if (active) {
          setTranscriptEvidence(null);
          setTranscriptError(
            cause instanceof Error
              ? cause.message
              : "Failed to load transcript",
          );
        }
      } finally {
        if (active) setTranscriptLoading(false);
      }
    }

    void loadTranscript();
    return () => {
      active = false;
    };
  }, [id, taskId, hasMediaTranscript, transcriptAttempt]);

  const handleSave = async () => {
    if (!id || saving || !hasUnsavedChanges) return;
    setSaving(true);
    try {
      const updated = await updateNote(id, localTitle, content);
      if (!updated) throw new Error(copy.noteEditor.saveFailed);
      setLocalTitle(updated.title);
      setContent(updated.content);
      setCurrentNote(updated);
      if (owner) {
        try {
          removeTextDraft(owner, `local:${id}`);
        } catch {
          /* Save already persisted to the backend. */
        }
      }
      setError("");
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : copy.noteEditor.saveFailed,
      );
    } finally {
      setSaving(false);
    }
  };

  const copyShareUrl = async (
    url: string,
    options?: { silentFailure?: boolean },
  ) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        setShareMessage(shareCopy.copied);
        setShareError("");
        return true;
      }
    } catch (copyError) {
      console.error("Failed to copy share url:", copyError);
    }

    if (options?.silentFailure) {
      setShareMessage(shareCopy.copyBlocked);
    } else {
      setShareMessage(shareCopy.copyBlocked);
    }
    setShareError("");
    return false;
  };

  const handleShare = async () => {
    if (!id) {
      return;
    }

    setSharePanelOpen(true);
    setShareLoading(true);
    setShareMessage("");
    setShareError("");

    const nextShareState = await createShareLink(id);
    setShareLoading(false);

    const nextShareUrl = nextShareState?.shareUrl;

    if (!nextShareState?.shareEnabled || !nextShareUrl) {
      setShareError(shareCopy.createFailed);
      return;
    }

    setShareState(nextShareState);
    setShareMessage(shareCopy.created);
    await copyShareUrl(nextShareUrl, { silentFailure: true });
  };

  const handleDisableShare = async () => {
    if (!id) {
      return;
    }

    setShareLoading(true);
    setShareMessage("");
    setShareError("");

    const nextShareState = await disableShareLink(id);
    setShareLoading(false);

    if (!nextShareState) {
      setShareError(shareCopy.disableFailed);
      return;
    }

    setShareState(nextShareState);
    setShareMessage(shareCopy.disabledSuccess);
  };

  const selectedText = () =>
    noteView === "transcript" && transcriptEvidence
      ? renderTranscriptMarkdown(transcriptEvidence, transcriptTextMode)
      : content;

  const handleCopyBody = async () => {
    try {
      await navigator.clipboard.writeText(selectedText());
    } catch {
      setError(
        zh
          ? "无法复制正文，请检查剪贴板权限或下载正文。"
          : "Could not copy text. Check clipboard permission or download it.",
      );
    }
  };

  const scrollPreviewToAnchor = (anchorId: string) => {
    const escape = window.CSS?.escape ?? ((value: string) => value);
    const target = previewRef.current?.querySelector<HTMLElement>(
      `#${escape(anchorId)}`,
    );
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const jumpToTimestamp = (seconds: number, anchorId?: string) => {
    setCurrentTimestamp(seconds);
    setJumpRequestId((value) => value + 1);

    if (isAudioNote && audioRef.current) {
      audioRef.current.currentTime = seconds;
      void audioRef.current.play().catch(() => {
        // The seek remains valid when autoplay is blocked.
      });
      return;
    }
    if (isVideoNote && videoRef.current) {
      videoRef.current.currentTime = seconds;
      void videoRef.current.play().catch(() => {
        // The seek remains valid when autoplay is blocked.
      });
      return;
    }

    if (workspaceMode === "write") {
      setWorkspaceMode("preview");
    }

    if (anchorId) {
      requestAnimationFrame(() => {
        scrollPreviewToAnchor(anchorId);
      });
    }
  };

  const handleSelectMoment = (moment: KeyMoment) => {
    jumpToTimestamp(moment.seconds, moment.anchorId);
  };

  const setNoteView = (view: NoteView) => {
    const next = new URLSearchParams(searchParams);
    next.set("view", view);
    setSearchParams(next, { replace: true, state: location.state });
  };

  const saveSpeakerAlias = async (speakerId: string, label: string) => {
    if (!id) return;
    const result = await apiJson<{ aliases: Record<string, string> }>(
      `/api/notes/${id}/speakers`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ aliases: { [speakerId]: label } }),
      },
    );
    setTranscriptEvidence((current) =>
      current ? { ...current, aliases: result.aliases } : current,
    );
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Button variant="ghost" onClick={() => navigate(returnTo)}><ArrowLeft data-icon="inline-start" />返回上级</Button>
        <LoadingState label="正在读取笔记…" />
      </div>
    );
  }

  if (error && !content) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
        <p className="text-lg font-medium">{error}</p>
        <Button onClick={() => setLoadAttempt((value) => value + 1)}>
          {zh ? "重新加载笔记" : "Reload note"}
        </Button>
        <Button
          type="button"
          onClick={() => navigate(returnTo)}
          variant="outline"
        >
          {copy.noteEditor.backToLibrary}
        </Button>
      </div>
    );
  }

  return (
    <div className="detail-page flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background">
      <div className="flex shrink-0 items-center gap-2 border-b px-6 py-3 text-xs text-muted-foreground">
        <Button
          onClick={() =>
            hasUnsavedChanges ? setLeaveOpen(true) : navigate(returnTo)
          }
          aria-label={zh ? pageParentLabel(returnTo) : "Return to list"}
          variant="ghost"
          size="sm"
          className="h-7 px-0"
        >
          <ArrowLeft className="size-4" />
          {zh ? pageParentLabel(returnTo) : 'Return to list'}
        </Button>
      </div>
      <header className="shrink-0 px-6 pt-5 lg:px-8">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0 flex-1">
            <p className="mb-2 text-xs text-muted-foreground">{zh ? isMeetingContent ? '会议纪要' : '笔记' : isMeetingContent ? 'Meeting notes' : 'Note'}</p>
            {workspaceMode === 'preview' ? <h1 className="break-words text-2xl font-medium">{localTitle || copy.noteEditor.untitled}</h1> : <div className="grid gap-2"><Label htmlFor="note-detail-title">{zh ? isMeetingContent ? '会议名称' : '笔记标题' : isMeetingContent ? 'Meeting title' : 'Note title'}</Label><Input id="note-detail-title" type="text" value={localTitle} disabled={saving} onChange={event => setLocalTitle(event.target.value)} placeholder={copy.noteEditor.untitled} className="w-full min-w-0 text-base" /></div>}
            <p className="mt-2 text-xs leading-5 text-muted-foreground">{[currentNote ? `${zh ? '已保存：' : 'Saved: '}${new Date(currentNote.createdAt).toLocaleString()}` : '', ['desktop', 'mobile', 'web'].includes(generationClient || '') ? noteOrigin(generationClient, zh) : '', workspaceBadge].filter(Boolean).join(' · ')}</p>
          </div>
          <div role="group" aria-label={zh ? '主要内容操作' : 'Primary content actions'} className="flex flex-wrap items-start gap-2">
            {hasUnsavedChanges ? <Button onClick={() => void handleSave()} size="sm" disabled={saving || !localTitle.trim()} aria-label={saving ? copy.noteEditor.saving : copy.noteEditor.save}><Save className="size-4" />{saving ? copy.noteEditor.saving : copy.noteEditor.save}</Button> : <Button variant="outline" size="sm" onClick={() => { setNoteView('summary'); setWorkspaceMode(workspaceMode === 'preview' ? 'write' : 'preview'); }} disabled={saving}><Edit3 />{workspaceMode === 'preview' ? zh ? '编辑' : 'Edit' : zh ? '返回阅读' : 'Back to reading'}</Button>}
            <ExportPanel title={currentNote?.title || localTitle} content={currentNote?.content || ''} version={`保存于 ${currentNote?.updatedAt || ''}`} transcript={transcriptEvidence ? renderTranscriptMarkdown(transcriptEvidence, transcriptTextMode) : undefined} />
            <Button variant="outline" size="sm" disabled={hasUnsavedChanges || saving} onClick={() => { setSharePanelOpen(true); setShareMessage(''); setShareError(''); }}><Share2 />{zh ? '分享' : 'Share'}</Button>
            <Button ref={deleteButtonRef} variant="ghost" size="sm" disabled={saving} className="text-destructive" onClick={() => { setDeleteError(''); setDeleteOpen(true); }}><Trash2 />{zh ? '删除' : 'Delete'}</Button>
            {id && <FeishuDelivery disabled={hasUnsavedChanges || saving} noteId={id} title={currentNote?.title || localTitle} content={currentNote?.content || ''} onClose={() => setDeliveryRevision(value => value + 1)} />}
          </div>
        </div>
        <div className="mt-4 grid gap-3">
          {hasUnsavedChanges && <span role="status" className="text-xs text-muted-foreground">{draftStatus}</span>}
          <details className="rounded-xl border bg-muted/20">
            <summary role="button" className="flex min-h-10 cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-ring [&::-webkit-details-marker]:hidden"><MoreHorizontal className="size-4" aria-hidden="true" />{zh ? '内容操作' : 'Content actions'}</summary>
            <div className="grid max-h-[40vh] gap-4 overflow-y-auto border-t p-3 lg:grid-cols-2">
              <section aria-label={zh ? '复制正文' : 'Copy text'} className="grid content-start gap-2"><h2 className="text-xs font-medium text-muted-foreground">{zh ? '复制正文' : 'Copy text'}</h2><div className="flex flex-wrap gap-2"><Button variant="ghost" size="sm" onClick={() => void handleCopyBody()}><Copy />{zh ? '复制正文' : 'Copy text'}</Button></div><p className="text-xs leading-5 text-muted-foreground">{zh ? '导出使用已保存正文。公开分享链接与飞书发布分别管理。' : 'Export uses saved content. Public links and Feishu publishing are managed separately.'}</p></section>
              <section aria-label={zh ? '版本与来源' : 'Versions and source'} className="grid content-start gap-2"><h2 className="text-xs font-medium text-muted-foreground">{zh ? '版本与来源' : 'Versions and source'}</h2><div className="flex flex-wrap items-center gap-2">{id && <><div><span className="mr-2 text-xs text-muted-foreground">{zh ? '历史版本' : 'Version history'}</span><NoteVersions noteId={id} revision={currentNote?.updatedAt} currentContent={content} onRestore={(title, body) => { setLocalTitle(title); setContent(body); setWorkspaceMode('write'); }} /></div><Button variant="ghost" size="sm" disabled={hasUnsavedChanges || saving} asChild><Link to={sourceFilesPath} state={{ returnTo: detailReturnTo }} aria-disabled={hasUnsavedChanges || saving || undefined} aria-describedby={hasUnsavedChanges || saving ? 'source-file-save-help' : undefined} tabIndex={hasUnsavedChanges || saving ? -1 : undefined} onClick={event => { if (hasUnsavedChanges || saving) event.preventDefault(); }}>{zh ? '查看原文件' : 'View original file'}</Link></Button></>}{sharedKey && <><Button variant="ghost" size="sm" disabled={hasUnsavedChanges || saving} asChild><Link to={`/workspace/${encodeURIComponent(sharedKey)}`} state={{ returnTo: detailReturnTo }} aria-disabled={hasUnsavedChanges || saving || undefined} tabIndex={hasUnsavedChanges || saving ? -1 : undefined} onClick={event => { if (hasUnsavedChanges || saving) event.preventDefault(); }}>{zh ? '查看保存版本' : 'View saved versions'}</Link></Button></>}</div>{(hasUnsavedChanges || saving) && <p id="source-file-save-help" className="text-xs leading-5 text-muted-foreground">{saving ? zh ? '正在保存修改，完成后可查看原文件。' : 'Saving changes. You can view the original file once saving finishes.' : zh ? '请先保存修改后查看原文件。' : 'Save your changes before viewing the original file.'}</p>}<p className="text-xs leading-5 text-muted-foreground">{zh ? '查看历史正文、保存记录和可核验的来源文件。查看不会修改当前内容。' : 'View content history, saved records and verified source files without changing the current content.'}</p></section>

              <section aria-label={zh ? '内容工具' : 'Content tools'} className="grid content-start gap-2"><h2 className="text-xs font-medium text-muted-foreground">{zh ? '内容工具' : 'Content tools'}</h2><div className="flex flex-wrap items-center gap-2">{sharedKey && <><Button variant="outline" size="sm" disabled={hasUnsavedChanges || saving} asChild><Link to={`/settings/mcp?mode=translation&note=${encodeURIComponent(sharedKey)}`} state={{ returnTo: detailReturnTo }} aria-disabled={hasUnsavedChanges || saving || undefined} tabIndex={hasUnsavedChanges || saving ? -1 : undefined} onClick={event => { if (hasUnsavedChanges || saving) event.preventDefault(); }}>{zh ? '全文翻译 · MCP' : 'Full-text translation · MCP'}</Link></Button></>}{!sharedKey && <><Button variant="outline" size="sm" disabled>{zh ? '全文翻译 · MCP' : 'Full-text translation · MCP'}</Button><Button variant="ghost" size="sm" asChild><Link to="/settings/mcp" state={{ returnTo: detailReturnTo }}>{zh ? '配置 MCP 工具' : 'Configure MCP tools'}</Link></Button></>}</div><p className="text-xs leading-5 text-muted-foreground">{sharedKey ? zh ? '工具使用所选已保存正文；确认发送范围后执行。核对结果后另存，保留原文。' : 'Tools use the selected saved text after you confirm what to send. Review results before saving a new version.' : zh ? '此工具尚未接入这份内容的已保存版本。正文与历史保留，可先配置工具。' : 'This tool does not yet support this saved content. Text and history remain available; you can configure tools first.'}</p></section>
              <section aria-label={zh ? '更多内容操作' : 'Additional content actions'} className="flex flex-wrap items-center gap-2 border-t pt-3 lg:col-span-2">{keyMoments.length > 0 && <Button variant="ghost" size="sm" onClick={() => setMomentsOpen(true)}><ListVideo />{zh ? '关键片段' : 'Key moments'}</Button>}</section>
            </div>
          </details>
        </div>
        {currentNote ? (
          <RecordingRetryBar
            note={currentNote}
            onUpdated={(updated) => {
              setCurrentNote(updated);
              setLocalTitle(updated.title);
              setContent(updated.content);
              setTaskId(updated.taskId || "");
            }}
          />
        ) : null}
      </header>
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-6 pt-2 lg:px-8">
        <ToggleGroup
          type="single"
          className="line-tabs"
          value={noteView}
          onValueChange={(value) => value && setNoteView(value as NoteView)}
          data-testid="note-view-switcher"
        >
          <ToggleGroupItem value="summary">
            {zh ? isMeetingContent ? "纪要" : "正文" : "Summary"}
          </ToggleGroupItem>
          {hasMediaTranscript && (
            <ToggleGroupItem value="transcript">
              {zh ? "逐字稿" : "Transcript"}
            </ToggleGroupItem>
          )}
          <ToggleGroupItem value="chat">{zh ? "对话" : "Chat"}</ToggleGroupItem>
        </ToggleGroup>
        {noteView === "summary" && (workspaceMode !== "preview" || hasUnsavedChanges) && (
          <ToggleGroup
            type="single"
            value={workspaceMode}
            onValueChange={(value) =>
              value && setWorkspaceMode(value as WorkspaceMode)
            }
            aria-label={zh ? isMeetingContent ? "纪要阅读与编辑" : "正文阅读与编辑" : "Content reading and editing"}
          >
            <ToggleGroupItem value="preview">
              <Eye />
              {copy.common.preview}
            </ToggleGroupItem>
            <ToggleGroupItem value="write">
              <Edit3 />
              {copy.common.edit}
            </ToggleGroupItem>
            <ToggleGroupItem value="split">{splitLabel}</ToggleGroupItem>
          </ToggleGroup>
        )}
      </div>

      <AlertDialog
        open={deleteOpen}
        onOpenChange={(open) => {
          if (!deleting) setDeleteOpen(open);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {zh ? '移入回收站？' : 'Move to trash?'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {zh ? `“${localTitle}”的正文与版本移入回收站，可在存储页恢复。原文件与飞书文档保留。` : 'Text and versions move to trash and can be restored in Storage. Original files and Feishu documents remain.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError ? (
            <Alert variant="destructive">
              <AlertDescription>{deleteError}</AlertDescription>
            </Alert>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>
              {zh ? "取消" : "Cancel"}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={deleting || !id}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={async (event) => {
                if (!id) return;
                event.preventDefault();
                setDeleting(true);
                setDeleteError("");
                try {
                  const receipt = await useWorkspaceStore.getState().changeDeleted(sharedKey || id, true);
                  if (!receipt?.deleted) throw new Error(zh ? '移入回收站未完成，正文与原文件保留，请重试。' : 'Could not move to trash. Text and originals remain; retry.');
                  navigate(returnTo, { replace: true });
                } catch (cause) {
                  setDeleteError(
                    cause instanceof Error
                      ? cause.message
                      : zh
                        ? "删除失败，请重试"
                        : "Could not delete note. Please retry.",
                  );
                } finally {
                  setDeleting(false);
                }
              }}
            >
              {deleting
                ? zh
                  ? "删除中…"
                  : "Deleting…"
                : zh
                  ? "确认删除"
                  : "Confirm deletion"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {error ? (
        <Alert
          variant="destructive"
          className="rounded-none border-x-0 border-t-0"
        >
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {mediaError && (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>{mediaError}</span>
            <Button
              variant="outline"
              onClick={() => {
                setMediaError("");
                setMediaAttempt((n) => n + 1);
              }}
            >
              重新加载原音
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <Dialog open={leaveOpen} onOpenChange={setLeaveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>离开编辑？</DialogTitle>
            <DialogDescription>
              {draftStatus}。已保存的正文不受影响。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLeaveOpen(false)}>
              继续编辑
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                if (owner && id) removeTextDraft(owner, `local:${id}`);
                navigate(returnTo);
              }}
            >
              放弃草稿并离开
            </Button>
            <Button onClick={() => navigate(returnTo)}>保留草稿并离开</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={sharePanelOpen} onOpenChange={setSharePanelOpen}>
        <DialogContent className="flex w-full flex-col sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{shareCopy.title}</DialogTitle>
            <DialogDescription>{shareCopy.description}</DialogDescription>
          </DialogHeader>
          <div className="grid flex-1 content-start gap-4 py-6">
            {shareUrl ? (
              <Input readOnly value={shareUrl} className="font-mono text-xs" />
            ) : (
              <p className="text-sm text-muted-foreground">
                {shareCopy.disabled}
              </p>
            )}
            {shareMessage ? (
              <Alert>
                <AlertDescription>{shareMessage}</AlertDescription>
              </Alert>
            ) : null}
            {shareError ? (
              <Alert variant="destructive">
                <AlertDescription>{shareError}</AlertDescription>
              </Alert>
            ) : null}
          </div>
          <DialogFooter className="gap-2">
            {shareUrl ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void handleDisableShare()}
                  disabled={shareLoading}
                  className="text-destructive"
                >
                  {shareCopy.disable}
                </Button>
                <Button
                  type="button"
                  onClick={() => void copyShareUrl(shareUrl)}
                  disabled={shareLoading}
                >
                  {shareCopy.copy}
                </Button>
              </>
            ) : (
              <Button
                type="button"
                onClick={() => void handleShare()}
                disabled={shareLoading}
              >
                {shareLoading ? copy.common.loading : shareCopy.create}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Sheet open={momentsOpen} onOpenChange={setMomentsOpen}>
        <SheetContent side="right" className="flex w-80 flex-col p-0">
          <SheetHeader className="p-4">
            <SheetTitle>{zh ? "关键片段" : "Key moments"}</SheetTitle>
            <SheetDescription>
              {zh
                ? "选择时间点回看会议。"
                : "Select a moment to review the meeting."}
            </SheetDescription>
          </SheetHeader>
          <KeyMomentsRail
            moments={keyMoments}
            activeAnchorId={activeMoment?.anchorId}
            onSelectMoment={(moment) => {
              handleSelectMoment(moment);
              setMomentsOpen(false);
            }}
          />
        </SheetContent>
      </Sheet>

      <div className="relative flex min-h-0 flex-1 flex-col-reverse overflow-hidden lg:flex-row">
        {id && (
          <div
            className={
              noteView === "chat" ? "flex min-h-0 min-w-0 flex-1" : "hidden"
            }
          >
            <MeetingConversation key={id} noteId={id} />
          </div>
        )}
        {noteView === "summary" ? (
          <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
            <ResizablePanelGroup
              key={workspaceMode}
              direction="horizontal"
              className="min-w-0 flex-1"
            >
              {workspaceMode !== "preview" ? (
                <ResizablePanel
                  defaultSize={workspaceMode === "split" ? 42 : 100}
                  minSize={30}
                  className="flex min-w-0 flex-col bg-card"
                >
                  <div className="border-b px-4 py-2 text-xs font-medium text-muted-foreground">
                    Markdown
                  </div>
                  <Textarea
                    aria-label={zh ? isMeetingContent ? "纪要 Markdown 正文" : "笔记 Markdown 正文" : "Markdown content"}
                    value={content}
                    disabled={saving}
                    onChange={(event) => setContent(event.target.value)}
                    className="stealth-scroll min-h-0 flex-1 resize-none bg-card px-4 py-4 font-mono text-[13px] leading-6 outline-none"
                    placeholder={copy.noteEditor.editorPlaceholder}
                  />
                </ResizablePanel>
              ) : null}

              {workspaceMode === "split" ? (
                <ResizableHandle withHandle />
              ) : null}

              {workspaceMode !== "write" ? (
                <ResizablePanel
                  defaultSize={workspaceMode === "split" ? 58 : 100}
                  minSize={32}
                  className="flex min-w-0 flex-col bg-background"
                >
                  <div className="flex min-h-0 flex-1 overflow-hidden">
                    <div
                      ref={previewRef}
                      className="stealth-scroll min-w-0 flex-1 overflow-auto"
                    >
                      <MarkdownContent
                        content={content ? previewContent : copy.noteEditor.previewEmpty}
                        className="prose mx-auto w-full max-w-4xl break-words px-6 py-6 dark:prose-invert lg:px-8"
                        videoUrl={videoUrl || undefined}
                        mediaUrl={localMediaUrl}
                        onVideoJump={(seconds) => {
                          jumpToTimestamp(seconds);
                        }}
                      />
                      {id && (
                        <FeishuDocumentFooter
                          noteId={id}
                          revision={`${currentNote?.updatedAt}:${deliveryRevision}`}
                        />
                      )}
                    </div>

                    {videoUrl && !isVideoNote ? (
                      <div className="hidden w-[320px] shrink-0 border-l border-border bg-card/80 p-4 xl:flex dark:border-border ">
                        <VideoReferencePanel
                          noteId={id}
                          taskId={undefined}
                          videoUrl={videoUrl}
                          currentTimestamp={currentTimestamp}
                          jumpRequestId={jumpRequestId}
                          activeMomentTitle={activeMoment?.title}
                          className="w-full"
                          onTimestampChange={setCurrentTimestamp}
                        />
                      </div>
                    ) : null}
                  </div>
                </ResizablePanel>
              ) : null}
            </ResizablePanelGroup>
          </div>
        ) : noteView === "chat" ? null : transcriptError ? (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 p-6 text-center">
            <p role="alert" className="text-sm text-destructive">
              {zh ? "逐字稿加载失败：" : "Transcript failed to load: "}
              {transcriptError}
            </p>
            <Button
              variant="outline"
              onClick={() => setTranscriptAttempt((value) => value + 1)}
            >
              {zh ? "重新加载逐字稿" : "Reload transcript"}
            </Button>
          </div>
        ) : (
          <TranscriptEvidencePanel
            evidence={transcriptEvidence}
            loading={transcriptLoading}
            currentTimestamp={currentTimestamp}
            textMode={transcriptTextMode}
            onTextModeChange={setTranscriptTextMode}
            onSeek={jumpToTimestamp}
            onSaveAlias={saveSpeakerAlias}
          />
        )}

        {id && isAudioNote && isMeetingContent && (
          <aside
            aria-label={zh ? "原录音" : "Original recording"}
            className="flex min-w-0 shrink-0 flex-col gap-4 border-b bg-card p-4 lg:order-first lg:w-60 lg:border-b-0 lg:border-r lg:p-6 xl:w-64"
          >
            <div>
              <p className="text-xs text-muted-foreground">
                {zh ? "原录音" : "Original recording"}
              </p>
              <div className="my-5">
                <RecordingWaveform
                  key={id}
                  noteId={id}
                  onSeek={jumpToTimestamp}
                />
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                {zh
                  ? "点击纪要或逐字稿中的时间点，回听对应讨论。"
                  : "Select timestamps to replay the discussion."}
              </p>
            </div>
            <SavedRecordingActions
              key={id}
              noteId={id}
              title={localTitle}
              onDeleted={() => setRecordingDeleted(true)}
            />
          </aside>
        )}
        {isVideoNote && localMediaUrl ? (
          <section
            aria-label={zh ? isMeetingContent ? "会议视频" : "来源视频" : isMeetingContent ? "Meeting video" : "Source video"}
            className={
              videoExpanded
                ? "absolute inset-0 z-10 flex min-h-0 flex-col bg-card"
                : "flex max-h-[40%] min-h-0 w-full shrink-0 flex-col border-b bg-card lg:max-h-none lg:order-first lg:w-[42%] lg:border-b-0 lg:border-r"
            }
          >
            <div className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2">
              <span className="text-sm font-medium">
                {zh ? isMeetingContent ? "会议视频" : "来源视频" : isMeetingContent ? "Meeting video" : "Source video"}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setVideoExpanded((value) => !value)}
                aria-expanded={videoExpanded}
              >
                {videoExpanded ? <Minimize2 /> : <Maximize2 />}
                {videoExpanded
                  ? zh
                    ? isMeetingContent ? "返回纪要" : "返回正文"
                    : "Back to notes"
                  : zh
                    ? "放大视频"
                    : "Expand video"}
              </Button>
            </div>
            {id && isMeetingContent && (
              <SavedRecordingActions
                key={id}
                noteId={id}
                title={localTitle}
                onDeleted={() => setRecordingDeleted(true)}
              />
            )}
            <div className="flex min-h-0 flex-1 flex-col overflow-auto p-3">
              <video
                key={mediaAttempt}
                ref={videoRef}
                data-testid="source-video"
                controls
                preload="metadata"
                src={resolveContentUrl(localMediaUrl)}
                className={
                  videoExpanded
                    ? "min-h-0 w-full flex-1 bg-black object-contain"
                    : "aspect-video max-h-full w-full shrink-0 bg-black object-contain"
                }
                onTimeUpdate={(event) =>
                  setCurrentTimestamp(event.currentTarget.currentTime)
                }
                onError={() =>
                  setMediaError(
                    "原视频不可播放，可能已移除、缺少权限或格式不支持。可检查原文件并重试，正文仍可阅读。",
                  )
                }
              />
              {!videoExpanded && (
                <p className="mt-3 text-xs text-muted-foreground">
                  {zh
                    ? isMeetingContent ? "点击纪要或逐字稿中的时间，可跳转到对应画面。" : "点击正文或逐字稿中的时间，可跳转到对应画面。"
                    : "Select a timestamp in the notes or transcript to seek the video."}
                </p>
              )}
            </div>
          </section>
        ) : null}
      </div>
      {isAudioNote && localMediaUrl ? (
        <div className="shrink-0 border-t border-border bg-card px-4 py-3 dark:border-border ">
          <div className="mx-auto flex max-w-6xl items-center gap-3">
            <span className="shrink-0 text-sm font-medium">
              {zh ? "原声" : "Audio"}
            </span>
            <audio
              key={mediaAttempt}
              ref={audioRef}
              data-testid="source-audio"
              controls
              preload="metadata"
              src={resolveContentUrl(localMediaUrl)}
              className="h-10 min-w-0 flex-1"
              onTimeUpdate={(event) =>
                setCurrentTimestamp(event.currentTarget.currentTime)
              }
              onError={() =>
                setMediaError(
                  "原音不可播放，可能已移除、缺少权限或格式不支持。可检查原文件并重试，正文仍可阅读。",
                )
              }
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
