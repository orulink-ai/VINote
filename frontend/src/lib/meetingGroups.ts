import type { MeetingTaskStates } from '@/hooks/useMeetingTaskStates';
import { libraryNoteIdentities, type LibraryNote as NoteRecord } from '@/hooks/useLibraryNotes';
import type { PendingMeeting } from './audioStorage';
import { serverTimestamp } from './serverTimestamp';

const timestamp = (value: string) => {
  const time = serverTimestamp(value).getTime();
  return Number.isFinite(time) ? time : 0;
};

export type MeetingRow = {
  key: string;
  title: string;
  date: string;
  state: string;
  recording?: PendingMeeting;
  note?: NoteRecord;
  notes: NoteRecord[];
  recordings: PendingMeeting[];
};

/** A projection only: every content object and retained original stays reachable. */
export function buildMeetingRows(recordings: PendingMeeting[], notes: NoteRecord[], taskStates: MeetingTaskStates = {}, ownerId?: string): MeetingRow[] {
  // Legacy records belong to the authenticated collection; explicit provenance
  // and recordings carry their own owner and must never cross that boundary.
  const recordingOwners = [...new Set(recordings.map(row => row.ownerId).filter(Boolean))];
  const collectionOwner = ownerId || (recordingOwners.length === 1 ? recordingOwners[0] : '');
  const retainedNotes = [...new Map(notes.flatMap(note => [note, ...(note.localSources || [])])
    .map(note => [JSON.stringify([note.meetingSource?.ownerId || collectionOwner, note.scope, note.teamId, note.workspaceKey, note.id]), note] as const)).values()];
  const nodes = [
    ...recordings.map(recording => {
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
    let state = recording ? recording.processingStatus === 'failed' ? '需处理'
      : recording.processingStatus === 'idle' ? '未生成' : recording.processingStatus === 'completed' ? '已完成' : '处理中' : note.status === 'failed' || note.status === 'transcribing_failed' || note.status === 'generation_failed' ? '需处理' : note.status === 'done' ? '已完成' : '状态未核验';
    const taskState = taskStates[recording?.taskId || note?.taskId || ''];
    if (taskState === 'failed') state = '需处理';
    else if (taskState === 'processing') state = '处理中';
    else if (taskState === 'checking') state = '状态核验中';
    else if (taskState === 'unverified') state = '状态未核验';
    else if (taskState === 'complete') state = note?.status === 'done' && (!recording || recording.processingStatus === 'completed' || recording.noteId === note.id) ? '已完成' : '纪要待保存';
    return {
      key: note?.meetingSource
        ? JSON.stringify([note.meetingSource.ownerId, note.scope, note.teamId, 'original', note.meetingSource.canonicalTaskId])
        : recording ? `recording:${recording.id}` : `note:${note.id}`,
      title: recording?.options.title || note.title,
      date: recording?.startedAt || note.recordingStartedAt || note.createdAt,
      state, recording, note, notes: content, recordings: originals,
    };
  }).sort((a, b) => timestamp(b.date) - timestamp(a.date));
}
