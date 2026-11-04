import '@testing-library/jest-dom/vitest'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock as typeof ResizeObserver

// Node 26 exposes its own localStorage on globalThis and leaves it unusable
// unless --localstorage-file is passed. jsdom's Storage has to win so tests
// keep exercising the same implementation the browser app runs on.
const storageHost = globalThis.window
for (const key of ['localStorage', 'sessionStorage'] as const) {
  if (globalThis[key] !== storageHost[key]) {
    Object.defineProperty(globalThis, key, {
      configurable: true,
      get: () => storageHost[key],
    })
  }
}
if (globalThis.Storage !== storageHost.Storage) {
  Object.defineProperty(globalThis, 'Storage', {
    configurable: true,
    value: storageHost.Storage,
  })
}
