import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { root, python } from './runtime.mjs'

function check(label, command, args, cwd = root) {
  console.log(`\n[check] ${label}`)
  const result = spawnSync(command, args, { cwd, stdio: 'inherit', windowsHide: true })
  if (result.error || result.status !== 0) {
    throw new Error(`${label} failed (${result.status ?? 'not started'})`)
  }
}

check('Backend tests', python(), ['-m', 'pytest', 'tests', '-q'])
check('Desktop script contracts', process.execPath, ['--test',
  'scripts/desktop-build-profile.test.mjs', 'scripts/project-scripts.test.mjs'])
check('Frontend tests', process.execPath,
  [join(root, 'frontend/node_modules/vitest/vitest.mjs'), 'run'], join(root, 'frontend'))
check('Frontend type check', process.execPath,
  [join(root, 'frontend/node_modules/typescript/bin/tsc')], join(root, 'frontend'))
check('Vite production build', process.execPath,
  [join(root, 'frontend/node_modules/vite/bin/vite.js'), 'build'], join(root, 'frontend'))
check('Documentation build', process.execPath,
  [join(root, 'docs/node_modules/vitepress/bin/vitepress.js'), 'build', '.'], join(root, 'docs'))

console.log('\nVINote project checks passed.')
