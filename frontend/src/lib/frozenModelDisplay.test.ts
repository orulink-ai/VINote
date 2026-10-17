import { expect, it } from 'vitest'
import { frozenModelDisplay, sameModelCatalogSource } from './frozenModelDisplay'

it('matches exact id plus kind, without decoding an opaque id or selecting the current default', () => {
  const rows = [{ id: 'asr:14:opaque', modelType: 'asr' as const, name: 'Verified name' }]
  expect(frozenModelDisplay(rows, 'asr:14:opaque', 'asr')).toBe('Verified name')
  expect(frozenModelDisplay(rows, 'asr:14:opaque ', 'asr')).toContain('名称暂不可读取')
  expect(frozenModelDisplay(rows, 'asr:14:opaque', 'llm')).toContain('原任务所选总结模型')
  expect(frozenModelDisplay([...rows, ...rows], rows[0].id, 'asr')).toContain('名称暂不可读取')
})
it.each(['asr:14:opaque', 'https://private.test', 'secret\nvalue', ''])('rejects inappropriate public name %s', name => {
  expect(frozenModelDisplay([{ id: 'asr:14:opaque', modelType: 'asr', name }], 'asr:14:opaque', 'asr')).toContain('名称暂不可读取')
})
it('matches catalog source including base path, never only host', () => {
  expect(sameModelCatalogSource('https://source.test/base/', 'https://source.test/base')).toBe(true)
  for (const source of ['https://source.test/other', 'http://source.test/base', 'https://user:secret@source.test/base', 'https://source.test/base?key=x', undefined]) expect(sameModelCatalogSource(source, 'https://source.test/base')).toBe(false)
})
