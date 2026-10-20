import { expect, it, vi } from 'vitest'
import { buildSummaryHtml } from './summaryPresentation'

it('renders facts and tables as safe standalone HTML without active markup or external images', async () => {
  const fetchImage = vi.fn()
  const html = await buildSummaryHtml('# Topic\n\n<script>alert(1)</script>\n\n[attack](javascript:alert)\n\n![remote](https://evil.invalid/pixel)\n\n| A | B |\n|---|---|\n| one | two |', '"<Title>', undefined, fetchImage)
  const doc = new DOMParser().parseFromString(html, 'text/html')
  expect(doc.querySelector('h1')?.textContent).toBe('Topic')
  expect(doc.querySelector('table')).not.toBeNull()
  expect(doc.querySelector('script, iframe, object, embed, form')).toBeNull()
  expect(doc.querySelector('img')).toBeNull()
  expect(doc.querySelector('a[href^="javascript"]')).toBeNull()
  expect(doc.title).toBe('"<Title>')
  expect(html).toContain('Content-Security-Policy')
  expect(fetchImage).not.toHaveBeenCalled()
})

it('embeds only this exact task authentic screenshot assets and fails rather than losing them', async () => {
  const task = '11111111-1111-4111-8111-111111111111'
  const src = `/api/task/${task}/artifacts/screenshots/summary-source-0.jpg`
  const fetchImage = vi.fn().mockResolvedValue('data:image/jpeg;base64,YWJj')
  const html = await buildSummaryHtml(`![source](${src})\n\n![other](/api/task/22222222-2222-4222-8222-222222222222/artifacts/screenshots/a.jpg)`, 'Topic', task, fetchImage)
  expect(html).toContain('data:image/jpeg;base64,YWJj')
  expect(fetchImage).toHaveBeenCalledTimes(1)
  await expect(buildSummaryHtml(`![source](${src})`, 'Topic', task, vi.fn().mockRejectedValue(new Error('missing')))).rejects.toThrow('missing')
})

it('preserves GFM marker states as readable static text, including nested and uppercase checked items', async () => {
  const markdown = '- [x] Check the same device\n- [ ] Check the same device\n  - [X] Verify the cable\n- Ordinary note'
  const html = await buildSummaryHtml(markdown, 'Task states')
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const items = [...doc.querySelectorAll('li')]
  expect(items).toHaveLength(4)
  // Marker labels remain Chinese for English text and do not assert factual completion.
  expect(items[0].textContent).toBe('（已勾选） Check the same device')
  expect(items[1].firstElementChild?.textContent).toBe('（未勾选）')
  expect(items[2].textContent).toBe('（已勾选） Verify the cable')
  expect(items[3].textContent).toBe('Ordinary note')
  const states = [...doc.querySelectorAll('li > span')]
  expect(states.map(state => state.textContent)).toEqual(['（已勾选）', '（未勾选）', '（已勾选）'])
  expect(states.every(state => !state.closest('[aria-hidden="true"], [hidden], [inert]'))).toBe(true)
  expect(doc.querySelector('input, button, form, [role="checkbox"], [tabindex]')).toBeNull()
})

it('keeps non-GFM indeterminate markers, escaped markers and code literal rather than inferring checkbox state', async () => {
  // GFM defines checked/unchecked only; [-] is not an indeterminate checkbox.
  const markdown = '- [-] State not established\n- [?] Unknown\n- \\[x] Escaped\n\n`- [x] Inline example`\n\n```md\n- [ ] Code example\n```'
  const html = await buildSummaryHtml(markdown, 'Literal states')
  const doc = new DOMParser().parseFromString(html, 'text/html')
  expect([...doc.querySelectorAll('li')].map(item => item.textContent)).toEqual(['[-] State not established', '[?] Unknown', '[x] Escaped'])
  expect([...doc.querySelectorAll('code')].map(code => code.textContent)).toEqual(['- [x] Inline example', '- [ ] Code example\n'])
  expect(doc.querySelector('input, li > span, [aria-checked]')).toBeNull()
  expect(doc.querySelector('main')?.textContent).not.toMatch(/（已勾选）|（未勾选）/)
})

it('does not admit malicious raw HTML controls or scripts when preserving real GFM task states', async () => {
  const fetchImage = vi.fn()
  const markdown = '<input type="checkbox" checked indeterminate tabindex="0" onchange="alert(1)">\n\n<script>alert(1)</script>\n\n- [x] Approved <img src="https://evil.invalid/pixel" onerror="alert(1)">\n- [ ] Pending <input type="checkbox" checked aria-label="Spoofed state">\n\n[unsafe](javascript:alert(1))'
  const html = await buildSummaryHtml(markdown, 'Safe states', undefined, fetchImage)
  const doc = new DOMParser().parseFromString(html, 'text/html')
  expect([...doc.querySelectorAll('li')].map(item => item.textContent?.trim())).toEqual(['（已勾选） Approved', '（未勾选） Pending'])
  expect(doc.querySelector('input, button, script, img, iframe, object, embed, form, [tabindex], [aria-checked], [onchange], [onerror]')).toBeNull()
  expect(doc.querySelector('a[href^="javascript:"]')).toBeNull()
  expect(doc.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content')).toBe("default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'")
  expect(fetchImage).not.toHaveBeenCalled()
})

it('compacts only the embedded reader stylesheet without changing body, source images or CSP', async () => {
  const task = '11111111-1111-4111-8111-111111111111'
  const source = `/api/task/${task}/artifacts/screenshots/summary-source-0.jpg`
  const markdown = `# 很长的真实纪要标题：硬件方案、采购条件与会议工具\n\n## 条件与安排\n\n${'保留完整正文、时间和条件。'.repeat(80)}\n\n- [x] 已标记\n- [ ] 未标记\n\n![实际原图](${source})\n\n最后一段不能截断。`
  const fetchImage = vi.fn().mockResolvedValue('data:image/jpeg;base64,YWJj')
  const standalone = await buildSummaryHtml(markdown, '标题', task, fetchImage)
  const preview = await buildSummaryHtml(markdown, '标题', task, fetchImage, undefined, 'preview')
  const exported = await buildSummaryHtml(markdown, '标题', task, fetchImage, undefined, 'export')
  const parse = (html: string) => new DOMParser().parseFromString(html, 'text/html')
  const a = parse(standalone), b = parse(preview)
  expect(exported).toBe(standalone)
  expect(b.body.innerHTML).toBe(a.body.innerHTML)
  expect(b.querySelector('main')?.textContent).toContain('最后一段不能截断。')
  expect(b.querySelector('img')?.getAttribute('src')).toBe('data:image/jpeg;base64,YWJj')
  expect(b.querySelector('style')?.textContent).toContain('h1{font-size:1.25rem;line-height:1.4;margin:0 0 .75rem}')
  expect(a.querySelector('style')?.textContent).not.toContain('font-size:1.25rem')
  expect(b.querySelector('meta[http-equiv="Content-Security-Policy"]')?.outerHTML).toBe(a.querySelector('meta[http-equiv="Content-Security-Policy"]')?.outerHTML)
  expect(b.querySelector('script, iframe, input, form, [hidden], [inert]')).toBeNull()
  expect(fetchImage.mock.calls.map(call => call[0])).toEqual([source, source, source])
})
