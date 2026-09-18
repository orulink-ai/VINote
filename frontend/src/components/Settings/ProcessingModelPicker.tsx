import { useEffect } from 'react'
import { ArrowUpRight, Bot, Radio } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useI18n } from '../../lib/i18n'
import { useModelProfileStore } from '../../stores/modelProfileStore'
import { useSTTProfileStore } from '../../stores/sttProfileStore'
import { Button } from '../ui/button'
import { Label } from '../ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select'

const SYSTEM_DEFAULT = '__system_default__'

export function ProcessingModelPicker() {
  const navigate = useNavigate()
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const modelProfiles = useModelProfileStore(state => state.profiles)
  const modelLoading = useModelProfileStore(state => state.loading)
  const loadModelProfiles = useModelProfileStore(state => state.loadProfiles)
  const selectedModelProfileId = useModelProfileStore(state => state.selectedProfileId)
  const selectModelProfile = useModelProfileStore(state => state.selectProfile)
  const sttProfiles = useSTTProfileStore(state => state.profiles)
  const sttLoading = useSTTProfileStore(state => state.loading)
  const loadSTTProfiles = useSTTProfileStore(state => state.loadProfiles)
  const selectedSTTProfileId = useSTTProfileStore(state => state.selectedProfileId)
  const selectSTTProfile = useSTTProfileStore(state => state.selectProfile)

  useEffect(() => {
    if (!modelProfiles.length && !modelLoading) void loadModelProfiles()
    if (!sttProfiles.length && !sttLoading) void loadSTTProfiles()
  }, [loadModelProfiles, loadSTTProfiles, modelLoading, modelProfiles.length, sttLoading, sttProfiles.length])

  const models = modelProfiles.filter(profile => profile.isActive)
  const speechModels = sttProfiles.filter(profile => profile.isActive)
  const selectedModel = models.find(profile => profile.id === selectedModelProfileId)
  const selectedSpeech = speechModels.find(profile => profile.id === selectedSTTProfileId)

  return <div className="grid gap-5">
    <div className="grid gap-4">
      <div className="rounded-2xl border bg-card p-4">
        <div className="mb-4 flex items-center gap-3"><span className="grid size-9 place-items-center rounded-xl bg-muted"><Radio className="size-4" /></span><div><Label htmlFor="task-stt-profile">{zh ? '语音转写' : 'Speech recognition'}</Label><p className="mt-0.5 text-xs text-muted-foreground">{zh ? '用于生成逐字稿' : 'Creates the transcript'}</p></div></div>
        <Select value={selectedSTTProfileId || SYSTEM_DEFAULT} onValueChange={value => selectSTTProfile(value === SYSTEM_DEFAULT ? '' : value)}>
          <SelectTrigger id="task-stt-profile" className="h-11"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={SYSTEM_DEFAULT}>{zh ? '跟随后端默认' : 'Backend default'}</SelectItem>{speechModels.map(profile => <SelectItem key={profile.id} value={profile.id}>{profile.name}{profile.isDefault ? (zh ? ' · 默认' : ' · Default') : ''}</SelectItem>)}</SelectContent>
        </Select>
        <p className="mt-3 truncate text-xs text-muted-foreground">{selectedSpeech ? (selectedSpeech.modelName || selectedSpeech.provider) : (zh ? '使用系统当前默认配置' : 'Uses the current system default')}</p>
      </div>

      <div className="rounded-2xl border bg-card p-4">
        <div className="mb-4 flex items-center gap-3"><span className="grid size-9 place-items-center rounded-xl bg-muted"><Bot className="size-4" /></span><div><Label htmlFor="task-llm-profile">{zh ? '内容总结' : 'Summary'}</Label><p className="mt-0.5 text-xs text-muted-foreground">{zh ? '用于生成会议纪要' : 'Creates meeting notes'}</p></div></div>
        <Select value={selectedModelProfileId || SYSTEM_DEFAULT} onValueChange={value => selectModelProfile(value === SYSTEM_DEFAULT ? '' : value)}>
          <SelectTrigger id="task-llm-profile" className="h-11"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={SYSTEM_DEFAULT}>{zh ? '跟随后端默认' : 'Backend default'}</SelectItem>{models.map(profile => <SelectItem key={profile.id} value={profile.id}>{profile.name}{profile.isDefault ? (zh ? ' · 默认' : ' · Default') : ''}</SelectItem>)}</SelectContent>
        </Select>
        <p className="mt-3 truncate text-xs text-muted-foreground">{selectedModel ? selectedModel.modelName : (zh ? '使用系统当前默认配置' : 'Uses the current system default')}</p>
      </div>
    </div>

    <div className="flex items-center justify-between gap-4 rounded-2xl bg-muted/45 px-4 py-3"><p className="text-xs leading-5 text-muted-foreground">{zh ? '这里仅选择本次任务使用的配置。新增、测试和密钥管理在设置中完成。' : 'Choose task profiles here. Create and manage them in Settings.'}</p><Button type="button" variant="ghost" className="shrink-0" onClick={() => navigate('/settings?tab=models')}><span>{zh ? '管理配置' : 'Manage'}</span><ArrowUpRight className="size-4" /></Button></div>
  </div>
}
