import { expect, it } from 'vitest';
import { taskDisplayTitle, taskDisplayMessage } from './taskDisplay';
it('uses meaningful titles without rewriting or exposing opaque media filenames as headings', () => {
  expect(taskDisplayTitle('1793586744472-zgrv9560uwb.m4a', true)).toBe('导入录音');
  expect(taskDisplayTitle('1793586744472-zgrv9560uwb.mp4', true)).toBe('导入视频');
  expect(taskDisplayTitle('项目评审.m4a', true)).toBe('项目评审.m4a');
  expect(taskDisplayTitle('1793586744472-zgrv9560uwb.m4a', true, '研发周会')).toBe('研发周会');
});
it('presents localized outcomes and keeps useful failure explanations', () => {
  const task = { label: '已完成', complete: true, terminal: true, failed: false, noteId: 'saved', message: 'Note generated successfully' };
  expect(taskDisplayMessage(task, false)).toBe('笔记已保存，可直接打开。');
  expect(taskDisplayMessage({...task,complete:false,failed:true,message:'无法读取录音时长，已保留原始媒体，请重试；未向云端提交未校验的大文件。'},true)).toBe('无法读取录音时长，请检查原文件后重试。');
});
