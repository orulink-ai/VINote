import { beforeEach, expect, it } from 'vitest';
import { desktopUpdateBlockReason } from './desktopUpdateSafety';
import { useMeetingRecorderStore } from '@/stores/meetingRecorderStore';
import { useNoteGenerationStore } from '@/stores/noteGenerationStore';
import { useAuthStore } from '@/stores/authStore';
import { trackGenerationNotification } from './taskNotifications';
beforeEach(() => { localStorage.clear(); useMeetingRecorderStore.getState().resetSession(); useNoteGenerationStore.getState().reset(); useAuthStore.setState({ user: { id: 'owner' } as never }); });
it('blocks recording, pending generation and tracked tasks', () => {
  useMeetingRecorderStore.setState({ phase: 'recording' });
  expect(desktopUpdateBlockReason()).toContain('结束录制');
  useMeetingRecorderStore.getState().resetSession(); useNoteGenerationStore.setState({ status: 'processing' });
  expect(desktopUpdateBlockReason()).toContain('内容正在处理中');
  useNoteGenerationStore.getState().reset(); trackGenerationNotification('owner', { taskId: 'task', meeting: true });
  expect(desktopUpdateBlockReason()).toContain('尚未完成的任务');
});
it('honors dirty editor unload protection without navigating', () => {
  const guard = (event: Event) => event.preventDefault();
  window.addEventListener('beforeunload', guard);
  expect(desktopUpdateBlockReason()).toContain('未保存的编辑');
  window.removeEventListener('beforeunload', guard);
  expect(desktopUpdateBlockReason()).toBe('');
});
