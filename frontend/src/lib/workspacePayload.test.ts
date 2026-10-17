import { beforeEach, expect, it, vi } from 'vitest';
const request = vi.hoisted(() => vi.fn());
vi.mock('./api', () => ({ apiJson: request }));
import { putWorkspaceNote, type WorkspaceVersion } from './workspace';

beforeEach(() => request.mockReset());

it('writes a fetched historical version without sending server-owned evidence metadata', async () => {
  const historical = {
    id: '__vinote:current:1', title: 'Saved title', content: 'Saved body',
    created_at: '2026-10-12T01:00:00Z', kind: 'imported',
    evidence_revision: 1, model: null, parent_id: null,
  };
  request.mockResolvedValue({ revision: 2 });
  await putWorkspaceNote('note-a', {
    base_revision: 1, operation_id: 'save-two', title: 'Updated title', content: 'Updated body',
    source_type: 'text', source_device: 'desktop', versions: [historical as unknown as WorkspaceVersion],
  });
  const payload = JSON.parse(request.mock.calls[0][1].body);
  expect(payload.versions[0]).not.toHaveProperty('evidence_revision');
  expect(payload.versions[0].parent_id).toBe('');
  expect(payload.versions[0].model).toBe('');
  expect(payload.versions[0].id).toBe('__vinote:current:1');
  expect(historical.evidence_revision).toBe(1);
  expect(historical.parent_id).toBeNull();
  expect(payload.operation_id).toBe('save-two');
  expect(payload.base_revision).toBe(1);
});
