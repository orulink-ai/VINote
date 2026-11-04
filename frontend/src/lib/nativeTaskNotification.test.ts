import { afterEach, expect, it, vi } from 'vitest'
import { deliverNativeNotification, enableNativeNotifications } from './nativeTaskNotification'
const mock = vi.hoisted(() => ({ permission: vi.fn(), request: vi.fn(), invoke: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: mock.invoke }))
vi.mock('@tauri-apps/plugin-notification', () => ({ isPermissionGranted: mock.permission, requestPermission: mock.request, onAction: vi.fn() }))
afterEach(() => { delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; vi.clearAllMocks() })
it('never requests permission during delivery, and no permission returns in-app fallback', async () => {
  Object.assign(window, { __TAURI_INTERNALS__: {} }); mock.permission.mockResolvedValue(false)
  expect(await deliverNativeNotification(1, '完成')).toBe(false)
  expect(mock.request).not.toHaveBeenCalled(); expect(mock.invoke).not.toHaveBeenCalled()
})
it('only explicit enable requests permission', async () => {
  Object.assign(window, { __TAURI_INTERNALS__: {} }); mock.permission.mockResolvedValue(false); mock.request.mockResolvedValue('granted')
  expect(await enableNativeNotifications()).toBe(true)
  expect(mock.request).toHaveBeenCalledTimes(1)
})
it('awaits native delivery and cancels account-stale delivery', async () => {
  Object.assign(window, { __TAURI_INTERNALS__: {} }); mock.permission.mockResolvedValue(true)
  expect(await deliverNativeNotification(1, '完成', () => false)).toBe(false)
  expect(mock.invoke).not.toHaveBeenCalled()
  mock.invoke.mockRejectedValue(new Error('unavailable'))
  await expect(deliverNativeNotification(1, '完成')).rejects.toThrow('unavailable')
})
