export function resolveDesktopDevProfile({ channel = 'test', env = {}, version }) {
  if (!['test', 'development'].includes(channel)) throw new Error('Dev channel must be test or development')
  const test = channel === 'test'
  const configured = test
    ? env.VINOTE_TEST_VILAB_SERVER_URL || 'http://192.168.1.143:9876'
    : env.VINOTE_DEV_VILAB_SERVER_URL || 'http://127.0.0.1:9878'
  const url = new URL(configured)
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('VILab URL must be an HTTP(S) origin without credentials, query or path')
  }
  return {
    channel,
    server: url.origin,
    productName: test ? 'VINote Test Dev' : 'VINote Dev',
    identifier: test ? 'app.vinote.desktop.test.dev' : 'app.vinote.desktop.dev',
    tracingEnvironment: test ? 'test' : 'development',
    release: `${version}-${test ? 'test-dev' : 'dev'}`,
  }
}
