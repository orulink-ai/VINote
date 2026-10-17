import { useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { apiJson } from '../lib/api'

export function PasswordRecovery({ email: initialEmail, onBack }: { email: string; onBack: () => void }) {
  const [email, setEmail] = useState(initialEmail); const [code, setCode] = useState(''); const [password, setPassword] = useState(''); const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false); const [sentAt, setSentAt] = useState(0); const [message, setMessage] = useState(''); const [error, setError] = useState(''); const [done, setDone] = useState(false)
  async function run(action: () => Promise<void>) { setBusy(true); setError(''); setMessage(''); try { await action() } catch (cause) { setError(cause instanceof Error ? cause.message : '请求失败，请重试') } finally { setBusy(false) } }
  return <form className="grid gap-5" onSubmit={event => { event.preventDefault(); void run(async () => { if (password !== confirmation) throw new Error('两次密码不一致'); const result = await apiJson<{ message: string }>('/api/auth/password/reset', { method: 'POST', body: JSON.stringify({ email, code, password }) }); setMessage(result.message); setDone(true); setPassword(''); setConfirmation(''); setCode('') }) }}>
    <p className="text-sm leading-6 text-muted-foreground">通过邮箱验证重设密码，保留原账号及笔记。设置后请返回登录。</p>
    {!done ? <FieldGroup className="gap-4"><Field><FieldLabel htmlFor="recovery-email">邮箱</FieldLabel><Input id="recovery-email" type="email" autoComplete="email" required disabled={busy} value={email} onChange={event => { setEmail(event.target.value); setCode('') }} /></Field><Button type="button" variant="outline" disabled={busy || !email} onClick={() => void run(async () => { if (Date.now() - sentAt < 60000) throw new Error('请等待 60 秒后再获取验证码'); const result = await apiJson<{ message: string }>('/api/auth/password/code', { method: 'POST', body: JSON.stringify({ email }) }); setSentAt(Date.now()); setMessage(result.message) })}>获取重设密码验证码</Button><Field><FieldLabel htmlFor="recovery-code">验证码</FieldLabel><Input id="recovery-code" required inputMode="numeric" pattern="[0-9]{6,10}" autoComplete="one-time-code" disabled={busy} value={code} onChange={event => setCode(event.target.value.trim())} /></Field><Field><FieldLabel htmlFor="recovery-password">新密码</FieldLabel><Input id="recovery-password" required type="password" minLength={6} maxLength={128} autoComplete="new-password" disabled={busy} value={password} onChange={event => setPassword(event.target.value)} /></Field><Field><FieldLabel htmlFor="recovery-confirmation">确认新密码</FieldLabel><Input id="recovery-confirmation" required type="password" autoComplete="new-password" disabled={busy} value={confirmation} onChange={event => setConfirmation(event.target.value)} /></Field><Button disabled={busy} size="lg">{busy ? '处理中…' : '确认重设密码'}</Button></FieldGroup> : null}
    {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}{message ? <Alert role="status"><AlertDescription>{message}</AlertDescription></Alert> : null}<Button type="button" variant="ghost" disabled={busy} onClick={onBack}>返回登录</Button>
  </form>
}
