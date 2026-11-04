import { useSyncExternalStore } from 'react';
import { readTrackedGenerations, TASK_ACTIVITY_EVENT } from '@/lib/taskNotifications';

function subscribe(update: () => void) {
  window.addEventListener(TASK_ACTIVITY_EVENT, update);
  window.addEventListener('storage', update);
  return () => {
    window.removeEventListener(TASK_ACTIVITY_EVENT, update);
    window.removeEventListener('storage', update);
  };
}

/** Navigation feedback reads existing receipts; it never adds network polling. */
export function ActiveTaskBadge({ owner, compact = false, zh = true }: { owner?: string; compact?: boolean; zh?: boolean }) {
  const count = useSyncExternalStore(subscribe, () => owner ? new Set(readTrackedGenerations(owner)
    .filter(task => task.active && !task.terminal)
    .map(task => task.taskId || task.operationId)).size : 0, () => 0);
  if (!count) return null;
  const label = zh ? `${count} 项任务尚未完成` : `${count} unfinished tasks`;
  return compact
    ? <span id="vinote-task-activity" title={label} className="absolute -right-1 -top-1 size-1.5 rounded-full bg-blue-600"><span className="sr-only">{label}</span></span>
    : <span id="vinote-task-activity" title={label} className="ml-auto rounded-md bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-blue-700 dark:bg-blue-950 dark:text-blue-200"><span aria-hidden="true">{count > 99 ? '99+' : count}</span><span className="sr-only">{label}</span></span>;
}
