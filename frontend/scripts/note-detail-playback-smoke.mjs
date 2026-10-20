// Real browser decoding and layout with synthetic media and intercepted GET-only APIs.
// Does not contact a deployed backend, invoke a model, publish, or send notifications.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { chromium } from 'playwright';

const base = process.argv[2] || 'http://127.0.0.1:3219';
assert.equal(new URL(base).hostname, '127.0.0.1', 'Use an isolated loopback Vite instance');
const out = mkdtempSync(path.join(tmpdir(), 'vinote-playback-ui-'));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const fixtures = [];
for (const [id, size, seconds] of [['fixture-landscape', '320x180', 6], ['fixture-portrait', '180x320', 7]]) {
  const original = path.join(out, id + '-original.webm');
  const preview = path.join(out, id + '-playback.webm');
  const run = args => {
    const result = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args], { encoding: 'utf8', windowsHide: true });
    assert.equal(result.status, 0, result.stderr || result.error?.message);
  };
  run(['-f', 'lavfi', '-i', `testsrc2=size=${size}:rate=10`, '-t', String(seconds), '-c:v', 'libvpx', '-b:v', '120k', '-f', 'webm', '-live', '1', original]);
  run(['-i', original, '-c', 'copy', preview]);
  fixtures.push({ id, original: readFileSync(original), preview: readFileSync(preview), seconds });
}
const methods = [];
const forbidden = [];
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true, args: ['--no-proxy-server'] });
const context = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: 'en-US', acceptDownloads: true });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
let mode = 'ready';
const mediaRequests = [];
await page.route('**/*', async route => {
  const request = route.request();
  const url = new URL(request.url());
  if (url.origin !== new URL(base).origin) return route.abort();
  if (!url.pathname.startsWith('/api/')) return route.continue();
  methods.push(request.method());
  if (request.method() !== 'GET') { forbidden.push(url.pathname); return route.abort(); }
  const json = body => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  if (url.pathname === '/api/auth/session') return json({ authenticated: true, user: { id: 'synthetic-owner', email: 'fixture@example.invalid' } });
  if (url.pathname === '/api/preferences') return json({ language: 'en' });
  if (url.pathname === '/api/vilab/config') return json({ configured: true, mode: 'cloud', llm_model: 'codex/gpt-6-luna' });
  if (url.pathname === '/api/feishu/status') return json({ configured: false, connected: false, expired: false, notify_self: true, groups: [], auto_publish: false, destination: 'personal' });
  if (url.pathname.includes('/feishu/deliveries')) return json(null);
  for (const fixture of fixtures) {
    const prefix = `/api/notes/${fixture.id}`;
    if (url.pathname === prefix) return json({ id: fixture.id, title: 'Playback review ' + 'unbroken-title-token'.repeat(26), content: '# Synthetic playback review\n\n## Checkpoint\n\n[00:02](' + prefix + '/media?t=2)\n\n' + 'long-content-token'.repeat(140), source_type: 'meeting_video', media_kind: 'video', task_id: fixture.id + '-task', status: 'done', scope: 'personal', created_at: '2026-10-19T00:00:00Z', updated_at: '2026-10-19T00:00:00Z' });
    if (url.pathname === prefix + '/recording') return json({ available: true, deleted: false, can_delete: false, filename: 'synthetic.webm', size_bytes: fixture.original.length });
    if (url.pathname === prefix + '/transcript') return json({ full_text: '', segments: [], aliases: {}, metadata: {} });
    if (url.pathname === prefix + '/waveform') return json({ peaks: [0, 0], duration_seconds: fixture.seconds });
    if (url.pathname === prefix + '/share') return json({ share_enabled: false });
    if (url.pathname === prefix + '/versions') return json([]);
    if (url.pathname === prefix + '/media') {
      const playback = url.searchParams.get('playback') === 'true';
      mediaRequests.push({ fixture: fixture.id, playback, range: request.headers().range || null });
      if (playback && mode === 'warming') return route.fulfill({ status: 503, headers: { 'Retry-After': '2' }, body: '' });
      const bytes = playback ? fixture.preview : fixture.original;
      const range = request.headers().range;
      if (range) {
        const match = /^bytes=(\d+)-(\d*)$/.exec(range);
        assert.ok(match, 'Expected one byte range');
        const start = Number(match[1]);
        const end = Math.min(match[2] ? Number(match[2]) : bytes.length - 1, bytes.length - 1);
        return route.fulfill({ status: 206, headers: { 'Content-Type': 'video/webm', 'Accept-Ranges': 'bytes', 'Content-Range': `bytes ${start}-${end}/${bytes.length}` }, body: bytes.subarray(start, end + 1) });
      }
      return route.fulfill({ headers: { 'Content-Type': 'video/webm', 'Accept-Ranges': 'bytes' }, body: bytes });
    }
  }
  if (url.pathname === '/api/notes' || url.pathname.includes('profiles') || url.pathname.includes('/teams') || url.pathname.includes('/models') || url.pathname.includes('/files')) return json([]);
  return json({});
});

