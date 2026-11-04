import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { FeishuDelivery } from './FeishuDelivery';
import { readPublishDraft } from '@/lib/feishuPublishReceipt';

vi.mock('@/stores/authStore', () => ({ useAuthStore: Object.assign(
  (selector: (state: { user: { id: string } }) => unknown) => selector({ user: { id: 'isolated-owner' } }),
  { getState: () => ({ user: { id: 'isolated-owner' } }), subscribe: () => () => {} },
) }));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; });

it('desktop panel restores a committed rejection and freezes an unknown response without external requests', async () => {
  localStorage.clear();
  localStorage.setItem('vinote:connector-plugins:v1:isolated-owner', JSON.stringify({ version: 1, feishu: { installed: true, enabled: true } }));
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
  const posts: string[] = [];
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/api/feishu/status')) return json({ publish_receipt_protocol: 1, configured: true, connected: true, expired: false, name: '隔离测试', notify_self: false, groups: [], auto_publish: false, destination: 'personal', destination_config: { kind: 'personal' } });
    if (url.endsWith('/api/feishu/groups')) return json([]);
    if (url.includes('/api/feishu/automatic-deliveries/local/')) return json({ detail: 'not found' }, 404);
    if (url.endsWith('/api/feishu/destinations/check')) return json({ kind: 'personal', can_create: true, can_attempt_create: true, path: ['个人云文档'], path_complete: true });
    if (url.endsWith('/api/feishu/deliveries/publish%3Aisolated-note')) return json(null);
    if (url.endsWith('/api/feishu/deliveries') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body)); posts.push(body.operation_id);
      expect(new Headers(init.headers).get('X-VINote-Client')).toBe('desktop');
      if (posts.length === 1) return json({ detail: { code: 'PUBLISH_DEFINITELY_REJECTED', protocol: 1, operation_id: body.operation_id, message: '隔离测试：来源尚不能核验' } }, 409);
      throw new Error('隔离测试：网络中断');
    }
    throw new Error('Unexpected isolated request: ' + url);
  }));
  render(<MemoryRouter><FeishuDelivery noteId="isolated-note" title="测试标题" content="测试正文" /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: '发布到飞书' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '创建文档' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '创建文档' }));
  await screen.findByText('隔离测试：来源尚不能核验');
  const restored = readPublishDraft('isolated-owner', 'isolated-note');
  expect(restored?.state).toBe('draft');
  expect(restored?.operationId).not.toBe(posts[0]);
  fireEvent.click(screen.getByRole('button', { name: '创建文档' }));
  await screen.findByText('隔离测试：网络中断');
  expect(posts).toHaveLength(2);
  expect(posts[1]).toBe(restored?.operationId);
  expect(readPublishDraft('isolated-owner', 'isolated-note')?.state).toBe('unknown');
  expect(screen.getByRole('button', { name: '创建文档' })).toBeDisabled();
});
