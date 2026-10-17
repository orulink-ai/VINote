/** Token verification failure is not proof of missing user permissions. */
export const feishuVerificationMessage = '暂时无法核验飞书连接，请稍后重试。原内容与选择保留。'
export function feishuVerificationUnavailable(value?: { configured?: boolean; connection_state?: string; grant_state?: string } | null): boolean {
  return value?.configured !== false && (value?.connection_state === 'service_unavailable' || value?.grant_state === 'unavailable')
}
