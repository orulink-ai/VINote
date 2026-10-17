import type { Delivery } from './feishu';
import { publishScope } from './feishuPublishReceipt';
import { readRuntimeConfig } from './runtimeConfig';

export type RetryReceipt = { jobId: string; observedRunning: boolean };
const key = (owner: string, note: string) => `vinote:${owner}:feishu-retry:${encodeURIComponent(note)}:${encodeURIComponent(readRuntimeConfig('VITE_API_BASE_URL') || window.location.origin)}`;
export function readRetryReceipt(owner: string, note: string): RetryReceipt | null {
  publishScope(owner)();
  const raw = localStorage.getItem(key(owner, note));
  if (!raw) return null;
  const value = JSON.parse(raw) as RetryReceipt;
  if (!value.jobId || typeof value.observedRunning !== 'boolean') throw new Error('原重试记录无法核验，请保留记录');
  return value;
}
export function beginRetryReceipt(owner: string, note: string, jobId: string) {
  publishScope(owner)();
  if (readRetryReceipt(owner, note)) throw new Error('原重试结果尚未确认，请查询原任务');
  const value = { jobId, observedRunning: false };
  localStorage.setItem(key(owner, note), JSON.stringify(value));
  return value;
}
// Only a GET can resolve this marker. A failed POST response may be the old failure.
export function observeRetryReceipt(owner: string, note: string, job: Delivery): RetryReceipt | null {
  const value = readRetryReceipt(owner, note);
  if (!value) return null;
  if (job.id !== value.jobId) throw new Error('查询结果不属于原重试任务');
  if (job.phase !== 'unknown' && (job.status === 'completed' || (value.observedRunning && job.status === 'failed'))) {
    localStorage.removeItem(key(owner, note));
    return null;
  }
  const next = { ...value, observedRunning: value.observedRunning || ['queued', 'processing'].includes(job.status) };
  localStorage.setItem(key(owner, note), JSON.stringify(next));
  return next;
}
