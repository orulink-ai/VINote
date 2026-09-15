import { useEffect, useState } from 'react'
import { apiJson } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { useAppModeStore } from '../../stores/appModeStore'
import { ModelProfileManager } from './ModelProfileManager'
import { STTProfileManager } from './STTProfileManager'

type CloudModel = { id: string; modelType: 'asr' | 'llm'; runtimeStatus: string }

export function ModelSourcePanel({ compact = false }: { compact?: boolean }) {
  const { config, saving, error, setMode, saveModels } = useAppModeStore()
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const [models, setModels] = useState<CloudModel[]>([])
  const [loading, setLoading] = useState(false)
  const [catalogError, setCatalogError] = useState('')
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    if (config?.mode !== 'cloud') return
    let active = true
    setLoading(true)
    setCatalogError('')
    void apiJson<CloudModel[]>('/api/vilab/models').then(result => {
      if (active) setModels(result)
    }).catch(cause => {
      if (active) setCatalogError(cause instanceof Error ? cause.message : (zh ? '无法读取模型列表' : 'Cannot load models'))
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [config?.mode, refresh, zh])

  return <div className="space-y-6">
    <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-[#202020]">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">{compact ? (zh ? '转写与总结模型' : 'Transcription and summary models') : (zh ? '模型配置' : 'Model settings')}</h3>
        {config?.mode === 'cloud' && <button type="button" disabled={loading || saving} onClick={() => setRefresh(value => value + 1)} className="text-xs text-primary-light disabled:opacity-40">{loading ? (zh ? '加载中…' : 'Loading…') : (zh ? '刷新模型' : 'Refresh models')}</button>}
      </div>
      {!compact && <div className="flex gap-2">{(['cloud', 'local'] as const).map(mode => <button key={mode} disabled={saving || !config} aria-pressed={config?.mode === mode}
        className={`rounded-lg border px-4 py-2 text-sm ${config?.mode === mode ? 'border-primary-light bg-primary-light/10 text-primary-light' : 'border-gray-300 dark:border-gray-700'}`}
        onClick={() => void setMode(mode)}>{mode === 'cloud' ? (zh ? '云端模型' : 'Cloud') : (zh ? '本地 / 自定义' : 'Local / custom')}</button>)}</div>}
      {config?.mode === 'cloud' && <>
        <div className="grid gap-4 sm:grid-cols-2">
          {(['asr', 'llm'] as const).map(kind => {
            const selected = kind === 'asr' ? config.asr_model : config.llm_model
            const choices = models.filter(model => model.modelType === kind)
            return <label key={kind} className="block space-y-2 text-sm">
              <span className="text-gray-600 dark:text-gray-300">{kind === 'asr' ? (zh ? '语音转写' : 'Speech recognition') : (zh ? '内容总结' : 'Summary')}</span>
              <select className="w-full rounded-xl border border-gray-200 bg-transparent px-3 py-2.5 dark:border-gray-700" value={selected} disabled={saving || loading || Boolean(catalogError)} onChange={event => {
                void saveModels(kind === 'asr' ? event.target.value : config.asr_model, kind === 'llm' ? event.target.value : config.llm_model).catch(() => undefined)
              }}>
                <option value="">{zh ? '跟随服务默认' : 'Use service default'}</option>
                {selected && !choices.some(model => model.id === selected) && <option value={selected} disabled>{selected} · {zh ? '不可用' : 'Unavailable'}</option>}
                {choices.map(model => <option key={model.id} value={model.id} disabled={model.runtimeStatus !== 'available'}>{model.id}{model.runtimeStatus !== 'available' ? (zh ? ' · 不可用' : ' · Unavailable') : ''}</option>)}
              </select>
            </label>
          })}
        </div>
        <p className="text-xs text-gray-500" role="status">{saving ? (zh ? '正在保存…' : 'Saving…') : (zh ? '选择后自动保存，对下一次生成生效。' : 'Selections save automatically and apply to your next generation.')}</p>
      </>}
      {config?.mode === 'local' && <p className="text-sm text-gray-500">{zh ? '使用本机语音模型，或自行配置模型服务。' : 'Use a local speech model or configure your own service.'}</p>}
      {(error || catalogError) && <p role="alert" className="text-sm text-red-600">{error || catalogError}</p>}
    </section>
    {config?.mode === 'local' && <><ModelProfileManager /><STTProfileManager /></>}
  </div>
}
