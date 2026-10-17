import { modelEligible, modelEligibility, type ModelEligibilityInput } from '../../lib/modelEligibility'
import { recordedAudioDescription, recordedAudioReady, type RecordedAudioModel } from '../../lib/recordedAudioPolicy'
import { frozenModelDisplay, type FrozenModelCatalogEntry } from '../../lib/frozenModelDisplay'
import { useEffect, useId, useState } from 'react'
import { Cloud, RefreshCw, Server } from 'lucide-react'
import { apiJson } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { useAppModeStore } from '../../stores/appModeStore'
import { Alert, AlertDescription } from '../ui/alert'
import { Button } from '../ui/button'
import { Label } from '../ui/label'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '../ui/select'
import { ToggleGroup, ToggleGroupItem } from '../ui/toggle-group'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs'
import { ModelProfileManager } from './ModelProfileManager'
import { STTProfileManager } from './STTProfileManager'
import { ProcessingModelPicker } from './ProcessingModelPicker'

type CloudModel = ModelEligibilityInput & RecordedAudioModel & FrozenModelCatalogEntry
const DEFAULT_VALUE = '__service_default__'

export function ModelSourcePanel({ compact = false }: { compact?: boolean }) {
  const fieldId = useId()
  const { config, saving, error, setMode, saveModels } = useAppModeStore()
  const { locale } = useI18n(); const zh = locale.startsWith('zh')
  const [models, setModels] = useState<CloudModel[]>([]); const [loading, setLoading] = useState(false); const [catalogError, setCatalogError] = useState(''); const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true
    setModels([])
    setCatalogError('')
    if (config?.mode !== 'cloud') { setLoading(false); return }
    setLoading(true)
    void apiJson<CloudModel[]>('/api/vilab/models', { cache: 'no-store' })
      .then(result => {
        if (active) setModels(result)
      })
      .catch(cause => {
        if (active) setCatalogError(cause instanceof Error ? cause.message : (zh ? '无法读取模型列表' : 'Cannot load models'))
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [config?.mode, refresh, zh])
  const unavailableSelection = !loading && !catalogError &&
    ([['asr', config?.asr_model], ['llm', config?.llm_model]] as const).some(([kind, selected]) => selected &&
      !models.some(model => model.id === selected && model.modelType === kind && modelEligible(model)))
  const speechChoice = models.find(model => model.modelType === 'asr' && model.id === config?.asr_model)
  return <div className="grid min-w-0 gap-6">
    <section className="bg-background"><header className="flex items-start justify-between gap-4 border-b py-4"><div><h3 className="font-semibold">{compact ? (zh ? '本次任务使用' : 'Use for this task') : (zh ? '模型运行方式' : 'Model runtime')}</h3><p className="mt-1 text-sm leading-6 text-muted-foreground">{compact ? (zh ? '选择转写与总结所用的服务，修改会用于下一次处理。' : 'Choose the services used for transcription and summary.') : (zh ? '决定任务使用部署服务，还是连接你管理的本地与兼容模型。' : 'Use deployed services or connect your managed local and compatible models.')}</p></div>{config?.mode === 'cloud' && <Button variant="ghost" size="sm" disabled={loading || saving} onClick={() => setRefresh(value => value + 1)}><RefreshCw className={loading ? 'animate-spin' : ''} />{zh ? '刷新' : 'Refresh'}</Button>}</header><div className="grid gap-5 py-5">
      {!compact && <ToggleGroup type="single" value={config?.mode} onValueChange={value => { if (value === 'cloud' || value === 'local') void setMode(value) }} className="grid grid-cols-2"><ToggleGroupItem value="cloud" disabled={saving || !config} className="gap-2"><Cloud className="h-4 w-4" />{zh ? '云端模型' : 'Cloud'}</ToggleGroupItem><ToggleGroupItem value="local" disabled={saving || !config} className="gap-2"><Server className="h-4 w-4" />{zh ? '本地 / 自定义' : 'Local / custom'}</ToggleGroupItem></ToggleGroup>}
      {config?.mode === 'cloud' && <><div className={compact ? 'grid gap-4' : 'grid min-w-0 gap-4 xl:grid-cols-2'}>{(['asr', 'llm'] as const).map(kind => { const selected = kind === 'asr' ? config.asr_model : config.llm_model; const choices = models.filter(model => model.modelType === kind); return <div key={kind} className="grid min-w-0 gap-2"><Label htmlFor={`${fieldId}-${kind}`}>{kind === 'asr' ? (zh ? '语音转写' : 'Speech recognition') : (zh ? '内容总结 / 画面分析' : 'Summary / image analysis')}</Label><Select value={selected || DEFAULT_VALUE} disabled={saving || loading || Boolean(catalogError)} onValueChange={value => { const normalized = value === DEFAULT_VALUE ? '' : value; if (normalized && !choices.some(model => model.id === normalized && modelEligible(model) && (kind !== 'asr' || recordedAudioReady(model)))) return; void saveModels(kind === 'asr' ? normalized : config.asr_model, kind === 'llm' ? normalized : config.llm_model).catch(() => undefined) }}><SelectTrigger id={`${fieldId}-${kind}`} aria-describedby={kind === 'asr' && speechChoice ? `${fieldId}-asr-help` : undefined} className="h-11 w-full min-w-0 overflow-hidden"><SelectValue className="truncate" /></SelectTrigger><SelectContent><SelectGroup><SelectItem value={DEFAULT_VALUE}>{zh ? '跟随服务默认' : 'Use service default'}</SelectItem>{selected && !choices.some(model => model.id === selected) && <SelectItem value={selected} disabled>{loading ? (zh ? '正在读取原选择…' : 'Loading saved selection…') : (zh ? '原选择暂不可用' : 'Saved selection unavailable')}</SelectItem>}{choices.map(model => <SelectItem key={model.id} value={model.id} disabled={!modelEligible(model) || (kind === 'asr' && !recordedAudioReady(model))}>{kind === 'asr' ? frozenModelDisplay([model], model.id, 'asr') : model.name || model.providerModel || model.id}{kind === 'asr' ? ` · ${recordedAudioDescription(model, zh)}` : ''}{modelEligibility(model) === 'retryable' ? (zh ? ' · 可重试' : ' · Retry allowed') : !modelEligible(model) ? (zh ? ' · 不可用' : ' · Unavailable') : ''}</SelectItem>)}</SelectGroup></SelectContent></Select></div> })}</div><p className="text-xs leading-5 text-muted-foreground" role="status">{saving ? (zh ? '正在保存…' : 'Saving…') : (zh ? '选择会自动保存，并用于下一次任务。画面分析优先使用所选模型；需模型支持图片输入。' : 'Selections save automatically for the next task.')}</p></>}
      {config?.mode === 'cloud' && speechChoice && <p id={`${fieldId}-asr-help`} className="text-sm leading-6 text-muted-foreground" role="status">{recordedAudioDescription(speechChoice, zh)}{recordedAudioReady(speechChoice) ? (zh ? '。长录音将分段处理，仍使用同一个模型。' : '. Long recordings use the same model across all parts.') : ''}</p>}
      {config?.mode === 'local' && !compact && <p className="text-sm text-muted-foreground">{zh ? '语音转写与内容总结分开管理，任务中只需选择已经配置好的服务。' : 'Manage speech and summary services separately, then select them in a task.'}</p>}
      {config?.mode === 'cloud' && unavailableSelection && <Alert><AlertDescription>{zh ? '原选择已不可用，已保留且不会自动切换。请刷新状态或明确选择其他模型。' : 'The unavailable selection is retained. Refresh its status or explicitly choose another model.'}</AlertDescription></Alert>}
      {config?.mode === 'cloud' && models.some(model => model.id === (model.modelType === 'asr' ? config.asr_model : config.llm_model) && modelEligibility(model) === 'retryable') && <Alert><AlertDescription>{zh ? '原模型可重试，仍使用原选择。开始任务后才会尝试，尚未确认服务恢复。' : 'Retry is allowed using the saved model. Recovery is not yet confirmed.'}</AlertDescription></Alert>}{(error || catalogError) && <Alert variant="destructive"><AlertDescription>{error || catalogError}</AlertDescription></Alert>}
    </div></section>
    {config?.mode === 'local' && (compact ? <ProcessingModelPicker /> : <Tabs defaultValue="llm" className="min-w-0"><div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><h3 className="text-xl font-semibold">{zh ? '本地与自定义模型' : 'Local and custom models'}</h3><p className="mt-1 text-sm text-muted-foreground">{zh ? '一次只管理一种服务，配置完成后会出现在会议和资料整理的任务选择器中。' : 'Manage one service type at a time. Saved profiles become available in task pickers.'}</p></div><TabsList className="grid w-full grid-cols-2 sm:w-[320px]"><TabsTrigger value="llm">{zh ? '内容总结 / 画面分析' : 'Summary / image analysis'}</TabsTrigger><TabsTrigger value="stt">{zh ? '语音转写' : 'Speech'}</TabsTrigger></TabsList></div><TabsContent value="llm" className="mt-0"><ModelProfileManager /></TabsContent><TabsContent value="stt" className="mt-0"><STTProfileManager /></TabsContent></Tabs>)}
  </div>
}
