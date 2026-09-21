import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { apiJson } from '../lib/api'
import { useAuthStore } from '../stores/authStore'
import { PasswordRecovery } from './PasswordRecovery'

export function EmailLogin({ isLogin, onSwitch }: { isLogin: boolean; onSwitch: () => void }) {
  const [email, setEmail] = useState(''); const [code, setCode] = useState(''); const [password, setPassword] = useState(''); const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false); const [seconds, setSeconds] = useState(0); const [registrationSent, setRegistrationSent] = useState(false); const [message, setMessage] = useState(''); const [recovering, setRecovering] = useState(false)
  const navigate = useNavigate()
  useEffect(() => { if (!seconds) return; const timer = window.setTimeout(() => setSeconds(value => value - 1), 1000); return () => clearTimeout(timer) }, [seconds])
  async function run(action: () => Promise<void>) { setBusy(true); setMessage(''); try { await action() } catch (error) { setMessage(error instanceof Error ? error.message : '登录失败，请重试') } finally { setBusy(false) } }
  if (recovering) return <PasswordRecovery email={email} onBack={() => { setRecovering(false); setPassword(''); setMessage('') }} />
  return <form className="grid gap-5" onSubmit={event => { event.preventDefault(); void run(async () => { if (!isLogin && password !== confirmation) throw new Error('两次密码不一致'); await apiJson(isLogin ? '/api/auth/sign-in' : '/api/auth/register/verify', { method: 'POST', body: JSON.stringify(isLogin ? { email, password } : { email, code }) }); await useAuthStore.getState().initialize(); if (!useAuthStore.getState().user) throw new Error('登录会话未建立，请重试'); navigate('/') }) }}>
    <FieldGroup className="gap-4"><Field><FieldLabel htmlFor="email-login-email">邮箱</FieldLabel><Input id="email-login-email" required type="email" disabled={busy || (!isLogin && registrationSent)} autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} /></Field><Field><FieldLabel htmlFor="email-login-password">密码</FieldLabel><Input id="email-login-password" required type="password" autoComplete={isLogin ? 'current-password' : 'new-password'} minLength={6} maxLength={128} disabled={busy || (!isLogin && registrationSent)} value={password} onChange={event => setPassword(event.target.value)} /></Field>
    {!isLogin ? <><Field><FieldLabel htmlFor="email-login-confirmation">确认密码</FieldLabel><Input id="email-login-confirmation" required type="password" autoComplete="new-password" disabled={busy || registrationSent} value={confirmation} onChange={event => setConfirmation(event.target.value)} /></Field><Field><FieldLabel htmlFor="email-login-code">验证码</FieldLabel><div className="flex gap-2"><Input id="email-login-code" required inputMode="numeric" autoComplete="one-time-code" minLength={6} maxLength={10} value={code} onChange={event => setCode(event.target.value)} /><Button type="button" variant="outline" disabled={busy || !email || password.length < 6 || password !== confirmation || seconds > 0} onClick={() => void run(async () => { await apiJson('/api/auth/register/code', { method: 'POST', body: JSON.stringify({ email, password }) }); setRegistrationSent(true); setSeconds(60); setMessage('验证码已发送，请检查邮箱') })}>{seconds ? `${seconds} 秒` : '获取验证码'}</Button></div></Field></> : null}</FieldGroup>
    {isLogin ? <div className="flex justify-end"><Button type="button" variant="link" disabled={busy} onClick={() => setRecovering(true)} className="h-auto px-0 py-0 text-xs text-muted-foreground">忘记密码？</Button></div> : null}
    {message ? <Alert><AlertDescription>{message}</AlertDescription></Alert> : null}
    <Button disabled={busy} size="lg" className="w-full">{busy ? '处理中…' : isLogin ? '登录' : '创建账号'}</Button>
    <p className="text-center text-sm text-muted-foreground">{isLogin ? '还没有账号？' : '已经有账号？'} <Button type="button" variant="link" className="h-auto px-1 py-0" onClick={onSwitch}>{isLogin ? '创建账号' : '返回登录'}</Button></p>
  </form>
}
