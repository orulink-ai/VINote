/** Disk-backed recording avoids accumulating a meeting video in JS memory. */
export async function createRecordingFile() {
  if (!navigator.storage?.getDirectory) throw new Error('当前环境不支持录屏文件存储。')
  const root = await navigator.storage.getDirectory()
  const name = `meeting-${crypto.randomUUID()}.webm`
  const handle = await root.getFileHandle(name, { create: true })
  const writable = await handle.createWritable()
  let pending = Promise.resolve()
  let failure: unknown
  let closed = false
  return {
    append(blob: Blob) {
      pending = pending.then(() => writable.write(blob)).catch(error => { failure = error })
    },
    async finish(type: string): Promise<Blob> {
      await pending
      await writable.close()
      closed = true
      if (failure) throw failure
      const file = await handle.getFile()
      return file.slice(0, file.size, type)
    },
    async remove() {
      await pending
      if (!closed) { await writable.abort().catch(() => undefined); closed = true }
      await root.removeEntry(name).catch(() => undefined)
    },
  }
}
