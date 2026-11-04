import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ owner: 'alice', listeners: new Set<(next: { user: { id: string } }, previous: { user: { id: string } }) => void>(), api: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiJson: state.api }));
vi.mock('@/stores/authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: state.owner } }), subscribe: (listener: (next: { user: { id: string } }, previous: { user: { id: string } }) => void) => { state.listeners.add(listener); return () => state.listeners.delete(listener); } } }));
import { useMeetingDisplay } from './useMeetingDisplay';
afterEach(() => { cleanup(); state.owner = 'alice'; state.listeners.clear(); });
it('rejects display metadata from an old request after A to B to A', async () => {
  let finish!: (value: unknown) => void;
  state.api.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const hook = renderHook(() => useMeetingDisplay('alice'));
  await act(async () => {
    for (const owner of ['bob', 'alice']) {
      const previous = state.owner; state.owner = owner;
      state.listeners.forEach(listener => listener({ user: { id: owner } }, { user: { id: previous } }));
    }
    finish({ items: [{ source_key: 'task:old', title: 'old response', meeting_date: '2026-11-04' }] });
  });
  expect(hook.result.current).toEqual({});
});
