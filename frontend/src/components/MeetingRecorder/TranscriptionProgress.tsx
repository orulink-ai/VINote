import { AudioLines, Check } from "lucide-react";
import { cn } from "@/lib/utils";

interface TranscriptionProgressProps {
  processedSeconds?: number;
  totalSeconds?: number;
  etaSeconds?: number;
  zh: boolean;
}

function duration(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

export function TranscriptionProgress({
  processedSeconds,
  totalSeconds,
  etaSeconds,
  zh,
}: TranscriptionProgressProps) {
  const measured =
    Number.isFinite(processedSeconds) &&
    processedSeconds! >= 0 &&
    Number.isFinite(totalSeconds) &&
    totalSeconds! > 0;
  const processed = measured
    ? Math.min(totalSeconds!, Math.max(0, processedSeconds!))
    : 0;
  const percentage = measured
    ? Math.floor((processed / totalSeconds!) * 100)
    : undefined;
  const complete = measured && processed >= totalSeconds!;
  const hasEstimate =
    Number.isFinite(etaSeconds) &&
    etaSeconds! > 0 &&
    processed > 0 &&
    !complete;
  return (
    <div
      className="flex flex-col gap-3 text-sm"
      aria-live="polite"
      aria-atomic="true"
    >
      <div className="flex items-center gap-2">
        {complete ? <Check aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" /> : <AudioLines aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />}
      <p className="font-medium tabular-nums">
        {measured
          ? `${zh ? "已转写" : "Transcribed"} ${duration(processed)} / ${duration(totalSeconds!)} (${percentage}%)`
          : zh
            ? "正在转写完整录音"
            : "Transcribing the complete recording"}
      </p>
      </div>
      {measured && <div
        role="progressbar"
        aria-label={zh ? "音频转写进度" : "Audio transcription progress"}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percentage}
        aria-valuetext={measured
          ? `${duration(processed)} / ${duration(totalSeconds!)} (${percentage}%)`
          : zh ? "正在转写，等待测量进度" : "Transcribing; waiting for measured progress"}
        className="h-1.5 w-full overflow-hidden rounded-sm bg-secondary"
      >
        <div
          className={cn(
            "h-full rounded-sm bg-primary",
          )}
          style={percentage !== undefined ? { width: `${percentage}%` } : undefined}
        />
      </div>}
      <p className="text-xs leading-5 text-muted-foreground">
        {complete
          ? zh
            ? "音频转写完成，正在整理结果。"
            : "Transcription complete; preparing results."
          : hasEstimate
            ? zh
              ? `预计还需约 ${Math.ceil(etaSeconds!)} 秒`
              : `About ${Math.ceil(etaSeconds!)} seconds remaining`
            : zh
              ? measured ? "暂无法估算剩余时间，正在等待识别结果。" : "服务尚未提供识别百分比，完成后会自动更新结果。"
              : "Remaining time is not yet available."}
      </p>
    </div>
  );
}
