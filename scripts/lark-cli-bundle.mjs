import { existsSync, realpathSync, statSync } from 'node:fs'
import { delimiter, isAbsolute, join } from 'node:path'

export function resolveLarkCli({ platform = process.platform, path = process.env.PATH || '', override = process.env.VINOTE_LARK_CLI_PATH } = {}) {
  const suffix = platform === 'win32' ? '.exe' : ''
  const candidates = override ? [override] : path.split(delimiter).filter(Boolean).flatMap(directory => [
    join(directory, `lark-cli${suffix}`),
    ...(platform === 'win32' ? [join(directory, 'node_modules', '@larksuite', 'cli', 'bin', 'lark-cli.exe')] : []),
  ])
  const found = candidates.find(candidate => isAbsolute(candidate) && existsSync(candidate) && statSync(candidate).isFile() &&
    (platform !== 'win32' || candidate.toLowerCase().endsWith('.exe')))
  if (!found) throw new Error('Install the official lark-cli native binary or set VINOTE_LARK_CLI_PATH; credentials are never bundled.')
  return realpathSync(found)
}
