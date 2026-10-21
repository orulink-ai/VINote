import { useEffect, useId, useRef, useState } from 'react'
import { useAppModeStore, type ModelSourceConfig } from '@/stores/appModeStore'
import { useI18n } from '@/lib/i18n'
import { checkVILabConnection, listVILabConnections, modelConnectionScope, onModelConnectionIdentityChange, type VILabConnection, type VILabConnectionCheck, type VILabConnectionDraft } from '@/lib/vilabConnections'
import { modelEligible } from '@/lib/modelEligibility'
import { recordedAudioReady } from '@/lib/recordedAudioPolicy'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const NEW = '__new__'; const DEFAULT = '__default_model__'
const ACCOUNT_ORIGINS = new Set(['http://192.168.1.143:9876', 'https://api.orulink.ai'])

export function VILabConnectionSettings({ config }: { config: ModelSourceConfig }) {
  const { locale } = useI18n(); const zh = locale.startsWith('zh'); const id = useId()
  const [open, setOpen] = useState(false); const [connections, setConnections] = useState<VILabConnection[]>([])
  const [target, setTarget] = useState(config.connection_id || 'default')
  const [url, setUrl] = useState(''); const [key, setKey] = useState('')
  const [authMode, setAuthMode] = useState<'account' | 'api_key'>(config.connection_auth_mode || 'account')
  const [accountConsent, setAccountConsent] = useState<{ draft: VILabConnectionDraft; origin: string; signature: string; active: () => boolean } | null>(null)
  const signature = JSON.stringify([target, url, key, authMode])
  const [checked, setChecked] = useState<VILabConnectionCheck | null>(null)
  const [asr, setAsr] = useState(''); const [llm, setLlm] = useState('')
  const [busy, setBusy] = useState<'list' | 'check' | 'save' | ''>(''); const [error, setError] = useState('')
  const sequence = useRef(0)
  useEffect(() => onModelConnectionIdentityChange(() => {
    sequence.current++; setOpen(false); setKey(''); setChecked(null); setConnections([]); setBusy(''); setError(''); setAccountConsent(null)
  }), [])
  useEffect(() => () => { sequence.current++ }, [])
  async function load() {
    const request = ++sequence.current; const active = modelConnectionScope()
    setBusy('list'); setConnections([]); setError('')
    try {
      const result = await listVILabConnections()
      if (request === sequence.current && active()) setConnections(result.connections)
    } catch (cause) {
      if (request === sequence.current && active()) setError(cause instanceof Error ? cause.message : '无法读取连接')
    } finally { if (request === sequence.current && active()) setBusy('') }
  }
  function change() { sequence.current++; setChecked(null); setError(''); setBusy(''); setAccountConsent(null) }
  function check() {
    const draft: VILabConnectionDraft = target === NEW ? { server_url: url } : { connection_id: target }
    if (target !== 'default') {
      draft.auth_mode = authMode
      if (authMode === 'account') {
        let origin: string
        try { origin = new URL(target === NEW ? url : connections.find(item => item.connection_id === target)?.server_url || config.server_url || '').origin }
        catch { setError(zh ? '请填写有效的目标服务地址' : 'Enter a valid service URL'); return }
        Object.assign(draft, { account_consent: true, authorized_origin: origin })
        if (!ACCOUNT_ORIGINS.has(origin)) {
          setAccountConsent({ draft, origin, signature, active: modelConnectionScope() }); return
        }
      } else if (key) draft.api_key = key
    }
    void runCheck(draft)
  }
  async function runCheck(draft: VILabConnectionDraft) {
    const request = ++sequence.current; const active = modelConnectionScope()
    setBusy('check'); setChecked(null); setError('')
    try {
      const result = await checkVILabConnection(draft)
      if (request !== sequence.current || !active()) return
      setChecked(result); setAsr(result.asr_model); setLlm(result.llm_model)
    } catch (cause) {
      if (request === sequence.current && active()) setError(cause instanceof Error ? cause.message : '连接检查失败')
    } finally { if (request === sequence.current && active()) setBusy('') }
  }
  async function save() {
    if (!checked) return
    const request = ++sequence.current; const active = modelConnectionScope()
    setBusy('save'); setError('')
    try {
      await useAppModeStore.getState().saveConnection(checked.check_id, asr, llm)
      if (request !== sequence.current || !active()) return
      setKey(''); setChecked(null); setOpen(false)
    } catch (cause) {
      if (request === sequence.current && active()) setError(cause instanceof Error ? cause.message : '保存失败，草稿已保留')
    } finally { if (request === sequence.current && active()) setBusy('') }
  }
  const selected = connections.find(item => item.connection_id === target)
  return <><Dialog open={open} onOpenChange={next => {
    sequence.current++; setOpen(next); setChecked(null); setKey(''); setBusy(''); setError(''); setAccountConsent(null)
    if (next) { setTarget(config.connection_id || 'default'); setAuthMode(config.connection_auth_mode || 'account'); void load() }
  }}>
    <div className="flex min-w-0 items-center justify-between gap-2 text-sm">
      <span className="min-w-0 truncate text-muted-foreground" title={config.server_url}>{zh ? 'VILab 连接' : 'VILab connection'} · {config.server_url || (zh ? '尚未配置' : 'Not configured')}</span>
      <DialogTrigger asChild><Button variant="outline" size="sm">{zh ? '管理连接' : 'Manage'}</Button></DialogTrigger>
    </div>
    <DialogContent closeLabel={zh ? '关闭连接设置' : 'Close connection settings'}>
      <DialogHeader><DialogTitle>{zh ? 'VILab 模型连接' : 'VILab model connection'}</DialogTitle>
        <DialogDescription>{zh ? '先读取模型列表，保存后才切换。已有任务继续使用原连接与模型。' : 'Check the model catalog, then save to switch. Existing tasks retain their connection and models.'}</DialogDescription></DialogHeader>
      <FieldGroup>
        <Field><FieldLabel htmlFor={`${id}-connection`}>{zh ? '服务连接' : 'Connection'}</FieldLabel>
          <Select value={target} disabled={Boolean(busy)} onValueChange={value => { change(); setTarget(value); setKey(''); setUrl(''); setAuthMode(value === NEW ? 'account' : connections.find(item => item.connection_id === value)?.auth_mode || 'api_key') }}>
            <SelectTrigger id={`${id}-connection`}><SelectValue /></SelectTrigger><SelectContent><SelectGroup>
              {connections.map(item => <SelectItem key={item.connection_id} value={item.connection_id}>{item.builtin ? (zh ? '内置默认服务' : 'Built-in default') : item.server_url}</SelectItem>)}
              <SelectItem value={NEW}>{zh ? '添加外部 VILab' : 'Add external VILab'}</SelectItem>
            </SelectGroup></SelectContent>
          </Select>
        </Field>
        {target === NEW && <Field><FieldLabel htmlFor={`${id}-url`}>{zh ? 'VILab 服务地址' : 'VILab URL'}</FieldLabel>
          <Input id={`${id}-url`} type="url" value={url} disabled={busy === 'save'} placeholder="http://127.0.0.1:9876" onChange={event => { change(); setUrl(event.target.value); setKey('') }} />
          <FieldDescription>{zh ? '内网或本机可用 HTTP，公网使用 HTTPS。填写服务根地址。' : 'Use HTTP for LAN or loopback, HTTPS for public services. Enter the service root URL.'}</FieldDescription>
        </Field>}
        {target !== 'default' && <Field><FieldLabel htmlFor={`${id}-auth`}>{zh ? '认证方式' : 'Authentication'}</FieldLabel>
          <Select value={authMode} disabled={Boolean(busy)} onValueChange={value => { if (value === 'account' || value === 'api_key') { change(); setAuthMode(value); setKey('') } }}>
            <SelectTrigger id={`${id}-auth`}><SelectValue /></SelectTrigger><SelectContent><SelectGroup>
              <SelectItem value="account">{zh ? '已登录的 VINote 账号' : 'Signed-in VINote account'}</SelectItem>
              <SelectItem value="api_key">{zh ? '此连接的 API key' : 'Connection API key'}</SelectItem>
            </SelectGroup></SelectContent>
          </Select>
          <FieldDescription>{authMode === 'account' ? (zh ? '无需 API key。点击“用已登录账号检查”才向所选地址发送当前账号凭据，保存后用于该连接。' : 'No API key needed. Check explicitly with your signed-in account, then save to authorize this connection.') : (zh ? '仅使用此连接明确配置的密钥，不继承其他地址或账号令牌。' : 'Use only this connection’s key; other connections’ credentials are never inherited.')}</FieldDescription>
        </Field>}
        {target !== 'default' && authMode === 'api_key' && <Field><FieldLabel htmlFor={`${id}-key`}>{zh ? '此连接的访问密钥（可选）' : 'Connection access key (optional)'}</FieldLabel>
          <Input id={`${id}-key`} type="password" autoComplete="off" value={key} disabled={busy === 'save'} placeholder={selected?.has_credential ? (zh ? '已保存；留空保留' : 'Saved; leave blank to retain') : ''} onChange={event => { change(); setKey(event.target.value) }} />
          <FieldDescription>{zh ? '新地址不会沿用其他连接的密钥或账号令牌。VINote 登录账号保持不变。' : 'New URLs never borrow credentials from another connection. Your VINote account stays signed in.'}</FieldDescription>
        </Field>}
        {checked && <>
          <p role="status" className="text-sm text-muted-foreground">{zh ? `已读取 ${checked.models.length} 个模型，尚未切换服务。` : `${checked.models.length} models found. Connection has not switched.`}</p>
          {(['asr', 'llm'] as const).map(kind => <Field key={kind}><FieldLabel htmlFor={`${id}-${kind}`}>{kind === 'asr' ? (zh ? '此连接的语音转写' : 'Speech model') : (zh ? '此连接的内容总结' : 'Summary model')}</FieldLabel>
            <Select value={(kind === 'asr' ? asr : llm) || DEFAULT} disabled={Boolean(busy)} onValueChange={value => (kind === 'asr' ? setAsr : setLlm)(value === DEFAULT ? '' : value)}>
              <SelectTrigger id={`${id}-${kind}`}><SelectValue /></SelectTrigger><SelectContent><SelectGroup>
                <SelectItem value={DEFAULT}>{zh ? '跟随此服务默认' : 'Use this service default'}</SelectItem>
                {checked.models.filter(model => model.modelType === kind).map(model => <SelectItem key={model.id} value={model.id} disabled={!modelEligible(model) || kind === 'asr' && !recordedAudioReady(model)}>{model.name || model.id}</SelectItem>)}
              </SelectGroup></SelectContent>
            </Select>
          </Field>)}
        </>}
      </FieldGroup>
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      {!connections.length && !busy && <Button variant="outline" onClick={() => void load()}>{zh ? '重新读取连接' : 'Reload connections'}</Button>}
      <DialogFooter><Button variant="outline" disabled={Boolean(busy) || target === NEW && !url} onClick={check}>{busy === 'check' ? (zh ? '正在读取模型…' : 'Checking…') : target !== 'default' && authMode === 'account' ? (zh ? '用已登录账号检查' : 'Check with signed-in account') : (zh ? '检查连接' : 'Check connection')}</Button>
        <Button disabled={!checked || Boolean(busy)} onClick={() => void save()}>{busy === 'save' ? (zh ? '正在保存…' : 'Saving…') : (zh ? '保存并使用' : 'Save and use')}</Button></DialogFooter>
    </DialogContent>
  </Dialog>
  <AlertDialog open={Boolean(accountConsent)} onOpenChange={next => { if (!next) setAccountConsent(null) }}>
    <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{zh ? '允许此服务使用当前账号？' : 'Allow this service to use your account?'}</AlertDialogTitle>
      <AlertDialogDescription>{zh ? '将向以下确切地址发送当前 VINote 账号凭据，只读取模型列表。确认服务由你信任的运营方管理；保存后仅授权这个连接，不跟随重定向。' : 'Send your current VINote credential to this exact trusted service to read its model catalog. Saving authorizes only this connection; redirects are not followed.'}
        <span className="mt-2 block break-all">{accountConsent?.origin}</span>
      </AlertDialogDescription></AlertDialogHeader><AlertDialogFooter>
      <AlertDialogCancel onClick={() => setAccountConsent(null)}>{zh ? '取消' : 'Cancel'}</AlertDialogCancel>
      <AlertDialogAction onClick={() => { const consent = accountConsent; setAccountConsent(null); if (consent?.active() && consent.signature === signature) void runCheck(consent.draft) }}>{zh ? '同意并检查此地址' : 'Allow and check this URL'}</AlertDialogAction>
    </AlertDialogFooter></AlertDialogContent>
  </AlertDialog></>
}
