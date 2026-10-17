import { describe, expect, it } from 'vitest'
import { formatContentTitle, formatMeetingTitle, meetingSubject } from './meetingTitle'

describe('meeting titles', () => {
  it('uses the supplied recording time, not the current generation time', () => {
    const started = new Date(2026, 8, 24, 10, 3)
    expect(formatMeetingTitle(started, '键盘麦克风方案讨论')).toBe('2026-09-24 10:03｜键盘麦克风方案讨论')
    expect(formatMeetingTitle(started)).toBe('2026-09-24 10:03｜待生成纪要')
  })
  it('extracts a subject from the final summary and removes markdown/timestamps', () => {
    expect(meetingSubject('# **键盘麦克风方案讨论**\n\n## 行动事项')).toBe('键盘麦克风方案讨论')
    expect(meetingSubject('# 会议纪要\n\n## 一、麦克风阵列方案 [03:20](#t=200)')).toBe('麦克风阵列方案')
    expect(meetingSubject('# 2026-09-24 10:03｜待生成纪要\n## 核心议题\n### 键盘音频方案')).toBe('键盘音频方案')
  })
  it('never invents a subject or time when evidence is missing', () => {
    expect(meetingSubject('# 会议纪要\n\n## 行动事项')).toBe('')
    expect(formatMeetingTitle('bad-date', '讨论')).toBe('时间未知｜讨论')
  })
  it('uses the final LLM topic for imported notes and never duplicates a date prefix', () => {
    const date = new Date(2026, 9, 12, 10, 30);
    expect(formatContentTitle(date, '# 展会物料与项目协作安排', 'source.mp4')).toBe('2026-10-12 10:30｜展会物料与项目协作安排');
    expect(formatContentTitle(date, '# 会议纪要', '2026-10-12 10:30｜项目周会')).toBe('2026-10-12 10:30｜项目周会');
  })
})
