import { useMeetingTaskStates } from '@/hooks/useMeetingTaskStates';
import { ImportedMeetingSources } from '@/components/MeetingRecorder/ImportedMeetingSources';
import { TextReveal } from "@/components/ui/motion";
import { isMeetingProcessing } from "../lib/meetingProcessing";
import { MeetingWorkbench, type MeetingArchiveView, type MeetingLocator } from "../components/MeetingRecorder/MeetingWorkbench";
import { PageReturn } from '@/components/Layout/PageReturn';
import { resolvePageParent } from '@/lib/navigation';
import { useLibraryNotes, libraryNoteUrl } from "@/hooks/useLibraryNotes";
import { publishToFeishu } from "../lib/feishu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Mic, Upload } from "lucide-react";
import { apiJson } from "../lib/api";
import { fetchTaskStatus } from "../lib/noteGenerationClient";
import {
  listPendingMeetings,
  updatePendingMeeting,
  type PendingMeeting,
} from "../lib/audioStorage";
import {
  acquireMeetingMicrophone,
  DEFAULT_CAPTURE_OPTIONS,
  START_MEETING_EVENT,
} from "../lib/meetingCapture";
import { mapMicrophoneError } from "../lib/microphonePermission";
import { useAuthStore } from "../stores/authStore";
import {
  isMeetingBusy,
  useMeetingRecorderStore,
} from "../stores/meetingRecorderStore";
import { useNoteLibraryStore } from "../stores/noteLibraryStore";
import { getWorkspaceLabel, useTeamStore } from "../stores/teamStore";
import { useI18n } from "../lib/i18n";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { StartMeetingButton } from "../components/MeetingRecorder/StartMeetingButton";
import { SavedRecordingChoice } from "../components/MeetingRecorder/SavedRecordingChoice";
import { MeetingCaptureWorkspace } from "../components/MeetingRecorder/MeetingCaptureWorkspace";
import { MicrophoneCheck } from '../components/MeetingRecorder/MicrophoneCheck';

const capturePhases = ["requesting", "recording", "paused", "stopping"];

function meetingLocator(params: URLSearchParams, state: unknown, ownerId: string | undefined, requestId: string): MeetingLocator | undefined {
  const saved = state && typeof state === 'object' && 'meetingLocator' in state ? state.meetingLocator : undefined;
  const fields = { noteId: 'locate_note', taskId: 'locate_task', recordingId: 'locate_recording' } as const;
  if (!saved && ![...Object.values(fields), 'locate_focus'].some(key => params.has(key))) return undefined;
  const record = saved && typeof saved === 'object' && !Array.isArray(saved) ? saved as Record<string, unknown> : {};
  let invalid = !!saved && (!Object.keys(record).length || record.ownerId !== ownerId);
  const target: MeetingLocator = { requestId, ownerId };
  for (const [field, key] of Object.entries(fields) as [keyof typeof fields, string][]) {
    const fromUrl = params.get(key), fromState = record[field];
    if (params.getAll(key).length > 1 || fromUrl !== null && fromState !== undefined && fromUrl !== fromState) invalid = true;
    const value = fromUrl ?? fromState;
    if (value !== undefined && value !== null) {
      if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,160}$/.test(value)) invalid = true;
      else target[field] = value;
    }
  }
  const fromUrl = params.get('locate_focus'), fromState = record.focus;
  if (params.getAll('locate_focus').length > 1 || fromUrl !== null && fromState !== undefined && fromUrl !== fromState) invalid = true;
  const focus = params.has('locate_focus') ? fromUrl : fromState;
  if (focus !== undefined) {
    if (focus !== 'meeting') invalid = true;
    else target.focus = focus;
  }
  return { ...target, invalid };
}

