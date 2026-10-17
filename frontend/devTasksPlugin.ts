import type { Plugin } from 'vite'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

/** Local source-run task registrations; never served by packaged builds. */
export function devTasksPlugin(): Plugin {
  return {
    name: 'vinote-dev-tasks',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/__vinote/dev-tasks', async (_req, res) => {
        res.setHeader('Content-Type', 'application/json')
        res.setHeader('Cache-Control', 'no-store')
        try {
          const entries: unknown = JSON.parse(await readFile(path.resolve(server.config.root, '../data/dev-tasks.json'), 'utf8'))
          const tasks = Array.isArray(entries) ? entries.filter((entry) =>
            entry && typeof entry.taskId === 'string' && /^[a-f0-9-]{36}$/.test(entry.taskId),
          ).slice(0, 10).map(({ taskId, label }) => ({ taskId,
            label: typeof label === 'string' ? label.slice(0, 60) : '会议任务' })) : []
          res.end(JSON.stringify(tasks))
        } catch { res.end('[]') }
      })
    },
  }
}
