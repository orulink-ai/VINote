import { python, loadEnv, run } from './runtime.mjs'
import { parseArgs } from 'node:util'
import { resolveDesktopDevProfile } from './desktop-dev-profile.mjs'
import { serviceOrigin } from './service-environments.mjs'
const { values } = parseArgs({ options: { desktop: { type: 'boolean' } } })
loadEnv()
if (values.desktop) {
  const profile = resolveDesktopDevProfile({ environment: 'public' })
  process.env.VINOTE_DESKTOP_RUNTIME = 'true'
  process.env.VINOTE_FEISHU_TRANSPORT = profile.feishuTransport
  process.env.VINOTE_INTEGRATION_URL ||= profile.integrationUrl
}
process.env.VILAB_SERVER_URL = serviceOrigin('public')
const child = run(python(), ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8900', '--reload'])
child.on('exit', code => { process.exitCode = code ?? 1 })
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal))
