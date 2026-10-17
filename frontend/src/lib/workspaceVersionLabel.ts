import type { WorkspaceVersion } from './workspace';

/** Snapshot revisions are encoded by the server; array positions are not revisions. */
export function savedWorkspaceVersionLabel(version: WorkspaceVersion): string {
  const snapshot = /^__vinote:(current|saved):([1-9]\d*)$/.exec(version.id);
  const meaning = snapshot
    ? `${snapshot[1] === 'current' ? '自动正文快照' : '写入前正文快照'} · 修订 ${snapshot[2]}`
    : version.kind === 'edit' ? '正文编辑'
    : `${version.kind === 'generated' ? '生成版本' : version.kind === 'imported' ? '导入记录' : '其他保存记录'}${version.title ? ` · ${version.title}` : ''}`;
  const time = version.created_at?.trim() ? new Date(version.created_at) : null;
  return `${meaning} · ${time && Number.isFinite(time.getTime()) ? time.toLocaleString() : '时间未记录'}`;
}
