import { useEffect, useState } from 'react'
import { Cloud, LogOut, Mail } from 'lucide-react'
import { apiJson } from '../../lib/api'
import { Alert, AlertDescription } from '../ui/alert'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Input } from '../ui/input'
import { Label } from '../ui/label'

type Account = { configured: boolean; authenticated: boolean; email?: string }

export function CloudAccountPanel({ onConnected }: { onConnected: () => void }) {
  const [account, setAccount] = useState<Account | null>(null)
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [resendSeconds, setResendSeconds] = useState(0)
  useEffect(() => {
    if (resendSeconds <= 0) return
    const timer = window.setTimeout(() => setResendSeconds(value => value - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [resendSeconds])
  useEffect(() => {
    let active = true
    apiJson<Account>('/api/vilab/account').then(value => { if (active) setAccount(value) })
      .catch(() => { if (active) setMessage('无法读取云端账号状态') })
    return () => { active = false }
  }, [])
  async function run(action: () => Promise<void>) {
    setBusy(true); setMessage('')
    try { await action() } catch (error) { setMessage(error instanceof Error ? error.message : '操作失败') }
    finally { setBusy(false) }
  }
  if (account && !account.configured) return null
  return <Card>
    <CardHeader><div className="flex items-center justify-between gap-3"><div><CardTitle className="flex items-center gap-2"><Cloud className="h-5 w-5 text-primary" />VINote 云端账号</CardTitle><CardDescription>连接云端模型账户，统一使用转写和总结服务。</CardDescription></div>{account?.authenticated && <Badge variant="secondary">已连接</Badge>}</div></CardHeader>
    <CardContent className="grid gap-4">
      {account?.authenticated ? <>
        <div className="rounded-xl border border-border bg-muted/40 p-4"><p className="text-sm font-medium">{account.email}</p><p className="mt-1 text-xs text-muted-foreground">当前桌面端已连接此云端账号</p></div>
        <Button variant="outline" className="w-fit" disabled={busy} onClick={() => void run(async () => {
          const result = await apiJson<{ remote_revoked: boolean }>('/api/vilab/account', { method: 'DELETE' })
          setAccount({ configured: true, authenticated: false }); onConnected()
          if (!result.remote_revoked) setMessage('本地云端会话已清除，上游会话撤销暂未完成。')
        })}><LogOut className="h-4 w-4" />退出云端账号</Button>
      </> : <>
        <p className="text-sm leading-6 text-muted-foreground">使用邮箱验证码注册或登录 VINote，登录后即可使用云端模型。</p>
        <div className="grid gap-2"><Label htmlFor="cloud-account-email">云端账号邮箱</Label><div className="flex flex-col gap-3 sm:flex-row"><div className="relative flex-1"><Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input id="cloud-account-email" aria-label="云端账号邮箱" autoComplete="email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="请输入邮箱" className="pl-9" /></div><Button variant="outline" disabled={busy || !email || resendSeconds > 0} onClick={() => void run(async () => { await apiJson('/api/vilab/account/code', { method: 'POST', body: JSON.stringify({ email }) }); setResendSeconds(60); setMessage('验证码已发送，请检查邮箱') })}>{resendSeconds > 0 ? String(resendSeconds) + ' 秒后重发' : '发送验证码'}</Button></div></div>
        <div className="grid gap-2"><Label htmlFor="cloud-account-code">邮箱验证码</Label><Input id="cloud-account-code" aria-label="邮箱验证码" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={e => setCode(e.target.value)} placeholder="请输入验证码" /></div>
        <Button className="w-fit" disabled={busy || !email || code.length < 6} onClick={() => void run(async () => { const value = await apiJson<Account>('/api/vilab/account/verify', { method: 'POST', body: JSON.stringify({ email, code }) }); setAccount(value); setCode(''); onConnected() })}>{busy ? '正在连接…' : '注册 / 登录'}</Button>
      </>}
      {message && <Alert><AlertDescription>{message}</AlertDescription></Alert>}
    </CardContent>
  </Card>
}
