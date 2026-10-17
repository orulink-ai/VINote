export function downloadRecording(blob: Blob, title: string, filename?: string) {
  const extension = filename?.split('.').pop() || (blob.type.includes('mp4') ? 'mp4' : 'webm')
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${title.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 120) || '会议录制'}.${extension}`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Keep the URL alive while the browser starts its download.
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}
