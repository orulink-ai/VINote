import { invoke } from '@tauri-apps/api/core'

const TAURI_INTERNALS_KEY = '__TAURI_INTERNALS__'

export function isTauriRuntime() {
  return typeof window !== 'undefined' && TAURI_INTERNALS_KEY in window
}

export async function requestDesktopMicrophoneAccess() {
  if (!isTauriRuntime()) {
    return
  }

  const status = await invoke<string>('request_microphone_access')
  if (status !== 'authorized' && status !== 'unsupported_platform') {
    throw new Error(status)
  }
}
