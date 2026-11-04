import { isMeetingBusy, useMeetingRecorderStore } from '@/stores/meetingRecorderStore';
import { useNoteGenerationStore } from '@/stores/noteGenerationStore';
import { useAuthStore } from '@/stores/authStore';
import { readTrackedGenerations } from '@/lib/taskNotifications';

/** Re-read immediately before any action that can terminate the process. */
export function desktopUpdateBlockReason(): string {
  const recorder = useMeetingRecorderStore.getState();
  if (isMeetingBusy(recorder) || recorder.generatedNote && !recorder.noteId) {
    return '请先结束录制并保存录音与生成结果，再安装更新。';
  }
  if (['uploading', 'processing'].includes(useNoteGenerationStore.getState().status)) {
    return '内容正在处理中，请等待任务完成后再安装更新。';
  }
  const owner = useAuthStore.getState().user?.id;
  if (owner && readTrackedGenerations(owner).some(task => task.active && !task.terminal)) {
    return '还有尚未完成的任务，请在任务与诊断中确认完成后再安装更新。';
  }
  // Reuse every mounted editor/recorder's existing unload guard. A synthetic
  // event does not navigate or close a window, but lets draft protection run.
  const event = new Event('beforeunload', { cancelable: true });
  if (!window.dispatchEvent(event)) return '还有未保存的编辑，请保存后再安装更新。';
  return '';
}
