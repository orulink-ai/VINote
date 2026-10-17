import { describe, expect, it } from 'vitest';
import { taskRecoveryView, sourceHistoryAction } from './taskRecoveryView';
const receipt = { id: 'same-task', operationId: 'old-operation', submissionState: 'accepted' };
const failed = { taskId: 'same-task', status: 'failed', errorCode: 'unknown_result', hasCompleteResult: false };
describe('task recovery presentation boundaries', () => {
  it('accepted unknown ASR failure is terminal without a save promise', () => {
    const result = taskRecoveryView(receipt, failed, false);
    expect(result.kind).toBe('failed_unknown');
    expect(result.action).toBe('查看原任务状态');
    expect(result.explanation).toContain('未获得可保存的完整结果');
  });
  it('unconfirmed POST stays separate even with a task-shaped old response', () => {
    const result = taskRecoveryView({ ...receipt, submissionState: 'unknown' }, failed, false);
    expect(result.kind).toBe('submission_unknown');
    expect(result.action).toBe('核验原提交');
  });
  it('a file-library task-only receipt becomes known failed only after exact task read', () => {
    expect(taskRecoveryView({ id: receipt.id }, failed, false).kind).toBe('failed_unknown');
  });
  it.each([null, { ...failed, taskId: 'other-task' }, { ...failed, status: 'not_found' }])('unverified identity/status does not promise recovery or save (%s)', task => {
    const result = taskRecoveryView(receipt, task, false);
    expect(result.kind).toBe('read_unverified');
    expect(result.action).toBe('重新查询原任务状态');
  });
  it('only complete successful result has a save recovery promise', () => {
    const result = taskRecoveryView(receipt, { ...failed, status: 'success', errorCode: undefined, hasCompleteResult: true }, false);
    expect(result.kind).toBe('result_ready');
    expect(result.action).toBe('查询原结果并恢复保存');
    expect(taskRecoveryView(receipt, { ...failed, status: 'success' }, false).kind).toBe('read_unverified');
  });
  it('explicitly retryable failure keeps the original-task retry action', () => {
    expect(taskRecoveryView(receipt, { ...failed, errorCode: 'service_unavailable' }, true).action).toBe('重试处理原任务');
  });
  it('history without task readback never claims restore and save', () => {
    expect(sourceHistoryAction(receipt)).toBe('查看原任务与处理记录');
    expect(sourceHistoryAction({ operationId: 'pending', submissionState: 'unknown' })).toBe('核验原提交');
  });
});
