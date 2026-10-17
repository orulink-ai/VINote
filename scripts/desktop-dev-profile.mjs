import { serviceOrigin } from './service-environments.mjs'

export function resolveDesktopDevProfile({ environment = 'lan', version } = {}) {
  const server = serviceOrigin(environment)
  const lan = environment === 'lan'
  return {
    environment,
    server,
    productName: lan ? 'VINote LAN Dev' : 'VINote Public Dev',
    identifier: lan ? 'app.vinote.desktop.test.dev' : 'app.vinote.desktop.dev',
    tracingEnvironment: 'development',
    release: `${version}-dev-${environment}`,
  }
}
