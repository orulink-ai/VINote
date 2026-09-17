import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../lib/i18n'
import { SettingsNav } from './SettingsNav'

vi.mock('../../stores/languageStore', () => ({
  useLanguageStore: () => ({
    language: 'zh-CN',
    setLanguage: vi.fn(),
    syncWithAccount: vi.fn(),
  }),
}))

describe('SettingsNav', () => {
  it('stays visible while settings content scrolls and uses compact desktop width', () => {
    render(
      <I18nProvider>
        <SettingsNav activeTab="models" onChange={vi.fn()} />
      </I18nProvider>
    )

    const nav = screen.getByRole('navigation')
    expect(nav.className).toContain('lg:sticky')
    expect(nav.className).toContain('lg:top-6')
    expect(nav.className).toContain('lg:self-start')
    expect(nav.className).toContain('lg:w-56')

    const modelsTab = screen.getByRole('button', { name: '模型' })
    expect(modelsTab.className).toContain('gap-2')
    expect(modelsTab.className).toContain('px-4')
  })
})
