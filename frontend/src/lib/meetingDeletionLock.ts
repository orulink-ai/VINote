/** One owner may have only one deletion transaction across desktop windows. */
export async function withMeetingDeletionLock<T>(owner: string, work: () => Promise<T>): Promise<T> {
  if (!navigator.locks || typeof navigator.locks.request !== 'function') {
    throw new Error('当前环境无法安全协调会议删除，请使用最新版桌面端。')
  }
  return navigator.locks.request(`vinote:meeting-deletion:${owner}`, { mode: 'exclusive', ifAvailable: true }, async lock => {
    if (!lock) throw new Error('正在删除会议，请等待完成后重试。')
    return work()
  })
}
