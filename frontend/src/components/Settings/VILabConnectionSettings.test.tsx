import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { VILabConnectionSettings } from './VILabConnectionSettings'
import { useAppModeStore } from '@/stores/appModeStore'
import { useAuthStore } from '@/stores/authStore'
import { apiJson } from '@/lib/api'

vi.mock('@/lib/api', () => ({ apiJson: vi.fn() }))
vi.mock('@/lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }))
vi.mock('@/stores/modelProfileStore', () => ({ useModelProfileStore: { getState: () => ({ selectProfile: vi.fn(), loadProfiles: vi.fn() }) } }))
vi.mock('@/stores/sttProfileStore', () => ({ useSTTProfileStore: { getState: () => ({ selectProfile: vi.fn(), loadProfiles: vi.fn() }) } }))

const config = { configured: true, mode: 'cloud' as const, server_url: 'https://original.example', asr_model: 'old-asr', llm_model: 'old-llm', connection_protocol: 1 }
const checked = { check_id: 'opaque-check', server_url: 'http://127.0.0.1:9876', expires_in: 600, asr_model: '', llm_model: '', models: [{ id: 'new-llm', modelType: 'llm', runtimeStatus: 'available' }] }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }

beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = vi.fn()
  HTMLElement.prototype.hasPointerCapture = vi.fn(() => false)
  HTMLElement.prototype.setPointerCapture = vi.fn()
  HTMLElement.prototype.releasePointerCapture = vi.fn()
  useAuthStore.setState({ user: { id: 'alice', email: 'alice@example.invalid' } })
  useAppModeStore.getState().reset(); useAppModeStore.setState({ config })
  vi.mocked(apiJson).mockReset()
  vi.mocked(apiJson).mockImplementation(async path => {
    if (path.endsWith('/connections')) return { connections: [{ connection_id: 'default', server_url: config.server_url, builtin: true }, { connection_id: 'saved', server_url: 'https://saved.example', has_credential: true }] }
    if (path.endsWith('/check')) return checked
    return { ...config, connection_id: 'new-id', connection_revision: 'r2', server_url: checked.server_url, asr_model: '', llm_model: '' }
  })
})

async function newConnection(authMode: 'account' | 'api_key' = 'api_key', url = checked.server_url) {
  render(<VILabConnectionSettings config={config} />)
  await userEvent.click(screen.getByRole('button', { name: '管理连接' }))
  await waitFor(() => expect(screen.getByRole('combobox', { name: '服务连接' })).not.toBeDisabled())
  await userEvent.click(screen.getByRole('combobox', { name: '服务连接' }))
  await userEvent.click(screen.getByRole('option', { name: '添加外部 VILab' }))
  await userEvent.type(screen.getByLabelText('VILab 服务地址'), url)
  if (authMode === 'api_key') {
    await userEvent.click(screen.getByRole('combobox', { name: '认证方式' }))
    await userEvent.click(screen.getByRole('option', { name: '此连接的 API key' }))
  }
}

