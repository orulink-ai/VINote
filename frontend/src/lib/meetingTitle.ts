const genericHeading = /^(会议纪要|会议记录|会议总结|纪要|总结|核心结论|关键结论|核心议题|主要讨论|会议主题|会议基本信息|会议基本情况|会议概况|会议概览|会议信息|讨论要点|主题讨论|行动事项|待办事项|meeting (notes|minutes|summary)|summary|overview)$/i

export function meetingSubject(markdown: string): string {
  const headings = [...markdown.replace(/```[\s\S]*?```/g, '').matchAll(/^#{1,3}\s+(.+)$/gm)]
  for (const match of headings) {
    const text = match[1].replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/\*|`/g, '')
      .replace(/\[?\d{1,2}:\d{2}(?::\d{2})?\]?/g, '')
      .replace(/^[一二三四五六七八九十\d]+[、.．)）]\s*/, '').trim()
    if (text && !genericHeading.test(text) && !/^会议录音|^Meeting recording|^\d{4}[-/]/i.test(text)) return text.slice(0, 64)
  }
  return ''
}

export function formatMeetingTitle(startedAt: Date | string, subject = '', locale = 'zh-CN') {
  const date = new Date(startedAt)
  const zh = locale.startsWith('zh')
  const pad = (value: number) => String(value).padStart(2, '0')
  const time = Number.isNaN(date.getTime()) ? (zh ? '时间未知' : 'Time unknown')
    : `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
  return `${time}｜${subject.trim() || (zh ? '待生成纪要' : 'Notes pending')}`.slice(0, 255)
}

/** A server result may carry the canonical recording clock; preserve it verbatim, without timezone conversion. */
function resultSourceTime(title: string): string | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})[ \t]+(\d{2}):(\d{2})[ \t]*[｜|]/.exec(title.trim())
  if (!match) return undefined
  const [, year, month, day, hour, minute] = match
  const value = new Date(Date.UTC(+year, +month - 1, +day, +hour, +minute))
  if (value.getUTCFullYear() !== +year || value.getUTCMonth() !== +month - 1 || value.getUTCDate() !== +day || value.getUTCHours() !== +hour || value.getUTCMinutes() !== +minute) return undefined
  return `${year}-${month}-${day} ${hour}:${minute}`
}

/** The date is supplied by capture/import, never inferred from media duration. */
export function formatContentTitle(createdAt: Date | string, markdown: string, fallback = '', locale = 'zh-CN') {
  const subject = meetingSubject(markdown) || fallback
    .replace(/^\d{4}[-/]\d{2}[-/]\d{2}(?:\s+\d{2}:\d{2})?\s*[｜|·-]\s*/, '')
    .replace(/\.[a-z0-9]{2,5}$/i, '').trim() || (locale.startsWith('zh') ? '内容摘要' : 'Content summary');
  const sourceTime = resultSourceTime(fallback)
  return sourceTime ? `${sourceTime}｜${subject}`.slice(0, 255) : formatMeetingTitle(createdAt, subject, locale);
}
