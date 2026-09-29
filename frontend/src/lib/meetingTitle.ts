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
