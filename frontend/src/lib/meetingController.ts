import { invoke } from '@tauri-apps/api/core'
import { emit, listen } from '@tauri-apps/api/event'
import { isTauriRuntime } from './desktopRecorderWindow'
import type { MeetingRecorderExternalSnapshot } from '../stores/meetingRecorderStore'

const STATE_EVENT = 'vinote-meeting-controller-state'
const ACTION_EVENT = 'vinote-meeting-controller-action'
export type MeetingControlAction = 'sync' | 'pause' | 'resume' | 'stop' | 'generate' | 'retry'

export function isMeetingController() {
  return new URLSearchParams(window.location.search).get('controller') === '1'
}

export async function openMeetingController() {
  if (isTauriRuntime()) await invoke('open_recorder_window', { controller: true })
}

export async function publishMeetingState(snapshot: MeetingRecorderExternalSnapshot) {
  if (isTauriRuntime()) await emit(STATE_EVENT, snapshot)
}

export function listenMeetingState(handler: (state: MeetingRecorderExternalSnapshot) => void) {
  return listen<MeetingRecorderExternalSnapshot>(STATE_EVENT, event => handler(event.payload))
}

export function sendMeetingAction(action: MeetingControlAction) { return emit(ACTION_EVENT, action) }
export function listenMeetingActions(handler: (action: MeetingControlAction) => void) {
  return listen<MeetingControlAction>(ACTION_EVENT, event => handler(event.payload))
}
