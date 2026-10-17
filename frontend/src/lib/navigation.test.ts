import { describe, expect, it } from 'vitest'
import { loadingPageParent, resolvePageParent } from './navigation'

describe('safe contextual parents', () => {
  it('preserves project and archive view when returning from content', () => {
    expect(resolvePageParent('/notes?project=Demo&archived=1')).toBe('/notes?project=Demo&archived=1')
    expect(resolvePageParent('/workspace/abc-123')).toBe('/workspace/abc-123')
    expect(resolvePageParent('/tasks')).toBe('/tasks')
    expect(resolvePageParent('/settings/storage#trash')).toBe('/settings/storage#trash')
    expect(resolvePageParent('/note/48b84237-2003-5e8c-97aa-59f7e989a466')).toBe('/note/48b84237-2003-5e8c-97aa-59f7e989a466')
    expect(resolvePageParent('/files?type=video')).toBe('/files?type=video')
    expect(resolvePageParent('/settings/sync#trash')).toBe('/settings/sync#trash')
    expect(resolvePageParent('/settings/mcp')).toBe('/settings/mcp')
  })
  it('rejects external, protocol-relative and unknown destinations', () => {
    for (const value of ['https://example.com', '//example.com', '/\\example.com', '/unknown', null, 17]) expect(resolvePageParent(value)).toBe('/notes')
  })
})

describe('loading page return context', () => {
  it('does not invent a back destination on top-level pages or accept an unsafe context', () => {
    for (const path of ['/notes', '/meetings', '/files', '/connections', '/settings']) {
      expect(loadingPageParent(path, '')).toBeNull()
      expect(loadingPageParent(path, '?returnTo=https%3A%2F%2Fexample.com')).toBeNull()
    }
  })
  it('preserves validated query or state parents and uses the same known workflow for details', () => {
    expect(loadingPageParent('/files', '?returnTo=%2Fworkspace%2Ftest%3FreturnTo%3D%252Fnotes')).toBe('/workspace/test?returnTo=%2Fnotes')
    expect(loadingPageParent('/workspace/test', '', '/meetings?archived=1')).toBe('/meetings?archived=1')
    expect(loadingPageParent('/generate', '?meeting=1')).toBe('/meetings')
    expect(loadingPageParent('/settings/sync', '')).toBe('/settings?tab=storage')
    expect(loadingPageParent('/settings/feishu', '')).toBe('/connections')
    expect(loadingPageParent('/settings/mcp', '')).toBe('/connections')
    expect(loadingPageParent('/settings/mcp', '?mode=translation&note=abc')).toBe('/workspace/abc')
    expect(loadingPageParent('/settings/mcp', '?note=..%2Fsecret')).toBe('/connections')
    expect(loadingPageParent('/write', '', '//example.com')).toBe('/notes')
  })
  it('keeps settings sections one level below their overview and does not let an invalid URL hide safe state', () => {
    expect(loadingPageParent('/settings', '?tab=models&returnTo=%2Fworkspace%2Ftest')).toBe('/settings?returnTo=%2Fworkspace%2Ftest')
    expect(loadingPageParent('/settings', '?tab=storage')).toBe('/settings')
    expect(loadingPageParent('/settings', '?returnTo=%2Fsettings%3Ftab%3Dmodels')).toBeNull()
    expect(loadingPageParent('/settings', '?returnTo=https%3A%2F%2Fexample.com', '/meetings?q=review')).toBe('/meetings?q=review')
  })
})
