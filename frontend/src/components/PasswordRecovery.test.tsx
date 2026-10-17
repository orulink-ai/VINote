import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { PasswordRecovery } from './PasswordRecovery'
import { apiJson } from '../lib/api'
vi.mock('../lib/api', () => ({ apiJson: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
it('blocks mismatched passwords and returns to login after recovery', async () => {
  const back = vi.fn()
  vi.mocked(apiJson).mockResolvedValue({message: '密码已更新，请使用新密码登录。'})
  render(<PasswordRecovery email="a@example.com" onBack={back} />)
  await userEvent.type(screen.getByLabelText('验证码'), '12345678')
  await userEvent.type(screen.getByLabelText('新密码'), 'password-one')
  await userEvent.type(screen.getByLabelText('确认新密码'), 'password-two')
  await userEvent.click(screen.getByRole('button', {name:'确认重设密码'}))
  expect(screen.getByRole('alert')).toHaveTextContent('两次密码不一致')
  expect(apiJson).not.toHaveBeenCalled()
  await userEvent.clear(screen.getByLabelText('确认新密码'))
  await userEvent.type(screen.getByLabelText('确认新密码'), 'password-one')
  await userEvent.click(screen.getByRole('button', {name:'确认重设密码'}))
  expect(await screen.findByRole('status')).toHaveTextContent('密码已更新')
  expect(screen.queryByLabelText('新密码')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', {name:'返回登录'}))
  expect(back).toHaveBeenCalledOnce()
})
