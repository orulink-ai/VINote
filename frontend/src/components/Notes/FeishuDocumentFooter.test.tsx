import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { FeishuDocumentFooter } from './FeishuDocumentFooter';
import { deliveryStatus } from '@/lib/feishu';
vi.mock('@/lib/feishu', () => ({ deliveryStatus: vi.fn(), openExternal: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it.each([
  [{ protocol: 'feishu-markdown-selective-v2', status: 'written', native_write_confirmed: true, native_required: ['table'] }, 'completed', '原生表格已确认写入。'],
  [{ protocol: 'feishu-markdown-selective-v2', status: 'pending', native_required: ['table'] }, 'failed', '原生表格写入结果尚未确认。'],
  [undefined, 'completed', '正文格式尚未核验。'],
] as const)('renders the original GET receipt formatting without dispatching writes', async (formatting, status, message) => {
  vi.mocked(deliveryStatus).mockResolvedValue({ id: 'original', status, document_url: 'https://company.feishu.cn/docx/original', error: '', recipients: {}, formatting: formatting ? { ...formatting, native_required: [...formatting.native_required] } : undefined });
  render(<MemoryRouter><FeishuDocumentFooter noteId="saved-note" /></MemoryRouter>);
  expect(await screen.findByRole('status')).toHaveTextContent(message);
  expect(deliveryStatus).toHaveBeenCalledExactlyOnceWith('saved-note');
});
