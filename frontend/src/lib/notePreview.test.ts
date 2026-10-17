import { describe, expect, it } from 'vitest'
import { notePreview } from './notePreview'

describe('notePreview', () => {
  it('keeps words and time labels without exposing Markdown and artifact paths', () => {
    expect(notePreview('# 会议\n## 讨论 [01:38](/api/task/private/media/video.webm?t=98)\n![截图](/api/task/private/frame.jpg)\n**保留原声** [[Screenshot:01:38]]')).toBe('会议 讨论 01:38 保留原声')
  })
  it('keeps linked labels and multilingual text', () => {
    expect(notePreview('> [飞书文档](https://example.com/doc)\n- 确认 **UI**\n1. 保存录音')).toBe('飞书文档 确认 UI 保存录音')
  })
})
