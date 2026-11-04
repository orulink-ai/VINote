import { AlertCircle, CheckCircle2, Clock3, Loader2 } from 'lucide-react';
import type { CenterTask } from '@/hooks/useTaskCenter';

/** Only verified stage measurements are rendered as percentages. */
export function TaskProgress({ task }: { task: CenterTask }) {
  const Icon = task.failed || task.unavailable ? AlertCircle : task.noteId ? CheckCircle2 : task.terminal || !task.status ? Clock3 : Loader2;
  const spinning = Icon === Loader2;
  const measured = typeof task.progress === 'number' && Number.isFinite(task.progress) && task.progress >= 0 && task.progress <= 100;
  return <div className="min-w-0 max-w-sm space-y-2">
    <div className={`flex items-center gap-2 text-xs ${task.failed ? 'text-destructive' : task.noteId ? 'text-emerald-700 dark:text-emerald-400' : 'text-muted-foreground'}`}>
      <Icon aria-hidden="true" className={`size-3.5 shrink-0 ${spinning ? 'motion-safe:animate-spin' : ''}`} />
      <span>{task.label}</span>
    </div>
    {measured && <div role="progressbar" aria-label="转写进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={task.progress} aria-valuetext={task.measure} className="h-1.5 overflow-hidden rounded-full bg-muted">
      <div className="h-full rounded-full bg-primary motion-safe:transition-[width] motion-safe:duration-300" style={{ width: `${task.progress}%` }} />
    </div>}
    {task.measure && <p className="text-xs tabular-nums text-muted-foreground">{task.measure}</p>}
    {task.unavailable && <p className="text-xs text-muted-foreground">暂时无法更新进度，保留上次状态；正在重新查询。</p>}
  </div>;
}
