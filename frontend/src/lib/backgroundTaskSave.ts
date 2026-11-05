import { apiJson } from './api';
import { readRuntimeConfig } from './runtimeConfig';
import { useAuthStore } from '@/stores/authStore';
import { deletedMeetingTasks } from './deletedMeetingTasks';

/** Saves completed generated content only; never starts generation or sends messages. */
export const BACKGROUND_NOTE_SAVED = 'vinote:background-note-saved';
type Receipt = { taskId: string; scope: 'personal' | 'team'; teamId: string | null; sourceType: string; sourceUrl: string | null; meeting: boolean };
type SavedNote = { id: string; task_id: string; scope: string; team_id?: string | null };
const sourceTypes = new Set(['webpage', 'document', 'file', 'transcript', 'audio', 'video', 'meeting_recording', 'meeting_video']);
const inFlight = new Map<string, Promise<string | null>>();
let ownerEpoch = 0;
let observedOwner = useAuthStore.getState().user?.id;
useAuthStore.subscribe(state => { if (state.user?.id !== observedOwner) { observedOwner = state.user?.id; ownerEpoch++; } });
const origin = () => readRuntimeConfig('VITE_API_BASE_URL') || window.location.origin;
const id = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{1,160}$/.test(value);

function acceptedReceipt(owner: string, taskId: string): Receipt | null {
  let selected: Receipt | null = null;
  const prefixes = ['source-receipt', 'source-task-receipt', 'import-receipt', 'import-draft'].map(kind => `vinote:${kind}:${owner}:`);
  for (let index = 0; index < localStorage.length; index++) {
    const key = localStorage.key(index) || '';
    if (!prefixes.some(prefix => key.startsWith(prefix))) continue;
    let belongsToTask = false;
    try {
      const item = JSON.parse(localStorage.getItem(key) || 'null');
      if (!item || item.id !== taskId || item.submissionState !== 'accepted') continue;
      belongsToTask = true;
      if (item.owner && item.owner !== owner || typeof item.meeting !== 'boolean'
          || item.summaryOnly || item.meetingVersion || item.independentGeneration) return null;
      if (key.startsWith(prefixes[0]) && (!id(item.operationId) || key !== prefixes[0] + item.operationId)) return null;
      if (!item.workspace || !['personal', 'team'].includes(item.workspace.scope)
          || item.workspace.scope === 'team' && !id(item.workspace.teamId)
          || !sourceTypes.has(item.sourceType)) return null;
      if (item.sourceUrl !== undefined && item.sourceUrl !== null && typeof item.sourceUrl !== 'string') return null;
      const sourceUrl = item.sourceUrl || null;
      if (sourceUrl) { const parsed = new URL(sourceUrl); if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password) return null; }
      if (!item.meeting && item.sourceType.startsWith('meeting_')) return null;
      if (item.meeting && !['audio', 'video', 'transcript', 'meeting_recording', 'meeting_video'].includes(item.sourceType)) return null;
      const next: Receipt = { taskId, scope: item.workspace.scope, teamId: item.workspace.scope === 'team' ? item.workspace.teamId : null,
        sourceType: item.meeting ? ['video', 'meeting_video'].includes(item.sourceType) ? 'meeting_video' : 'meeting_recording' : item.sourceType,
        sourceUrl, meeting: item.meeting };
      if (selected && JSON.stringify(selected) !== JSON.stringify(next)) return null;
      selected = next;
    } catch { if (belongsToTask || key === prefixes[1] + taskId) return null; }
  }
  return selected;
}

export function backgroundSaveCompletedTask(owner: string, taskId: string): Promise<string | null> {
  if (!owner || !id(taskId) || useAuthStore.getState().user?.id !== owner || deletedMeetingTasks(owner).has(taskId)) return Promise.resolve(null);
  const invocationKey = JSON.stringify([origin(), ownerEpoch, owner, taskId]);
  const previous = inFlight.get(invocationKey);
  if (previous) return previous;
  const pending = save(owner, taskId).finally(() => { if (inFlight.get(invocationKey) === pending) inFlight.delete(invocationKey); });
  inFlight.set(invocationKey, pending);
  return pending;
}

async function save(owner: string, taskId: string): Promise<string | null> {
  const receipt = acceptedReceipt(owner, taskId);
  if (!receipt) return null;
  const epoch = ownerEpoch, service = origin(), frozen = JSON.stringify(receipt);
  const active = () => ownerEpoch === epoch && origin() === service && useAuthStore.getState().user?.id === owner
    && !deletedMeetingTasks(owner).has(taskId) && JSON.stringify(acceptedReceipt(owner, taskId)) === frozen;
  const data = await apiJson<{ task_id?: string; status: string; result?: { task_id: string; title: string; markdown: string } }>(`/api/task/${encodeURIComponent(taskId)}`);
  if (!active() || data.status !== 'success' || data.task_id && data.task_id !== taskId
      || data.result?.task_id !== taskId || typeof data.result.title !== 'string' || !data.result.title.trim()
      || data.result.title.length > 255 || typeof data.result.markdown !== 'string' || !data.result.markdown.trim()) return null;
  const query = new URLSearchParams({ scope: receipt.scope, task_id: taskId });
  if (receipt.teamId) query.set('team_id', receipt.teamId);
  const rows = await apiJson<SavedNote[]>(`/api/notes?${query}`);
  if (!active() || !Array.isArray(rows)) return null;
  const matches = (note: SavedNote) => note && typeof note.id === 'string' && note.task_id === taskId
    && note.scope === receipt.scope && (note.team_id || null) === receipt.teamId;
  const existing = rows.find(matches);
  const marker = `vinote:background-task-saved:${owner}:${encodeURIComponent(JSON.stringify([service, taskId, receipt.scope, receipt.teamId]))}`;
  if (existing) { localStorage.setItem(marker, existing.id); return existing.id; }
  // A later delete must not be undone by another completion poll.
  if (localStorage.getItem(marker)) return null;
  if (!active()) return null;
  const saved = await apiJson<SavedNote>('/api/notes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
    title: data.result.title, content: data.result.markdown, video_url: receipt.sourceUrl, task_id: taskId,
    source_type: receipt.sourceType, scope: receipt.scope, team_id: receipt.teamId, status: 'done',
  }) });
  if (!active() || !matches(saved)) return null;
  localStorage.setItem(marker, saved.id);
  window.dispatchEvent(new CustomEvent(BACKGROUND_NOTE_SAVED, { detail: { owner, noteId: saved.id, workspace: { scope: receipt.scope, teamId: receipt.teamId } } }));
  return saved.id;
}
