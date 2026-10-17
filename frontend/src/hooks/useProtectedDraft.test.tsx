import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'
import { useProtectedDraft } from './useProtectedDraft'
import { requestPageNavigation } from '@/lib/navigation'

vi.mock('@/stores/authStore', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ user: { id: 'owner' } }) }))
function Editor() { useProtectedDraft('example', 'Title', 'New body', true); return <a href="/projects">项目</a> }
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear() })

it('guards navigation and confirms that the current draft is actually retained', () => {
  const request = vi.fn(); window.addEventListener('vinote:draft-navigation', request)
  const view = render(<Editor />)
  fireEvent.click(view.getByText('项目'))
  expect(request.mock.calls[0][0].detail).toEqual({ to: '/projects', protectedDraft: true })
  const navigate = vi.fn(); requestPageNavigation('/connections', navigate)
  expect(navigate).not.toHaveBeenCalled()
  window.removeEventListener('vinote:draft-navigation', request)
})

it('does not treat an old draft as protection when writing the current draft fails', () => {
  localStorage.setItem('vinote:draft:owner:example', JSON.stringify({ title: 'Title', content: 'Old body' }))
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
  const request = vi.fn(); window.addEventListener('vinote:draft-navigation', request)
  const view = render(<Editor />); fireEvent.click(view.getByText('项目'))
  expect(request.mock.calls[0][0].detail.protectedDraft).toBe(false)
  window.removeEventListener('vinote:draft-navigation', request)
})
