import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { EmailLogin } from './EmailLogin'
import { apiJson } from '../lib/api'

vi.mock('../lib/api', () => ({ apiJson: vi.fn() }))

it('keeps registration credentials fixed after the resend cooldown', async () => {
  vi.useFakeTimers()
  try {
    vi.mocked(apiJson).mockResolvedValue({})
    render(<MemoryRouter><EmailLogin isLogin={false} onSwitch={() => {}} /></MemoryRouter>)
    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'a@example.com' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password-one' } })
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'password-one' } })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '获取验证码' })) })
    for (let i = 0; i < 60; i++) await act(async () => { vi.advanceTimersByTime(1000) })
    expect(screen.getByRole('button', { name: '获取验证码' })).toBeEnabled()
    expect(screen.getByLabelText('邮箱')).toBeDisabled()
    expect(screen.getByLabelText('密码')).toBeDisabled()
    expect(screen.getByLabelText('确认密码')).toBeDisabled()
    expect(screen.getByLabelText('验证码')).toBeEnabled()
  } finally { vi.useRealTimers() }
})
