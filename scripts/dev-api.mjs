import { python, loadEnv, run } from './runtime.mjs'
import { serviceOrigin } from './service-environments.mjs'
loadEnv()
process.env.VILAB_SERVER_URL = serviceOrigin('public')
const child = run(python(), ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8900', '--reload'])
child.on('exit', code => { process.exitCode = code ?? 1 })
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal))
