import { beforeEach, describe, expect, it } from 'vitest'
import { isMeetingBusy, useMeetingRecorderStore } from './meetingRecorderStore'

describe('meetingRecorderStore', () => {
  beforeEach(() => {
    useMeetingRecorderStore.getState().resetSession()
  })

  it('opens, minimizes, and restores the floating recorder', () => {
    const store = useMeetingRecorderStore.getState()

    store.openPanel()
    expect(useMeetingRecorderStore.getState().isPanelOpen).toBe(true)
    expect(useMeetingRecorderStore.getState().isMinimized).toBe(false)

    useMeetingRecorderStore.getState().minimizePanel()
    expect(useMeetingRecorderStore.getState().isPanelOpen).toBe(true)
    expect(useMeetingRecorderStore.getState().isMinimized).toBe(true)

    useMeetingRecorderStore.getState().restorePanel()
    expect(useMeetingRecorderStore.getState().isMinimized).toBe(false)
  })

  it('records completion metadata and exposes a success notification', () => {
    useMeetingRecorderStore.getState().setTaskId('task-1')
    useMeetingRecorderStore.getState().complete('note-1')

    const state = useMeetingRecorderStore.getState()
    expect(state.phase).toBe('completed')
    expect(state.taskId).toBe('task-1')
    expect(state.noteId).toBe('note-1')
    expect(state.notification).toMatchObject({
      kind: 'success',
      title: '会议已总结好',
      noteId: 'note-1',
    })
  })

  it('keeps failure details and allows retry by resetting transient state', () => {
    useMeetingRecorderStore.getState().setPhase('summarizing')
    useMeetingRecorderStore.getState().fail('network failed')

    expect(useMeetingRecorderStore.getState().phase).toBe('failed')
    expect(useMeetingRecorderStore.getState().error).toBe('network failed')
    expect(useMeetingRecorderStore.getState().notification?.kind).toBe('error')

    useMeetingRecorderStore.getState().resetSession()

    const state = useMeetingRecorderStore.getState()
    expect(state.phase).toBe('idle')
    expect(state.error).toBe('')
    expect(state.taskId).toBeUndefined()
    expect(state.notification).toBeNull()
  })
})

it('allows retry after saved failure but protects unsaved failures and in-flight generation', () => {
  expect(isMeetingBusy({ phase: 'failed', hasRecoverableRecording: true, localRecordingSaved: true })).toBe(false)
  expect(isMeetingBusy({ phase: 'failed', hasRecoverableRecording: true, localRecordingSaved: false })).toBe(true)
  expect(isMeetingBusy({ phase: 'summarizing', hasRecoverableRecording: true, localRecordingSaved: true })).toBe(true)
})
