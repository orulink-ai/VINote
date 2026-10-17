# 离线全量回归测试修复

- 日期：2026-10-17，Asia/Shanghai；作者 wugui，协作：主线程、Darwin、Codex。
- 范围：只修复候选测试的过期契约、账号偏好/数据库/模型资源 fixture 隔离；不修改提供方、飞书服务、已取消同步契约或原运行目录。删除记录泛化的 store 修复独立提交。

## 修改

- CloudModelSelection、ModelSourcePanel、api：有效服务预算和公开名称 fixture、不可用模型保留且不自动替换、网页请求标记清理。NoteEditor 保留 MCP/context/dirty guards，版本历史与删除入口对齐现有界面。
- WorkspaceNote.read：使用设备正文和版本读取，保留深链接、准确版本身份、草稿、原件返回、MCP 返回、账号切换与迟到响应保护。历史未知操作归档且不重发；设备删除独立执行。
- Notes.layout、Tasks.sync：不再断言同步状态/恢复入口；保留缓存读取错误、过滤上下文和独立删除。旧同步深链接转向存储页，保留有效返回位置并拒绝外站目标，无同步请求。
- 云客户端四文件：隔离偏好 session；旧 HTTP ASR 测试明确调用兼容 HTTP 路径；正常 PCM 路径另测服务预算、确认缓存不重发。不可用已选模型明确拒绝，不自动替换默认模型。
- 并行分析用临时假模型签名资源；multipart 显式 mock readiness 并验证桌面隐式说话人分析；原件保留测试注册 LocalFileDB 并共享隔离 session/artifact service，避免读取开发机数据库。

## 验证与边界

最终候选严格离线完整后端 1217 passed / 17 subtests passed，0 fail；完整前端 96 文件 / 811 passed，0 fail；tsc --noEmit 和 Vite 生产构建通过。所有测试 mock 传输，不实际请求 ASR/LLM、发飞书通知或操作服务设备。Vite 使用 Node 512MB；保留 Browserslist 数据陈旧和 chunk 大小提示，不提交构建输出。

实际桌面/App 飞书验收证据由主线程提供，见 docs/reviews/2026-10-16-feishu-publish-repair.md。App PR 独立关联，不更新为其 head；本线程不 push、不创建 PR。
