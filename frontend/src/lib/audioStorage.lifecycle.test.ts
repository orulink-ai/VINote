import { afterEach, expect, it, vi } from 'vitest'
import { IDBFactory, IDBKeyRange } from 'fake-indexeddb'

const removeFile = vi.hoisted(() => vi.fn(async () => {}))
vi.mock('./recordingFile', () => ({ removeSavedRecordingFile: removeFile }))

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); vi.clearAllMocks() })

const meeting = (id: string, fileName?: string) => ({ id, ownerId: 'owner', fileName } as import('./audioStorage').PendingMeeting)

function setup() {
  vi.stubGlobal('indexedDB', new IDBFactory())
  vi.stubGlobal('IDBKeyRange', IDBKeyRange)
}

it('keeps a deletion tombstone that prevents late saves of the same recording', async () => {
  setup()
  const storage = await import('./audioStorage')
  await storage.savePendingMeeting(meeting('rec'))
  await storage.deleteLocalRecording('rec', 'owner')
  await expect(storage.savePendingMeeting(meeting('rec'))).rejects.toThrow()
  expect(await storage.getPendingMeeting('rec')).toBeNull()
})

it('refuses to delete an OPFS file shared by another pending recording', async () => {
  setup()
  const storage = await import('./audioStorage')
  await storage.savePendingMeeting(meeting('first', 'meeting-shared.webm'))
  await storage.savePendingMeeting(meeting('second', 'meeting-shared.webm'))
  await expect(storage.deleteLocalRecording('first', 'owner')).rejects.toThrow()
  expect(await storage.getPendingMeeting('first')).not.toBeNull()
  expect(await storage.getPendingMeeting('second')).not.toBeNull()
  expect(removeFile).not.toHaveBeenCalled()
})

it('keeps the deletion intent after OPFS failure and resumes cleanup without reviving audio', async () => {
  setup()
  const storage = await import('./audioStorage')
  await storage.savePendingMeeting(meeting('rec', 'meeting-recovery.webm'))
  await storage.saveRecordedAudio('rec', new Blob(['audio']))
  removeFile.mockRejectedValueOnce(new Error('busy'))
  await expect(storage.deleteLocalRecording('rec', 'owner')).rejects.toThrow('busy')
  await expect(storage.saveRecordedAudio('rec', new Blob(['late']))).rejects.toThrow()
  await expect(storage.savePendingMeeting(meeting('rec', 'meeting-recovery.webm'))).rejects.toThrow()
  await expect(storage.savePendingMeeting(meeting('another', 'meeting-recovery.webm'))).rejects.toThrow()
  await storage.deleteLocalRecording('rec', 'owner')
  expect(await storage.getRecordedAudio('rec')).toBeNull()
  expect(await storage.getPendingMeeting('rec')).toBeNull()
})
