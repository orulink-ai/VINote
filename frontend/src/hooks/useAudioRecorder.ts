import { captureMeetingSources, type MeetingCaptureOptions } from '../lib/meetingCapture'
import { createRecordingFile } from '../lib/recordingFile'
import { useCallback, useEffect, useRef, useState } from 'react'
import { requestDesktopMicrophoneAccess } from '../lib/desktopMicrophonePermission'
import { checkMicrophoneReadiness, mapMicrophoneError } from '../lib/microphonePermission'

type AudioRecorderStatus = 'idle' | 'requesting' | 'recording' | 'paused' | 'stopped' | 'failed'

const MIME_TYPE_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
]

const STOP_FALLBACK_MS = 3000

export function getPreferredAudioMimeType() {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return ''
  }

  return MIME_TYPE_CANDIDATES.find((mimeType) => MediaRecorder.isTypeSupported(mimeType)) || ''
}

export function useAudioRecorder() {
  const [status, setStatus] = useState<AudioRecorderStatus>('idle')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [error, setError] = useState('')
  const captureCleanupRef = useRef<(() => void) | null>(null)
  const diskRef = useRef<Awaited<ReturnType<typeof createRecordingFile>> | null>(null)
  const [preview, setPreview] = useState<MediaStream | null>(null)
  const [sizeBytes, setSizeBytes] = useState(0)
  const [sourceEnded, setSourceEnded] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const requestVersionRef = useRef(0)
  const captureAbortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<ReturnType<typeof window.setInterval> | null>(null)
  const timerStartedAtRef = useRef(0)
  const accumulatedMsRef = useRef(0)
  const mimeTypeRef = useRef('')

  const isSupported =
    typeof navigator !== 'undefined' &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== 'undefined'

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const captureElapsed = useCallback(() => {
    if (timerStartedAtRef.current) {
      accumulatedMsRef.current += Date.now() - timerStartedAtRef.current
      timerStartedAtRef.current = 0
    }
    setElapsedSeconds(Math.floor(accumulatedMsRef.current / 1000))
  }, [])

  const startTimer = useCallback(() => {
    clearTimer()
    timerStartedAtRef.current = Date.now()
    timerRef.current = window.setInterval(() => {
      const elapsedMs = accumulatedMsRef.current + Date.now() - timerStartedAtRef.current
      setElapsedSeconds(Math.floor(elapsedMs / 1000))
    }, 500)
  }, [clearTimer])

  const cleanupStream = useCallback(() => {
    captureCleanupRef.current?.()
    captureCleanupRef.current = null
    setPreview(null)
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }, [])

  const stopActiveRecorder = useCallback(() => {
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.ondataavailable = null
      recorder.onerror = null
      recorder.onstop = null
      try {
        recorder.stop()
      } catch {
        // Ignore stop races during cleanup; the stream is also stopped below.
      }
    }
    recorderRef.current = null
  }, [])

  const reset = useCallback(() => {
    requestVersionRef.current += 1
    captureAbortRef.current?.abort()
    captureAbortRef.current = null
    clearTimer()
    stopActiveRecorder()
    cleanupStream()
    chunksRef.current = []
    timerStartedAtRef.current = 0
    accumulatedMsRef.current = 0
    mimeTypeRef.current = ''
    setElapsedSeconds(0)
    setSizeBytes(0)
    setSourceEnded(false)
    void diskRef.current?.remove()
    diskRef.current = null
    setError('')
    setStatus('idle')
  }, [cleanupStream, clearTimer, stopActiveRecorder])

  const start = useCallback(async (options?: MeetingCaptureOptions) => {
    if (!isSupported) {
      const message = 'microphone_unsupported'
      setError(message)
      setStatus('failed')
      throw new Error(message)
    }

    reset()
    const requestVersion = requestVersionRef.current
    const captureAbort = new AbortController()
    captureAbortRef.current = captureAbort
    setStatus('requesting')

    try {
      // Acquire display capture before any unrelated await consumes user activation.
      const captured = options ? await captureMeetingSources(options, captureAbort.signal) : null
      if (captured && requestVersion !== requestVersionRef.current) { captured.cleanup(); return false }
      captureCleanupRef.current = captured?.cleanup || null
      if (captured?.display) {
        setPreview(options?.screen ? captured.display : null)
        captured.display.getVideoTracks().forEach(track => { track.onended = () => setSourceEnded(true) })
      }
      if (!captured) await requestDesktopMicrophoneAccess()
      const readiness = captured ? { ok: true, reason: undefined } : await checkMicrophoneReadiness()
      if (!readiness.ok) {
        throw new Error(`microphone_${readiness.reason}`)
      }
      if (requestVersion !== requestVersionRef.current) return false
      let timer: ReturnType<typeof setTimeout> | undefined
      let expired = false
      const mediaRequest = (captured ? Promise.resolve(captured.stream) : navigator.mediaDevices.getUserMedia({ audio: true })).then(stream => {
        if (expired || requestVersion !== requestVersionRef.current) {
          stream.getTracks().forEach(track => track.stop())
          throw new Error('microphone_request_cancelled')
        }
        return stream
      })
      const stream = await Promise.race([
        mediaRequest,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => { expired = true; reject(new Error('microphone_request_timeout')) }, 20000)
        }),
      ]).finally(() => clearTimeout(timer))
      streamRef.current = stream
      if (stream.getAudioTracks().length === 0) {
        throw new Error('microphone_no-device')
      }
      if (options?.screen) {
        const disk = await createRecordingFile()
        if (requestVersion !== requestVersionRef.current) { await disk.remove(); return false }
        diskRef.current = disk
      }
      const mimeType = options?.screen
        ? ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm'].find(type => MediaRecorder.isTypeSupported(type)) || ''
        : getPreferredAudioMimeType()
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType, ...(options?.screen ? { videoBitsPerSecond: 1500000 } : {}) }) : new MediaRecorder(stream)

      streamRef.current = stream
      recorderRef.current = recorder
      chunksRef.current = []
      mimeTypeRef.current = mimeType || recorder.mimeType || 'audio/webm'

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          setSizeBytes(size => size + event.data.size)
          if (diskRef.current) diskRef.current.append(event.data)
          else chunksRef.current.push(event.data)
        }
      }
      recorder.onerror = () => {
        captureElapsed()
        clearTimer()
        stopActiveRecorder()
        cleanupStream()
        setError('Audio recording failed.')
        setStatus('failed')
      }

      recorder.start(1000)
      accumulatedMsRef.current = 0
      setElapsedSeconds(0)
      setStatus('recording')
      startTimer()
      return true
    } catch (recordingError) {
      if (requestVersion !== requestVersionRef.current) return false
      cleanupStream()
      const reason = mapMicrophoneError(recordingError)
      const message = reason === 'unknown' && recordingError instanceof Error ? recordingError.message : `microphone_${reason}`
      setError(message)
      setStatus('failed')
      throw new Error(message)
    }
  }, [captureElapsed, clearTimer, cleanupStream, isSupported, reset, startTimer, stopActiveRecorder])

  const pause = useCallback(() => {
    const recorder = recorderRef.current
    if (!recorder || recorder.state !== 'recording') {
      return
    }

    recorder.pause()
    captureElapsed()
    clearTimer()
    setStatus('paused')
  }, [captureElapsed, clearTimer])

  const resume = useCallback(() => {
    const recorder = recorderRef.current
    if (!recorder || recorder.state !== 'paused') {
      return
    }

    recorder.resume()
    setStatus('recording')
    startTimer()
  }, [startTimer])

  const stop = useCallback(async () => {
    const recorder = recorderRef.current
    if (!recorder || recorder.state === 'inactive') {
      throw new Error('No active meeting recording.')
    }

    captureElapsed()
    clearTimer()

    return new Promise<Blob>((resolve, reject) => {
      let settled = false
      let fallbackTimer: ReturnType<typeof window.setTimeout> | null = null

      const clearFallbackTimer = () => {
        if (fallbackTimer) {
          window.clearTimeout(fallbackTimer)
          fallbackTimer = null
        }
      }

      const finalize = async () => {
        if (settled) {
          return
        }
        settled = true
        clearFallbackTimer()
        cleanupStream()
        let rawBlob: Blob
        try {
          const type = mimeTypeRef.current || recorder.mimeType || 'audio/webm'
          rawBlob = diskRef.current ? await diskRef.current.finish(type) : new Blob(chunksRef.current, { type })
        } catch (error) {
          cleanupStream()
          setStatus('failed')
          reject(error)
          return
        }
        chunksRef.current = []
        recorder.onstop = null
        recorder.onerror = null
        recorderRef.current = null
        cleanupStream()
        if (rawBlob.size === 0) {
          setStatus('failed')
          reject(new Error('microphone_no_audio'))
          return
        }
        // Preserve the exact MediaRecorder container. The backend keeps this
        // source artifact and creates a separate normalized copy only when the
        // selected transcriber cannot decode the original container.
        setStatus('stopped')
        resolve(rawBlob)
      }

      const fail = (message = 'Audio recording failed.') => {
        if (settled) {
          return
        }
        settled = true
        clearFallbackTimer()
        cleanupStream()
        setStatus('failed')
        reject(new Error(message))
      }

      recorder.onstop = finalize
      recorder.onerror = () => {
        fail()
      }

      fallbackTimer = window.setTimeout(finalize, STOP_FALLBACK_MS)

      try {
        recorder.requestData()
      } catch {
        // Some WebViews throw if data is not currently available; stop can still finalize the recording.
      }

      try {
        recorder.stop()
      } catch (stopError) {
        fail(stopError instanceof Error ? stopError.message : 'Failed to stop audio recording.')
      }
    })
  }, [captureElapsed, cleanupStream, clearTimer])

  useEffect(() => () => {
    requestVersionRef.current += 1
    captureAbortRef.current?.abort()
    clearTimer()
    stopActiveRecorder()
    cleanupStream()
    void diskRef.current?.remove()
  }, [cleanupStream, clearTimer, stopActiveRecorder])

  return {
    status,
    preview,
    sizeBytes,
    sourceEnded,
    elapsedSeconds,
    error,
    isSupported,
    start,
    pause,
    resume,
    stop,
    reset,
  }
}
