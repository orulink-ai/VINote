import { afterEach, describe, expect, it, vi } from 'vitest'

const removeFile = vi.hoisted(() => vi.fn())
vi.mock('./recordingFile', () => ({ removeSavedRecordingFile: removeFile }))

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); vi.clearAllMocks() })

describe('local recording deletion', () => {
  it('does not remove an OPFS file when the recording changed before the write transaction', async () => {
    const original = { id: 'rec', ownerId: 'owner', fileName: 'old.webm' }
    const changed = { ...original, fileName: 'new.webm' }
    const db = { transaction: (_store: string, mode: string) => {
      const tx = {
        error: null, oncomplete: () => {}, onerror: () => {}, onabort: () => {},
        abort: () => tx.onabort(),
        objectStore: () => ({
          get: () => {
            const request = { result: mode === 'readonly' ? original : changed, onsuccess: () => {}, onerror: () => {} }
            queueMicrotask(() => { request.onsuccess(); if (mode === 'readwrite') tx.oncomplete() })
            return request
          },
          put: () => {}, delete: () => { queueMicrotask(() => tx.oncomplete()) },
        }),
      }
      return tx
    } }
    vi.stubGlobal('indexedDB', { open: () => {
      const request = { result: db, onsuccess: () => {} }
      queueMicrotask(() => request.onsuccess())
      return request
    } })
    const { deleteLocalRecording } = await import('./audioStorage')
    await expect(deleteLocalRecording('rec', 'owner')).rejects.toThrow()
    expect(removeFile).not.toHaveBeenCalled()
  })
  it.each([true, false])('keeps OPFS until IDB commits (abort=%s)', async abort => {
    const events: string[] = []
    const metadata = { id: 'rec', ownerId: 'owner', fileName: 'meeting-file.webm' }
    const db = { transaction: (_store: string, mode: string) => {
      const tx = {
        error: new Error('storage failure'), oncomplete: () => {}, onerror: () => {}, onabort: () => {},
        abort: () => tx.onabort(),
        objectStore: () => ({
          get: () => {
            const request = { result: metadata, onsuccess: () => {}, onerror: () => {} }
            queueMicrotask(() => {
              request.onsuccess()
            })
            return request
          },
          openCursor: () => {
            const request = { result: null, onsuccess: () => {} }
            queueMicrotask(() => {
              events.push(abort ? 'abort' : 'commit')
              if (abort) tx.onabort(); else { request.onsuccess(); tx.oncomplete() }
            })
            return request
          },
          put: () => {},
          delete: () => { queueMicrotask(() => tx.oncomplete()) },
        }),
      }
      return tx
    } }
    vi.stubGlobal('indexedDB', { open: () => {
      const request = { result: db, onsuccess: () => {} }
      queueMicrotask(() => request.onsuccess())
      return request
    } })
    removeFile.mockImplementation(async () => { events.push('remove-file') })
    const { deleteLocalRecording } = await import('./audioStorage')
    if (abort) {
      await expect(deleteLocalRecording('rec', 'owner')).rejects.toThrow()
      expect(removeFile).not.toHaveBeenCalled()
    } else {
      await deleteLocalRecording('rec', 'owner')
      expect(events.slice(0, 2)).toEqual(['commit', 'remove-file'])
    }
  })
})
