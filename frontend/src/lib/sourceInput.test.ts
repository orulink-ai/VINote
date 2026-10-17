import { describe, expect, it } from 'vitest'
import { sourceVideoUrl, isBilibiliSourceUrl } from './sourceInput'

describe('video source input', () => {
  it('recognizes Bilibili audio intake without trusting lookalike hosts or credentials', () => {
    expect(isBilibiliSourceUrl('分享 https://b23.tv/example')).toBe(true)
    expect(isBilibiliSourceUrl('https://www.bilibili.com/video/BV12iFezdEZS/')).toBe(true)
    expect(isBilibiliSourceUrl('https://www.bilibili.com.evil.example/video/BV12iFezdEZS/')).toBe(false)
    expect(isBilibiliSourceUrl('https://user:secret@www.bilibili.com/video/BV12iFezdEZS/')).toBe(false)
  })
  it('accepts the original video link inside Bilibili share text', () => {
    expect(sourceVideoUrl('【示例】 https://b23.tv/example 分享给你')).toBe('https://b23.tv/example')
  })
  it('rejects plain text and credentials in URLs before submission', () => {
    expect(() => sourceVideoUrl('这不是链接')).toThrow()
    expect(() => sourceVideoUrl('https://user:password@example.com/video')).toThrow()
  })
})
