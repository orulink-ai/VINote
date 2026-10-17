import { beforeEach, describe, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ json: vi.fn(), fetch: vi.fn(), reset: vi.fn() }))
vi.mock('../lib/api', async importOriginal => ({ ...await importOriginal<typeof import('../lib/api')>(), apiJson: mocks.json, apiFetch: mocks.fetch }))
vi.mock('./modelProfileStore', () => ({ useModelProfileStore: { getState: () => ({ reset: mocks.reset }) } }))
vi.mock('./sttProfileStore', () => ({ useSTTProfileStore: { getState: () => ({ reset: mocks.reset }) } }))
vi.mock('./noteLibraryStore', () => ({ useNoteLibraryStore: { getState: () => ({ reset: mocks.reset }) } }))
vi.mock('./teamStore', () => ({ useTeamStore: { getState: () => ({ reset: mocks.reset }) } }))
vi.mock('./workspaceStore', () => ({ useWorkspaceStore: { getState: () => ({ reset: mocks.reset }) } }))
import { ApiError } from '../lib/api'
import { useAuthStore } from './authStore'
const user = { id: 'account-a', email: 'a@example.test' }
describe('session recovery and isolation', () => {
  beforeEach(() => { vi.clearAllMocks(); useAuthStore.setState({ user: null, initialized: false, loading: false, status: 'checking', sessionError: '' }) })
  it('retains a previously verified identity after transport failure', async () => {
    useAuthStore.setState({ user, status: 'authenticated', initialized: true })
    mocks.json.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await useAuthStore.getState().initialize()
    expect(useAuthStore.getState()).toMatchObject({ user, status: 'offline-known', initialized: true })
    expect(mocks.reset).not.toHaveBeenCalled()
  })
  it('does not turn a cold-start service failure into sign-out or expose an unverified identity', async () => {
    mocks.json.mockRejectedValueOnce(new ApiError('Unavailable', 503, null))
    await useAuthStore.getState().initialize()
    expect(useAuthStore.getState()).toMatchObject({ user: null, status: 'checking', initialized: true })
    expect(useAuthStore.getState().sessionError).not.toBe('')
  })
  it('locks the previous account on explicit 401', async () => {
    useAuthStore.setState({ user, status: 'authenticated' })
    mocks.json.mockRejectedValueOnce(new ApiError('Expired', 401, null))
    await useAuthStore.getState().initialize()
    expect(useAuthStore.getState()).toMatchObject({ user: null, status: 'expired' })
    expect(mocks.reset).toHaveBeenCalledTimes(5)
  })
  it('does not restore account A from a late session request after logout', async () => {
    useAuthStore.setState({ user, status: 'authenticated' })
    let resolve!: (value: unknown) => void
    mocks.json.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const checking = useAuthStore.getState().initialize()
    mocks.fetch.mockResolvedValueOnce({ ok: true })
    await useAuthStore.getState().signOut()
    resolve({ authenticated: true, user }); await checking
    expect(useAuthStore.getState()).toMatchObject({ user: null, status: 'signed-out' })
  })
  it('keeps the current account when sign-out fails', async () => {
    useAuthStore.setState({ user, status: 'authenticated' })
    mocks.fetch.mockResolvedValueOnce({ ok: false })
    await expect(useAuthStore.getState().signOut()).rejects.toThrow('退出未完成')
    expect(useAuthStore.getState().user).toEqual(user)
  })
  it('clears all user stores before accepting account B', async () => {
    useAuthStore.setState({ user, status: 'authenticated' })
    const other = { id: 'account-b', email: 'b@example.test' }
    mocks.json.mockResolvedValueOnce(other)
    await useAuthStore.getState().signIn(other.email, 'test-password')
    expect(useAuthStore.getState()).toMatchObject({ user: other, status: 'authenticated', sessionError: '' })
    expect(mocks.reset).toHaveBeenCalledTimes(5)
  })
})
