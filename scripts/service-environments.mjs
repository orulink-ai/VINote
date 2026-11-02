// All product entry points use the public service. `lan` remains a legacy
// installation identity only; it cannot select another model service.
const publicOrigin = 'https://api-hk.orulink.ai'
export const serviceOrigins = Object.freeze({
  lan: publicOrigin,
  public: publicOrigin,
})

export function serviceOrigin(environment) {
  if (!Object.hasOwn(serviceOrigins, environment)) throw new Error('Environment must be lan or public')
  return serviceOrigins[environment]
}
