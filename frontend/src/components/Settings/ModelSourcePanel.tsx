import { useEffect, useState } from 'react'
import { Cloud, RefreshCw, Server } from 'lucide-react'
import { apiJson } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { useAppModeStore } from '../../stores/appModeStore'
import { Alert, AlertDescription } from '../ui/alert'
import { Button } from '../ui/button'
import { Label } from '../ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select'
import { ToggleGroup, ToggleGroupItem } from '../ui/toggle-group'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs'
import { ModelProfileManager } from './ModelProfileManager'
import { STTProfileManager } from './STTProfileManager'
import { ProcessingModelPicker } from './ProcessingModelPicker'

type CloudModel = { id: string; modelType: 'asr' | 'llm'; runtimeStatus: string }
const DEFAULT_VALUE = '__service_default__'

export function ModelSourcePanel({ compact = false }: { compact?: boolean }) {
  const { config, saving, error, setMode, saveModels } = useAppModeStore()
  const { locale } = useI18n(); const zh = locale.startsWith('zh')
  const [models, setModels] = useState<CloudModel[]>([]); const [loading, setLoading] = useState(false); const [catalogError, setCatalogError] = useState(''); const [refresh, setRefresh] = useState(0)
  useEffect(() => { if (config?.mode !== 'cloud') return; let active = true; setLoading(true); setCatalogError(''); void apiJson<CloudModel[]>('/api/vilab/models').then(result => { if (active) setModels(result) }).catch(cause => { if (active) setCatalogError(cause instanceof Error ? cause.message : (zh ? '无法读取模型列表' : 'Cannot load models')) }).finally(() => { if (active) setLoading(false) }); return () => { active = false } }, [config?.mode, refresh, zh])
  return <div className="grid gap-6">
    <section className="overflow-hidden rounded-2xl border bg-card"><header className="flex items-start justify-between gap-4 border-b px-5 py-4"><div><h3 className="font-semibold">{compact ? (zh ? '本次任务使用' : 'Use for this task') : (zh ? '模型运行方式' : 'Model runtime')}</h3><p className="mt-1 text-sm leading-6 text-muted-foreground">{compact ? (zh ? '选择转写与总结所用的服务，修改会用于下一次处理。' : 'Choose the services used for transcription and summary.') : (zh ? '决定任务使用部署服务，还是连接你管理的本地与兼容模型。' : 'Use deployed services or connect your managed local and compatible models.')}</p></div>{config?.mode === 'cloud' && <Button variant="ghost" size="sm" disabled={loading || saving} onClick={() => setRefresh(value => value + 1)}><RefreshCw className={loading ? 'animate-spin' : ''} />{zh ? '刷新' : 'Refresh'}</Button>}</header><div className="grid gap-5 p-5">
      {!compact && <ToggleGroup type="single" value={config?.mode} onValueChange={value => { if (value === 'cloud' || value === 'local') void setMode(value) }} className="grid grid-cols-2"><ToggleGroupItem value="cloud" disabled={saving || !config} className="gap-2"><Cloud className="h-4 w-4" />{zh ? '云端模型' : 'Cloud'}</ToggleGroupItem><ToggleGroupItem value="local" disabled={saving || !config} className="gap-2"><Server className="h-4 w-4" />{zh ? '本地 / 自定义' : 'Local / custom'}</ToggleGroupItem></ToggleGroup>}
      {config?.mode === 'cloud' && <><div className={compact ? 'grid gap-4' : 'grid gap-4 sm:grid-cols-2'}>{(['asr', 'llm'] as const).map(kind => { const selected = kind === 'asr' ? config.asr_model : config.llm_model; const choices = models.filter(model => model.modelType === kind); return <div key={kind} className="grid gap-2"><Label>{kind === 'asr' ? (zh ? '语音转写' : 'Speech recognition') : (zh ? '内容总结' : 'Summary')}</Label><Select value={selected || DEFAULT_VALUE} disabled={saving || loading || Boolean(catalogError)} onValueChange={value => { const normalized = value === DEFAULT_VALUE ? '' : value; void saveModels(kind === 'asr' ? normalized : config.asr_model, kind === 'llm' ? normalized : config.llm_model).catch(() => undefined) }}><SelectTrigger className="h-11"><SelectValue /></SelectTrigger><SelectContent><SelectItem value={DEFAULT_VALUE}>{zh ? '跟随服务默认' : 'Use service default'}</SelectItem>{selected && !choices.some(model => model.id === selected) && <SelectItem value={selected} disabled>{selected} · {zh ? '不可用' : 'Unavailable'}</SelectItem>}{choices.map(model => <SelectItem key={model.id} value={model.id} disabled={model.runtimeStatus !== 'available'}>{model.id}{model.runtimeStatus !== 'available' ? (zh ? ' · 不可用' : ' · Unavailable') : ''}</SelectItem>)}</SelectContent></Select></div> })}</div><p className="text-xs leading-5 text-muted-foreground" role="status">{saving ? (zh ? '正在保存…' : 'Saving…') : (zh ? '选择会自动保存，并用于下一次任务。' : 'Selections save automatically for the next task.')}</p></>}
      {config?.mode === 'local' && !compact && <p className="text-sm text-muted-foreground">{zh ? '语音转写与内容总结分开管理，任务中只需选择已经配置好的服务。' : 'Manage speech and summary services separately, then select them in a task.'}</p>}
      {(error || catalogError) && <Alert variant="destructive"><AlertDescription>{error || catalogError}</AlertDescription></Alert>}
    </div></section>
    {config?.mode === 'local' && (compact ? <ProcessingModelPicker /> : <Tabs defaultValue="llm" className="min-w-0"><div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><h3 className="text-xl font-semibold">{zh ? '本地与自定义模型' : 'Local and custom models'}</h3><p className="mt-1 text-sm text-muted-foreground">{zh ? '一次只管理一种服务，配置完成后会出现在会议和资料整理的任务选择器中。' : 'Manage one service type at a time. Saved profiles become available in task pickers.'}</p></div><TabsList className="grid w-full grid-cols-2 sm:w-[320px]"><TabsTrigger value="llm">{zh ? '内容总结' : 'Summary'}</TabsTrigger><TabsTrigger value="stt">{zh ? '语音转写' : 'Speech'}</TabsTrigger></TabsList></div><TabsContent value="llm" className="mt-0"><ModelProfileManager /></TabsContent><TabsContent value="stt" className="mt-0"><STTProfileManager /></TabsContent></Tabs>)}
  </div>
}
