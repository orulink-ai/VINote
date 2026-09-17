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
import { ModelProfileManager } from './ModelProfileManager'
import { STTProfileManager } from './STTProfileManager'

type CloudModel = { id: string; modelType: 'asr' | 'llm'; runtimeStatus: string }
const DEFAULT_VALUE = '__service_default__'

export function ModelSourcePanel({ compact = false }: { compact?: boolean }) {
  const { config, saving, error, setMode, saveModels } = useAppModeStore()
  const { locale } = useI18n(); const zh = locale.startsWith('zh')
  const [models, setModels] = useState<CloudModel[]>([]); const [loading, setLoading] = useState(false); const [catalogError, setCatalogError] = useState(''); const [refresh, setRefresh] = useState(0)
  useEffect(() => { if (config?.mode !== 'cloud') return; let active = true; setLoading(true); setCatalogError(''); void apiJson<CloudModel[]>('/api/vilab/models').then(result => { if (active) setModels(result) }).catch(cause => { if (active) setCatalogError(cause instanceof Error ? cause.message : (zh ? '无法读取模型列表' : 'Cannot load models')) }).finally(() => { if (active) setLoading(false) }); return () => { active = false } }, [config?.mode, refresh, zh])
  return <div className="grid gap-6">
    <section className="border"><header className="flex items-start justify-between gap-4 border-b p-5"><div><h3 className="font-semibold">{compact ? (zh ? '转写与总结模型' : 'Transcription and summary models') : (zh ? '模型运行方式' : 'Model runtime')}</h3><p className="mt-1 text-sm text-muted-foreground">{zh ? '云端模式直接使用部署模型，本地模式使用你自己的模型服务。' : 'Use deployed cloud models or connect your own local services.'}</p></div>{config?.mode === 'cloud' && <Button variant="ghost" size="sm" disabled={loading || saving} onClick={() => setRefresh(value => value + 1)}><RefreshCw className={loading ? 'animate-spin' : ''} />{zh ? '刷新' : 'Refresh'}</Button>}</header><div className="grid gap-5 p-5">
      {!compact && <ToggleGroup type="single" value={config?.mode} onValueChange={value => { if (value === 'cloud' || value === 'local') void setMode(value) }} className="grid grid-cols-2"><ToggleGroupItem value="cloud" disabled={saving || !config} className="gap-2"><Cloud className="h-4 w-4" />{zh ? '云端模型' : 'Cloud'}</ToggleGroupItem><ToggleGroupItem value="local" disabled={saving || !config} className="gap-2"><Server className="h-4 w-4" />{zh ? '本地 / 自定义' : 'Local / custom'}</ToggleGroupItem></ToggleGroup>}
      {config?.mode === 'cloud' && <><div className="grid gap-4 sm:grid-cols-2">{(['asr', 'llm'] as const).map(kind => { const selected = kind === 'asr' ? config.asr_model : config.llm_model; const choices = models.filter(model => model.modelType === kind); return <div key={kind} className="grid gap-2"><Label>{kind === 'asr' ? (zh ? '语音转写' : 'Speech recognition') : (zh ? '内容总结' : 'Summary')}</Label><Select value={selected || DEFAULT_VALUE} disabled={saving || loading || Boolean(catalogError)} onValueChange={value => { const normalized = value === DEFAULT_VALUE ? '' : value; void saveModels(kind === 'asr' ? normalized : config.asr_model, kind === 'llm' ? normalized : config.llm_model).catch(() => undefined) }}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value={DEFAULT_VALUE}>{zh ? '跟随服务默认' : 'Use service default'}</SelectItem>{selected && !choices.some(model => model.id === selected) && <SelectItem value={selected} disabled>{selected} · {zh ? '不可用' : 'Unavailable'}</SelectItem>}{choices.map(model => <SelectItem key={model.id} value={model.id} disabled={model.runtimeStatus !== 'available'}>{model.id}{model.runtimeStatus !== 'available' ? (zh ? ' · 不可用' : ' · Unavailable') : ''}</SelectItem>)}</SelectContent></Select></div> })}</div><p className="text-xs text-muted-foreground" role="status">{saving ? (zh ? '正在保存…' : 'Saving…') : (zh ? '选择会自动保存，并用于下一次任务。' : 'Selections save automatically for the next task.')}</p></>}
      {config?.mode === 'local' && <p className="text-sm text-muted-foreground">{zh ? '配置本机语音模型或兼容的模型 API。' : 'Configure a local speech model or compatible model API.'}</p>}
      {(error || catalogError) && <Alert variant="destructive"><AlertDescription>{error || catalogError}</AlertDescription></Alert>}
    </div></section>
    {config?.mode === 'local' && <><ModelProfileManager /><STTProfileManager /></>}
  </div>
}
