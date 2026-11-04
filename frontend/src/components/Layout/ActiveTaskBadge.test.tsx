import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { ActiveTaskBadge } from './ActiveTaskBadge';
import { observeGeneration, trackGenerationNotification } from '@/lib/taskNotifications';
beforeEach(() => localStorage.clear());
afterEach(cleanup);
it('updates immediately for new and terminal tasks without another network poll', () => {
  render(<ActiveTaskBadge owner="a" />);
  expect(screen.queryByText('1')).toBeNull();
  const first = { taskId: 'one', operationId: 'op', meeting: false };
  act(() => trackGenerationNotification('a', first));
  expect(screen.getByTitle('1 项任务尚未完成')).toHaveTextContent('1');
  act(() => trackGenerationNotification('a', first));
  expect(screen.getByText('1')).toBeVisible();
  act(() => trackGenerationNotification('a', { taskId: 'two', meeting: true }));
  expect(screen.getByText('2')).toBeVisible();
  act(() => observeGeneration('a', first, 'success'));
  expect(screen.getByText('1')).toBeVisible();
  act(() => observeGeneration('a', { taskId: 'two', meeting: true }, 'failed'));
  expect(screen.queryByText('1')).toBeNull();
});
it('isolates accounts and preserves accessible status when navigation is collapsed', () => {
  trackGenerationNotification('a', { taskId: 'one', meeting: false });
  const view = render(<ActiveTaskBadge owner="a" compact />);
  expect(screen.getByText('1 项任务尚未完成')).toHaveClass('sr-only');
  view.rerender(<ActiveTaskBadge owner="b" compact />);
  expect(screen.queryByText('1 项任务尚未完成')).toBeNull();
});
