import { invoke } from '@tauri-apps/api/core'
import { apiJson } from './api'
import { isTauriRuntime } from './desktopMicrophonePermission'

/** Resolve only an owned original, never a playback derivative or arbitrary path. */
export async function revealOriginalFile(sourceUrl: string | { taskId: string }, current = () => true, signal?: AbortSignal): Promise<'shown' | 'cancelled'> {
  if (!isTauriRuntime()) throw new Error('请在桌面端应用中打开原文件所在文件夹。')
  let endpoint: string
  if (typeof sourceUrl !== 'string') {
    if (!sourceUrl || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(sourceUrl.taskId)) throw new Error('原文件地址未通过核验。')
    endpoint = `/api/task/${sourceUrl.taskId}/original/local-path`
  } else {
    let path: string
    try { path = decodeURIComponent(sourceUrl) } catch { throw new Error('原文件地址未通过核验。') }
    if (/[\\\x00-\x20\x7f#]/.test(path) || path.includes('//') || path.split('/').some(part => part === '.' || part === '..')
      || !/^\/api\/(?:files\/[^/?]+\/content|notes\/[^/?]+\/media|task\/[^/?]+\/artifacts\/media\/[^./?][^/?]*)(?:\?download=true)?$/.test(path)) {
      throw new Error('原文件地址未通过核验。')
    }
    const sourcePath = path.replace(/\?download=true$/, '')
    const file = /^\/api\/files\/([^/]+)\/content$/.exec(sourcePath)
    const note = /^\/api\/notes\/([^/]+)\/media$/.exec(sourcePath)
    const task = /^\/api\/task\/([^/]+)\/artifacts\//.exec(sourcePath)
    endpoint = file ? `/api/files/${encodeURIComponent(file[1])}/local-path`
      : note ? `/api/notes/${encodeURIComponent(note[1])}/media/local-path`
        : task ? `/api/task/${encodeURIComponent(task[1])}/original/local-path` : ''
    if (!endpoint) throw new Error('原文件地址未通过核验。')
  }
  const valid = () => current() && !signal?.aborted
  if (!valid()) return 'cancelled'
  const receipt = await apiJson<{ local_path_protocol: number; absolute_path: string }>(endpoint, {
    cache: 'no-store', redirect: 'error', signal,
  })
  if (!valid()) return 'cancelled'
  if (receipt?.local_path_protocol !== 1 || typeof receipt.absolute_path !== 'string' || /[\x00-\x1f\x7f]/.test(receipt.absolute_path)
    || !(/^[A-Za-z]:[\\/](?![\\/])/.test(receipt.absolute_path) || /^\/(?!\/)/.test(receipt.absolute_path))
    || receipt.absolute_path.split(/[\\/]/).some(part => part === '..')) throw new Error('原文件位置未核验，请重新读取。')
  try { await invoke('reveal_original_file', { path: receipt.absolute_path }) }
  catch { throw new Error('无法定位原文件，请检查文件是否仍在原位置，以及文件夹是否可访问。') }
  return valid() ? 'shown' : 'cancelled'
}