it('checks catalog without switching, then explicitly saves without sending keys in the save body', async () => {
  await newConnection()
  expect(screen.getByRole('button', { name: '保存并使用' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('此连接的访问密钥（可选）'), 'new-secret')
  await userEvent.click(screen.getByRole('button', { name: '检查连接' }))
  await screen.findByText('已读取 1 个模型，尚未切换服务。')
  expect(useAppModeStore.getState().config?.server_url).toBe(config.server_url)
  expect(vi.mocked(apiJson).mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(0)
  await userEvent.click(screen.getByRole('button', { name: '保存并使用' }))
  await waitFor(() => expect(useAppModeStore.getState().config?.server_url).toBe(checked.server_url))
  const put = vi.mocked(apiJson).mock.calls.find(([, init]) => init?.method === 'PUT')!
  expect(put[0]).toBe('/api/vilab/connection')
  expect(JSON.parse(put[1]!.body as string)).toEqual({ check_id: 'opaque-check', asr_model: '', llm_model: '' })
})

it('closing a checked draft performs no PUT and keeps the current connection', async () => {
  await newConnection(); await userEvent.click(screen.getByRole('button', { name: '检查连接' }))
  await screen.findByText('已读取 1 个模型，尚未切换服务。')
  await userEvent.click(screen.getByRole('button', { name: '关闭连接设置' }))
  expect(useAppModeStore.getState().config).toEqual(config)
  expect(vi.mocked(apiJson).mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
})

it('URL editing clears the key and invalidates a late catalog result', async () => {
  const pending = deferred<typeof checked>()
  await newConnection()
  await userEvent.type(screen.getByLabelText('此连接的访问密钥（可选）'), 'old-draft-key')
  vi.mocked(apiJson).mockImplementationOnce(() => pending.promise)
  await userEvent.click(screen.getByRole('button', { name: '检查连接' }))
  await userEvent.type(screen.getByLabelText('VILab 服务地址'), '0')
  expect(screen.getByLabelText('此连接的访问密钥（可选）')).toHaveValue('')
  await act(async () => pending.resolve(checked))
  expect(screen.queryByText('已读取 1 个模型，尚未切换服务。')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '保存并使用' })).toBeDisabled()
})

it('failed save retains the checked draft and permits an explicit retry', async () => {
  await newConnection(); await userEvent.click(screen.getByRole('button', { name: '检查连接' }))
  await screen.findByText('已读取 1 个模型，尚未切换服务。')
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('连接检查已过期，请重新检查；尚未切换'))
  await userEvent.click(screen.getByRole('button', { name: '保存并使用' }))
  await screen.findByText('连接检查已过期，请重新检查；尚未切换')
  expect(screen.getByLabelText('VILab 服务地址')).toHaveValue(checked.server_url)
  expect(screen.getByRole('button', { name: '检查连接' })).not.toBeDisabled()
  expect(useAppModeStore.getState().config?.server_url).toBe(config.server_url)
})

it('account A→B→A rejects a pending save and clears its busy state', async () => {
  const pending = deferred<typeof config>()
  vi.mocked(apiJson).mockImplementationOnce(() => pending.promise)
  const save = useAppModeStore.getState().saveConnection('old-check', '', '')
  act(() => {
    useAuthStore.setState({ user: { id: 'bob', email: 'bob@example.invalid' } })
    useAuthStore.setState({ user: { id: 'alice', email: 'alice@example.invalid' } })
    useAppModeStore.setState({ config: { ...config, server_url: 'https://current.example' } })
  })
  await act(async () => { pending.resolve(config); await save })
  expect(useAppModeStore.getState().config?.server_url).toBe('https://current.example')
  expect(useAppModeStore.getState().saving).toBe(false)
})

it('account change dismisses and discards a pending check without saving', async () => {
  const pending = deferred<typeof checked>()
  await newConnection(); vi.mocked(apiJson).mockImplementationOnce(() => pending.promise)
  await userEvent.click(screen.getByRole('button', { name: '检查连接' }))
  act(() => useAuthStore.setState({ user: { id: 'bob', email: 'bob@example.invalid' } }))
  await act(async () => pending.resolve(checked))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(vi.mocked(apiJson).mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
})

it('connection list failure is shown as failure with a GET-only retry', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('连接列表读取失败'))
  render(<VILabConnectionSettings config={config} />)
  await userEvent.click(screen.getByRole('button', { name: '管理连接' }))
  await screen.findByText('连接列表读取失败')
  await userEvent.click(screen.getByRole('button', { name: '重新读取连接' }))
  await waitFor(() => expect(screen.queryByText('连接列表读取失败')).not.toBeInTheDocument())
  expect(vi.mocked(apiJson).mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it.each(['http://192.168.1.143:9876', 'https://api.orulink.ai'])('uses shared account only after an explicit check of %s, without an API key', async origin => {
  await newConnection('account', origin)
  expect(screen.getByRole('combobox', { name: '认证方式' })).toHaveTextContent('已登录的 VINote 账号')
  expect(screen.queryByLabelText('此连接的访问密钥（可选）')).not.toBeInTheDocument()
  expect(vi.mocked(apiJson).mock.calls.every(([, init]) => !init?.method)).toBe(true)
  vi.mocked(apiJson).mockResolvedValueOnce({ ...checked, server_url: origin, auth_mode: 'account' })
  await userEvent.click(screen.getByRole('button', { name: '用已登录账号检查' }))
  await screen.findByText('已读取 1 个模型，尚未切换服务。')
  const call = vi.mocked(apiJson).mock.calls.find(([path]) => path.endsWith('/check'))!
  expect(JSON.parse(call[1]!.body as string)).toEqual({ server_url: origin, auth_mode: 'account', account_consent: true, authorized_origin: origin })
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  expect(useAppModeStore.getState().config?.server_url).toBe(config.server_url)
})

it('an arbitrary account Origin requires exact confirmation; cancelling sends no check', async () => {
  await newConnection('account', 'https://custom.example')
  await userEvent.click(screen.getByRole('button', { name: '用已登录账号检查' }))
  expect(await screen.findByRole('alertdialog')).toHaveTextContent('https://custom.example')
  expect(vi.mocked(apiJson).mock.calls.every(([, init]) => !init?.method)).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: '取消', exact: true }))
  expect(vi.mocked(apiJson).mock.calls.every(([, init]) => !init?.method)).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: '用已登录账号检查' }))
  await userEvent.click(screen.getByRole('button', { name: '同意并检查此地址' }))
  await screen.findByText('已读取 1 个模型，尚未切换服务。')
  const call = vi.mocked(apiJson).mock.calls.find(([path]) => path.endsWith('/check'))!
  expect(JSON.parse(call[1]!.body as string).authorized_origin).toBe('https://custom.example')
})
