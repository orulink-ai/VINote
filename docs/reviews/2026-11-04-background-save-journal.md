# 后台成功任务自动保存 · 2026-11-04

## 问题与实现

离开 NoteGenerator 后，成功任务只产生通知，笔记可能要重新打开生成页才保存。新增 `backgroundSaveCompletedTask(owner, taskId)` 供全局 TaskNotifications 挂接；本子任务未改 TaskNotifications。

- 仅使用该 owner 本地 accepted 来源回执的确切 workspace、sourceType、sourceUrl、meeting，不根据当前页面猜工作区。缺少信息、同 task 回执冲突或特殊版本冻结上下文未核验时保留精确恢复入口，不自动保存。
- GET 成功 task 的完整原始 result，核对 task ID、正文非空。随后 GET `/api/notes?scope=...&team_id=...&task_id=...`；已有笔记直接返回 ID，不修改人工编辑。不存在才 POST 保存原 title/markdown 至原工作区。
- 同任务并发调用共享 Promise；账号 A→B→A、服务或回执在等待期间变化时丢弃旧响应。owner-scoped 保存 marker 防止后台在用户删除笔记后再次创建；不清原任务回执。
- 新保存发出 `vinote:background-note-saved` 事件；既有笔记仅返回 ID。模块无模型调用、重试生成或消息发送。普通笔记不会因该模块自动发布飞书；会议保存仍走现有明确设置的 outbox。
- 后端所有有 task_id 的生成笔记按 owner/task/scope/team 幂等。历史已有 ID/内容优先复用；会议保留原 vinote-meeting UUID namespace，普通生成使用 vinote-generated；无 task_id 手写笔记仍独立创建。SQLite BEGIN IMMEDIATE 与稳定主键保护同时保存。
- 新增 GETnotes 可选 task_id 精确筛选，限定当前 owner 与原工作区；普通列表契约不变。

## 验证

- 后端 RED：5 failed / 1 passed，覆盖普通重复保存、同时保存、工作区/owner、历史 ID、exacttask 查询。
- GREEN：generated_note_idempotency + feishu_auto_outbox + note_library_router 共 38 passed；追加 HTTP task filter 回归后目标文件 7 passed。
- 前端最终 backgroundTaskSave 18 passed；包含 ABA、同 task 并发、已编辑内容不覆盖、团队目的地、不足回执、精确坏回执隔离、无关坏历史不阻塞、删除后不复活。
- 最新 tsc --noEmit exit 0。
- 本任务没有真实 POST 笔记、生成模型或飞书。主线程负责全局通知挂接及真实闭环验收，不将模块测试当成用户界面验收。
