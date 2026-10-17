import { expect, it } from 'vitest';
import { feishuFormattingMessage } from './feishuFormatting';
const native = { protocol: 'feishu-markdown-selective-v2', status: 'written', native_write_confirmed: true, native_required: ['table', 'code', 'inline'] };
it.each([undefined, { protocol: 'legacy-unknown' }, { ...native, protocol: 'unexpected' }])('does not infer format confirmation for old/unknown receipts', receipt => {
  expect(feishuFormattingMessage(receipt, 'completed')).toBe('正文格式尚未核验。');
});
it('reports all native classes only for explicit written and completed evidence', () => {
  expect(feishuFormattingMessage(native, 'completed')).toBe('原生表格、代码块、行内样式已确认写入。');
});
it.each([
  ['failed', native], ['processing', native], ['completed', { ...native, status: 'pending' }],
  ['completed', { ...native, native_write_confirmed: false }],
])('does not promote inconsistent or pending format evidence to success', (status, receipt) => {
  expect(feishuFormattingMessage(receipt, status)).toContain('尚未确认');
});
it('uses precise unsupported image copy and never claims raw references were published', () => {
  expect(feishuFormattingMessage({ ...native, status: 'unsupported', image_source_preserved: true }, 'failed')).toBe('正文含图片，当前不支持图片发布。');
  expect(feishuFormattingMessage({ ...native, status: 'unsupported' }, 'failed')).toContain('尚不支持');
});
it('keeps partial and basic format evidence distinct from native completion', () => {
  expect(feishuFormattingMessage({ ...native, status: 'partial' }, 'completed')).toContain('未完整确认');
  expect(feishuFormattingMessage({ protocol: 'legacy-safe-v1', status: 'basic' }, 'failed')).toBe('基础正文格式。');
});
it('ignores unknown or duplicate labels instead of rendering arbitrary service values', () => {
  expect(feishuFormattingMessage({ ...native, native_required: ['table', 'table', '__proto__', 'secret'] }, 'completed')).toBe('原生表格已确认写入。');
});
