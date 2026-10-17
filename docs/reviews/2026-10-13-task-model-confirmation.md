# 任务模型冻结与旧任务确认入口

2026-10-13。此报告区分代码/路由回归与实际设备证据。

## 初始路由验证

FastAPI TestClient 分别调用真实 `POST /api/generate_from_upload` 与
`POST /api/generate_from_file`，使用一秒 WAV，经过实际请求持久化、后台调度和
`NoteService.generate_from_file` 的冻结装饰器，仅替换最终 pipeline 以避免云调用。
两条入口均先保存 `model_source_snapshot.json` 再写 `request.json`。随后改变全局
模式和模型，生成方法仍读到原快照。因此 `allow_capture=not request.exists`
不会导致这两条新任务入口全部返回 409。

## 本次修复

- 新增认证 GET `/api/task/{task_id}/model-confirmation`。验证 owner、失败状态和
  原来源；返回来源标题、配置服务 Origin、当前具体 ASR/LLM 和服务端允许确认状态。
  读取不会写快照、启动生成或返回原文件路径。已有快照不允许在此替换。
- NoteGenerator 的原任务重试遇到 409 后打开确认 Sheet。沿用原 task、来源和保存
  回执，两个模型选择控件禁用切换，确认后 POST 同 task 的 retry，body 包含
  `confirmed: true` 和显示的具体模型及 Origin，由后端原子持久化冻结。
- 刷新若发现模型选择变化，不替换已显示模型。切账号/路由或卸载使旧异步响应失效。
  读取失败可重试，确定拒绝不显示成功，未知 POST 结果只能查询原任务而不重复提交。
- HTTP 回归确认：旧任务无快照普通 retry 返回 409；读取确认信息后改变全局偏好，
  POST 仍冻结显示过的具体模型、只排队一次，原媒体和 request.json 字节不变。

## 验证与限制

2026-10-14 native 追加证据（主线程报告，本 agent 未控制设备）：约 00:00，旧
50 分钟任务的 409 确认 Sheet 实际显示原 Aliyun/Luna，主线程核对一致并点击恢复。
原 task 已恢复，speaker evidence 已缓存，目前正在 ASR；尚无完整 final、LLM 或
新纪要保存完成证据。本项证明确认入口可达及显式恢复动作，不证明长录音最终成功。

- 后端：`tests/test_task_model_source.py tests/test_asr_stream.py tests/test_speaker_worker.py`
  共 57 项通过，串行 pytest；其中包含实际 router 测试，无真实 ASR/LLM 请求。
- 前端：NoteGenerator 与 TaskModelConfirmationSheet 两个测试文件，单 worker，
  30 项通过；调整测试归属后又单独验证 retry409 集成项通过。
- TypeScript `tsc --noEmit --incremental false` 通过；`git diff --check` 通过。
- 本 agent 未操作原生 UI，未启动新 340 秒/50 分钟云生成，未运行全量构建。
  父任务提供的 Desktop 导入链及真实 heartbeat 证据属于独立验证；上述新增 native
  报告证明本 Sheet 的入口及恢复动作，最终产物和失败恢复仍需分别验收。
- 无快照的历史任务无法还原曾经实际使用的模型；此入口明确确认当前显示选择，
  不声称它就是历史模型。历史本地模型快照缺失时仍拒绝恢复，要求保留原件另建确认操作。
