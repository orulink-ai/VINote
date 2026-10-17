import { useEffect, useRef, useState } from 'react'
import { apiJson } from '@/lib/api'
import { frozenModelDisplay, sameModelCatalogSource, type FrozenModelCatalogEntry } from '@/lib/frozenModelDisplay'
import { useAuthStore } from '@/stores/authStore'

type Models = { mode: string; origin: string; asr_model: string; llm_model: string }

/** Reads names for one confirmation context; cannot select or dispatch a model. */
export function FrozenModelDisplay({ owner, contextKey, models }: { owner: string; contextKey: string; models: Models }) {
  const currentOwner = useAuthStore(state => state.user?.id)
  const sequence = useRef(0)
  const binding = JSON.stringify([owner, contextKey, models.mode, models.origin, models.asr_model, models.llm_model])
  const [catalog, setCatalog] = useState<{ binding: string; entries: FrozenModelCatalogEntry[] } | null>(null)
  useEffect(() => useAuthStore.subscribe((next, previous) => {
    if (next.user?.id !== previous.user?.id) {
      sequence.current++
      setCatalog(null)
    }
  }), [])
  useEffect(() => {
    const request = ++sequence.current
    let mounted = true
    setCatalog(null)
    if (currentOwner !== owner || models.mode !== 'cloud') return () => { mounted = false }
    const active = () => mounted && request === sequence.current && useAuthStore.getState().user?.id === owner
    void Promise.all([
      apiJson<{ server_url?: string }>('/api/vilab/config', { cache: 'no-store' }),
      apiJson<unknown>('/api/vilab/models', { cache: 'no-store' }),
    ]).then(([config, result]) => {
      if (!active() || !sameModelCatalogSource(config.server_url, models.origin) || !Array.isArray(result)) return
      const entries = result.filter((value): value is FrozenModelCatalogEntry => value != null && typeof value === 'object' && typeof value.id === 'string' && (value.modelType === 'asr' || value.modelType === 'llm'))
      setCatalog({ binding, entries })
    }).catch(() => { /* Missing names do not change availability, confirmation or frozen selection. */ })
    return () => { mounted = false; sequence.current++ }
  }, [binding, currentOwner, owner, models.mode, models.origin])
  const entries = currentOwner === owner && catalog?.binding === binding ? catalog.entries : []
  return <>
    <div><dt>模型服务</dt><dd>{models.mode === 'cloud' ? '云端模型' : models.mode === 'local' ? '本地 / 自定义模型' : '原任务模型服务（模式暂不可读取）'}</dd></div>
    <div><dt>转写模型</dt><dd className="break-words">{frozenModelDisplay(entries, models.asr_model, 'asr')}</dd></div>
    <div><dt>总结模型</dt><dd className="break-words">{frozenModelDisplay(entries, models.llm_model, 'llm')}</dd></div>
  </>
}
