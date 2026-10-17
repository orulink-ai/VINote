import { useEffect, useRef, useState } from 'react'
import { Mic2, Square } from 'lucide-react'
import { acquireMeetingMicrophone } from '@/lib/meetingCapture'
import { mapMicrophoneError } from '@/lib/microphonePermission'
import { Button } from '@/components/ui/button'

// Live input measurement only: never record, persist or upload this audio.
export function MicrophoneCheck({ deviceId, onActiveChange }: { deviceId: string; onActiveChange?: (active: boolean) => void }) {
  const [phase, setPhase] = useState<'idle' | 'requesting' | 'testing'>('idle')
  const [level, setLevel] = useState(0)
  const [message, setMessage] = useState('测试现场声音，10 秒后自动释放麦克风。')
  const epoch = useRef(0)
  const release = useRef<() => void>(() => {})
  useEffect(() => {
    onActiveChange?.(phase !== 'idle')
    return () => onActiveChange?.(false)
  }, [phase, onActiveChange])
  const stop = (label: string) => {
    ++epoch.current; release.current(); setPhase('idle'); setLevel(0); setMessage(label)
  }
  useEffect(() => {
    setPhase('idle'); setLevel(0); setMessage('测试现场声音，10 秒后自动释放麦克风。')
    const hidden = () => { if (document.hidden) stop('测试已停止，麦克风已释放。') }
    document.addEventListener('visibilitychange', hidden)
    return () => { ++epoch.current; release.current(); document.removeEventListener('visibilitychange', hidden) }
  }, [deviceId])
  const test = async () => {
    if (phase !== 'idle') return
    const run = ++epoch.current
    const abort = new AbortController()
    let stream: MediaStream | undefined, context: AudioContext | undefined
    let interval: ReturnType<typeof setInterval> | undefined, deadline: ReturnType<typeof setTimeout> | undefined
    const cleanup = () => {
      abort.abort(); clearInterval(interval); clearTimeout(deadline)
      stream?.getTracks().forEach(track => track.stop())
      if (context && context.state !== 'closed') void context.close().catch(() => {})
    }
    release.current = cleanup
    setPhase('requesting'); setMessage('等待麦克风授权，可随时取消。')
    try {
      stream = await acquireMeetingMicrophone(deviceId, abort.signal)
      if (run !== epoch.current) { cleanup(); return }
      context = new AudioContext()
      await context.resume()
      if (run !== epoch.current) { cleanup(); return }
      const input = context.createMediaStreamSource(stream), analyser = context.createAnalyser()
      analyser.fftSize = 512; input.connect(analyser)
      const samples = new Float32Array(analyser.fftSize)
      setPhase('testing')
      interval = setInterval(() => {
        if (run !== epoch.current) return
        analyser.getFloatTimeDomainData(samples)
        let energy = 0, peak = 0
        for (const sample of samples) { energy += sample * sample; peak = Math.max(peak, Math.abs(sample)) }
        const db = 20 * Math.log10(Math.max(Math.sqrt(energy / samples.length), 0.00001))
        setLevel(Math.round(Math.max(0, Math.min(100, (db + 60) / 60 * 100))))
        setMessage(peak >= .98 ? '输入接近失真，请降低输入音量或远离麦克风。' : db < -48 ? '声音较轻，请说话或检查麦克风位置。' : '已检测到声音，继续说话检查输入是否稳定。')
      }, 100)
      deadline = setTimeout(() => { if (run === epoch.current) stop('测试完成，麦克风已释放。可以开始录制。') }, 10000)
    } catch (cause) {
      cleanup()
      if (run !== epoch.current) return
      setPhase('idle'); setLevel(0)
      const reason = mapMicrophoneError(cause)
      setMessage(reason === 'denied' ? '麦克风权限未开启，请在系统设置授权后重试。' : reason === 'no-device' ? '未检测到麦克风，请连接设备后重试。' : '输入测试未完成，请检查设备后重试。')
    }
  }
  return <section aria-label="麦克风音量测试" className="mt-4 flex flex-col gap-3 rounded-xl border bg-muted/40 p-4">
    <div className="flex items-center justify-between gap-3"><span className="text-sm font-medium">输入音量</span><Button size="sm" variant="outline" onClick={() => phase === 'idle' ? void test() : stop('测试已取消，麦克风已释放。')}>
      {phase === 'idle' ? <Mic2 data-icon="inline-start" /> : <Square data-icon="inline-start" />}{phase === 'idle' ? '测试麦克风' : phase === 'requesting' ? '取消授权等待' : '停止测试'}
    </Button></div>
    <div role="meter" aria-label="实时输入音量" aria-valuemin={0} aria-valuemax={100} aria-valuenow={level} className="flex h-6 items-end gap-1" >{Array.from({ length: 20 }, (_, index) => <span key={index} className={level > index * 5 ? 'flex-1 rounded-sm bg-primary' : 'flex-1 rounded-sm bg-border'} style={{ height: `${30 + index * 3}%` }} />)}</div>
    <p className="text-xs leading-5 text-muted-foreground">{message}</p>
  </section>
}
