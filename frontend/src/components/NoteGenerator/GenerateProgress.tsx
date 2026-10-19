import {
  CheckCircle2,
  Circle,
  Loader2 as LoaderCircle,
  AlertCircle,
} from "lucide-react";
import { useI18n } from "../../lib/i18n";
import { Alert, AlertDescription } from "../ui/alert";
import { Badge } from "../ui/badge";
import { cn } from "../../lib/utils";
import { ProcessingWave } from "@/components/ui/motion";

interface GenerateProgressProps {
  status: "idle" | "uploading" | "processing" | "success" | "failed";
  /** Legacy phase estimate; deliberately not used as measured progress. */
  progress?: number;
  processedSeconds?: number;
  totalSeconds?: number;
  receivedSeconds?: number;
  speakerDetectionProgress?: number;
  speakersReady?: boolean;
  currentStep: string;
  error?: string;
  message?: string;
  documentSource?: boolean;
  meeting?: boolean;
  audioOnlySource?: boolean;
  videoSource?: boolean;
}

export function GenerateProgress({
  status,
  processedSeconds,
  totalSeconds,
  receivedSeconds,
  speakerDetectionProgress,
  speakersReady,
  currentStep,
  error,
  documentSource = false,
  meeting = false,
  audioOnlySource = false,
  videoSource = false,
}: GenerateProgressProps) {
  const { copy } = useI18n();
  const videoStep = videoSource || currentStep === 'analyzing_video' ? [{ key: 'analyzing_video', label: '核对共享画面与发言' }] : [];
  const steps = documentSource ? [
    { key: "preparing", label: "读取来源正文" },
    { key: "summarizing", label: "生成总结笔记" },
    { key: "saving", label: "保存笔记" },
  ] : meeting ? [
    { key: 'preparing', label: '准备会议文件' },
    { key: 'transcribing', label: '转写与说话人分析' },
    ...videoStep,
    { key: 'summarizing', label: '生成并核对会议纪要' },
    { key: 'saving', label: '保存会议纪要' },
  ] : [
    { key: "uploading", label: copy.progress.prepareRequest },
    { key: "downloading", label: copy.progress.downloadAudio },
    { key: "transcribing", label: copy.progress.transcribeAudio },
    ...videoStep,
    { key: "summarizing", label: copy.progress.generateNote },
    ...(!audioOnlySource ? [{
      key: "screenshots",
      label: copy.progress.processScreenshots,
    }] : []),
    { key: "saving", label: "保存笔记" },
  ];
  const phase = meeting && ['parallel_analysis', 'diarizing', 'aligning', 'transcript_ready'].includes(currentStep) ? 'transcribing'
    : (meeting || documentSource) && currentStep === 'uploading' ? 'preparing'
    : !meeting && !documentSource && currentStep === 'preparing' ? 'uploading' : currentStep;
  const stepLabels = Object.fromEntries(
    steps.map((step) => [step.key, step.label]),
  );
  const activeStep = Math.max(
    1,
    steps.findIndex((step) => step.key === phase) + 1,
  );
  const running = status === "processing" || status === "uploading";
  // Backend coverage describes transcription, not overall note completion.
  // Ignore retained transcription measurements when the next stage begins.
  const measured = phase === "transcribing" &&
    Number.isFinite(processedSeconds) && processedSeconds! >= 0 &&
    Number.isFinite(totalSeconds) && totalSeconds! > 0;
  const receivedMeasured = phase === 'transcribing' && Number.isFinite(receivedSeconds) && receivedSeconds! >= 0 && Number.isFinite(totalSeconds) && totalSeconds! > 0;
  const percentage = status === "success" ? 100 : receivedMeasured
    ? Math.floor(Math.min(measured && processedSeconds! >= totalSeconds! ? 1 : .99, receivedSeconds! / totalSeconds!) * 100) : measured
    ? Math.floor(Math.min(1, processedSeconds! / totalSeconds!) * 100)
    : undefined;
  const progressLabel = phase === 'transcribing' && status !== 'success' ? receivedMeasured ? '音频提交进度' : '音频转写进度' : meeting ? '会议纪要生成进度' : '生成笔记阶段进度';
  const analysis = phase === 'transcribing' && !documentSource;
  const savedTranscript = measured && processedSeconds! >= totalSeconds!;
  const speakerMeasured = Number.isFinite(speakerDetectionProgress) && speakerDetectionProgress! >= 0 && speakerDetectionProgress! <= 1;
  const speakerPercentage = speakerMeasured ? Math.floor(speakerDetectionProgress! * 100) : undefined;
  const duration = (seconds: number) => {
    const value = Math.floor(Math.max(0, seconds));
    return `${Math.floor(value / 60).toString().padStart(2, '0')}:${(value % 60).toString().padStart(2, '0')}`;
  };
  const knownTotal = Number.isFinite(totalSeconds) && totalSeconds! > 0;
  const audioSeconds = receivedMeasured ? receivedSeconds : measured ? processedSeconds : undefined;
  const renderBar = (label: string, value?: number) => <div
    className="h-2 overflow-hidden rounded-full bg-secondary" role="progressbar"
    aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}
    aria-valuetext={value !== undefined ? `${value}%` : status === 'failed' ? '处理已停止，未获得测量进度' : '等待测量进度'}>
    <div className={cn('h-full rounded-full', value === undefined && 'w-1/3 opacity-60', value === undefined && running && 'motion-safe:animate-pulse motion-reduce:animate-none', status === 'failed' ? 'bg-destructive' : 'bg-primary')}
      style={value !== undefined ? { width: `${value}%` } : undefined} />
  </div>;
  const stageTitle = status === 'success' ? copy.progress.completed : status === 'failed' ? copy.progress.failed
    : phase === 'analyzing_video' ? '核对共享画面与发言' : meeting ? '正在生成会议纪要' : analysis ? '语音转写' : stepLabels[phase] || copy.progress.preparing;
  const statusCopy = analysis
    ? savedTranscript && speakersReady ? (meeting ? '音频分析已完成，接下来生成纪要。' : '转写已完成，接下来生成笔记。')
      : receivedMeasured && receivedSeconds! >= totalSeconds! && !savedTranscript ? '音频已提交，正在等待最终逐字稿。'
      : meeting ? '转写和说话人分析完成后，将生成纪要；返回后可继续查看。'
      : '转写完成后，将生成笔记；返回后可继续查看。'
    : phase === 'analyzing_video' ? '正在核对共享画面与发言，完成后继续生成纪要。逐字稿已就绪不代表纪要已完成。'
    : phase === 'saving' ? '正在保存生成内容，请稍候。'
    : phase === 'summarizing' ? meeting ? '正在整理并核对会议纪要。' : '正在整理笔记。'
    : '正在准备来源，完成后继续处理。';

  const getStepStatus = (stepKey: string) => {
    if (status === "success") return "completed";
    const currentIndex = steps.findIndex((step) => step.key === phase);
    const stepIndex = steps.findIndex((step) => step.key === stepKey);
    if (stepIndex < currentIndex) return "completed";
    if (stepIndex === currentIndex)
      return status === "failed" ? "failed" : "processing";
    return "pending";
  };

  if (status === "idle") return null;

  return (
    <section className="border">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b p-5">
        <h2 className="flex items-center gap-2 text-balance text-base font-semibold">
          {running && !(meeting && analysis) && (phase === 'analyzing_video' ? <span aria-hidden="true"><ProcessingWave label={stageTitle} /></span> : <ProcessingWave label={meeting ? '正在生成会议纪要' : '正在生成笔记'} />)}
          {stageTitle}
        </h2>
        <Badge variant={status === 'failed' ? 'destructive' : 'secondary'}>{status === 'success' ? '已完成' : status === 'failed' ? '已停止' : `第 ${activeStep} / ${steps.length} 步`}</Badge>
      </header>
      <div className="grid gap-5 p-5">
        {analysis ? <div className="grid gap-5">
          <section aria-label="语音转写" className="grid gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <h3 className="font-medium">语音转写</h3>
              <span className="text-muted-foreground">{savedTranscript ? '逐字稿已保存' : status === 'failed' ? '已停止' : audioSeconds === undefined ? '等待识别进度' : '正在识别'}</span>
            </div>
            {renderBar(progressLabel, percentage)}
            <p className="flex flex-wrap justify-between gap-2 text-sm tabular-nums text-muted-foreground">
              <span>{audioSeconds !== undefined ? `${receivedMeasured ? '已提交识别' : '已保存转写'} ${duration(Math.min(audioSeconds, totalSeconds!))} / ${duration(totalSeconds!)}` : knownTotal ? `音频时长 ${duration(totalSeconds!)} · 已识别时长待更新` : '音频时长与识别进度待更新'}</span>
              {percentage !== undefined && <span>{percentage}%</span>}
            </p>
          </section>
          {meeting && <section aria-label="说话人分析" className="grid gap-2 border-t pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <div className="flex items-center gap-2">{running && !speakersReady && <ProcessingWave label="正在分析说话人" />}<h3 className="font-medium">说话人分析</h3></div>
              <span className="text-muted-foreground">{speakersReady ? '分析已保存' : status === 'failed' ? '已停止' : speakerMeasured && speakerDetectionProgress === 1 ? '正在核对声音特征' : speakerMeasured ? '正在检测发言区间' : '等待分析进度'}</span>
            </div>
            {speakersReady ? <>
              {renderBar('说话人分析已保存', 100)}
              <p className="text-right text-sm tabular-nums text-muted-foreground">100%</p>
            </> : <>
              {renderBar('发言区间检测进度', speakerPercentage)}
              <p className="flex justify-between gap-2 text-sm tabular-nums text-muted-foreground"><span>{speakerPercentage === 100 ? '发言区间检测完成' : '发言区间检测'}</span>{speakerPercentage !== undefined && <span>{speakerPercentage}%</span>}</p>
            </>}
          </section>}
        </div> : <>
          {renderBar(progressLabel, percentage)}
          <p className="text-sm tabular-nums text-muted-foreground">{status === 'success' ? `100% · ${meeting ? '会议纪要已保存' : '笔记已完成'}` : status === 'failed' ? '处理已停止' : '进度待更新'}</p>
        </>}
        {running && <p role="status" className="text-pretty text-sm leading-6 text-muted-foreground">{statusCopy}</p>}

        <div role="list" aria-label={meeting ? '会议纪要处理步骤' : '笔记处理步骤'} className="grid gap-2 sm:grid-cols-2">
          {steps.map((step) => {
            const stepStatus = getStepStatus(step.key);
            const stateLabel = { pending: '待开始', processing: '进行中', completed: '已完成', failed: '失败' }[stepStatus];

            return (
              <div
                key={step.key}
                data-state={stepStatus}
                data-stage-state={stepStatus === 'processing' ? 'active' : stepStatus}
                role="listitem"
                aria-label={`${step.label}：${stateLabel}`}
                aria-current={stepStatus === 'processing' ? 'step' : undefined}
                className={cn(
                  "flex items-center gap-3 border-l-2 border-transparent p-3",
                  stepStatus === "processing"
                    ? "border-primary/30 bg-primary/5"
                    : "border-transparent",
                )}
              >
                {stepStatus === "completed" && (
                  <CheckCircle2 aria-hidden="true" className="size-5 text-muted-foreground" />
                )}
                {stepStatus === "processing" && (
                  <LoaderCircle aria-hidden="true" className="size-5 motion-safe:animate-spin motion-reduce:animate-none text-primary" />
                )}
                {stepStatus === "failed" && (
                  <AlertCircle aria-hidden="true" className="size-5 text-destructive" />
                )}
                {stepStatus === "pending" && (
                  <Circle aria-hidden="true" className="size-5 text-muted-foreground/50" />
                )}

                <span
                  className={cn(
                    "text-sm",
                    stepStatus === "completed" && "text-muted-foreground",
                    stepStatus === "processing" && "text-primary font-medium",
                    stepStatus === "failed" && "text-destructive",
                    stepStatus === "pending" && "text-muted-foreground",
                  )}
                >
                  {step.label}
                </span>
                <span className="ml-auto shrink-0 text-xs text-muted-foreground">{stateLabel}</span>
              </div>
            );
          })}
        </div>

        {status === "failed" && error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </div>
    </section>
  );
}
