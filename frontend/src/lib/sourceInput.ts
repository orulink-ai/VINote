export function sourceVideoUrl(value: string) {
  const match = value.trim().match(/https?:\/\/[^\s<>"，。]+/i)
  if (!match) throw new Error('请粘贴完整的 http 或 https 网页或视频链接')
  const url = new URL(match[0])
  if (url.username || url.password) throw new Error('链接不能包含账号密码')
  return url.href
}

export function isBilibiliSourceUrl(value: string) {
  try {
    const host = new URL(sourceVideoUrl(value)).hostname.toLowerCase();
    return ['bilibili.com', 'www.bilibili.com', 'm.bilibili.com', 'b23.tv'].includes(host);
  } catch { return false; }
}
