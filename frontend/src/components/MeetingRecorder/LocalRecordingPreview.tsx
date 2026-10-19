import { formatMeetingTitle } from '../../lib/meetingTitle'
import { RecordingTitleEditor } from './RecordingTitleEditor'
import { TranscriptionProgress } from './TranscriptionProgress'
import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, Download, FileText, Play, RotateCcw, Sparkles, Trash2 } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { deleteLocalRecording, getRecordedAudio, getPendingMeeting, type PendingMeeting, type MeetingGenerationSelection } from '../../lib/audioStorage'
import { processSavedMeeting, isMeetingProcessing } from '../../lib/meetingProcessing'
import { ModelSourcePanel } from '../Settings/ModelSourcePanel'
import { useAppModeStore } from '../../stores/appModeStore'
import { useModelProfileStore } from '../../stores/modelProfileStore'
import { useSTTProfileStore } from '../../stores/sttProfileStore'
import { downloadRecording } from '../../lib/recordingDownload'
import { useI18n } from '../../lib/i18n'

interface LocalRecordingPreviewProps { recording: PendingMeeting; onDeleted: () => void; onOpenNote?: (noteId: string) => void; confirmOnOpen?: boolean; onRecordingUpdated?: (recording: PendingMeeting) => void }
const stageCopy: Record<PendingMeeting['processingStatus'], string> = { idle: '尚未生成纪要', queued: '等待处理', preparing_media: '准备和校验媒体', transcribing: '云端转写完整音频', diarizing: '区分说话人', parallel_analysis: '转写与说话人分析同时进行', aligning: '对齐逐字稿', analyzing_video: '核对共享画面与发言', generating: '生成并校验纪要', saving_result: '保存结果', completed: '纪要已完成', failed: '处理失败' }

