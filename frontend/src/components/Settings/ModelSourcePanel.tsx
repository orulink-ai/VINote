import { modelEligible, modelEligibility, type ModelEligibilityInput } from '../../lib/modelEligibility'
import { meetingReady, recordedAudioDescription, type RecordedAudioModel } from '../../lib/recordedAudioPolicy'
import { frozenModelDisplay, type FrozenModelCatalogEntry } from '../../lib/frozenModelDisplay'
import { useEffect, useId, useState } from 'react'
import { RefreshCw, Server } from 'lucide-react'
import { apiJson } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { useAppModeStore } from '../../stores/appModeStore'
import { Alert, AlertDescription } from '../ui/alert'
import { Button } from '../ui/button'
import { Label } from '../ui/label'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '../ui/select'
import { modelSourceScope } from '@/lib/modelSourceIdentity'

type CloudModel = ModelEligibilityInput & RecordedAudioModel & FrozenModelCatalogEntry

export function ModelSourcePanel({ compact = false }: { compact?: boolean }) {
  const fieldId = useId()
  const { config, saving, error, saveModels: saveSelectedModels } = useAppModeStore()
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
          <h3 className="text-base font-medium">{compact ? (zh ? '本次任务使用' : 'Use for this task') : (zh ? '公网服务模型' : 'Public service models')}</h3>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{compact
            ? (zh ? '为会议转写与纪要选择模型，修改用于下一次处理' : 'Choose models for meeting transcription and notes. Changes apply to the next run.')
            : (zh ? '会议转写与纪要仅使用固定公网服务，请明确选择下一次处理使用的模型' : 'Meeting transcription and notes use the fixed public service. Choose models explicitly for the next run.')}</p>
        </div>
        {config?.mode === 'cloud' && <Button variant="outline" size="sm" className="shrink-0" disabled={loading || saving} onClick={() => setRefresh(value => value + 1)}>
          <RefreshCw className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />{loading ? (zh ? '正在读取' : 'Loading') : (zh ? '刷新' : 'Refresh')}
        </Button>}
      </header>

      <div className="grid gap-5 py-5">
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
              const choices = models.filter(model => model.modelType === kind && (kind !== 'asr' || meetingReady(model).ready))
              return <div key={kind} className="grid min-w-0 gap-2">
                <Label htmlFor={`${fieldId}-${kind}`}>{kind === 'asr' ? (zh ? '语音转写' : 'Speech recognition') : (zh ? '内容总结 / 画面分析' : 'Summary / image analysis')}</Label>
                <Select value={selected} disabled={saving || loading || Boolean(catalogError) || choices.length === 0} onValueChange={value => {
                  const normalized = value
                  if (!choices.some(model => model.id === normalized && modelEligible(model) &&
                    (kind !== 'asr' || meetingReady(model).ready))) return
                  void saveModels(kind === 'asr' ? normalized : selectedAsr, kind === 'llm' ? normalized : selectedLlm).catch(() => undefined)
                }}>
                  <SelectTrigger id={`${fieldId}-${kind}`} aria-describedby={kind === 'asr' && speechReadiness?.ready ? `${fieldId}-asr-help` : undefined} className="h-11 w-full min-w-0 overflow-hidden">
                    <SelectValue className="truncate" placeholder={zh ? '请选择模型' : 'Choose a model'} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {selected && !choices.some(model => model.id === selected) && <SelectItem value={selected} disabled>
                        {kind === 'asr' && speechChoice ? `${frozenModelDisplay([speechChoice], selected, 'asr')} · ${zh ? '原选择暂不可用' : 'Saved selection unavailable'}` : loading ? (zh ? '正在读取原选择' : 'Loading saved selection') : (zh ? '原选择暂不可用' : 'Saved selection unavailable')}
                      </SelectItem>}
                      {choices.map(model => {
                        const label = kind === 'asr' ? frozenModelDisplay([model], model.id, 'asr') : model.name || model.providerModel || model.id
                        const detail = kind === 'asr' ? recordedAudioDescription(model, zh) : ''
                        const state = modelEligibility(model) === 'retryable' ? (zh ? '可重试' : 'Retry allowed') : !modelEligible(model) ? (zh ? '不可用' : 'Unavailable') : ''
                        return <SelectItem key={model.id} value={model.id} disabled={!modelEligible(model)}>
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

          {!loading && !catalogError && !models.some(model => model.modelType === 'asr' && meetingReady(model).ready) && <Alert><AlertDescription>{zh
            ? '公网服务暂未提供支持整段识别、说话人分离和时间戳的会议模型。请稍后刷新或联系管理员。原选择已保留，不会自动替换。'
            : 'The public service does not currently offer a meeting model with whole-file recognition, speaker diarization and timestamps. Refresh later or contact your administrator. Your saved selection is retained and will not be replaced automatically.'}</AlertDescription></Alert>}
          {!loading && !catalogError && !models.some(model => model.modelType === 'llm' && modelEligible(model)) && <p role="status" className="text-sm text-muted-foreground">{zh ? '暂无可用总结模型，请检查公网服务配置后刷新。' : 'No summary model is available. Check the public service configuration and refresh.'}</p>}

          {speechChoice && speechReadiness?.ready && <div id={`${fieldId}-asr-help`} className="max-w-2xl text-sm leading-6 text-muted-foreground" role="status">
            {recordedAudioDescription(speechChoice, zh)}
            <p className="mt-1">{zh ? '会议录音整段提交，结果包含说话人与发言时间。' : 'Each meeting is submitted as one recording and returns speakers and timings.'}</p>
          </div>}

          <p className="max-w-2xl text-xs leading-5 text-muted-foreground" role="status">{saving
            ? (zh ? '正在保存' : 'Saving')
            : (zh ? '选择自动保存，用于下一次生成' : 'Selections save automatically for the next run')}</p>

          {meetingBlockedSpeech && <Alert><AlertDescription>{zh
            ? `原语音选择不满足会议转写要求：${speechReadiness?.reason}。已保留原选择，请明确选择可用会议模型。`
            : `The saved speech model does not meet meeting requirements: ${speechReadiness?.reason}. Choose an available meeting model explicitly.`}</AlertDescription></Alert>}
        </>}

        {config?.mode === 'local' && <Alert variant="destructive"><AlertDescription>{zh
          ? '当前配置仍为旧版本地模式。VINote 仅使用固定公网服务，请更新服务并重新加载设置。'
          : 'This configuration still uses legacy local mode. VINote requires the fixed public service. Update the service and reload settings.'}</AlertDescription></Alert>}

        {config?.mode === 'cloud' && unavailableSelection && <Alert><AlertDescription>{zh
          ? '原选择已不可用，已保留且不会自动切换。请刷新状态或明确选择其他模型。'
          : 'The unavailable selection is retained. Refresh its status or explicitly choose another model.'}</AlertDescription></Alert>}
        {config?.mode === 'cloud' && models.some(model => model.id === (model.modelType === 'asr' ? selectedAsr : selectedLlm) && modelEligibility(model) === 'retryable' && (model.modelType !== 'asr' || meetingReady(model).ready)) && <Alert><AlertDescription>{zh
          ? '原模型可重试，仍使用原选择。开始任务后才会尝试，尚未确认服务恢复。'
          : 'Retry is allowed using the saved model. Recovery is not yet confirmed.'}</AlertDescription></Alert>}
        {(error || catalogError) && <Alert variant="destructive"><AlertDescription>{error || catalogError}{catalogError && <p className="mt-1">{zh ? '无法确认会议模型能力。请检查固定公网服务是否可用、是否已升级，然后刷新。' : 'Meeting capabilities could not be verified. Check the fixed public service and its upgrade status, then refresh.'}</p>}</AlertDescription></Alert>}
      </div>
    </section>

  </div>
}
