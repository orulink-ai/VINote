export type RecoveryTask = { taskId: string; status: string; errorCode?: string; hasCompleteResult: boolean };
export type RecoveryReceipt = { id?: string; operationId?: string; submissionState?: string };
export function taskRecoveryView(receipt: RecoveryReceipt | null, task: RecoveryTask | null, retryable: boolean) {
  if (receipt?.operationId && receipt.submissionState !== 'accepted') return {
    kind: 'submission_unknown' as const, action: '核验原提交',
    explanation: '提交是否被接收尚未确认。请核验原提交，确认前不会重复上传或生成。',
  };
  const sameTask = !!receipt?.id && task?.taskId === receipt.id;
  if (sameTask && ['failed', 'error'].includes(task!.status)) {
    if (['unknown_result', 'unknown_error', 'asr_incomplete_result'].includes(task!.errorCode || '')) return {
      kind: 'failed_unknown' as const, action: '查看原任务状态',
      explanation: '此次转写未完成，未获得可保存的完整结果。原文件和处理记录已保留。再次查看只读取原任务状态，不会重新转写。',
    };
    return { kind: 'failed_terminal' as const,
      action: retryable ? '重试处理原任务' : '查看原任务状态',
      explanation: retryable ? '原任务已保留，重试会继续该任务，不重复创建。' : '此次处理未完成。原文件和处理记录已保留，可返回查看资料。',
    };
  }
  if (sameTask && task?.status === 'success' && task.hasCompleteResult) return {
    kind: 'result_ready' as const, action: '查询原结果并恢复保存',
    explanation: '完整结果已生成但尚未确认保存。查询原结果后继续保存，不重新生成。',
  };
  return { kind: 'read_unverified' as const, action: retryable ? '重试处理原任务' : '重新查询原任务状态',
    explanation: '原任务状态尚未核验，请重新查询。原来源和处理记录继续保留。',
  };
}

/** History has not loaded task status; it must not promise a saveable result. */
export function sourceHistoryAction(receipt: RecoveryReceipt) {
  return receipt.operationId && receipt.submissionState !== 'accepted' ? '核验原提交' : '查看原任务与处理记录';
}
