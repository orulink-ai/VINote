import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { attachmentAccess, attachmentId, boundedContentImage } from '@/lib/workspaceAttachments'
import { resolveContentUrl } from '@/lib/videoLinks'
import { useAuthStore } from '@/stores/authStore'

export type RemoteImagePolicy = 'allow' | 'confirm'

// The local artifact API checks task ownership. Arbitrary relative paths are
// never promoted to this channel, and attachment access URLs stay above it.
function deviceArtifact(source: string) {
  return /^\/api\/task\/[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\/artifacts\/(?:screenshots|media)\/[\w-]+\.(?:png|jpe?g|webp)$/i.test(source)
}

function remoteImageUrl(source: string): URL | undefined {
  if (!/^https?:\/\//i.test(source) || /[\s\\\u0000-\u001f\u007f]/.test(source)) return
  const authority = /^https?:\/\/([^/?#]+)/i.exec(source)?.[1]
  if (!authority || /[@%]/.test(authority)) return
  try {
    const url = new URL(source)
    if (!url.hostname || url.username || url.password) return
    return url
  } catch { return }
}

function ConfirmedRemoteImage({ src, alt, owner }: { src: string; alt: string; owner: string }) {
  const url = remoteImageUrl(src)
  const description = alt || '图片未提供说明'
  const [state, setState] = useState<'idle' | 'loading' | 'loaded' | 'failed'>('idle')
  const [attempt, setAttempt] = useState(0)
  const sequence = useRef(0), active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  const current = () => !!owner && useAuthStore.getState().user?.id === owner
  return <span className="my-4 block min-h-12 rounded-xl border border-border bg-muted/20 p-4">
    <span className="flex min-h-12 flex-col items-start gap-2 text-sm">
      <span className="break-words text-muted-foreground">{description}{url ? ` · ${url.hostname}` : ' · 图片地址不可加载'}</span>
      {state === 'failed' && <span role="status" className="text-muted-foreground">图片加载失败，可单独重试。</span>}
      {url && state !== 'loaded' && <button type="button" className="inline-flex min-h-11 items-center justify-center rounded-lg border border-border bg-background px-4 font-medium transition-colors hover:bg-muted focus-visible:outline focus-visible:outline-2 disabled:cursor-wait disabled:opacity-60" disabled={!owner || state === 'loading'} aria-busy={state === 'loading'} aria-label={`${state === 'failed' ? '重试加载' : '加载'}图片：${description}（${url.hostname}）`} onClick={() => { if (active.current && current()) { sequence.current += 1; setAttempt(sequence.current); setState('loading') } }}>{state === 'loading' ? '正在加载' : state === 'failed' ? '重试图片' : '加载图片'}</button>}
    </span>
    {url && (state === 'loading' || state === 'loaded') && <img key={attempt} src={url.href} alt={description} referrerPolicy="no-referrer" crossOrigin="anonymous" className="mt-3 max-w-full rounded-lg border border-border" onLoad={() => { if (active.current && current() && sequence.current === attempt) setState('loaded') }} onError={() => { if (active.current && current() && sequence.current === attempt) setState('failed') }} />}
  </span>
}

export function ContentImage({ src = '', alt = '', remoteImagePolicy = 'confirm', imageSessionKey = '' }: { src?: string; alt?: string; remoteImagePolicy?: RemoteImagePolicy; imageSessionKey?: string }) {
  const id = attachmentId(src)
  const owner = useAuthStore(state => state.user?.id || '')
  const container = useRef<HTMLSpanElement>(null)
  const [visible, setVisible] = useState(false)
  const [url, setUrl] = useState(''), [error, setError] = useState(''), [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!id || !('IntersectionObserver' in window)) { setVisible(true); return }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { setVisible(true); observer.disconnect() }
    }, { rootMargin: '120px' })
    if (container.current) observer.observe(container.current)
    return () => observer.disconnect()
  }, [id])
  useEffect(() => {
    let active = true, objectUrl = ''
    const controller = new AbortController()
    setError(''); setUrl('')
    if (!id || !visible) return
    const load = async () => {
      try {
        const access = await attachmentAccess(id)
        if (!active || (useAuthStore.getState().user?.id || '') !== owner) return
        if (!access.authenticated) { setUrl(access.url); return }
        const response = await apiFetch(access.url, { signal: controller.signal })
        if (!response.ok) throw new Error('图片读取失败')
        const blob = await boundedContentImage(response)
        if (active && (useAuthStore.getState().user?.id || '') === owner) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) }
      } catch { if (active) setError('图片暂不可用') }
    }
    void load()
    return () => { active = false; controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [id, attempt, visible, owner])
  if (!id && !deviceArtifact(src) && remoteImagePolicy === 'confirm') return <ConfirmedRemoteImage key={JSON.stringify([src, owner, imageSessionKey])} src={src} alt={alt} owner={owner} />
  return <span ref={container} className="block min-h-12">
    {id && error ? <span className="my-3 flex items-center gap-3 text-sm" role="status">{alt || '内容图片'}：{error}<button type="button" className="underline" onClick={() => setAttempt(n => n + 1)}>重试</button></span>
      : id && !url ? <span role="status" className="block py-4 text-sm text-muted-foreground">{visible ? '正在读取' : ''}{alt || '内容图片'}…</span>
      : <img src={id ? url : resolveContentUrl(src)} alt={alt || '关键截图'} className="mb-4 max-w-full border border-border" loading="lazy" onError={() => { if (id) setError('图片读取失败') }} />}
  </span>
}
