import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { I18nProvider } from '../lib/i18n'
import { Settings } from './Settings'

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
  it('keeps the settings canvas responsive within the main area', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <I18nProvider>
          <Settings />
        </I18nProvider>
      </MemoryRouter>
    )

    const page = screen.getByRole('heading', { name: '设置' }).parentElement?.parentElement as HTMLElement

    expect(page.className).toContain('w-full')
    expect(screen.getByRole('navigation')).toBeInTheDocument()
  })
})
