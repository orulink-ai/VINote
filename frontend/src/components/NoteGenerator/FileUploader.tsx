import { useCallback, useEffect, useRef, useState } from 'react'
import { FileAudio, Link as LinkIcon, Upload, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { useI18n } from '../../lib/i18n'
export type UploadMode = 'url' | 'file' | 'transcript'
interface Props { onVideoUrlChange: (url: string) => void; onFileSelect: (file: File | null) => void; onModeChange: (mode: UploadMode) => void; videoUrl: string; fileUploadEnabled?: boolean; initialMode?: UploadMode; urlEnabled?: boolean }
export function FileUploader({ onVideoUrlChange, onFileSelect, onModeChange, videoUrl, fileUploadEnabled = true, initialMode = 'url', urlEnabled = true }: Props) {
  const { copy } = useI18n(); const [mode, setMode] = useState<UploadMode>(initialMode); const [dragActive, setDragActive] = useState(false); const [selectedFile, setSelectedFile] = useState<File | null>(null); const inputRef = useRef<HTMLInputElement>(null)
  const setModeSafe = (next: UploadMode) => { if (!fileUploadEnabled && next !== 'url') return; if (selectedFile) { setSelectedFile(null); onFileSelect(null) } setMode(next); onModeChange(next) }
  useEffect(() => { if (!fileUploadEnabled && mode !== 'url') setModeSafe('url') }, [fileUploadEnabled, mode])
  useEffect(() => { setMode(initialMode); setSelectedFile(null) }, [initialMode])
  const choose = (file: File) => { const next: UploadMode = /.(txt|srt|vtt|json|md)$/i.test(file.name) ? 'transcript' : 'file'; setMode(next); onModeChange(next); setSelectedFile(file); onFileSelect(file) }
  const handleDrag = useCallback((event: React.DragEvent) => { event.preventDefault(); event.stopPropagation(); setDragActive(['dragenter', 'dragover'].includes(event.type)) }, [])
  return <div className="grid gap-4"><Tabs value={mode === 'url' ? 'url' : 'file'} onValueChange={value => setModeSafe(value as UploadMode)}><TabsList>{urlEnabled ? <TabsTrigger value="url"><LinkIcon />{copy.fileUploader.videoUrl}</TabsTrigger> : null}{fileUploadEnabled ? <TabsTrigger value="file"><FileAudio />{copy.fileUploader.localFile || '文件'}</TabsTrigger> : null}</TabsList></Tabs>
    {mode === 'url' ? <Field><FieldLabel>网页、文章或公开视频链接</FieldLabel><Input value={videoUrl} onChange={event => onVideoUrlChange(event.target.value)} placeholder={copy.fileUploader.videoPlaceholder} /><FieldDescription>{!fileUploadEnabled ? copy.fileUploader.browserModeHint : '系统会提取链接中的可读内容或公开媒体。'}</FieldDescription></Field> : <div onDragEnter={handleDrag} onDragLeave={handleDrag} onDragOver={handleDrag} onDrop={event => { handleDrag(event); const file = event.dataTransfer.files?.[0]; if (file) choose(file) }} className={cn('grid min-h-60 place-items-center rounded-lg border border-dashed p-8 text-center transition', dragActive && 'bg-muted')}>
      {selectedFile ? <div className="flex items-center gap-3"><div className="grid size-10 place-items-center border bg-muted"><FileAudio /></div><div className="text-left"><p className="font-medium">{selectedFile.name}</p><p className="text-sm text-muted-foreground">{(selectedFile.size / 1024 / 1024).toFixed(1)} MB</p></div><Button variant="ghost" size="icon" onClick={() => { setSelectedFile(null); onFileSelect(null) }}><X /></Button></div> : <div className="grid justify-items-center gap-3"><div className="grid size-12 place-items-center border bg-muted"><Upload /></div><div><p className="font-medium">{copy.fileUploader.dragHint}</p><p className="mt-1 text-sm text-muted-foreground">音频、视频、TXT、Markdown、SRT、VTT、JSON</p></div><Input ref={inputRef} type="file" accept="audio/*,video/*,.mp3,.wav,.m4a,.flac,.ogg,.mp4,.mov,.mkv,.webm,.avi,.txt,.srt,.vtt,.json,.md" onChange={event => { const file = event.target.files?.[0]; if (file) choose(file) }} className="hidden" /><Button type="button" variant="outline" onClick={() => inputRef.current?.click()}>{copy.fileUploader.selectFile}</Button></div>}
    </div>}
  </div>
}
