import type { MeetingTaskStates } from '@/hooks/useMeetingTaskStates';
import { libraryNoteIdentities, type LibraryNote as NoteRecord } from '@/hooks/useLibraryNotes';
import type { PendingMeeting } from './audioStorage';
import { serverTimestamp } from './serverTimestamp';

const timestamp = (value: string) => {
  const time = serverTimestamp(value).getTime();
  return Number.isFinite(time) ? time : 0;
};

export type MeetingRow = {
  kind: 'meeting' | 'unlinked';
  key: string;
  title: string;
  date: string;
  dateKind: 'recording' | 'unknown';
  state: string;
  recording?: PendingMeeting;
  note?: NoteRecord;
  notes: NoteRecord[];
  recordings: PendingMeeting[];
};

// Only an explicit capture timestamp names a meeting. Saved-note dates and
// legacy workspace metadata are not evidence of when recording began.
function captureTimestamp(value: string | undefined) {
  if (!value || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return undefined;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toISOString() : undefined;
}

export function meetingRecordingTitle(value: string | undefined) {
  const instant = captureTimestamp(value);
  if (!instant) return '录制时间未记录';
  const date = new Date(instant);
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function meetingNoteState(note: NoteRecord, taskStates: MeetingTaskStates = {}) {
  const state = taskStates[note.taskId || ''];
  if (state === 'failed') return '需处理';
  if (state === 'processing') return '处理中';
  if (state === 'checking') return '状态核验中';
  if (state === 'unverified') return '状态未核验';
  if (state === 'complete' && note.status !== 'done') return '纪要待保存';
  return ['failed', 'transcribing_failed', 'generation_failed'].includes(note.status)
    ? '需处理' : note.status === 'done' ? '已完成' : '状态未核验';
}

/** A projection only: every content object and retained original stays reachable. */
export function buildMeetingRows(recordings: PendingMeeting[], notes: NoteRecord[], taskStates: MeetingTaskStates = {}, ownerId?: string): MeetingRow[] {
  // Legacy records belong to the authenticated collection; explicit provenance
  // and recordings carry their own owner and must never cross that boundary.
  const recordingOwners = [...new Set(recordings.map(row => row.ownerId).filter(Boolean))];
  const collectionOwner = ownerId || (recordingOwners.length === 1 ? recordingOwners[0] : '');
  const retainedNotes = [...new Map(notes.flatMap(note => [note, ...(note.localSources || [])])
    .filter(note => !ownerId || !note.meetingSource || note.meetingSource.ownerId === ownerId)
    .map(note => [JSON.stringify([note.meetingSource?.ownerId || collectionOwner, note.scope, note.teamId, note.workspaceKey, note.id]), note] as const)).values()];
  const nodes = [
    ...recordings.filter(recording => !ownerId || recording.ownerId === ownerId).map(recording => {
      const scope = `${recording.ownerId || collectionOwner}:${recording.workspace.scope}:${recording.workspace.scope === 'team' ? recording.workspace.teamId : ''}:`;
      return { recording, note: undefined as NoteRecord | undefined, identities: [
        `${scope}task:${recording.id}`, ...(recording.taskId ? [`${scope}task:${recording.taskId}`] : []),
        ...[recording.noteId, recording.draftNoteId].filter(Boolean).map(id => `${scope}note:${id}`),
      ] };
    }),
    ...retainedNotes.map(note => ({ note, recording: undefined as PendingMeeting | undefined, identities: [
      ...libraryNoteIdentities(note),
      ...(note.meetingSource ? [`${note.scope}:${note.teamId || ''}:task:${note.meetingSource.canonicalTaskId}`] : []),
    ].map(id => `${note.meetingSource?.ownerId || collectionOwner}:${id}`) })),
  ];
  const parents = nodes.map((_, index) => index);
  const root = (index: number): number => parents[index] === index ? index : (parents[index] = root(parents[index]));
  const canonicals = nodes.map(node => node.note?.meetingSource
    ? JSON.stringify([node.note.meetingSource.ownerId, node.note.scope, node.note.teamId || '', node.note.meetingSource.canonicalTaskId])
    : undefined);
  const verifiedGroups = new Map<string, number>();
  canonicals.forEach((canonical, index) => {
    if (!canonical) return;
    const previous = verifiedGroups.get(canonical);
    if (previous !== undefined) parents[root(index)] = root(previous);
    verifiedGroups.set(canonical, index);
  });
  const identities = new Map<string, number[]>();
  nodes.forEach((node, index) => node.identities.forEach(identity => {
    const members = identities.get(identity) || [];
    members.push(index);
    identities.set(identity, members);
  }));
  // Canonical tuples are authoritative. First build legacy-only components,
  // without letting any inferred alias connect two proven source groups.
  for (const members of identities.values()) {
    const legacy = members.filter(index => !canonicals[index]);
    legacy.slice(1).forEach(index => { parents[root(index)] = root(legacy[0]); });
  }
  // Inspect the whole legacy component before attaching it. Greedily attaching
  // the first edge would assign an ambiguous bridge by input order.
  const candidates = new Map<number, Set<number>>();
  for (const members of identities.values()) {
    const verified = members.filter(index => canonicals[index]).map(root);
    if (!verified.length) continue;
    for (const index of members.filter(index => !canonicals[index])) {
      const component = root(index);
      const targets = candidates.get(component) || new Set<number>();
      verified.forEach(target => targets.add(target));
      candidates.set(component, targets);
    }
  }
  for (const [component, targets] of candidates) {
    if (targets.size === 1) parents[component] = targets.values().next().value!;
    // Multiple targets remain a separate legacy group with every member intact.
  }
  const groups = new Map<number, typeof nodes>();
  nodes.forEach((node, index) => { const key = root(index); groups.set(key, [...(groups.get(key) || []), node]); });
  return [...groups.values()].map(group => {
    const content = group.flatMap(node => node.note ? [node.note] : [])
      .sort((a, b) => timestamp(b.createdAt) - timestamp(a.createdAt) || timestamp(b.updatedAt) - timestamp(a.updatedAt) || Number(!!b.workspaceKey) - Number(!!a.workspaceKey));
    const originals = group.flatMap(node => node.recording ? [node.recording] : []);
    const recording = originals.find(row => row.processingStatus !== 'completed') || originals[0];
    const note = content.find(row => row.status === 'done' && row.content.trim() &&
      (!row.taskId || !taskStates[row.taskId] || taskStates[row.taskId] === 'complete')) ||
      content.find(row => row.status === 'done' && row.content.trim()) || content[0];
    const sourceNote = content.find(row => row.meetingSource);
    const proven = sourceNote?.meetingSource;
    const canonicalTimes = [...new Set(content.flatMap(row => {
      const time = captureTimestamp(row.meetingSource?.recordingStartedAt);
      return time ? [time] : [];
    }))];
    const deviceTimes = [...new Set(originals.flatMap(row => {
      const time = captureTimestamp(row.startedAt);
      return time ? [time] : [];
    }))];
    // Conflicting canonical clocks fail closed, without choosing by input order.
    const date = canonicalTimes.length ? canonicalTimes.length === 1 ? canonicalTimes[0] : ''
      : deviceTimes.length === 1 ? deviceTimes[0] : '';
    const hasSavedMinutes = content.some(item => meetingNoteState(item, taskStates) === '已完成');
    let state = recording ? recording.processingStatus === 'failed' ? '需处理'
      : recording.processingStatus === 'idle' ? hasSavedMinutes ? '已完成' : '未生成'
        : recording.processingStatus === 'completed' ? hasSavedMinutes ? '已完成' : '纪要待保存'
          : '处理中' : meetingNoteState(note, taskStates);
    const taskState = taskStates[recording?.taskId || note?.taskId || ''];
    if (taskState === 'failed') state = '需处理';
    else if (taskState === 'processing') state = '处理中';
    else if (taskState === 'checking') state = '状态核验中';
    else if (taskState === 'unverified') state = '状态未核验';
    else if (taskState === 'complete') state = hasSavedMinutes ? '已完成' : '纪要待保存';
    return {
      kind: recording || proven ? 'meeting' as const : 'unlinked' as const,
      key: proven
        ? JSON.stringify([proven.ownerId, sourceNote!.scope, sourceNote!.teamId, 'original', proven.canonicalTaskId])
        : recording ? `recording:${recording.id}` : `note:${note.id}`,
      title: meetingRecordingTitle(date),
      date,
      dateKind: date ? 'recording' as const : 'unknown' as const,
      state, recording, note, notes: content, recordings: originals,
    };
  }).sort((a, b) => timestamp(b.date) - timestamp(a.date) || a.key.localeCompare(b.key));
}
