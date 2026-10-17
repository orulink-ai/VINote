export type MicrophoneReadinessReason = 'unsupported' | 'denied' | 'no-device' | 'unavailable' | 'unknown'

export type MicrophoneReadinessResult =
  | { ok: true }
  | { ok: false; reason: MicrophoneReadinessReason }

interface MicrophoneReadinessEnvironment {
  permissions?: Permissions
  mediaDevices?: MediaDevices
}

export function mapMicrophoneError(error: unknown): MicrophoneReadinessReason {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') return 'denied'
    if (error.name === 'NotFoundError' || error.name === 'DevicesNotFoundError') return 'no-device'
    if (error.name === 'NotReadableError' || error.name === 'AbortError') return 'unavailable'
  }

  const message = error instanceof Error ? error.message.toLowerCase() : String(error || '').toLowerCase()
  if (message.includes('denied') || message.includes('notallowed')) return 'denied'
  if (message.includes('notfound') || message.includes('no-device') || message.includes('no audio')) return 'no-device'
  if (message.includes('notreadable') || message.includes('busy') || message.includes('unavailable')) return 'unavailable'
  return 'unknown'
}

async function queryPermissionState(permissions?: Permissions) {
  if (!permissions?.query) return 'unknown'

  try {
    const status = await permissions.query({ name: 'microphone' as PermissionName })
    return status.state
  } catch {
    return 'unknown'
  }
}

async function hasAudioInputDevice(mediaDevices: MediaDevices) {
  if (!mediaDevices.enumerateDevices) return true

  try {
    const devices = await mediaDevices.enumerateDevices()
    return devices.some((device) => device.kind === 'audioinput')
  } catch {
    return true
  }
}

export async function checkMicrophoneReadiness(
  environment: MicrophoneReadinessEnvironment = {
    permissions: typeof navigator !== 'undefined' ? navigator.permissions : undefined,
    mediaDevices: typeof navigator !== 'undefined' ? navigator.mediaDevices : undefined,
  },
): Promise<MicrophoneReadinessResult> {
  const mediaDevices = environment.mediaDevices
  if (!mediaDevices?.getUserMedia) {
    return { ok: false, reason: 'unsupported' }
  }

  const permissionState = await queryPermissionState(environment.permissions)
  if (permissionState === 'denied') {
    return { ok: false, reason: 'denied' }
  }

  if (permissionState === 'granted') {
    const hasDevice = await hasAudioInputDevice(mediaDevices)
    if (!hasDevice) {
      return { ok: false, reason: 'no-device' }
    }
  }

  return { ok: true }
}
