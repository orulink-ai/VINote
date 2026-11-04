import { useEffect, useState } from 'react';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
export type MeetingDisplay = { source_key: string; title: string; meeting_date: string | null };
export const MEETING_DISPLAY_CHANGED = 'vinote-meeting-display-changed';
export function useMeetingDisplay(owner?: string) {
  const [values, setValues] = useState<Record<string, MeetingDisplay>>({});
  useEffect(() => {
    let active = true, revision = 0;
    const unsubscribe = useAuthStore.subscribe?.((next, previous) => {
      if (next.user?.id !== previous.user?.id) { revision++; setValues({}); }
    });
    setValues({});
    const read = () => {
      const current = ++revision;
      if (!owner) return;
      void apiJson<{ items: MeetingDisplay[] }>('/api/meeting-source-links/display').then(data => {
        if (active && current === revision && useAuthStore.getState().user?.id === owner && Array.isArray(data.items))
          setValues(Object.fromEntries(data.items.map(item => [item.source_key, item])));
      }).catch(() => undefined); // Original capture labels remain usable when display metadata cannot be read.
    };
    read(); window.addEventListener(MEETING_DISPLAY_CHANGED, read);
    return () => { active = false; unsubscribe?.(); window.removeEventListener(MEETING_DISPLAY_CHANGED, read); };
  }, [owner]);
  return values;
}
