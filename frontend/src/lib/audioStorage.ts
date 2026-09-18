import { removeSavedRecordingFile } from './recordingFile'
// Persists recorded audio blobs in IndexedDB so a meeting recording can be
// retried even after the recorder window is closed, the page is reloaded, or
// the device restarts. The blob is keyed by an opaque recording id that is
// also written into the meeting recorder store, so we can recover it from
// the note detail page later.

const DB_NAME = 'vinote-meeting-audio'
const DB_VERSION = 1
const STORE_NAME = 'recordings'

let dbPromise: Promise<IDBDatabase> | null = null

function isIndexedDBSupported() {
  return typeof indexedDB !== 'undefined'
}

function openDatabase(): Promise<IDBDatabase> {
  if (!isIndexedDBSupported()) {
    return Promise.reject(new Error('indexeddb_unsupported'))
  }
  if (dbPromise) return dbPromise
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME)
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('indexeddb_open_failed'))
    request.onblocked = () => reject(new Error('indexeddb_open_blocked'))
  })
  return dbPromise
}

export async function saveRecordedAudio(id: string, blob: Blob): Promise<void> {
  if (!isIndexedDBSupported()) return
  const db = await openDatabase()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).put(blob, id)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error ?? new Error('indexeddb_write_failed'))
    tx.onabort = () => reject(tx.error ?? new Error('indexeddb_write_aborted'))
  })
}

export async function getRecordedAudio(id: string): Promise<Blob | null> {
  if (!isIndexedDBSupported()) return null
  try {
    const db = await openDatabase()
    return await new Promise<Blob | null>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly')
      const request = tx.objectStore(STORE_NAME).get(id)
      request.onsuccess = () => resolve((request.result as Blob | undefined) ?? null)
      request.onerror = () => reject(request.error ?? new Error('indexeddb_read_failed'))
    })
  } catch {
    return null
  }
}

export async function deleteRecordedAudio(id: string): Promise<void> {
  if (!isIndexedDBSupported()) return
  try {
    const db = await openDatabase()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      tx.objectStore(STORE_NAME).delete(id)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error ?? new Error('indexeddb_delete_failed'))
    })
  } catch {
    // Best effort — missing audio in IndexedDB should not block the user.
  }
}

export function generateRecordingId() {
  return `rec-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export interface PendingMeeting {
  id: string
  ownerId: string
  workspace: import('../stores/teamStore').WorkspaceSelection
  options: import('./meetingCapture').MeetingCaptureOptions
  startedAt: string
  endedAt?: string
  fileName?: string
  elapsedSeconds: number
  transcript?: import('../types/liveTranscript').LiveTranscriptSegment[]
  transcriptStatus?: import('../types/liveTranscript').LiveTranscriptStatus
  realtimeDiagnostics?: import('../types/liveTranscript').LiveTranscriptDiagnostics
}

export async function savePendingMeeting(meeting: PendingMeeting) {
  const db = await openDatabase()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).put(meeting, `pending:${meeting.id}`)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
    tx.onabort = () => reject(tx.error)
  })
}

export async function listPendingMeetings(ownerId: string): Promise<PendingMeeting[]> {
  if (!isIndexedDBSupported()) return []
  const db = await openDatabase()
  return new Promise((resolve, reject) => {
    const result: PendingMeeting[] = []
    const tx = db.transaction(STORE_NAME, 'readonly')
    const request = tx.objectStore(STORE_NAME).openCursor(IDBKeyRange.bound('pending:', 'pending:\uffff'))
    request.onsuccess = () => {
      const cursor = request.result
      if (!cursor) return
      if (cursor.value.ownerId === ownerId) result.push(cursor.value)
      cursor.continue()
    }
    tx.oncomplete = () => resolve(result)
    tx.onerror = () => reject(tx.error)
  })
}

export function deletePendingMeeting(id: string) { return deleteRecordedAudio(`pending:${id}`) }

/** User-visible deletion must report storage failures, unlike best-effort cleanup. */
export async function deleteLocalRecording(id: string, ownerId: string) {
  const db = await openDatabase()
  const metadata = await new Promise<PendingMeeting>((resolve, reject) => {
    const request = db.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).get(`pending:${id}`)
    request.onsuccess = () => request.result?.ownerId === ownerId ? resolve(request.result) : reject(new Error('录制不存在或无权删除'))
    request.onerror = () => reject(request.error)
  })
  if (metadata.fileName) await removeSavedRecordingFile(metadata.fileName)
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    const request = store.get(`pending:${id}`)
    request.onsuccess = () => {
      const recording = request.result as PendingMeeting | undefined
      if (!recording || recording.ownerId !== ownerId) { tx.abort(); return }
      store.delete(id)
      store.delete(`pending:${id}`)
    }
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error ?? new Error('无法删除录制文件'))
    tx.onabort = () => reject(new Error('录制不存在、无权删除或存储操作失败'))
  })
}
