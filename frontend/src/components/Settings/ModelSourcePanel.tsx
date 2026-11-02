import { modelEligible, modelEligibility, type ModelEligibilityInput } from '../../lib/modelEligibility'
import { meetingReady, recordedAudioDescription, transcriptionReady, type RecordedAudioModel } from '../../lib/recordedAudioPolicy'
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
import { modelSourceScope } from '@/lib/modelSourceIdentity'

type CloudModel = ModelEligibilityInput & RecordedAudioModel & FrozenModelCatalogEntry
const DEFAULT_VALUE = '__service_default__'

export function ModelSourcePanel({ compact = false }: { compact?: boolean }) {
  const fieldId = useId()
  const { config, saving, error, setMode, saveModels: saveSelectedModels } = useAppModeStore()
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const [catalog, setCatalog] = useState<{ key: string; models: CloudModel[] }>({ key: '', models: [] })
  const [fetching, setLoading] = useState(false)
  const [catalogError, setCatalogError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const sourceKey = JSON.stringify([config?.mode, config?.server_url])
  const models = catalog.key === sourceKey ? catalog.models : []
  const loading = fetching || config?.mode === 'cloud' && catalog.key !== sourceKey
  const saveModels = (asr: string, llm: string) => {
    if (typeof useAppModeStore.getState === 'function') {
      const selected = useAppModeStore.getState().config
      if (sourceKey !== JSON.stringify([selected?.mode, selected?.server_url])) return Promise.resolve()
    }
    return saveSelectedModels(asr, llm)
  }

  useEffect(() => {
    let active = true
    const ownerActive = modelSourceScope()
    const current = () => active && ownerActive() && (typeof useAppModeStore.getState !== 'function' || sourceKey === JSON.stringify([
      useAppModeStore.getState().config?.mode, useAppModeStore.getState().config?.server_url,
    ]))
    setCatalog({ key: sourceKey, models: [] })
    setCatalogError('')
    if (config?.mode !== 'cloud') { setLoading(false); return }
    setLoading(true)
    void apiJson<CloudModel[]>('/api/vilab/models', { cache: 'no-store' })
      .then(result => {
        if (current()) setCatalog({ key: sourceKey, models: result })
      })
      .catch(cause => {
        if (current()) setCatalogError(cause instanceof Error ? cause.message : (zh ? '无法读取模型列表' : 'Cannot load models'))
      })
      .finally(() => { if (current()) setLoading(false) })
    return () => { active = false }
  }, [sourceKey, refresh, zh])

  const selectedAsr = config?.asr_model || ''
  const selectedLlm = config?.llm_model || ''
  const speechChoice = models.find(model => model.modelType === 'asr' && model.id === selectedAsr)
  const speechReadiness = speechChoice ? meetingReady(speechChoice) : null
  const unavailableSelection = !loading && !catalogError &&
    ([['asr', selectedAsr], ['llm', selectedLlm]] as const).some(([kind, selected]) => selected &&
      !models.some(model => model.id === selected && model.modelType === kind && modelEligible(model)))
  const meetingBlockedSpeech = Boolean(selectedAsr && speechChoice && speechReadiness && !speechReadiness.ready)

  return <div className="grid min-w-0 gap-6">
    <section className="min-w-0 border-b">
      <header className="flex flex-col gap-4 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="text-base font-medium">{compact ? (zh ? '本次任务使用' : 'Use for this task') : (zh ? '模型运行方式' : 'Model runtime')}</h3>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{compact
            ? (zh ? '为会议转写与纪要选择模型，修改用于下一次处理' : 'Choose models for meeting transcription and notes. Changes apply to the next run.')
            : (zh ? '会议录音使用固定服务部署，也可以改用本机或兼容服务' : 'Meeting recordings use a fixed deployment, or your own local and compatible services')}</p>
        </div>
        {config?.mode === 'cloud' && <Button variant="outline" size="sm" className="shrink-0" disabled={loading || saving} onClick={() => setRefresh(value => value + 1)}>
          <RefreshCw className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />{loading ? (zh ? '正在读取' : 'Loading') : (zh ? '刷新' : 'Refresh')}
        </Button>}
      </header>

      <div className="grid gap-5 py-5">
        {!compact && <ToggleGroup type="single" value={config?.mode} onValueChange={value => {
          if (value === 'cloud' || value === 'local') void setMode(value)
        }} className="grid w-full max-w-sm grid-cols-2">
          <ToggleGroupItem value="cloud" disabled={saving || !config} className="gap-2"><Cloud className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />{zh ? '服务模型' : 'Service models'}</ToggleGroupItem>
          <ToggleGroupItem value="local" disabled={saving || !config} className="gap-2"><Server className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />{zh ? '本地 / 自定义' : 'Local / custom'}</ToggleGroupItem>
        </ToggleGroup>}

        {config?.mode === 'cloud' && <>
          <div className="flex flex-col gap-2 border-y py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Server className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
              <span>{zh ? '模型服务' : 'Model service'}</span>
            </div>
            <div className="min-w-0 sm:text-right">
              <p className="truncate font-mono text-xs text-foreground">{config.server_url || (zh ? '由服务端固定' : 'Fixed by the service')}</p>
              <p className="mt-1 text-xs text-muted-foreground">{zh ? '公网地址，不可编辑' : 'Public address, read only'}</p>
            </div>
          </div>

          <div className={compact ? 'grid gap-4' : 'grid min-w-0 gap-4 xl:grid-cols-2'}>
            {(['asr', 'llm'] as const).map(kind => {
              const selected = kind === 'asr' ? selectedAsr : selectedLlm
              const choices = models.filter(model => model.modelType === kind)
              return <div key={kind} className="grid min-w-0 gap-2">
                <Label htmlFor={`${fieldId}-${kind}`}>{kind === 'asr' ? (zh ? '语音转写' : 'Speech recognition') : (zh ? '内容总结 / 画面分析' : 'Summary / image analysis')}</Label>
                <Select value={selected || DEFAULT_VALUE} disabled={saving || loading || Boolean(catalogError)} onValueChange={value => {
                  const normalized = value === DEFAULT_VALUE ? '' : value
                  if (normalized && !choices.some(model => model.id === normalized && modelEligible(model) &&
                    (kind !== 'asr' || transcriptionReady(model)))) return
                  void saveModels(kind === 'asr' ? normalized : selectedAsr, kind === 'llm' ? normalized : selectedLlm).catch(() => undefined)
                }}>
                  <SelectTrigger id={`${fieldId}-${kind}`} aria-describedby={kind === 'asr' && speechChoice ? `${fieldId}-asr-help` : undefined} className="h-11 w-full min-w-0 overflow-hidden">
                    <SelectValue className="truncate" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value={DEFAULT_VALUE}>{zh ? '跟随服务默认' : 'Use service default'}</SelectItem>
                      {selected && !choices.some(model => model.id === selected) && <SelectItem value={selected} disabled>
                        {loading ? (zh ? '正在读取原选择' : 'Loading saved selection') : (zh ? '原选择暂不可用' : 'Saved selection unavailable')}
                      </SelectItem>}
                      {choices.map(model => {
                        const label = kind === 'asr' ? frozenModelDisplay([model], model.id, 'asr') : model.name || model.providerModel || model.id
                        const detail = kind === 'asr' ? recordedAudioDescription(model, zh) : ''
                        const state = modelEligibility(model) === 'retryable' ? (zh ? '可重试' : 'Retry allowed') : !modelEligible(model) ? (zh ? '不可用' : 'Unavailable') : ''
                        return <SelectItem key={model.id} value={model.id} disabled={!modelEligible(model) || (kind === 'asr' && !transcriptionReady(model))}>
                          <span className="truncate">{label}</span>
                          {(detail || state) && <span className="text-muted-foreground"> · {[detail, state].filter(Boolean).join(' · ')}</span>}
                        </SelectItem>
                      })}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>
            })}
          </div>

          {speechChoice && <div id={`${fieldId}-asr-help`} className="max-w-2xl text-sm leading-6 text-muted-foreground" role="status">
            {recordedAudioDescription(speechChoice, zh)}
            {speechReadiness?.ready
              ? <p className="mt-1">{zh ? '会议录音整段提交，结果包含说话人与发言时间。' : 'Each meeting is submitted as one recording and returns speakers and timings.'}</p>
              : transcriptionReady(speechChoice) && <p className="mt-1">{zh ? '可继续用于录音转写；会议纪要需要上面这类整段识别模型。' : 'Still usable for recording transcription; meeting notes need a whole-file model like the one above.'}</p>}
          </div>}

          <p className="max-w-2xl text-xs leading-5 text-muted-foreground" role="status">{saving
            ? (zh ? '正在保存' : 'Saving')
            : (zh ? '选择自动保存，用于下一次生成' : 'Selections save automatically for the next run')}</p>

          {meetingBlockedSpeech && <Alert><AlertDescription>{zh
            ? `所选语音模型可用于录音转写，暂不能用于会议纪要：${speechReadiness?.reason}。会议提交前会再次确认。`
            : `This speech model handles recordings but not meeting notes: ${speechReadiness?.reason}. Submission will re-check it.`}</AlertDescription></Alert>}
        </>}

        {config?.mode === 'local' && !compact && <p className="text-sm leading-6 text-muted-foreground">{zh
          ? '语音转写与内容总结分开管理，任务中只需选择已经配置好的服务'
          : 'Manage speech and summary services separately, then select them in a task'}</p>}

        {config?.mode === 'cloud' && unavailableSelection && <Alert><AlertDescription>{zh
          ? '原选择已不可用，已保留且不会自动切换。请刷新状态或明确选择其他模型。'
          : 'The unavailable selection is retained. Refresh its status or explicitly choose another model.'}</AlertDescription></Alert>}
        {config?.mode === 'cloud' && models.some(model => model.id === (model.modelType === 'asr' ? selectedAsr : selectedLlm) && modelEligibility(model) === 'retryable') && <Alert><AlertDescription>{zh
          ? '原模型可重试，仍使用原选择。开始任务后才会尝试，尚未确认服务恢复。'
          : 'Retry is allowed using the saved model. Recovery is not yet confirmed.'}</AlertDescription></Alert>}
        {(error || catalogError) && <Alert variant="destructive"><AlertDescription>{error || catalogError}</AlertDescription></Alert>}
      </div>
    </section>

    {config?.mode === 'local' && (compact ? <ProcessingModelPicker /> : <Tabs defaultValue="llm" className="min-w-0">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h3 className="text-xl font-medium">{zh ? '本地与自定义模型' : 'Local and custom models'}</h3>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{zh ? '一次管理一种服务，保存后可在任务中选择' : 'Manage one service type at a time. Saved profiles become available in task pickers.'}</p>
        </div>
        <TabsList className="grid w-full grid-cols-2 sm:w-[320px]">
          <TabsTrigger value="llm">{zh ? '内容总结 / 画面分析' : 'Summary / image analysis'}</TabsTrigger>
          <TabsTrigger value="stt">{zh ? '语音转写' : 'Speech'}</TabsTrigger>
        </TabsList>
      </div>
      <TabsContent value="llm" className="mt-0"><ModelProfileManager /></TabsContent>
      <TabsContent value="stt" className="mt-0"><STTProfileManager /></TabsContent>
    </Tabs>)}
  </div>
}
