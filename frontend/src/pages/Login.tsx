import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EmailLogin } from '@/components/EmailLogin'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { apiJson } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import { useAuthStore } from '@/stores/authStore'

const brandMarkUrl = import.meta.env.BASE_URL + 'vinote-mark.svg'

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
        if (active) {
          setEmailLogin(value.email_code)
          setError('')
        }
      } catch {
        if (!active) return
        if (attempt < 3) timer = setTimeout(() => void load(attempt + 1), 1000)
        else setError('无法连接登录服务，请稍后重试')
      }
    }
    setError('')
    void load(0)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [retryConfig])

  const switchMode = (mode: string) => {
    setIsLogin(mode === 'login')
    setError('')
    setConfirmPassword('')
  }

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

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted p-6 md:p-10">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex items-center justify-center gap-2 font-semibold tracking-tight">
          <img src={brandMarkUrl} alt="VINote" className="size-7" />
          VINote
        </div>

        <Card>
          <CardContent className="p-6 md:p-8">
            <div className="flex flex-col gap-6">
              <header className="flex flex-col items-center gap-2 text-center">
                <h1 className="text-2xl font-semibold tracking-tight">{isLogin ? '欢迎回来' : '创建账号'}</h1>
                <p className="text-sm text-muted-foreground">{isLogin ? '登录并继续你的工作' : '开始记录会议与整理笔记'}</p>
              </header>

              <Tabs value={isLogin ? 'login' : 'register'} onValueChange={switchMode}>
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="login">登录</TabsTrigger>
                  <TabsTrigger value="register">注册</TabsTrigger>
                </TabsList>
              </Tabs>

              {emailLogin === null ? (
                <div className="flex flex-col gap-4 text-center">
                  <p className="text-sm text-muted-foreground">{error || '正在连接登录服务…'}</p>
                  {error ? <Button onClick={() => setRetryConfig(value => value + 1)}>重试连接</Button> : null}
                </div>
              ) : emailLogin ? (
                <EmailLogin isLogin={isLogin} onSwitch={() => switchMode(isLogin ? 'register' : 'login')} />
              ) : (
                <form onSubmit={handleSubmit}>
                  <FieldGroup>
                    <Field>
                      <FieldLabel htmlFor="login-email">{copy.login.email}</FieldLabel>
                      <Input id="login-email" type="email" value={email} onChange={event => setEmail(event.target.value)} autoComplete="email" placeholder={copy.login.emailPlaceholder} required />
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="login-password">{copy.login.password}</FieldLabel>
                      <Input id="login-password" type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete={isLogin ? 'current-password' : 'new-password'} placeholder={copy.login.passwordPlaceholder} required minLength={6} />
                      {!isLogin ? <FieldDescription>{copy.login.passwordRules}</FieldDescription> : null}
                    </Field>
                    {!isLogin ? (
                      <Field>
                        <FieldLabel htmlFor="login-confirm-password">{copy.login.confirmPassword}</FieldLabel>
                        <Input id="login-confirm-password" type="password" value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} autoComplete="new-password" placeholder={copy.login.confirmPasswordPlaceholder} required minLength={6} />
                      </Field>
                    ) : null}
                    {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
                    <Button type="submit" disabled={loading} size="lg" className="w-full">
                      {loading ? copy.login.working : isLogin ? copy.login.signIn : copy.login.signUp}
                    </Button>
                  </FieldGroup>
                </form>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
