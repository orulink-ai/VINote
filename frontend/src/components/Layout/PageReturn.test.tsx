import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { PageReturn } from './PageReturn';

afterEach(cleanup);

it('keeps the exact content and list context after a URL-only reload', () => {
  const parent = '/workspace/review-note?returnTo=%2Fnotes%3Fq%3Dpdf#正文';
  render(<MemoryRouter initialEntries={['/settings/sync?' + new URLSearchParams({ returnTo: parent })]}>
    <PageReturn to="/settings?tab=storage" label="返回存储与同步设置" />
  </MemoryRouter>);
  expect(screen.getByRole('link', { name: '返回内容详情' })).toHaveAttribute('href', parent.replace('#正文', '#' + encodeURIComponent('正文')));
});

it('rejects an external URL parent without navigating outside the application', () => {
  render(<MemoryRouter initialEntries={['/settings/sync?returnTo=https%3A%2F%2Fexample.com']}>
    <PageReturn to="/settings?tab=storage" label="返回存储与同步设置" />
  </MemoryRouter>);
  expect(screen.getByRole('link', { name: '返回存储与同步设置' })).toHaveAttribute('href', '/settings?tab=storage');
});

it('keeps existing explicit navigation state when there is no URL parent', () => {
  render(<MemoryRouter initialEntries={[{ pathname: '/settings/feishu', state: { returnTo: '/notes?q=pdf' } }]}>
    <PageReturn to="/connections" label="返回插件" />
  </MemoryRouter>);
  expect(screen.getByRole('link', { name: '返回笔记' })).toHaveAttribute('href', '/notes?q=pdf');
});

it('does not rebind a previously resolved parent or restore self references', () => {
  render(<MemoryRouter initialEntries={['/settings?tab=models&returnTo=%2Fworkspace%2Ftest']}>
    <PageReturn to="/settings?returnTo=%2Fworkspace%2Ftest" label="返回设置总览" contextual={false} />
  </MemoryRouter>);
  expect(screen.getByRole('link', { name: '返回设置总览' })).toHaveAttribute('href', '/settings?returnTo=%2Fworkspace%2Ftest');
});

it('falls back from an invalid or self URL to a valid state parent', () => {
  render(<MemoryRouter initialEntries={[{ pathname: '/settings/sync', search: '?returnTo=%2Fsettings%2Fsync', state: { returnTo: '/notes?q=review' } }]}>
    <PageReturn to="/settings?tab=storage" label="返回存储与同步设置" />
  </MemoryRouter>);
  expect(screen.getByRole('link', { name: '返回笔记' })).toHaveAttribute('href', '/notes?q=review');
});
