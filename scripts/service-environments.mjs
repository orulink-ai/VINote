// Product entry points intentionally ignore environment URL overrides.
export const serviceOrigins = Object.freeze({
  lan: 'http://192.168.1.143:9876',
  public: 'https://api.orulink.ai',
})

export function serviceOrigin(environment) {
  if (!Object.hasOwn(serviceOrigins, environment)) throw new Error('Environment must be lan or public')
  return serviceOrigins[environment]
}
