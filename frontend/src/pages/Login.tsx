import { useEffect, useState } from 'react'
import { EmailLogin } from '../components/EmailLogin'
import { apiJson } from '../lib/api'
import { useNavigate } from 'react-router-dom'
import { AudioLines, CheckCircle2, Eye, EyeOff, FileText, Lock, Mail, Mic2, Sparkles, Users2 } from 'lucide-react'
import { useI18n } from '../lib/i18n'
import { useAuthStore } from '../stores/authStore'
import { Alert, AlertDescription } from '../components/ui/alert'
import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'

const brandMarkUrl = `${import.meta.env.BASE_URL}vinote-mark.svg`

export function Login() {
  const [emailLogin, setEmailLogin] = useState<boolean | null>(null)
  const [retryConfig, setRetryConfig] = useState(0)
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

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')

    if (isLogin) {
      setLoading(true)
      const { error: signInError } = await signIn(email, password)

      if (signInError) {
        setError(signInError.message)
        setLoading(false)
        return
      }

      setLoading(false)
      navigate('/')
      return
    }

    if (password !== confirmPassword) {
      setError(copy.login.passwordMismatch)
      return
    }

    setLoading(true)

    const { error: signUpError, user } = await signUp(email, password)

    if (signUpError) {
      setError(signUpError.message)
      setLoading(false)
      return
    }

    setLoading(false)

    if (user) {
      navigate('/')
      return
    }

    setError(copy.login.accountCreated)
    setIsLogin(true)
  }

  return (
    <main className="min-h-screen bg-background text-foreground lg:grid lg:grid-cols-[minmax(520px,1.08fr)_minmax(460px,0.92fr)]">
      <section className="relative hidden min-h-screen overflow-hidden bg-foreground p-10 text-background lg:flex lg:flex-col xl:p-14">
        <div className="absolute inset-0 opacity-70 [background-image:radial-gradient(circle_at_15%_10%,hsl(var(--primary)/0.55),transparent_27%),radial-gradient(circle_at_90%_90%,hsl(var(--primary)/0.25),transparent_30%)]" />
        <div className="absolute inset-0 opacity-[0.08] [background-image:linear-gradient(hsl(var(--background))_1px,transparent_1px),linear-gradient(90deg,hsl(var(--background))_1px,transparent_1px)] [background-size:44px_44px]" />
        <header className="relative z-10 flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-2xl bg-background shadow-xl"><img src={brandMarkUrl} alt="VINote" className="size-7" /></span>
          <div><h1 className="text-xl font-semibold tracking-tight">VINote</h1><p className="text-xs text-background/55">Meetings become shared knowledge</p></div>
        </header>

        <div className="relative z-10 my-auto grid gap-8 py-12">
          <div className="max-w-2xl">
            <div className="mb-5 flex items-center gap-2 text-sm text-background/65"><Sparkles className="size-4 text-primary" />会议记录与知识整理工作台</div>
            <h2 className="text-5xl font-semibold leading-[1.04] tracking-[-0.055em] xl:text-6xl">让每次讨论，<br />成为清晰的下一步。</h2>
            <p className="mt-6 max-w-xl text-base leading-7 text-background/60">录制会议、区分说话人、整理链接与文件，再把结论放进个人或团队空间。</p>
          </div>

          <div className="max-w-2xl rounded-[30px] border border-background/10 bg-background/[0.07] p-3 shadow-2xl backdrop-blur-xl">
            <div className="flex items-center justify-between border-b border-background/10 px-3 pb-3 pt-1">
              <div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-xl bg-primary text-primary-foreground"><Mic2 className="size-4" /></span><div><p className="text-sm font-medium">产品周会</p><p className="text-xs text-background/45">正在记录 · 12:48</p></div></div>
              <div className="flex items-center gap-2 rounded-full bg-red-500/15 px-3 py-1.5 text-xs text-red-300"><span className="size-1.5 animate-pulse rounded-full bg-red-400" />REC</div>
            </div>
            <div className="grid gap-3 p-3">
              <div className="flex gap-3"><span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary/25 text-xs font-semibold text-primary">林</span><div className="max-w-[82%] rounded-2xl rounded-tl-md bg-background/10 px-4 py-3"><div className="mb-1 text-xs text-background/45">林洁 · 12:41</div><p className="text-sm leading-6 text-background/85">本周先完成桌面端交互统一，会议与笔记入口合并到同一个工作区。</p></div></div>
              <div className="flex gap-3"><span className="grid size-8 shrink-0 place-items-center rounded-full bg-emerald-400/20 text-xs font-semibold text-emerald-300">周</span><div className="max-w-[82%] rounded-2xl rounded-tl-md bg-background/10 px-4 py-3"><div className="mb-1 text-xs text-background/45">周扬 · 12:46</div><p className="text-sm leading-6 text-background/85">我负责打包流程，测试版和正式版使用统一脚本。</p></div></div>
              <div className="flex items-center gap-3 rounded-2xl border border-primary/25 bg-primary/10 px-4 py-3 text-sm text-background/75"><AudioLines className="size-5 text-primary" /><div className="flex flex-1 items-center gap-1">{[10,18,13,24,16,28,12,20,15,25,11,18,9,22,14].map((height, index) => <span key={index} className="w-1 rounded-full bg-primary/75" style={{ height }} />)}</div><span className="text-xs text-background/45">转写中</span></div>
            </div>
          </div>
        </div>

        <footer className="relative z-10 flex gap-6 text-xs text-background/45"><span className="flex items-center gap-2"><FileText className="size-4" />链接与文件整理</span><span className="flex items-center gap-2"><Users2 className="size-4" />团队知识共享</span></footer>
      </section>

      <section className="relative flex min-h-screen items-center justify-center overflow-hidden px-6 py-12 sm:px-10">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_100%_0%,hsl(var(--primary)/0.10),transparent_28rem)]" />
        <div className="relative w-full max-w-[430px]">
          <div className="mb-10 flex items-center gap-3 lg:hidden"><span className="grid size-11 place-items-center rounded-2xl border border-border bg-card shadow-sm"><img src={brandMarkUrl} alt="VINote" className="size-7" /></span><div><h1 className="text-xl font-semibold">VINote</h1><p className="text-xs text-muted-foreground">会议与知识工作台</p></div></div>
          <div className="mb-8">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium text-primary"><CheckCircle2 className="size-4" />安全连接已就绪</div>
            <h2 className="text-3xl font-semibold tracking-[-0.035em]">{isLogin ? '欢迎回来' : '创建你的工作空间'}</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{isLogin ? '登录后继续处理会议、笔记和团队知识。' : '一个账号管理你的个人笔记和团队协作内容。'}</p>
          </div>
          <div className="mb-7 grid grid-cols-2 rounded-xl bg-muted p-1">
            <Button type="button" variant={isLogin ? 'secondary' : 'ghost'} className={isLogin ? 'bg-card shadow-sm hover:bg-card' : ''} onClick={() => setIsLogin(true)}>登录</Button>
            <Button type="button" variant={!isLogin ? 'secondary' : 'ghost'} className={!isLogin ? 'bg-card shadow-sm hover:bg-card' : ''} onClick={() => setIsLogin(false)}>注册</Button>
          </div>
          <Card className="border-border/70 bg-card/75 shadow-xl shadow-foreground/[0.04] backdrop-blur">
          <CardContent className="p-6 sm:p-7">

          {emailLogin === null ? <div className="grid gap-4"><p className="text-sm text-muted-foreground">{error || '正在连接登录服务…'}</p>{error && <Button onClick={() => setRetryConfig(value => value + 1)}>重试连接</Button>}</div> : emailLogin ? <EmailLogin isLogin={isLogin} onSwitch={() => setIsLogin(value => !value)} /> : <>
          <form onSubmit={handleSubmit} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="login-email">{copy.login.email}</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="login-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  className="h-11 pl-10"
                  placeholder={copy.login.emailPlaceholder}
                  required
                />
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="login-password">{copy.login.password}</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={isLogin ? 'current-password' : 'new-password'}
                  className="h-11 pl-10 pr-12"
                  placeholder={copy.login.passwordPlaceholder}
                  required
                  minLength={6}
                />
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground"
                >
                  {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </Button>
              </div>
              {!isLogin ? (
                <p className="text-xs text-muted-foreground">
                  {copy.login.passwordRules}
                </p>
              ) : null}
            </div>

            {!isLogin ? (
              <div className="grid gap-2">
                <Label htmlFor="login-confirm-password">{copy.login.confirmPassword}</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="login-confirm-password"
                    type={showPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    autoComplete="new-password"
                    className="h-11 pl-10"
                    placeholder={copy.login.confirmPasswordPlaceholder}
                    required
                    minLength={6}
                  />
                </div>
              </div>
            ) : null}

            {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}

            <Button
              type="submit"
              disabled={loading}
              size="lg"
              className="w-full"
            >
              {loading ? copy.login.working : isLogin ? copy.login.signIn : copy.login.signUp}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-muted-foreground">
            {isLogin ? copy.login.noAccount : copy.login.hasAccount}
            <Button
              type="button"
              variant="link"
              className="h-auto px-1 py-0"
              onClick={() => {
                setIsLogin(!isLogin)
                setError('')
                setConfirmPassword('')
              }}
            >
              {isLogin ? copy.login.createAccount : copy.login.backToSignIn}
            </Button>
          </p>
          </>}
          </CardContent>
          </Card>
          <p className="mt-6 text-center text-xs text-muted-foreground">登录即表示你同意在本设备安全保存会话信息</p>
        </div>
      </section>
    </main>
  )
}
