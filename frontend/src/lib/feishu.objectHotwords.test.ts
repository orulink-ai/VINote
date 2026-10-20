import { beforeEach, expect, it, vi } from 'vitest';
import { apiJson } from './api';
import { feishuObjectHotwords, refreshFeishuObjectHotwords, bindFeishuObjectAlias, deleteFeishuObjectAlias } from './feishu';
vi.mock('./api', () => ({ apiJson: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
it.each([
  undefined,
  { objects: [], aliases: [] },
  { objects: [{ id: 'one', name: '', kind: 'contact' }], aliases: [], partial: false },
  { objects: [{ id: 'one', name: '姓名', kind: 'other' }], aliases: [], partial: true },
  { objects: [], aliases: [{ id: 'alias', alias: '简称', target_id: 'one' }], partial: false },
  { objects: [], aliases: [], partial: false, updated_at: 'now' },
])('does not turn malformed directory evidence into a successful empty list: %j', async response => {
  vi.mocked(apiJson).mockResolvedValue(response); await expect(feishuObjectHotwords()).rejects.toThrow('对象目录响应未核验');
});
it('uses the agreed endpoints, preserves exact IDs and sends no fabricated target name', async () => {
  const response = { objects: [{ id: 'ou_one', name: '姓名', kind: 'contact' }], aliases: [], partial: false };
  vi.mocked(apiJson).mockResolvedValue(response);
  expect(await feishuObjectHotwords()).toEqual(response); await refreshFeishuObjectHotwords(); await bindFeishuObjectAlias('别称', 'ou_one'); await deleteFeishuObjectAlias('alias/one');
  expect(vi.mocked(apiJson).mock.calls).toEqual([
    ['/api/feishu/object-hotwords', { cache: 'no-store' }], ['/api/feishu/object-hotwords/refresh', { method: 'POST' }],
    ['/api/feishu/object-hotwords', { method: 'POST', body: JSON.stringify({ alias: '别称', target_id: 'ou_one' }) }],
    ['/api/feishu/object-hotwords/alias%2Fone', { method: 'DELETE' }],
  ]);
});
