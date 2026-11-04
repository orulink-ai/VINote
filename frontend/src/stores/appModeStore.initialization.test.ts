import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => { vi.unstubAllGlobals() })

for (const entry of ['./authStore', './appModeStore', '../lib/modelSourceIdentity']) {
  it(`initializes real stores from ${entry}, with no requests and synchronous ABA invalidation`, async () => {
    vi.resetModules()
    const fetch = vi.fn(() => { throw new Error('Module loading must not send requests') })
    vi.stubGlobal('fetch', fetch)
    // Keep the real auth/workspace/profile import graph; mocking those stores
    // would conceal initialization-order failures.
    await import(entry)
    const { useAuthStore } = await import('./authStore')
    const { useAppModeStore } = await import('./appModeStore')
    const { modelSourceScope } = await import('../lib/modelSourceIdentity')
    const alice = { id: 'alice', email: 'alice@example.invalid' }
    useAuthStore.setState({ user: alice })
    useAppModeStore.setState({ config: { mode: 'cloud', configured: true, asr_model: 'asr', llm_model: 'llm' }, saving: true })
    const original = modelSourceScope()
    expect(original()).toBe(true)
    useAuthStore.setState({ user: { id: 'bob', email: 'bob@example.invalid' } })
    useAuthStore.setState({ user: alice })
    expect(original()).toBe(false)
    expect(modelSourceScope()()).toBe(true)
    expect(useAppModeStore.getState()).toMatchObject({ config: null, saving: false })
    expect(fetch).not.toHaveBeenCalled()
  })
}
