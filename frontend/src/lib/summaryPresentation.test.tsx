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
