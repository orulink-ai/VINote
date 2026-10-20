import { sourceHistoryAction } from '@/lib/taskRecoveryView';
import { isRejectedVersionReceipt, readVersionReceipt, meetingVersionDetails } from '@/lib/meetingVersionRecovery';
import { depthLabels, presentationLabels } from '@/lib/summaryPresentation';
import { useEffect, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { listPendingMeetings, type PendingMeeting } from "@/lib/audioStorage";
import { useAuthStore } from "@/stores/authStore";
import { deliveryStatus, type Delivery } from "@/lib/feishu";
import { listMCPRuns, mcpRunLabel, type MCPRun } from "@/lib/mcpConnections";
import { useLibraryNotes, libraryNoteUrl } from "@/hooks/useLibraryNotes";
import { pageParentLabel, resolvePageParent } from '@/lib/navigation';
import { PageReturn } from '@/components/Layout/PageReturn';
import { PageHeading } from "@/components/Layout/PageHeading";
import {
  ErrorState,
  LoadingState,
  EmptyState,
} from "@/components/Feedback/ResourceState";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function Tasks() {
  const [params, setParams] = useSearchParams();
  const historyReturn = `/tasks${params.toString() ? `?${params.toString()}` : ''}`;
  const tab = ["generation", "feishu", "mcp"].includes(
    params.get("tab") || "",
  )
    ? params.get("tab")!
    : "generation";
  const owner = useAuthStore((s) => s.user?.id);
  const notes = useLibraryNotes();
  const legacySync = params.get('tab') === 'sync';
  const [recordings, setRecordings] = useState<PendingMeeting[]>([]);
  type SourceImport = { id?: string; operationId?: string; meeting: boolean; mode?: string; submissionState?: string };
  const [imports, setImports] = useState<SourceImport[]>([]);
  const [runs, setRuns] = useState<MCPRun[]>([]);
  const [deliveries, setDeliveries] = useState<
    { noteId: string; title: string; url: string; job: Delivery }[]
  >([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (legacySync) return;
    let active = true;
    setLoading(true);
    setError("");
    const load = async () => {
      if (tab === "generation") {
        const accepted = new Map<string, SourceImport>();
        const keys = owner ? ['note', 'meeting'].map(kind => `vinote:import-receipt:${owner}:${kind}`) : [];
        if (owner) for (let index = 0; index < localStorage.length; index++) {
          const key = localStorage.key(index);
          if (key?.startsWith(`vinote:source-receipt:${owner}:`) || key?.startsWith(`vinote:source-task-receipt:${owner}:`)) keys.push(key);
        }
        for (const key of keys) {
          const raw = localStorage.getItem(key);
          if (raw) {
            const saved = owner && key.startsWith(`vinote:source-receipt:${owner}:`)
              ? readVersionReceipt(localStorage, owner, key.slice(`vinote:source-receipt:${owner}:`.length)) as SourceImport
              : JSON.parse(raw);
            if (!saved) continue;
            if ((typeof saved.id === 'string' && saved.id || typeof saved.operationId === 'string' && /^[A-Za-z0-9_-]{1,160}$/.test(saved.operationId)) && typeof saved.meeting === 'boolean') accepted.set(saved.operationId || saved.id, saved);
          }
        }
        if (active) setImports([...accepted.values()]);
        const local = owner ? await listPendingMeetings(owner) : [];
        if (active) setRecordings(local);
      } else if (tab === "mcp") {
        const next = await listMCPRuns();
        if (active) setRuns(next.runs);
      } else if (tab === "feishu") {
        const next: typeof deliveries = [];
        // Serial readback avoids issuing one request per note simultaneously.
        for (const note of notes) {
          if (!active) return;
          const job = await deliveryStatus(note.id);
          if (job)
            next.push({
              noteId: note.id,
              title: note.title,
              url: libraryNoteUrl(note),
              job,
            });
        }
        if (active) setDeliveries(next);
      }
    };
    void load()
      .catch((cause) => {
        if (active) setError(cause.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [owner, tab, attempt, legacySync]);
  if (legacySync) return <Navigate replace to={'/settings/storage?' + new URLSearchParams({ returnTo: resolvePageParent(params.get('returnTo')) })} />;
  return (
    <div className="workspace-page max-w-5xl">
      <PageReturn to={resolvePageParent(params.get("returnTo"))} label={pageParentLabel(resolvePageParent(params.get("returnTo")))} />
      <PageHeading
        title="任务与恢复"
        description="查看实际处理阶段与运行位置，从所属记录继续恢复。"
        actions={
          <Button
            variant="outline"
            disabled={loading}
            onClick={() => setAttempt((n) => n + 1)}
          >
            <RefreshCw />
            刷新状态
          </Button>
        }
      />
      <Tabs value={tab} onValueChange={(value) => setParams(previous => {
        const next = new URLSearchParams(previous);
        next.set('tab', value);
        return next;
      })}>
        <TabsList className="line-tabs">
          <TabsTrigger value="generation">生成</TabsTrigger>
          <TabsTrigger value="feishu">飞书</TabsTrigger>
          <TabsTrigger value="mcp">MCP</TabsTrigger>
        </TabsList>
      </Tabs>
      {error && (
        <ErrorState
          error={error}
          onRetry={() => setAttempt((n) => n + 1)}
          busy={loading}
        />
      )}
      {loading && <LoadingState rows={1} label="正在更新任务状态…" />}
      {tab === "generation" && (
        <>
          {imports.map((item) => {
            const version = meetingVersionDetails(item, owner);
            const rejected = isRejectedVersionReceipt(item, owner);
            return <article key={item.operationId || item.id} className="grid gap-2 border-b pb-4">
            <h2 className="text-balance font-medium">{version ? `${version.title} · 新版本` : item.meeting ? '会议导入任务' : '资料整理任务'}</h2>
            {version && <dl className="grid gap-2 text-sm sm:grid-cols-2">
              <div><dt className="text-muted-foreground">本次选择的总结模型</dt><dd className="break-words">{version.model}</dd></div>
              <div><dt className="text-muted-foreground">内容与形式</dt><dd>{depthLabels[version.depth]} · {presentationLabels[version.presentation]}</dd></div>
              <div><dt className="text-muted-foreground">语音识别</dt><dd>{version.reuse ? '复用已有转写' : '重新识别（已确认）'}</dd></div>
              <div><dt className="text-muted-foreground">提交时间</dt><dd><time className="tabular-nums" dateTime={version.createdAt}>{new Date(version.createdAt).toLocaleString('zh-CN', { hour12: false })}</time></dd></div>
            </dl>}
            <p className="text-pretty text-sm text-muted-foreground">{rejected ? '本次未受理，未创建任务。失败记录已保留，重新生成需要返回来源再次核验确认。' : item.operationId && item.submissionState !== 'accepted' ? item.submissionState === 'reserved' ? '已收到提交，排队状态待确认；请查询原任务。' : '提交状态待确认，原来源已保留，请查询原任务。' : '任务已接收，请查询原结果，避免重复生成。'}</p>
            {import.meta.env.DEV && <details className="text-xs text-muted-foreground"><summary>开发诊断</summary>{item.operationId && <p>提交编号：{item.operationId}</p>}{item.id && <p>任务编号：{item.id}</p>}</details>}
            <Button variant="outline" className="w-fit" asChild><Link to={`/generate?mode=${item.mode === 'url' ? 'url' : 'file'}${item.meeting ? '&meeting=1' : ''}${item.operationId ? `&operation=${encodeURIComponent(item.operationId)}` : item.id ? `&task=${encodeURIComponent(item.id)}` : ''}`} state={{ returnTo: historyReturn }}>{rejected ? '查看未受理记录' : sourceHistoryAction(item)}</Link></Button>
          </article>})}
          {recordings.map((r) => (
            <article key={r.id} className="flex flex-col gap-2 border-b pb-4">
              <div className="flex justify-between gap-3">
                <h2 className="font-medium">{r.options.title}</h2>
                <Badge
                  variant={
                    r.processingStatus === "failed"
                      ? "destructive"
                      : "secondary"
                  }
                >
                  {
                    {
                      idle: "已保存",
                      queued: "排队中",
                      preparing_media: "准备资料",
                      transcribing: "转写",
                      diarizing: "说话人分析",
                      parallel_analysis: "转写与说话人分析",
                      aligning: "对齐",
                      analyzing_video: "视频分析",
                      generating: "生成与核对",
                      saving_result: "保存结果",
                      completed: "完成",
                      failed: "需处理",
                    }[r.processingStatus]
                  }
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                原录音已保留 · {r.taskId ? "正在处理" : "尚未生成纪要"}
              </p>
              {r.processingError && (
                <p className="text-sm text-destructive">{r.processingError}</p>
              )}
              <Button variant="outline" className="w-fit" asChild>
                <Link to={r.noteId ? `/note/${encodeURIComponent(r.noteId)}` : `/files?${new URLSearchParams({ type: 'all', q: '', file: `recording:${r.id}`, returnTo: historyReturn })}`} state={{ returnTo: historyReturn }}>
                  {r.processingStatus === "failed"
                    ? "查看原录音与恢复选项"
                    : r.noteId ? "查看会议纪要" : "查看原录音"}
                </Link>
              </Button>
            </article>
          ))}
          {!loading && !error && !recordings.length && !imports.length && (
            <EmptyState
              title="暂无生成任务"
              description="录制或导入资料，保存后可开始生成。"
            >
              <Button asChild>
                <Link to="/meetings">前往会议</Link>
              </Button>
            </EmptyState>
          )}
        </>
      )}
      {tab === "feishu" && (
        <>
          {deliveries.map((item) => (
            <div
              key={item.noteId}
              className="flex flex-col gap-3 border-b py-3"
            >
              <h2>{item.title}</h2>
              <p className="text-sm">
                {item.job.status === "completed"
                  ? "已完成交付"
                  : item.job.status === "failed"
                    ? "需处理"
                    : "处理中"}{" "}
                · 飞书集成服务
              </p>
              {item.job.error && (
                <p className="text-sm text-destructive">{item.job.error}</p>
              )}
              <Button variant="outline" className="w-fit" asChild>
                <Link to={item.url}>打开交付记录并恢复失败步骤</Link>
              </Button>
            </div>
          ))}
          {!loading && !error && !deliveries.length && (
            <EmptyState
              title="暂无交付记录"
              description="从已保存内容的详情页发起飞书交付。"
            >
              <Button variant="outline" asChild>
                <Link to="/settings/feishu" state={{ returnTo: historyReturn }}>检查飞书配置</Link>
              </Button>
            </EmptyState>
          )}
        </>
      )}
      {tab === "mcp" && (
        <>
          {runs.map((run) => (
            <div key={run.id} className="border-b py-3">
              <p>
                {run.toolName} · {mcpRunLabel[run.status]}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                集成服务 · {new Date(run.updatedAt).toLocaleString()}
              </p>
              {run.error && (
                <p className="mt-2 text-sm text-destructive">
                  {run.error.message}
                </p>
              )}
            </div>
          ))}
          {!loading && !error && !runs.length && (
            <EmptyState
              title="暂无工具任务"
              description="连接真实服务并确认调用后，在这里查看进度与结果。"
            />
          )}
          <Button variant="outline" className="w-fit" asChild>
            <Link to="/settings/mcp" state={{ returnTo: historyReturn }}>管理工具与运行记录</Link>
          </Button>
        </>
      )}
    </div>
  );
}