const results = [];
try {
  for (const fixture of fixtures) {
    await page.goto(`${base}/note/${fixture.id}`, { waitUntil: 'networkidle' });
    const video = page.getByTestId('source-video');
    await video.waitFor();
    await page.waitForFunction(() => { const v = document.querySelector('video'); return v && Number.isFinite(v.duration) && v.readyState >= 2; });
    const duration = await video.evaluate(v => v.duration);
    assert.ok(Math.abs(duration - fixture.seconds) < 0.2);
    for (const seconds of [0.2, duration / 2, duration - 0.35]) {
      await video.evaluate((v, seconds) => { v.pause(); v.currentTime = seconds; }, seconds);
      await page.waitForFunction(seconds => { const v = document.querySelector('video'); return v && Math.abs(v.currentTime - seconds) < 0.2 && v.readyState >= 2 && !v.seeking; }, seconds);
    }
    await video.evaluate(v => { v.muted = true; return v.play(); });
    await page.waitForFunction(() => document.querySelector('video')?.ended === true);
    await video.evaluate(v => { v.pause(); v.currentTime = 2; v.playbackRate = 1.25; v.dataset.fixtureIdentity = 'retained-player'; });
    await page.getByRole('button', { name: 'Expand video', exact: true }).click();
    assert.equal(await video.getAttribute('data-fixture-identity'), 'retained-player');
    await page.getByRole('button', { name: 'Back to notes', exact: true }).click();
    mode = 'warming';
    await video.evaluate(v => v.dispatchEvent(new Event('error')));
    await page.getByRole('button', { name: 'Reload video', exact: true }).waitFor();
    assert.match(await page.getByRole('alert').innerText(), /Preparing the playback copy/);
    mode = 'ready';
    await page.getByRole('button', { name: 'Reload video', exact: true }).click();
    await page.waitForFunction(() => { const v = document.querySelector('video'); return v && v.readyState >= 2 && Math.abs(v.currentTime - 2) < 0.2; });
    assert.equal(await video.getAttribute('data-fixture-identity'), 'retained-player');
    assert.equal(await video.evaluate(v => v.playbackRate), 1.25);
    const layout = [];
    for (const [width, height] of [[1360, 900], [900, 700], [480, 800]]) {
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(150);
      const geometry = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth, heading: document.querySelector('.detail-page h1')?.getBoundingClientRect().toJSON(), actions: [...document.querySelectorAll('.detail-page > header [role="group"] button')].map(b => b.getBoundingClientRect().toJSON()) }));
      assert.ok(geometry.scroll <= geometry.width + 1, JSON.stringify(geometry));
      assert.ok(geometry.heading.right <= width + 1, 'Long title must wrap inside the viewport');
      for (const action of geometry.actions) assert.ok(action.right <= width + 1 && action.left >= 0, 'Toolbar actions must stay reachable');
      const player = await video.boundingBox();
      assert.ok(player && player.height >= 70 && player.y < height, 'The video must remain visible below the title and toolbar');
      layout.push({ width, horizontalOverflow: geometry.scroll - geometry.width });
    }
    await page.screenshot({ path: path.join(out, fixture.id + '.png') });
    await page.getByRole('button', { name: 'Read full title', exact: true }).click();
    await page.getByRole('dialog', { name: 'Full title' }).waitFor();
    await page.keyboard.press('Escape');
    await page.getByText('Original video file', { exact: true }).click();
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export original video', exact: true }).click();
    const downloaded = await downloadEvent;
    const target = path.join(out, fixture.id + '-export.webm');
    await downloaded.saveAs(target);
    assert.equal(hash(readFileSync(target)), hash(fixture.original));
    results.push({ fixture: fixture.id, seconds: duration, beginningMiddleEndAndEnded: true, samePlayerAndPositionOnReload: true, originalExportSha256: hash(fixture.original), previewSha256: hash(fixture.preview), layout });
    await page.setViewportSize({ width: 1360, height: 900 });
  }
  assert.deepEqual(forbidden, []);
  assert.deepEqual(errors, []);
  const evidence = { scope: 'Frontend browser E2E only; two generated synthetic videos, mocked GET APIs, real Chromium decoding. Does not establish the private two-recording backend/provider acceptance.', modelCalls: 0, notifications: 0, nonGetCalls: forbidden.length, results, mediaRequests };
  writeFileSync(path.join(out, 'evidence.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify({ passed: true, evidence: path.join(out, 'evidence.json'), results }, null, 2));
} finally {
  await browser.close();
}