export function LocalRecordingPreview({ recording, onDeleted, onOpenNote, confirmOnOpen = false, onRecordingUpdated }: LocalRecordingPreviewProps) {
  const { locale } = useI18n(); const zh = locale.startsWith('zh')
  const [url, setUrl] = useState(''); const [error, setError] = useState(''); const [deleting, setDeleting] = useState(false); const [expanded, setExpanded] = useState(false)
  const [renamedTitle, setRenamedTitle] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [loading, setLoading] = useState(false)
  const [confirmGeneration, setConfirmGeneration] = useState(false)
  const [generating, setGenerating] = useState(false)
  const generationLock = useRef(false)
  const { config, saving: modelSaving, error: modeError, load: loadMode } = useAppModeStore()
  const models = useModelProfileStore()
  const speech = useSTTProfileStore()
  const request = useRef(0)
  useEffect(() => {
    request.current += 1; setUrl(''); setExpanded(false); setError(''); setLoading(false); setConfirmGeneration(false); setGenerating(false)
    return () => { request.current += 1 }
  }, [recording.id, recording.ownerId])
  useEffect(() => { setRenamedTitle('') }, [recording.options.title])
  useEffect(() => {
    if (confirmOnOpen && recording.processingStatus !== 'completed') { setConfirmGeneration(true); void loadMode() }
  }, [confirmOnOpen, recording.id, recording.ownerId, loadMode])
  const title = renamedTitle || recording.options.title || formatMeetingTitle(recording.startedAt, '', locale)
  const isVideo = recording.options.meetingType === 'video' || recording.options.screen
  const processing = generating || !['idle', 'completed', 'failed'].includes(recording.processingStatus)
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  const load = async (download: boolean) => {
    const current = ++request.current; setError(''); setLoading(true)
    try {
      const blob = await getRecordedAudio(recording.id)
      if (request.current !== current) return
      if (!blob) throw new Error(zh ? '找不到此设备上的录制文件' : 'Recording not found on this device')
      if (download) downloadRecording(blob, title)
      else { setUrl(URL.createObjectURL(blob)); setExpanded(true) }
    } catch (cause) {
      if (request.current === current) setError(cause instanceof Error ? cause.message : String(cause))
    } finally { if (request.current === current) setLoading(false) }
  }
  const playbackFailed = () => { setUrl(''); setError(zh ? '文件暂时无法播放，请重新加载；也可以下载后使用播放器打开。' : 'Playback failed. Reload the file or download it to play.') }
  const remove = async () => { setDeleting(true); setError(''); setUrl(''); try { await deleteLocalRecording(recording.id, recording.ownerId); setConfirmDelete(false); onDeleted() } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) } finally { setDeleting(false) } }
  const selectedASR = speech.profiles.find(profile => profile.id === speech.selectedProfileId && profile.isActive)
  const selectedLLM = models.profiles.find(profile => profile.id === models.selectedProfileId && profile.isActive)
  const selection: MeetingGenerationSelection | null = config?.mode === 'cloud'
    ? config.configured && config.asr_model && config.llm_model ? { mode: 'cloud', asr: config.asr_model, llm: config.llm_model, asrLabel: config.asr_model, llmLabel: config.llm_model } : null
    : config?.mode === 'local' && selectedASR && selectedLLM ? { mode: 'local', asr: selectedASR.id, llm: selectedLLM.id, asrLabel: `${selectedASR.name} · ${selectedASR.modelName || selectedASR.provider}`, llmLabel: `${selectedLLM.name} · ${selectedLLM.modelName}` } : null
  const modelError = modeError || (config?.mode === 'local' ? models.error || speech.error : '')
  const needsConfirmation = recording.generationConfirmationRequired || (!recording.taskId && !recording.generationOperation)
  const generate = async (confirm = false) => {
    if (generationLock.current || isMeetingProcessing(recording.id)) return
    if (confirm && (!selection || modelSaving || modelError)) return
    generationLock.current = true
    const current = request.current
    setGenerating(true); setError('')
    try {
      await processSavedMeeting(recording, locale, undefined, confirm ? { selection: selection!, previousTaskId: recording.taskId, previousOperationId: recording.generationOperation?.id } : undefined)
      if (request.current !== current) return
      const updated = await getPendingMeeting(recording.id)
      if (request.current !== current) return
      if (updated && updated.ownerId === recording.ownerId) onRecordingUpdated?.(updated)
      if (updated?.processingStatus === 'failed') setError(updated.processingError || '处理未完成，原录制保留。')
      else setConfirmGeneration(false)
    } catch (cause) { if (request.current === current) setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { generationLock.current = false; if (request.current === current) setGenerating(false) }
  }
  const restore = () => {
    if (needsConfirmation) { setConfirmGeneration(true); setError(''); void loadMode() }
    else void generate()
  }
  const statusText = zh ? stageCopy[recording.processingStatus] : recording.processingStatus.replace(/_/g, ' ')

  return <article className="flex min-w-0 flex-col gap-3">
    {expanded ? <div className="border-y bg-muted/20 py-3">{url ? isVideo ? <video src={url} controls preload="metadata" onError={playbackFailed} aria-label={zh ? '录屏回放' : 'Recording playback'} className="max-h-72 w-full rounded-md bg-black" /> : <audio src={url} controls preload="metadata" onError={playbackFailed} aria-label={zh ? '录音回放' : 'Recording playback'} className="w-full" /> : <button type="button" disabled={loading} onClick={() => void load(false)} className="flex min-h-32 w-full flex-col items-center justify-center rounded-md border border-dashed bg-background text-sm text-muted-foreground"><Play className="mb-2 size-5" />{loading ? (zh ? '正在读取文件…' : 'Loading file…') : (zh ? '重新加载并回放' : 'Reload and play')}</button>}</div> : null}
    <div className="flex flex-col gap-3"><div className="py-2"><div className="flex items-start gap-3">{recording.processingStatus === 'completed' ? <CheckCircle2 className="mt-0.5 size-5 text-emerald-600" /> : <FileText className="mt-0.5 size-5 text-muted-foreground" />}<div className="min-w-0 flex-1"><p className="text-sm font-medium">{statusText}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{recording.processingStatus === 'failed' ? recording.processingError || (zh ? '原始媒体已保留，可重试。' : 'Original media is preserved and retryable.') : processing ? (zh ? '后台处理中，录制控制已经退出。' : 'Processing in the background; capture controls are closed.') : recording.processingStatus === 'completed' ? (zh ? '在详情中查看带说话人的逐字稿、代表画面证据和纪要。' : 'Open details for transcript, visual evidence and notes.') : (zh ? '原始媒体已保存在本机，可播放、下载或生成纪要。' : 'Original media is saved locally.')}</p></div></div></div>
      {recording.processingStatus === 'transcribing' ? <TranscriptionProgress processedSeconds={recording.processedSeconds} totalSeconds={recording.totalSeconds} etaSeconds={recording.etaSeconds} zh={zh} /> : null}
      <details className="text-sm"><summary className="cursor-pointer text-muted-foreground">修改记录名称</summary><div className="pt-3"><RecordingTitleEditor recording={recording} title={title} onSaved={setRenamedTitle} /></div></details>
      {recording.generationOperation && <p className="text-xs leading-5 text-muted-foreground">本次语音转写：{recording.generationOperation.selection.asrLabel}；总结：{recording.generationOperation.selection.llmLabel}。恢复原任务沿用原选择。</p>}
      {recording.generationConfirmationRequired && recording.processingStatus !== 'failed' && recording.processingError && <p role="status" className="text-sm text-muted-foreground">{recording.processingError}</p>}
      {confirmGeneration && <section aria-label="确认生成模型" className="grid gap-3 border-y py-4">
        <h3 className="font-medium">{recording.taskId || recording.generationOperation ? '确认另建生成操作' : '确认本次生成'}</h3>
        <p className="text-sm text-muted-foreground">{recording.taskId || recording.generationOperation ? '原操作不会自动重新提交。确认后从同一份原录制另建操作，原有纪要保留。' : '原录制已保存。确认转写与总结模型后开始会后处理。'}</p>
        {generating ? <p role="status">正在处理，原录制保留…</p> : <ModelSourcePanel compact />}
        {selection && <p className="text-sm">语音转写：{selection.asrLabel}；内容总结：{selection.llmLabel}</p>}
        {!selection && <p role="status" className="text-sm text-muted-foreground">请明确选择可用的转写和总结模型，不使用尚未核验的默认配置。</p>}
        {modelError && <p role="alert" className="text-sm text-destructive">{modelError}</p>}
        <div className="flex flex-wrap gap-2"><Button disabled={generating || !selection || modelSaving || !!modelError || models.loading || speech.loading} onClick={() => void generate(true)}>{generating ? '正在处理…' : '确认模型并生成'}</Button><Button variant="outline" disabled={generating} onClick={() => setConfirmGeneration(false)}>暂不生成</Button><Button variant="ghost" disabled={generating || modelSaving} onClick={() => { void loadMode(); if (config?.mode === 'local') { void models.loadProfiles(); void speech.loadProfiles() } }}>重新读取模型配置</Button></div>
      </section>}
      <div className="mt-auto grid gap-2">{recording.processingStatus === 'failed' ? <Alert variant="destructive"><AlertDescription>{recording.failedStage ? (zh ? '失败阶段：' : 'Failed stage: ') + (stageCopy[recording.failedStage as keyof typeof stageCopy] || recording.failedStage) + '。' : ''}{recording.processingError}</AlertDescription></Alert> : null}{recording.processingStatus === 'completed' && recording.noteId ? <Button onClick={() => onOpenNote?.(recording.noteId!)}><FileText />{zh ? '查看会议纪要' : 'Open meeting notes'}</Button> : <Button disabled={processing || deleting} onClick={restore}>{recording.processingStatus === 'failed' ? <RotateCcw /> : <Sparkles />}{processing ? statusText : recording.processingStatus === 'failed' ? (zh ? '重试会后处理' : 'Retry processing') : (zh ? '生成会议纪要' : 'Generate meeting notes')}</Button>}
        <div className="flex flex-wrap gap-1">
          <Button variant="outline" size="sm" disabled={loading || deleting} onClick={() => void load(false)}><Play />{loading ? (zh ? '正在读取…' : 'Loading…') : (zh ? '预览' : 'Preview')}</Button>
          <Button variant="outline" size="sm" disabled={loading || deleting} onClick={() => void load(true)}><Download />{zh ? '下载文件' : 'Download file'}</Button>
          <AlertDialog open={confirmDelete} onOpenChange={value => { if (!deleting) { setConfirmDelete(value); setError('') } }}>
            <AlertDialogTrigger asChild><Button variant="ghost" size="sm" disabled={processing || deleting || loading} className="text-destructive hover:text-destructive"><Trash2 />{zh ? '删除录制文件' : 'Delete recording'}</Button></AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader><AlertDialogTitle>{zh ? '删除录制文件？' : 'Delete recording?'}</AlertDialogTitle><AlertDialogDescription>{zh ? '删除这台设备上的录制文件与列表记录。已有纪要、逐字稿和全部版本保留；尚未完成的处理将无法继续。' : 'This removes the recording on this device. Saved notes, transcripts and versions remain.'}</AlertDialogDescription></AlertDialogHeader>
              {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
              <AlertDialogFooter><AlertDialogCancel disabled={deleting}>{zh ? '取消' : 'Cancel'}</AlertDialogCancel><AlertDialogAction disabled={deleting} onClick={event => { event.preventDefault(); void remove() }}>{deleting ? (zh ? '正在删除…' : 'Deleting…') : (zh ? '确认删除文件' : 'Delete recording')}</AlertDialogAction></AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
        {error && !confirmDelete ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      </div>
    </div>
  </article>
}
