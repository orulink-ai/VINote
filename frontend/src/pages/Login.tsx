import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EmailLogin } from '@/components/EmailLogin'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { apiJson } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import { useAuthStore } from '@/stores/authStore'

export function Login() {
  const [emailLogin, setEmailLogin] = useState<boolean | null>(null)
  const [retryConfig, setRetryConfig] = useState(0)
  const [isLogin, setIsLogin] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { signIn, signUp } = useAuthStore()
  const { copy } = useI18n()
  const navigate = useNavigate()

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const load = async (attempt: number) => {
      try {
        const value = await apiJson<{ email_code: boolean }>('/api/auth/config')
        if (active) { setEmailLogin(value.email_code); setError('') }
      } catch {
        if (!active) return
        if (attempt < 3) timer = setTimeout(() => void load(attempt + 1), 1000)
        else setError('无法连接登录服务，请稍后重试')
      }
    }
    setError('')
    void load(0)
    return () => { active = false; clearTimeout(timer) }
  }, [retryConfig])

  const switchMode = (mode: string) => { setIsLogin(mode === 'login'); setError(''); setConfirmPassword('') }
  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    if (isLogin) {
      setLoading(true)
      const { error: signInError } = await signIn(email, password)
      setLoading(false)
      if (signInError) return setError(signInError.message)
      navigate('/')
      return
    }
    if (password !== confirmPassword) return setError(copy.login.passwordMismatch)
    setLoading(true)
    const { error: signUpError, user } = await signUp(email, password)
    setLoading(false)
    if (signUpError) return setError(signUpError.message)
    if (user) return navigate('/')
    setError(copy.login.accountCreated)
    setIsLogin(true)
  }

  return <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-muted/30 px-5 py-10">
    <div className="pointer-events-none absolute inset-0 [background-image:linear-gradient(to_right,hsl(var(--border)/.45)_1px,transparent_1px),linear-gradient(to_bottom,hsl(var(--border)/.45)_1px,transparent_1px)] [background-size:32px_32px] [mask-image:radial-gradient(ellipse_at_center,black,transparent_72%)]" />
    <section className="relative w-full max-w-[420px] animate-in fade-in slide-in-from-bottom-2 duration-500 rounded-2xl border bg-background p-7 shadow-sm sm:p-9">
      <div className="mb-8"><p className="text-sm font-medium tracking-wide">VINote</p><p className="mt-1 text-xs text-muted-foreground">桌面工作空间</p></div>
      <div className="w-full">
        <header className="mb-7 flex flex-col gap-2"><h1 className="text-2xl font-semibold tracking-tight">{isLogin ? '登录' : '创建账号'}</h1><p className="text-sm leading-6 text-muted-foreground">{isLogin ? '输入账号信息继续。' : '验证邮箱后即可进入工作空间。'}</p></header>
        {emailLogin === null ? <div className="flex flex-col gap-4 text-center"><p className="text-sm text-muted-foreground">{error || '正在连接登录服务…'}</p>{error ? <Button onClick={() => setRetryConfig(value => value + 1)}>重试连接</Button> : null}</div> : emailLogin ? <EmailLogin isLogin={isLogin} onSwitch={() => switchMode(isLogin ? 'register' : 'login')} /> : <form onSubmit={handleSubmit}><FieldGroup><Field><FieldLabel htmlFor="login-email">{copy.login.email}</FieldLabel><Input id="login-email" type="email" value={email} onChange={event => setEmail(event.target.value)} autoComplete="email" placeholder={copy.login.emailPlaceholder} required /></Field><Field><FieldLabel htmlFor="login-password">{copy.login.password}</FieldLabel><Input id="login-password" type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete={isLogin ? 'current-password' : 'new-password'} placeholder={copy.login.passwordPlaceholder} required minLength={6} />{!isLogin ? <FieldDescription>{copy.login.passwordRules}</FieldDescription> : null}</Field>{!isLogin ? <Field><FieldLabel htmlFor="login-confirm-password">{copy.login.confirmPassword}</FieldLabel><Input id="login-confirm-password" type="password" value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} autoComplete="new-password" placeholder={copy.login.confirmPasswordPlaceholder} required minLength={6} /></Field> : null}{error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}<Button type="submit" disabled={loading} size="lg" className="w-full transition-transform duration-200 active:scale-[.99]">{loading ? copy.login.working : isLogin ? copy.login.signIn : copy.login.signUp}</Button><p className="text-center text-sm text-muted-foreground">{isLogin ? '还没有账号？' : '已经有账号？'} <Button type="button" variant="link" className="h-auto px-1 py-0" onClick={() => switchMode(isLogin ? 'register' : 'login')}>{isLogin ? copy.login.createAccount : copy.login.signIn}</Button></p></FieldGroup></form>}
      </div>
    </section>
  </main>
}
