import { describe, expect, it } from 'vitest'
import { sourceVideoUrl } from './sourceInput'

describe('video source input', () => {
  it('accepts the original video link inside Bilibili share text', () => {
    expect(sourceVideoUrl('【示例】 https://b23.tv/example 分享给你')).toBe('https://b23.tv/example')
  })
  it('rejects plain text and credentials in URLs before submission', () => {
    expect(() => sourceVideoUrl('这不是链接')).toThrow()
    expect(() => sourceVideoUrl('https://user:password@example.com/video')).toThrow()
  })
})
