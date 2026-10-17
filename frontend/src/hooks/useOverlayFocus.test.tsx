import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { useOverlayFocus } from './useOverlayFocus'

afterEach(() => document.body.replaceChildren())

it('restores a controlled overlay opener but does not steal focus from the next task', () => {
  const opener = document.createElement('button')
  const input = document.createElement('input')
  document.body.append(opener, input)
  opener.focus()
  const { result } = renderHook(() => useOverlayFocus())
  act(() => result.current.onOpenAutoFocus(new Event('open', { cancelable: true })))
  input.focus()
  const close = new Event('close', { cancelable: true })
  act(() => result.current.onCloseAutoFocus(close))
  expect(document.activeElement).toBe(opener)
  expect(close.defaultPrevented).toBe(true)

  const next = document.createElement('div')
  next.setAttribute('role', 'dialog')
  next.dataset.state = 'open'
  next.append(input)
  document.body.append(next)
  input.focus()
  act(() => result.current.onCloseAutoFocus(new Event('close', { cancelable: true })))
  expect(document.activeElement).toBe(input)
})
