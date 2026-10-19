// Read-only renderer acceptance with synthetic notes, no runtime/private media access.
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';
const base = process.argv[2] || 'http://127.0.0.1:3219';
assert.equal(new URL(base).hostname, '127.0.0.1');
const out = mkdtempSync(path.join(tmpdir(), 'vinote-meeting-status-'));
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--no-proxy-server'] });
const context = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: 'zh-CN' });
const page = await context.newPage();
const writes = [], reads = [], errors = [];
page.on('pageerror', error => errors.push(error.message));
const rows = [['fixture-a', '合成录屏 A'], ['fixture-b', '合成录屏 B'], ['fixture-ready', '合成已完成会议'], ['fixture-unknown', '合成状态待核验']].map(([id, title]) => ({ id, title, content: id === 'fixture-ready' ? '# 已保存的合成纪要' : '原始媒体已保存，正在进行会后处理。', task_id: id + '-task', source_type: 'meeting_video', status: 'done', scope: 'personal', created_at: '2026-10-19T00:00:00Z', updated_at: '2026-10-19T00:00:00Z' }));
await page.route('**/*', async route => {
  const req = route.request(), url = new URL(req.url());
  if (url.origin !== new URL(base).origin) return route.abort();
  if (!url.pathname.startsWith('/api/')) return route.continue();
  if (req.method() !== 'GET') { writes.push(url.pathname); return route.abort(); }
  reads.push(url.pathname);
  const json = body => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  if (url.pathname === '/api/auth/session') return json({ authenticated: true, user: { id: 'fixture-owner', email: 'fixture@example.invalid' } });
  if (url.pathname === '/api/preferences') return json({ language: 'zh-CN' });
  if (url.pathname === '/api/vilab/config') return json({ configured: true, mode: 'cloud', llm_model: 'selected-model', server_url: 'https://fixture.invalid' });
  if (url.pathname === '/api/notes') return json(rows);
  if (url.pathname.startsWith('/api/task/')) {
    const task_id = url.pathname.split('/').at(-1);
    if (task_id === 'fixture-unknown-task') return route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"unavailable"}' });
    return json(task_id === 'fixture-ready-task' ? { task_id, status: 'success', result: { title: '合成已完成会议', markdown: '# 已保存的合成纪要' } } : { task_id, status: 'failed', failed_stage: 'transcribing', retryable: false });
  }
  if (url.pathname === '/api/feishu/status') return json({ configured: false, connected: false, auto_publish: false, groups: [] });
  if (url.pathname.endsWith('/capabilities')) return json({ diarization: { available: true } });
  if (url.pathname.includes('/files') || url.pathname.includes('/teams') || url.pathname.includes('profiles') || url.pathname.includes('/models')) return json([]);
  return json({});
});
try {
  await page.goto(base + '/meetings', { waitUntil: 'networkidle' });
  for (const title of ['合成录屏 A', '合成录屏 B']) await page.getByRole('button', { name: title + ' · 需处理', exact: true }).waitFor();
  await page.getByRole('button', { name: '合成已完成会议 · 已完成', exact: true }).waitFor();
  await page.getByRole('button', { name: '合成状态待核验 · 状态未核验', exact: true }).waitFor();
  assert.equal(await page.getByText('· 纪要已完成', { exact: true }).count(), 1);
  await page.screenshot({ path: path.join(out, 'meetings-status-wide.png'), fullPage: true });
  await page.getByRole('tab', { name: '需处理', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: '合成已完成会议 · 已完成', exact: true }).count(), 0);
  await page.getByRole('button', { name: '合成录屏 B · 需处理', exact: true }).waitFor();
  await page.setViewportSize({ width: 480, height: 900 });
  await page.screenshot({ path: path.join(out, 'meetings-status-narrow.png'), fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  assert.equal(writes.length, 0); assert.deepEqual(errors, []);
  const evidence = { result: 'passed', synthetic: true, screenshots: ['meetings-status-wide.png', 'meetings-status-narrow.png'], reads, writes, modelCalls: 0, notifications: 0 };
  writeFileSync(path.join(out, 'evidence.json'), JSON.stringify(evidence, null, 2));
  process.stdout.write(JSON.stringify({ out, result: 'passed', writes: writes.length }));
} finally { await browser.close(); }
