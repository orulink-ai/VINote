export function noteOrigin(client: string | undefined, zh = true): string {
  const labels = zh
    ? { mobile: 'App 生成', desktop: '桌面端生成', web: '网页端生成' }
    : { mobile: 'Created in app', desktop: 'Created on desktop', web: 'Created on web' }
  return labels[client as keyof typeof labels] || (zh ? '来源未知' : 'Unknown origin')
}
