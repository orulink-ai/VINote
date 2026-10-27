import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '@/lib/api'

type Phase = 'loading' | 'ready' | 'buffering' | 'checking' | 'warming' | 'missing' | 'error'

/** Playback-only recovery. Never submits generation or changes a saved original. */
export function useNoteMediaPlayback(sourceUrl: string | undefined, identity: string, video: boolean, zh: boolean) {
  const [phase, setPhase] = useState<Phase>('loading')
  const [message, setMessage] = useState('')
  const sequence = useRef(0)
  const probe = useRef<AbortController | null>(null)
  const scope = useRef({ sourceUrl, identity })
  // Keep one token per visit, independent of request/ready/reload sequence changes.
  if (scope.current.sourceUrl !== sourceUrl || scope.current.identity !== identity) {
    scope.current = { sourceUrl, identity }
  }
  const visit = scope.current
  const position = useRef(0)
  const resume = useRef<{ element: HTMLMediaElement; seconds: number; rate: number; playing: boolean } | null>(null)

  useEffect(() => {
    sequence.current++
    probe.current?.abort()
    position.current = 0
    resume.current = null
    setMessage('')
    setPhase('loading')
    return () => { sequence.current++; probe.current?.abort() }
  }, [sourceUrl, identity])

  const remember = (element: HTMLMediaElement) => {
    if (Number.isFinite(element.currentTime)) position.current = element.currentTime
  }
  const ready = () => {
    sequence.current++
    probe.current?.abort()
    setPhase('ready')
    setMessage('')
  }
  const waiting = () => setPhase(current => ['loading', 'ready', 'buffering'].includes(current) ? 'buffering' : current)
  const failed = async (element: HTMLMediaElement) => {
    if (!sourceUrl) return
    if (element.currentTime > 0) remember(element)
    const request = ++sequence.current
    probe.current?.abort()
    const controller = new AbortController()
    probe.current = controller
    const timer = window.setTimeout(() => controller.abort(), 10000)
    const current = () => request === sequence.current && scope.current.sourceUrl === sourceUrl && scope.current.identity === identity
    const generic = zh
      ? `${video ? '视频' : '音频'}尚未就绪或读取失败，请重新加载。原文件状态未确认，正文仍可阅读。`
      : `${video ? 'Video' : 'Audio'} is not ready or could not be read. Reload playback; original availability is unverified. Saved text remains readable.`
    setPhase('checking')
    setMessage('')
    try {
      // A bounded range distinguishes a confirmed 404 from warmup/network/decode errors.
      const response = await apiFetch(sourceUrl, { headers: { Range: 'bytes=0-0' }, cache: 'no-store', signal: controller.signal })
      await response.body?.cancel()
      if (!current()) return
      if (response.status === 202 || (response.status === 503 && response.headers.has('Retry-After'))) {
        setPhase('warming')
        setMessage(zh ? '正在准备播放副本，请稍后重新加载视频。原文件与正文保留。' : 'Preparing the playback copy. Reload video shortly; original and saved text are retained.')
      } else if (response.status === 404 || response.status === 410) {
        setPhase('missing')
        setMessage(zh ? '当前播放来源不可用，正文仍保留。这不表示笔记已删除。可到原文件核对后重新加载。' : 'Playback source unavailable; saved text is retained. This does not mean the note was deleted. Check the original and reload.')
      } else if (response.status === 401 || response.status === 403) {
        setPhase('error')
        setMessage(zh ? '当前账号无法读取媒体，请核对登录与权限后重新加载。正文仍保留。' : 'Sign in with the original account and check permission, then reload media. Saved text is retained.')
      } else {
        setPhase('error')
        setMessage(generic)
      }
    } catch {
      if (current()) { setPhase('error'); setMessage(generic) }
    } finally {
      window.clearTimeout(timer)
    }
  }
  const reload = (element: HTMLMediaElement | null) => {
    if (!element) return
    sequence.current++
    probe.current?.abort()
    resume.current = { element, seconds: element.currentTime > 0 ? element.currentTime : position.current, rate: element.playbackRate, playing: !element.paused }
    setMessage('')
    setPhase('loading')
    element.load()
  }
  const metadata = (element: HTMLMediaElement) => {
    if (scope.current !== visit) return
    // Metadata supersedes earlier read failures, but does not prove decodable playback.
    sequence.current++
    probe.current?.abort()
    setMessage('')
    setPhase(current => current === 'ready' ? current : 'loading')
    const saved = resume.current
    if (!saved || saved.element !== element) return
    resume.current = null
    const end = Number.isFinite(element.duration) && element.duration > 0 ? element.duration : saved.seconds
    element.currentTime = Math.min(saved.seconds, end)
    element.playbackRate = saved.rate
    if (saved.playing) void element.play().catch(() => undefined)
  }
  const status = phase === 'loading' || phase === 'checking'
    ? zh ? `正在加载${video ? '视频播放副本' : '音频'}…` : `Loading ${video ? 'video playback copy' : 'audio'}…`
    : phase === 'buffering' ? zh ? '正在缓冲，原文件保留…' : 'Buffering; original retained…' : ''
  return { phase, message, status, remember, ready, waiting, failed, reload, metadata }
}
