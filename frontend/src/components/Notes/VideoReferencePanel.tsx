import { useEffect, useRef, useState } from 'react'
import { ExternalLink, PlayCircle } from 'lucide-react'
import { buildVideoJumpUrl, formatTimestampLabel, resolveContentUrl } from '../../lib/videoLinks'
import { Button } from '../ui/button'

interface VideoReferencePanelProps {
  noteId?: string
  taskId?: string
  videoUrl: string
  currentTimestamp: number
  jumpRequestId?: number
  activeMomentTitle?: string
  className?: string
  onTimestampChange?: (seconds: number) => void
}

type PlayerKind = 'video' | 'audio'

export function VideoReferencePanel({
  noteId,
  taskId,
  videoUrl,
  currentTimestamp,
  jumpRequestId = 0,
  activeMomentTitle,
  className,
  onTimestampChange,
}: VideoReferencePanelProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playerKind, setPlayerKind] = useState<PlayerKind>('video')
  const localMediaUrl = noteId && taskId ? resolveContentUrl(`/api/notes/${noteId}/media`) : null
  const jumpUrl = buildVideoJumpUrl(localMediaUrl || videoUrl, currentTimestamp)
  const timestampLabel = formatTimestampLabel(currentTimestamp)

  useEffect(() => {
    if (!localMediaUrl) {
      setPlayerKind('video')
      return
    }

    let cancelled = false
    setPlayerKind('video')

    void fetch(localMediaUrl, { method: 'HEAD', credentials: 'include' })
      .then((response) => {
        if (!response.ok || cancelled) {
          return
        }

        const contentType = response.headers.get('content-type') || ''
        if (contentType.startsWith('audio/')) {
          setPlayerKind('audio')
        } else if (contentType.startsWith('video/')) {
          setPlayerKind('video')
        }
      })
      .catch(() => {
        // Keep the video element as the optimistic default.
      })

    return () => {
      cancelled = true
    }
  }, [localMediaUrl])

  useEffect(() => {
    const player = playerKind === 'video' ? videoRef.current : audioRef.current
    if (!player || !localMediaUrl || jumpRequestId === 0) {
      return
    }

    player.currentTime = currentTimestamp
    if (currentTimestamp > 0) {
      void player.play().catch(() => {
        // Keep the seek even if autoplay is blocked.
      })
    }
  }, [currentTimestamp, jumpRequestId, localMediaUrl, playerKind])

  return (
    <aside className={className}>
      <section className="border xl:sticky xl:top-4">
        <header className="border-b p-4">
          <p className="text-xs font-medium text-muted-foreground">源媒体</p>
          <h2 className="mt-1 text-sm font-semibold">从笔记跳回录制现场</h2>
          <p className="text-sm text-muted-foreground">当前位置 · {timestampLabel}</p>
          {activeMomentTitle ? <p className="mt-3 border-l-2 border-foreground pl-3 text-sm text-foreground">当前片段 · {activeMomentTitle}</p> : null}
        </header>
        <div className="grid gap-4 p-4">
          {localMediaUrl ? (
          <div className="border bg-muted/20 p-2">
            {playerKind === 'video' ? (
              <video
                ref={videoRef}
                controls
                preload="metadata"
                src={localMediaUrl}
                className="aspect-video w-full bg-black"
                onError={() => setPlayerKind('audio')}
                onTimeUpdate={(event) => {
                  onTimestampChange?.(Math.floor(event.currentTarget.currentTime))
                }}
              />
            ) : (
              <audio
                ref={audioRef}
                controls
                preload="metadata"
                src={localMediaUrl}
                className="w-full"
                onTimeUpdate={(event) => {
                  onTimestampChange?.(Math.floor(event.currentTarget.currentTime))
                }}
              />
            )}
            <p className="mt-3 text-sm text-muted-foreground">点击纪要时间戳会直接定位到这份本地媒体。</p>
          </div>
        ) : (
          <div className="border border-dashed p-4 text-sm text-muted-foreground">
            这条笔记没有可播放的本地媒体，可以打开原始来源查看。
          </div>
        )}
          <Button asChild className="w-full">
            <a href={jumpUrl} target="_blank" rel="noreferrer"><PlayCircle className="size-4" />打开 {timestampLabel}<ExternalLink className="size-4" /></a>
          </Button>
        </div>
      </section>
    </aside>
  )
}
