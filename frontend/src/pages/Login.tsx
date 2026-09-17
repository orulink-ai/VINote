import { useEffect, useState } from 'react'
import { ArrowRight, Eye, EyeOff, Lock, Mail } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { EmailLogin } from '../components/EmailLogin'
import { Alert, AlertDescription } from '../components/ui/alert'
import { Button } from '../components/ui/button'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '../components/ui/field'
import { Input } from '../components/ui/input'
import { apiJson } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { useAuthStore } from '../stores/authStore'

const brandMarkUrl = import.meta.env.BASE_URL + 'vinote-mark.svg'

export function Login() {
  const [emailLogin, setEmailLogin] = useState<boolean | null>(null)
  const [retryConfig, setRetryConfig] = useState(0)
  const [isLogin, setIsLogin] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
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

  const switchMode = (nextIsLogin: boolean) => {
    setIsLogin(nextIsLogin)
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
      if (signInError) {
        setError(signInError.message)
        return
      }
      navigate('/')
      return
    }

    if (password !== confirmPassword) {
      setError(copy.login.passwordMismatch)
      return
    }

    setLoading(true)
    const { error: signUpError, user } = await signUp(email, password)
    setLoading(false)
    if (signUpError) {
      setError(signUpError.message)
      return
    }
    if (user) {
      navigate('/')
      return
    }
    setError(copy.login.accountCreated)
    setIsLogin(true)
  }

  return (
    <main className="grid min-h-screen bg-background text-foreground lg:grid-cols-[44%_56%]">
      <section className="hidden min-h-screen border-r bg-muted/40 p-12 lg:flex lg:flex-col xl:p-16">
        <div className="flex items-center gap-3">
          <img src={brandMarkUrl} alt="VINote" className="size-8" />
          <span className="text-lg font-semibold tracking-tight">VINote</span>
        </div>

        <div className="my-auto max-w-lg">
          <p className="mb-5 text-sm font-medium text-muted-foreground">会议与知识工作台</p>
          <h1 className="text-4xl font-semibold leading-tight tracking-[-0.045em] xl:text-5xl">
            记录讨论，沉淀可以继续使用的知识。
          </h1>
          <p className="mt-6 max-w-md text-base leading-7 text-muted-foreground">
            从实时会议记录到链接、文件与团队笔记，在一个桌面工作区完成。
          </p>
        </div>

        <p className="text-sm text-muted-foreground">VINote Desktop</p>
      </section>

      <section className="flex min-h-screen items-center justify-center px-6 py-12 sm:px-10">
        <div className="w-full max-w-[380px]">
          <div className="mb-12 flex items-center gap-3 lg:hidden">
            <img src={brandMarkUrl} alt="VINote" className="size-8" />
            <span className="text-lg font-semibold tracking-tight">VINote</span>
          </div>

          <div className="mb-8">
            <h2 className="text-3xl font-semibold tracking-[-0.04em]">
              {isLogin ? '登录 VINote' : '创建账号'}
            </h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {isLogin ? '继续你的会议、笔记和团队工作。' : '创建账号，开始整理你的知识。'}
            </p>
          </div>

          <div className="mb-8 flex gap-7 border-b">
            <button type="button" className={isLogin ? 'border-b-2 border-foreground pb-3 text-sm font-medium' : 'pb-3 text-sm text-muted-foreground'} onClick={() => switchMode(true)}>
              登录
            </button>
            <button type="button" className={!isLogin ? 'border-b-2 border-foreground pb-3 text-sm font-medium' : 'pb-3 text-sm text-muted-foreground'} onClick={() => switchMode(false)}>
              注册
            </button>
          </div>

          {emailLogin === null ? (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-muted-foreground">{error || '正在连接登录服务…'}</p>
              {error ? <Button onClick={() => setRetryConfig(value => value + 1)}>重试连接</Button> : null}
            </div>
          ) : emailLogin ? (
            <EmailLogin isLogin={isLogin} onSwitch={() => switchMode(!isLogin)} />
          ) : (
            <form onSubmit={handleSubmit}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="login-email">{copy.login.email}</FieldLabel>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input id="login-email" type="email" value={email} onChange={event => setEmail(event.target.value)} autoComplete="email" className="h-11 pl-10" placeholder={copy.login.emailPlaceholder} required />
                  </div>
                </Field>

                <Field>
                  <FieldLabel htmlFor="login-password">{copy.login.password}</FieldLabel>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input id="login-password" type={showPassword ? 'text' : 'password'} value={password} onChange={event => setPassword(event.target.value)} autoComplete={isLogin ? 'current-password' : 'new-password'} className="h-11 pl-10 pr-11" placeholder={copy.login.passwordPlaceholder} required minLength={6} />
                    <Button type="button" size="icon" variant="ghost" onClick={() => setShowPassword(value => !value)} className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground" aria-label={showPassword ? '隐藏密码' : '显示密码'}>
                      {showPassword ? <EyeOff /> : <Eye />}
                    </Button>
                  </div>
                  {!isLogin ? <FieldDescription>{copy.login.passwordRules}</FieldDescription> : null}
                </Field>

                {!isLogin ? (
                  <Field>
                    <FieldLabel htmlFor="login-confirm-password">{copy.login.confirmPassword}</FieldLabel>
                    <div className="relative">
                      <Lock className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                      <Input id="login-confirm-password" type={showPassword ? 'text' : 'password'} value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} autoComplete="new-password" className="h-11 pl-10" placeholder={copy.login.confirmPasswordPlaceholder} required minLength={6} />
                    </div>
                  </Field>
                ) : null}

                {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}

                <Button type="submit" disabled={loading} size="lg" className="w-full">
                  {loading ? copy.login.working : isLogin ? copy.login.signIn : copy.login.signUp}
                  {!loading ? <ArrowRight data-icon="inline-end" /> : null}
                </Button>
              </FieldGroup>
            </form>
          )}
        </div>
      </section>
    </main>
  )
}
