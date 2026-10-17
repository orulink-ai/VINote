import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { I18nProvider } from '../lib/i18n'
import { Settings } from './Settings'

vi.mock('@/components/Settings/ModelSourcePanel', () => ({ ModelSourcePanel: () => <p>模型配置</p> }))

function Destination() {
  const location = useLocation()
  return <output aria-label="当前路径">{location.pathname + location.search + location.hash}</output>
}

function renderSettings(path: string, state?: { returnTo: string }) {
  return render(<MemoryRouter initialEntries={[{ pathname: '/settings', search: path.split('?')[1] ? '?' + path.split('?')[1] : '', state }]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><I18nProvider><Routes>
    <Route path="/settings" element={<Settings />} />
    <Route path="/meetings" element={<Destination />} />
    <Route path="/notes" element={<Destination />} />
    <Route path="/connections" element={<Destination />} />
  </Routes></I18nProvider></MemoryRouter>)
}

vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({ initialized: true, user: { id: 'user-1', email: 'user@example.com' } }),
}))

vi.mock('../stores/languageStore', () => ({
  useLanguageStore: () => ({
    language: 'zh-CN',
    setLanguage: vi.fn(),
    syncWithAccount: vi.fn(),
  }),
}))

vi.mock('../stores/themeStore', () => ({
  useThemeStore: () => ({ theme: 'light', setTheme: vi.fn() }),
}))

describe('Settings page layout', () => {
  afterEach(cleanup)
  it('keeps the settings canvas responsive within the main area', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <I18nProvider>
          <Settings />
        </I18nProvider>
      </MemoryRouter>
    )

    const page = screen.getByRole('heading', { name: '设置' }).closest('.workspace-page') as HTMLElement

    expect(page).not.toBeNull()
    expect(screen.getByRole('navigation')).toBeInTheDocument()
  })
  it('keeps team management out of the account panel and exposes an explicit parent', () => {
    render(<MemoryRouter initialEntries={['/settings?tab=profile']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><I18nProvider><Settings /></I18nProvider></MemoryRouter>)
    expect(screen.queryByRole('link', { name: /管理已有团队/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回设置总览' })).toHaveAttribute('href', '/settings')
    expect(screen.getByText('user@example.com')).toBeInTheDocument()
  })

  it('preserves the original meeting filter and hash through overview links and tab changes', async () => {
    const parent = '/meetings?archived=1&q=pdf#selected'
    renderSettings('/settings?' + new URLSearchParams({ returnTo: parent }).toString())
    const user = userEvent.setup()
    const models = screen.getByRole('link', { name: /转写与总结/ })
    expect(new URL(models.getAttribute('href')!, 'https://vinote.invalid').searchParams.get('returnTo')).toBe(parent)
    await user.click(models)
    expect(screen.getByText('模型配置')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '外观与语言' }))
    expect(new URL(screen.getByRole('link', { name: '返回设置总览' }).getAttribute('href')!, 'https://vinote.invalid').searchParams.get('returnTo')).toBe(parent)
    await user.click(screen.getByRole('link', { name: '返回设置总览' }))
    expect(screen.getByRole('link', { name: '返回会议' })).toHaveAttribute('href', parent)
    await user.click(screen.getByRole('link', { name: '返回会议' }))
    expect(screen.getByLabelText('当前路径')).toHaveTextContent(parent)
  })

  it('makes a state-only source durable in links before returning to the overview', async () => {
    const parent = '/notes?project=Review&q=word#row'
    renderSettings('/settings?tab=profile', { returnTo: parent })
    const back = screen.getByRole('link', { name: '返回设置总览' })
    expect(new URL(back.getAttribute('href')!, 'https://vinote.invalid').searchParams.get('returnTo')).toBe(parent)
    await userEvent.click(back)
    expect(screen.getByRole('link', { name: '返回笔记' })).toHaveAttribute('href', parent)
  })

  it('returns child recovery pages to the storage section before the source meeting', () => {
    const parent = '/meetings?archived=1&q=pdf#selected'
    renderSettings('/settings?' + new URLSearchParams({ tab: 'storage', returnTo: parent }).toString())
    for (const name of [/内容与回收站/, /任务与恢复/]) {
      const child = new URL(screen.getByRole('link', { name }).getAttribute('href')!, 'https://vinote.invalid')
      const section = new URL(child.searchParams.get('returnTo')!, 'https://vinote.invalid')
      expect(section.pathname).toBe('/settings')
      expect(section.searchParams.get('tab')).toBe('storage')
      expect(section.searchParams.get('returnTo')).toBe(parent)
    }
  })

  it.each([undefined, 'https://outside.invalid', '//outside.invalid', '/unsupported', '/settings', '/settings?tab=models', '/settings/sync?returnTo=%2Fmeetings'])('does not invent an overview parent for missing, unsafe or self-referential parents (%s)', parent => {
    renderSettings('/settings' + (parent === undefined ? '' : '?' + new URLSearchParams({ returnTo: parent }).toString()))
    expect(screen.queryByRole('link', { name: /^返回/ })).not.toBeInTheDocument()
  })

  it('uses a valid state parent when a URL parent is invalid and keeps the overview as the first step', async () => {
    renderSettings('/settings?tab=models&returnTo=https%3A%2F%2Foutside.invalid', { returnTo: '/meetings?q=review' })
    const overview = screen.getByRole('link', { name: '返回设置总览' })
    expect(overview).toHaveAttribute('href', '/settings?returnTo=%2Fmeetings%3Fq%3Dreview')
    await userEvent.click(overview)
    expect(screen.getByRole('link', { name: '返回会议' })).toHaveAttribute('href', '/meetings?q=review')
  })

  it('keeps a safe source when following the legacy connections tab redirect', async () => {
    const parent = '/meetings?archived=1#row'
    renderSettings('/settings?' + new URLSearchParams({ tab: 'connections', returnTo: parent }).toString())
    const target = new URL((await screen.findByLabelText('当前路径')).textContent!, 'https://vinote.invalid')
    expect(target.pathname).toBe('/connections')
    expect(target.searchParams.get('returnTo')).toBe(parent)
  })
})
