// Compatibility for direct invocations of the former desktop launcher.
const channelIndex = process.argv.indexOf('--channel')
if (channelIndex !== -1) {
  const channel = process.argv[channelIndex + 1]
  if (!['test', 'development'].includes(channel)) throw new Error('Legacy channel must be test or development')
  process.argv.splice(channelIndex, 2, '--environment', channel === 'test' ? 'lan' : 'public')
}
console.error('[compat] Use yarn dev:desktop:lan or yarn dev:desktop:public.')
await import('./dev.mjs')
