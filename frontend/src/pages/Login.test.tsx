vi.mock("../lib/api", () => ({ apiJson: vi.fn().mockResolvedValue({ email_code: false }) }))
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { I18nProvider } from '../lib/i18n'
import { Login } from './Login'

const authStoreMock = vi.hoisted(() => ({
  signIn: vi.fn(),
  signUp: vi.fn(),
}))
const navigateMock = vi.hoisted(() => vi.fn())

vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    signIn: authStoreMock.signIn,
    signUp: authStoreMock.signUp,
  }),
}))

vi.mock('../stores/languageStore', () => ({
  useLanguageStore: () => ({
    language: 'en',
    setLanguage: vi.fn(),
    syncWithAccount: vi.fn(),
  }),
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
}))

function renderLogin() {
  return render(
    <I18nProvider>
      <Login />
    </I18nProvider>
  )
}

describe('Login sign up form', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authStoreMock.signIn.mockResolvedValue({ error: null, user: { id: 'user-1', email: 'user@example.com' } })
    authStoreMock.signUp.mockResolvedValue({ error: null, user: { id: 'user-1', email: 'user@example.com' } })
  })

  it('shows confirm password and password rules only while creating an account', async () => {
    renderLogin()

    expect(screen.queryByLabelText('Confirm password')).not.toBeInTheDocument()

    await userEvent.click(await screen.findByRole('button', { name: 'Create account' }))

    expect(screen.getByLabelText('Confirm password')).toBeInTheDocument()
    expect(screen.getByText('Password must be at least 6 characters.')).toBeInTheDocument()
  })

  it('blocks sign up when the confirmation password does not match', async () => {
    renderLogin()

    await userEvent.click(await screen.findByRole('button', { name: 'Create account' }))
    await userEvent.type(screen.getByLabelText('Email'), 'user@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'abcdef')
    await userEvent.type(screen.getByLabelText('Confirm password'), 'abcdeg')
    await userEvent.click(screen.getByRole('button', { name: 'Sign up' }))

    expect(await screen.findByText('Passwords do not match.')).toBeInTheDocument()
    await waitFor(() => expect(authStoreMock.signUp).not.toHaveBeenCalled())
  })
})
