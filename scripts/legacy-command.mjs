import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { root } from './runtime.mjs'
const [alias, canonical, ...args] = process.argv.slice(2)
const scripts = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).scripts
const command = scripts[canonical]
const match = command?.match(/^node scripts\/(dev|build-desktop)\.mjs (.+)$/)
if (!match) throw new Error('Invalid compatibility command')
console.error(`[compat] ${alias} → yarn ${canonical}`)
process.argv = [process.execPath, join(root, `scripts/${match[1]}.mjs`), ...match[2].split(' '), ...args]
await import(`./${match[1]}.mjs`)
