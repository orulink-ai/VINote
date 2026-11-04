import type { CenterTask } from '@/hooks/useTaskCenter';

// Display labels never replace original filenames, identities or stored receipts.
export function taskDisplayTitle(source: string | undefined, meeting: boolean, generated?: string) {
  if (generated?.trim()) return generated.trim();
  const value = source?.trim() || '';
  if (/^(?:\d{10,}[-_][\w-]+|[a-f\d-]{24,})\.(m4a|mp3|wav|aac|ogg|flac|mp4|mov|webm)$/i.test(value)) {
    return /\.(mp4|mov|webm)$/i.test(value) ? '导入视频' : '导入录音';
  }
  return value || (meeting ? '会议导入任务' : '资料整理任务');
}

export function taskDisplayMessage(task: CenterTask, meeting: boolean) {
  if (task.complete) return task.noteId ? `${meeting ? '纪要' : '笔记'}已保存，可直接打开。` : '内容已生成，等待保存。';
  if (task.failed) {
    if (task.message?.includes('无法读取录音时长')) return '无法读取录音时长，请检查原文件后重试。';
    return task.message && /[\u3400-\u9fff]/.test(task.message) ? task.message : '处理未完成，原资料已保留。';
  }
  return task.status ? '正在后台处理，可以继续其他工作。' : '正在确认提交状态，请勿重复提交。';
}