export function Meetings() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  // Old ?archived= links still open the complete meeting collection. Personal
  // archive metadata no longer defines whether content has a meeting dossier.
  const meetingView: MeetingArchiveView = params.get('view') === 'pending' ? 'pending' : 'meetings';
  const userId = useAuthStore((state) => state.user?.id);
  const [pending, setPending] = useState<PendingMeeting[]>([]);
  const [options, setOptions] = useState(DEFAULT_CAPTURE_OPTIONS);
  const [diarizationReady, setDiarizationReady] = useState<boolean | null>(
    null,
  );
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [inputTesting, setInputTesting] = useState(false);
  const [microphoneCheckOpen, setMicrophoneCheckOpen] = useState(false);
  const startAttempt = useRef<string | null>(null);
  useEffect(() => {
    if (params.get('capture') === '1') {
      setSetupOpen(true);
      const next = new URLSearchParams(params); next.delete('capture');
      setParams(next, { replace: true });
    }
  }, [params, setParams]);
  const feishuRetryAfter = useRef(new Map<string, number>());
  const navigate = useNavigate();
  const { locale } = useI18n();
  const zh = locale.startsWith("zh");
  const { loading, error: notesError, loadNotes } = useNoteLibraryStore();
  const notes = useLibraryNotes();
  const { currentWorkspace, teams } = useTeamStore();
  const readScope = JSON.stringify([userId, currentWorkspace]);
  const [readiness, setReadiness] = useState({ scope: '', ready: false });
  const locator = meetingLocator(params, location.state, userId, JSON.stringify([location.key, location.search, readScope]));
  const filesParent = [params.get('returnTo'), params.get('sourceReturnTo'), location.state?.returnTo, location.state?.sourceReturnTo]
    .map(value => resolvePageParent(value, '')).find(value => value.split(/[?#]/)[0] === '/files');
  const readonlyArchiveVisit = !!locator || !!filesParent;
  const withoutLocatorState = () => {
    const state = location.state && typeof location.state === 'object' ? { ...location.state } : {};
    delete state.meetingLocator;
    return state;
  };
  const clearLocator = () => {
    const next = new URLSearchParams(params);
    for (const key of ['locate_note', 'locate_task', 'locate_recording', 'locate_focus']) next.delete(key);
    navigate({ pathname: location.pathname, search: next.toString() ? '?' + next.toString() : '', hash: location.hash }, { replace: true, state: withoutLocatorState() });
  };
  const session = useMeetingRecorderStore();
  const isCapturing = capturePhases.includes(session.phase);
  const busy = isMeetingBusy(session);
  useEffect(() => {
    if (session.phase === 'failed' && startAttempt.current === session.captureOptions?.sessionId && !session.hasRecoverableRecording) {
      startAttempt.current = null;
      setSetupOpen(true);
    }
  }, [session.phase, session.captureOptions?.sessionId, session.hasRecoverableRecording]);
  const workspace = getWorkspaceLabel(
    currentWorkspace,
    teams,
    zh ? "个人空间" : "Personal workspace",
  );
  const workspacePending = pending.filter(
    (item) =>
      item.workspace.scope === currentWorkspace.scope &&
      (item.workspace.scope === "personal" ||
        (currentWorkspace.scope === "team" &&
          item.workspace.teamId === currentWorkspace.teamId)),
  );
  const meetingNotes = notes.filter(
    (note) =>
      !!note.meetingSource && note.meetingSource.ownerId === userId || ["meeting_recording", "meeting_video"].includes(note.sourceType || ""),
  );

  const meetingTaskStates = useMeetingTaskStates(meetingNotes, JSON.stringify([location.key, location.pathname, location.search, currentWorkspace]));

  useEffect(() => {
    let active = true;
    setReadiness({ scope: readScope, ready: false });
    void Promise.resolve(loadNotes(currentWorkspace)).finally(() => { if (active) setReadiness({ scope: readScope, ready: true }); });
    setPending([]);
    setHistoryError("");
    setHistoryLoading(!!userId);
    if (userId)
      void listPendingMeetings(userId)
        .then((items) => {
          if (active) setPending(items);
        })
        .catch(() => {
          if (active)
            setHistoryError(
              zh
                ? "无法读取本地录制，原件尚未删除。"
                : "Cannot load local recordings. Originals have not been deleted.",
            );
        })
        .finally(() => {
          if (active) setHistoryLoading(false);
        });
    return () => {
      active = false;
    };
  }, [currentWorkspace, loadNotes, session.phase, userId, zh, historyAttempt]);
  useEffect(() => {
    // File-library navigation only reads the dossier. It must not activate the
    // legacy restore event or pending Feishu publication while locating it.
    if (readonlyArchiveVisit) return;
    let active = true;
    let refreshing = false;
    const refresh = () => {
      if (userId && !refreshing && active) {
        refreshing = true;
        void listPendingMeetings(userId)
          .then(async (items) => {
            if (active) setPending(items);
            for (const item of items) {
              if (!active) return;
              if (
                item.feishuPending &&
                item.noteId &&
                item.processingStatus === "completed" &&
                (feishuRetryAfter.current.get(item.id) || 0) <= Date.now()
              ) {
                feishuRetryAfter.current.set(item.id, Date.now() + 60000);
                const note = await useNoteLibraryStore
                  .getState()
                  .loadNoteById(item.noteId);
                if (
                  active &&
                  useAuthStore.getState().user?.id === item.ownerId &&
                  note
                ) {
                  try {
                    await publishToFeishu(
                      note.id,
                      note.title,
                      note.content,
                      true,
                    );
                    await updatePendingMeeting(item.id, {
                      feishuPending: false,
                    });
                  } catch {
                    /* Keep the durable submission for the next refresh. */
                  }
                }
              }
              if (
                isMeetingProcessing(item.id) ||
                ["idle", "completed", "failed"].includes(
                  item.processingStatus,
                ) ||
                (session.recordingId === item.id && isMeetingBusy(session))
              )
                continue;
              if (!item.taskId) {
                await updatePendingMeeting(item.id, {
                  processingStatus: "failed",
                  processingError: "处理被中断，原始媒体已保存，请重试。",
                });
                continue;
              }
              try {
                const status = await fetchTaskStatus(item.taskId);
                if (!active) return;
                if (status.status === "success") {
                  window.dispatchEvent(
                    new CustomEvent("vinote-restore-meeting", { detail: item }),
                  );
                } else if (["failed", "not_found"].includes(status.status)) {
                  await updatePendingMeeting(item.id, {
                    processingStatus: "failed",
                    failedStage: status.failed_stage || item.processingStatus,
                    processingError: status.message,
                  });
                } else {
                  const stages: Record<
                    string,
                    PendingMeeting["processingStatus"]
                  > = {
                    preparing: "preparing_media",
                    preparing_media: "preparing_media",
                    uploaded: "preparing_media",
                    transcribing: "transcribing",
                    diarizing: "diarizing",
                    parallel_analysis: "parallel_analysis",
                    aligning: "aligning",
                    analyzing_video: "analyzing_video",
                    summarizing: "generating",
                    screenshots: "generating",
                    saving: "saving_result",
                    saving_result: "saving_result",
                  };
                  await updatePendingMeeting(item.id, {
                    processingStatus:
                      stages[status.stage || status.status] ||
                      item.processingStatus,
                    progress: status.progress ?? undefined,
                    processedSeconds: status.processed_seconds ?? undefined,
                    totalSeconds: status.total_seconds ?? undefined,
                    etaSeconds: status.eta_seconds ?? undefined,
                  });
                }
              } catch {
                await updatePendingMeeting(item.id, {
                  processingStatus: "failed",
                  processingError:
                    "暂时无法连接处理服务。原始媒体已保留，重试将检查并继续现有任务。",
                });
              }
            }
          })
          .catch(() => undefined)
          .finally(() => {
            refreshing = false;
          });
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [userId, session.recordingId, session.phase, readonlyArchiveVisit]);
  useEffect(() => {
    void apiJson<{ diarization: { available: boolean } }>(
      "/api/meeting-capabilities",
    )
      .then((result) => setDiarizationReady(result.diarization.available))
      .catch(() => setDiarizationReady(false));
  }, []);
  useEffect(() => {
    const refresh = () => {
      void navigator.mediaDevices
        ?.enumerateDevices()
        .then((items) =>
          setDevices(items.filter((item) => item.kind === "audioinput")),
        )
        .catch(() => undefined);
    };
    refresh();
    navigator.mediaDevices?.addEventListener("devicechange", refresh);
    return () =>
      navigator.mediaDevices?.removeEventListener("devicechange", refresh);
  }, []);

  const refreshDevices = async () => {
    setError("");
    try {
      const stream = await acquireMeetingMicrophone(options.microphoneId);
      stream.getTracks().forEach((track) => track.stop());
      const nextDevices = (
        await navigator.mediaDevices.enumerateDevices()
      ).filter((device) => device.kind === "audioinput");
      setDevices(nextDevices);
      if (
        options.microphoneId &&
        !nextDevices.some((device) => device.deviceId === options.microphoneId)
      ) {
        setOptions((current) => ({ ...current, microphoneId: "" }));
      }
    } catch (deviceError) {
      const reason = mapMicrophoneError(deviceError);
      setError(
        reason === "denied"
          ? zh
            ? "麦克风权限未开启，请在 Windows 隐私设置中允许 VINote 使用麦克风。"
            : "Microphone permission is disabled. Allow VINote to use it in Windows privacy settings."
          : reason === "no-device"
            ? zh
              ? "没有检测到可用的麦克风，请重新连接耳机后检测。"
              : "No microphone was detected. Reconnect the headset and check again."
            : zh
              ? "暂时无法启动这个麦克风。请重新检测，或改用“系统默认麦克风”。"
              : "This microphone could not start. Check again or use the system default microphone.",
      );
    }
  };
  const startRecording = (meetingType: "audio" | "video") => {
    if (busy) return;
    setSetupOpen(false);
    setError("");
    const nextOptions = {
      ...options,
      sessionId: crypto.randomUUID(),
      mode: "recording" as const,
      meetingType,
      screen: meetingType === "video",
      // The microphone is the required meeting audio source. Screen capture must
      // never be blocked by optional WebView/Windows system-audio capture.
      systemAudio: false,
      diarize: true,
      speakerCount: undefined,
    };
    setOptions(nextOptions);
    startAttempt.current = nextOptions.sessionId;
    window.dispatchEvent(
      new CustomEvent(START_MEETING_EVENT, { detail: nextOptions }),
    );
  };

  return (
    <div className="workspace-page pb-24">
      {filesParent && <PageReturn contextual={false} to={filesParent} label="返回文件库" />}
      <SavedRecordingChoice />
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-medium tracking-tight">
            <TextReveal>
              {isCapturing
                ? session.phase === "requesting"
                  ? zh
                    ? "正在准备录制"
                    : "Preparing recording"
                  : session.phase === "stopping"
                    ? zh
                      ? "正在保存录制"
                      : "Saving recording"
                    : zh
                      ? "会议正在进行"
                      : "Meeting in progress"
                : zh
                  ? "会议"
                  : "Recordings"}
            </TextReveal>
          </h1>
          {isCapturing && (
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {zh
                ? "专注讨论即可。录制结束并保存后，再选择是否生成会议纪要。"
                : "Record first, then choose whether to generate notes after saving."}
            </p>
          )}
        </div>
        <span className="pt-1 text-xs text-muted-foreground">{workspace}</span>
      </header>

      {isCapturing ? (
        <MeetingCaptureWorkspace title={options.title} />
      ) : (
        <Dialog open={setupOpen} onOpenChange={setSetupOpen}>
          <DialogContent closeLabel={zh ? "关闭准备录制" : "Close recording setup"} className="max-h-[85vh] overflow-auto sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>准备录制</DialogTitle>
              <DialogDescription>选择录制方式，检查声音是否清晰。</DialogDescription>
            </DialogHeader>
            <section aria-label="采集设备" className="flex flex-col gap-4 py-2">
              <Field>
                <FieldLabel htmlFor="meeting-title">{zh ? "会议标题（可选）" : "Meeting title (optional)"}</FieldLabel>
                <Input id="meeting-title" value={options.title} disabled={busy} placeholder={zh ? "留空将按录制时间命名" : "Leave blank to name by recording time"} onChange={event => setOptions(current => ({ ...current, title: event.target.value }))} />
              </Field>
              <Field>
                <div className="flex items-center justify-between gap-2">
                  <FieldLabel htmlFor="meeting-microphone">麦克风</FieldLabel>
                  <Button variant="ghost" size="sm" disabled={busy || inputTesting} onClick={() => void refreshDevices()}>重新检测</Button>
                </div>
                <Select disabled={busy || inputTesting} value={options.microphoneId || "default"} onValueChange={value => setOptions({ ...options, microphoneId: value === "default" ? "" : value })}>
                  <SelectTrigger id="meeting-microphone"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">系统默认麦克风</SelectItem>
                    {devices.filter(device => device.deviceId && device.deviceId !== "default").map((device, index) => <SelectItem key={device.deviceId} value={device.deviceId}>{device.label || `麦克风 ${index + 1}`}</SelectItem>)}
                  </SelectContent>
                </Select>
              </Field>
              <details onToggle={event => setMicrophoneCheckOpen(event.currentTarget.open)}>
                <summary className="w-fit cursor-pointer rounded text-sm text-muted-foreground focus-visible:outline focus-visible:outline-ring">{zh ? '测试麦克风（可选）' : 'Test microphone (optional)'}</summary>
                {microphoneCheckOpen && <MicrophoneCheck deviceId={options.microphoneId || ''} onActiveChange={setInputTesting} />}
              </details>
            </section>
            {diarizationReady === false && <Alert><AlertDescription>说话人分析暂不可用，不影响录制。保存后可重新尝试生成会议纪要。</AlertDescription></Alert>}
            {(error || session.error) && <Alert variant="destructive"><AlertDescription>{error || session.error} 检查设备后可再次开始。</AlertDescription></Alert>}
            <div className="flex flex-col gap-3 border-t pt-4">
              <StartMeetingButton disabled={busy || inputTesting} type={options.meetingType} onTypeChange={meetingType => setOptions(current => ({ ...current, meetingType, screen: meetingType === "video" }))} onStart={startRecording} />
              <Button variant="ghost" disabled={busy} onClick={() => setSetupOpen(false)}>{zh ? "取消准备，返回会议" : "Cancel setup and return to meetings"}</Button>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {!isCapturing && (historyError || notesError) && (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>{[historyError, notesError].filter(Boolean).join(" ")}</span>
            <Button
              variant="outline"
              disabled={loading || historyLoading}
              onClick={() => setHistoryAttempt((value) => value + 1)}
            >
              {zh ? "重新读取记录" : "Reload recordings"}
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {!isCapturing && (
        <MeetingWorkbench
          taskStates={meetingTaskStates}
          key={userId + JSON.stringify(currentWorkspace)}
          recordings={workspacePending}
          notes={meetingNotes}
          view={meetingView}
          locator={locator}
          locateError={notesError || historyError}
          onLocateRetry={() => setHistoryAttempt(value => value + 1)}
          onClearLocator={clearLocator}
          associationContextKey={JSON.stringify([location.key, location.pathname, location.search, location.hash, currentWorkspace])}
          onAssociated={() => loadNotes(currentWorkspace)}
          onViewChange={value => {
            const next = new URLSearchParams(params);
            next.delete('archived');
            for (const key of ['locate_note', 'locate_task', 'locate_recording', 'locate_focus']) next.delete(key);
            value === 'pending' ? next.set('view', 'pending') : next.delete('view');
            navigate({ pathname: location.pathname, search: next.toString() ? '?' + next.toString() : '', hash: location.hash }, { state: withoutLocatorState() });
          }}
          loading={loading || historyLoading || !!locator && (readiness.scope !== readScope || !readiness.ready)}
          onOpenNote={(id, edit) => {
            const note = notes.find((n) => n.id === id);
            const target = new URL(note ? libraryNoteUrl(note) : "/note/" + encodeURIComponent(id), 'https://vinote.invalid');
            if (edit) target.searchParams.set('edit', '1');
            navigate(target.pathname + target.search, {
              state: { returnTo: location.pathname + location.search + location.hash },
            });
          }}
          onDeleted={(id) =>
            setPending((items) => items.filter((item) => item.id !== id))
          }
          actions={
            <>
              <Button onClick={() => setSetupOpen(true)} disabled={busy}>
                <Mic />
                {zh ? "录制会议" : "Record meeting"}
              </Button>
              <Button
                variant="outline"
                onClick={() => navigate("/generate?meeting=1", { state: { returnTo: location.pathname + location.search + location.hash } })}
              >
                <Upload />
                {zh ? "导入会议文件" : "Import meeting file"}
              </Button>
            </>
          }
        />
      )}
      {!isCapturing && meetingView === 'meetings' && <ImportedMeetingSources owner={userId} coveredTasks={[
        ...notes.flatMap(note => [note.taskId, note.meetingSource && note.meetingSource.ownerId === userId ? note.meetingSource.canonicalTaskId : undefined]),
        ...pending.map(record => record.taskId),
      ].filter((id): id is string => !!id)} returnTo={location.pathname + location.search + location.hash} />}
    </div>
  );
}
