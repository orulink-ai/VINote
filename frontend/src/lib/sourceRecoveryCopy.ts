/** Presentation only: retain raw service errors and operation identity for diagnosis. */
export function sourceRecoveryCopy(message: string): string {
  if (/文件注册|原件注册|不支持去重|提交去重/.test(message)) {
    return /注册/.test(message)
      ? '文件是否保存尚未确认，请到文件库查看。确认前不会重复保存或上传。'
      : '暂未查到原任务，请稍后重新查询。已有来源仍保留，不会自动重复提交。'
  }
  return message
    .replace(/回执/g, '处理记录')
    .replace(/原操作编号|操作编号与来源|原来源与编号/g, '原来源')
    .replace(/原操作/g, '原任务')
    .replace(/原编号/g, '原来源')
    .replace(/没有操作编号/g, '缺少恢复信息')
    .replace(/未返回有效任务编号|尚未收到任务编号/g, '尚未确认任务')
    .replace(/重新派发/g, '重复提交')
    .replace(/改绑当前服务/g, '切换处理服务')
    .replace(/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}/gi, '原任务')
}
