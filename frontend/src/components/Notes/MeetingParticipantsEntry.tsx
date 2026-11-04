import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { feishuStatus } from '@/lib/feishu';
import { feishuVerificationUnavailable } from '@/lib/feishuConnectionState';
import { publishScope } from '@/lib/feishuPublishReceipt';
import { MeetingParticipantsConfirmation, type MeetingParticipantsConfirmationProps } from './MeetingParticipantsConfirmation';

/** Connection availability is independent of automatic delivery consent. */
export function MeetingParticipantsEntry(props: MeetingParticipantsConfirmationProps) {
  const owner = useAuthStore(state => state.user?.id);
  const [visit, setVisit] = useState(0);
  const [connection, setConnection] = useState<{ owner: string; binding?: string; current: () => boolean } | null>(null);
  useEffect(() => useAuthStore.subscribe((next, previous) => {
    if (next.user?.id !== previous.user?.id) { setConnection(null); setVisit(value => value + 1); }
  }), []);
  useEffect(() => {
    setConnection(null);
    if (!owner) return;
    let alive = true, revision = 0;
    let scope: () => void;
    try { scope = publishScope(owner); } catch { return; }
    const live = () => { try { scope(); return alive && useAuthStore.getState().user?.id === owner; } catch { return false; } };
    const read = () => {
      const request = ++revision;
      const current = () => live() && request === revision;
      void feishuStatus().then(status => {
        if (!current()) return;
        if (status.connected === true && status.expired === false && !feishuVerificationUnavailable(status))
          setConnection({ owner, binding: status.connection_binding_hash, current: live });
        else setConnection(null);
      }).catch(() => { if (current()) setConnection(null); }); // Never block reading minutes.
    };
    read(); window.addEventListener('focus', read);
    return () => { alive = false; window.removeEventListener('focus', read); };
  }, [owner, visit, props.noteId]);
  if (!connection || connection.owner !== owner || !connection.current()) return null;
  return <div className="flex flex-wrap items-center gap-2">
    <MeetingParticipantsConfirmation {...props} connectionKey={connection.binding} />
    <p className="text-xs text-muted-foreground">匹配本会议的说话人与飞书联系人，用于人物归属和通知对象。</p>
  </div>;
}
