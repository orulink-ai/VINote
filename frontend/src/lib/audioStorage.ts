import { removeSavedRecordingFile } from './recordingFile'
// Persists recorded audio blobs in IndexedDB so a meeting recording can be
// retried even after the recorder window is closed, the page is reloaded, or
// the device restarts. The blob is keyed by an opaque recording id that is
// also written into the meeting recorder store, so we can recover it from
// the note detail page later.

const DB_NAME = 'vinote-meeting-audio'
const DB_VERSION = 2
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
    request.onerror = () => { dbPromise = null; reject(request.error ?? new Error('indexeddb_open_failed')) }
    request.onblocked = () => { dbPromise = null; reject(new Error('indexeddb_open_blocked')) }
  })
  return dbPromise
}

export async function saveRecordedAudio(id: string, blob: Blob): Promise<void> {
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
  recordingStatus: 'saved' | 'save_failed'
  processingStatus: 'idle' | 'queued' | 'preparing_media' | 'transcribing' | 'diarizing' | 'aligning' | 'analyzing_video' | 'generating' | 'saving_result' | 'completed' | 'failed'
  taskId?: string
  noteId?: string
  failedStage?: string
  processingError?: string
  processingUpdatedAt?: string
  retryCount?: number
  draftNoteId?: string
  progress?: number
  processedSeconds?: number
  totalSeconds?: number
  etaSeconds?: number
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

export async function getPendingMeeting(id: string): Promise<PendingMeeting | null> {
  if (!isIndexedDBSupported()) return null
  const db = await openDatabase()
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).get(`pending:${id}`)
    request.onsuccess = () => resolve((request.result as PendingMeeting | undefined) ?? null)
    request.onerror = () => reject(request.error ?? new Error('indexeddb_read_failed'))
  })
}

export async function updatePendingMeeting(
  id: string,
  update: Partial<Omit<PendingMeeting, 'id' | 'ownerId'>>,
): Promise<PendingMeeting> {
  const db = await openDatabase()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    const request = store.get(`pending:${id}`)
    let next: PendingMeeting | undefined
    request.onsuccess = () => {
      const current = request.result as PendingMeeting | undefined
      if (!current) { tx.abort(); return }
      next = { ...current, ...update, id: current.id, ownerId: current.ownerId }
      store.put(next, `pending:${id}`)
    }
    tx.oncomplete = () => next ? resolve(next) : reject(new Error('recording_not_found'))
    tx.onerror = () => reject(tx.error ?? new Error('indexeddb_write_failed'))
    tx.onabort = () => reject(tx.error ?? new Error('recording_not_found'))
  })
}

export async function listPendingMeetings(ownerId: string): Promise<PendingMeeting[]> {
  if (!isIndexedDBSupported()) return []
  const db = await openDatabase()
  // Resume physical cleanup after a failed removal or application restart.
  const cleanupIds = await new Promise<string[]>((resolve, reject) => {
    const ids: string[] = []
    const tx = db.transaction(STORE_NAME, 'readonly')
    const request = tx.objectStore(STORE_NAME).openCursor(IDBKeyRange.bound('cleanup:', 'cleanup:\uffff'))
    request.onsuccess = () => {
      const cursor = request.result
      if (!cursor) return
      if (cursor.value.ownerId === ownerId) ids.push(cursor.value.id)
      cursor.continue()
    }
    tx.oncomplete = () => resolve(ids)
    tx.onerror = () => reject(tx.error)
  })
  for (const id of cleanupIds) await deleteLocalRecording(id, ownerId).catch(() => undefined)
  return new Promise((resolve, reject) => {
    const result: PendingMeeting[] = []
    const tx = db.transaction(STORE_NAME, 'readonly')
    const request = tx.objectStore(STORE_NAME).openCursor(IDBKeyRange.bound('pending:', 'pending:\uffff'))
    request.onsuccess = () => {
      const cursor = request.result
      if (!cursor) return
      if (cursor.value.ownerId === ownerId) {
        const value = cursor.value as PendingMeeting
        result.push({
          ...value,
          recordingStatus: value.recordingStatus || 'saved',
          processingStatus: value.processingStatus || 'idle',
        })
      }
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
    const store = db.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME)
    const request = store.get(`pending:${id}`)
    const accept = (value: PendingMeeting | undefined) => value?.ownerId === ownerId ? resolve(value) : reject(new Error('录制不存在或无权删除'))
    request.onsuccess = () => {
      if (request.result) { accept(request.result); return }
      const cleanup = store.get(`cleanup:${id}`)
      cleanup.onsuccess = () => accept(cleanup.result)
      cleanup.onerror = () => reject(cleanup.error)
    }
    request.onerror = () => reject(request.error)
  })
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    const request = store.get(`pending:${id}`)
    request.onsuccess = () => {
      const recording = request.result as PendingMeeting | undefined
      if (!recording) return // A previous attempt already committed IDB deletion.
      if (recording.ownerId !== ownerId) { tx.abort(); return }
      store.delete(id)
      store.delete(`pending:${id}`)
      // Keep a cleanup receipt if OPFS removal fails or the app exits.
      if (recording.fileName) store.put(recording, `cleanup:${id}`)
    }
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error ?? new Error('无法删除录制文件'))
    tx.onabort = () => reject(new Error('录制不存在、无权删除或存储操作失败'))
  })
  // Never invalidate an OPFS-backed Blob before its IDB deletion commits.
  if (metadata.fileName) {
    await removeSavedRecordingFile(metadata.fileName)
    await deleteRecordedAudio(`cleanup:${id}`)
  }
}
