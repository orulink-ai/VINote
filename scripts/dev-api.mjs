import { python, loadEnv, run } from './runtime.mjs'
loadEnv()
process.env.VILAB_SERVER_URL ||= 'http://192.168.1.143:9876'
const child = run(python(), ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8900', '--reload'])
child.on('exit', code => { process.exitCode = code ?? 1 })
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal))
