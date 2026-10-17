import { test, expect } from 'vitest'
import { sourceRecoveryCopy } from './sourceRecoveryCopy'
test('ordinary copy hides implementation but preserves actionable recovery', () => {
  expect(sourceRecoveryCopy('首次文件注册尚未覆盖提交去重')).toContain('文件是否保存尚未确认')
  expect(sourceRecoveryCopy('当前服务不支持去重')).toContain('重新查询')
  const result = sourceRecoveryCopy('原操作编号 bf1cf8b3-c2d0-44f5-a9a0-d408d1234567 回执待核验，不会自动重新派发')
  expect(result).not.toMatch(/回执|编号|bf1cf8b3|重新派发/)
  expect(result).toContain('不会自动重复提交')
})
