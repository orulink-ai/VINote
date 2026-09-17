import { useEffect, useState } from 'react'
import { CheckCircle, Download, FileAudio, FileText, Image, Loader2, Mic, XCircle } from 'lucide-react'
import { useI18n } from '../../lib/i18n'
import { Alert, AlertDescription } from '../ui/alert'
import { Badge } from '../ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { cn } from '../../lib/utils'

interface GenerateProgressProps {
  status: 'idle' | 'uploading' | 'processing' | 'success' | 'failed'
  progress: number
  currentStep: string
  error?: string
  message?: string
}

export function GenerateProgress({ status, progress, currentStep, error, message }: GenerateProgressProps) {
  const { copy } = useI18n()
  const steps = [
    { key: 'uploading', label: copy.progress.prepareRequest, icon: FileAudio },
    { key: 'downloading', label: copy.progress.downloadAudio, icon: Download },
    { key: 'transcribing', label: copy.progress.transcribeAudio, icon: Mic },
    { key: 'summarizing', label: copy.progress.generateNote, icon: FileText },
    { key: 'screenshots', label: copy.progress.processScreenshots, icon: Image },
  ]
  const stepLabels = Object.fromEntries(steps.map((step) => [step.key, step.label]))
  const activeStep = Math.max(1, steps.findIndex(step => step.key === currentStep) + 1)
  const running = status === 'processing' || status === 'uploading'
  const [waitingSeconds, setWaitingSeconds] = useState(0)
  useEffect(() => {
    setWaitingSeconds(0)
    if (!running) return
    const started = Date.now()
    const timer = setInterval(() => setWaitingSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [running, currentStep])
  const detail = message?.replace(/Transcribing chunk (\d+)\/(\d+)/, '正在转写第 $1/$2 段')
    .replace('Transcribing audio...', '正在识别音频内容…')

  const getStepStatus = (stepKey: string) => {
    if (status === 'success') return 'completed'
    const currentIndex = steps.findIndex((step) => step.key === currentStep)
    const stepIndex = steps.findIndex((step) => step.key === stepKey)
    if (stepIndex < currentIndex) return 'completed'
    if (stepIndex === currentIndex) return status === 'failed' ? 'failed' : 'processing'
    return 'pending'
  }

  if (status === 'idle') return null

  return (
    <Card>
      <CardHeader className="gap-4 pb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-lg">
            {running && <Loader2 aria-hidden="true" className="h-5 w-5 animate-spin text-primary motion-reduce:animate-none" />}
            {status === 'success'
              ? copy.progress.completed
              : status === 'failed'
                ? copy.progress.failed
                : stepLabels[currentStep] || copy.progress.preparing}
          </CardTitle>
          <Badge variant={status === 'failed' ? 'destructive' : 'secondary'}>{status === 'success' ? '已完成' : `第 ${activeStep} / ${steps.length} 步`}</Badge>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-secondary">
          <div
            className={cn(
              'h-full rounded-full transition-all duration-300',
              status === 'failed' ? 'bg-destructive' : 'bg-primary'
            )}
            role="progressbar"
            aria-label="生成笔记阶段进度"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
            style={{ width: `${progress}%` }}
          />
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">

      {running && detail && <div role="status" className="rounded-xl border bg-muted/40 p-4">
        <p className="font-medium text-foreground">{detail}</p>
        <p className="mt-2 text-sm tabular-nums text-primary">本界面等待 {Math.floor(waitingSeconds / 60)} 分 {waitingSeconds % 60} 秒 · {message?.includes('无法获取') ? '状态检查异常，正在重试' : '等待服务端返回结果'}</p>
        {currentStep === 'transcribing' && <p className="mt-2 text-sm leading-6 text-muted-foreground">音频转写中，完成当前分段后更新进度。进度条表示处理阶段，不代表已转写的音频比例。</p>}
      </div>}

      <div className="grid gap-2 sm:grid-cols-2">
        {steps.map((step) => {
          const stepStatus = getStepStatus(step.key)
          const Icon = step.icon

          return (
            <div
              key={step.key}
              className={cn(
                'flex items-center gap-3 p-3 rounded-lg border',
                stepStatus === 'processing' ? 'border-primary/30 bg-primary/5' : 'border-transparent'
              )}
            >
              {stepStatus === 'completed' && <CheckCircle className="w-5 h-5 text-emerald-600" />}
              {stepStatus === 'processing' && <Loader2 className="w-5 h-5 animate-spin text-primary" />}
              {stepStatus === 'failed' && <XCircle className="w-5 h-5 text-destructive" />}
              {stepStatus === 'pending' && <Icon className="w-5 h-5 text-muted-foreground/50" />}

              <span className={cn(
                'text-sm',
                stepStatus === 'completed' && 'text-emerald-600',
                stepStatus === 'processing' && 'text-primary font-medium',
                stepStatus === 'failed' && 'text-destructive',
                stepStatus === 'pending' && 'text-muted-foreground'
              )}>
                {step.label}
              </span>
            </div>
          )
        })}
      </div>

      {error && (
        <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>
      )}
      </CardContent>
    </Card>
  )
}
