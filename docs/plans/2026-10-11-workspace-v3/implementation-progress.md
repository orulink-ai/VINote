# 确认后实施记录

2026-10-11 Asia/Shanghai；作者 wugui / Codex；分支 codex/meeting-workbench-feishu。状态：实施中，本地修改，未提交、未部署。

依据飞书 revision 62 及本目录 01–16 流程。此前 prototype.html 的历史布局不直接作为最终产品验收。

| 范围 | 本轮实际改动 | 验证与边界 |
| --- | --- | --- |
| 两端框架 | 统一内容入口、采集与处理恢复分开；对话归具体详情；删除独立助手页，保留桌面旧链接跳转 | 两端类型检查通过；App 根组件唯一导航，手机截图生效；尚未逐页完整视觉验收 |
| 内容采集 | 桌面来源选择、独立 Markdown 编辑与保护草稿；App 来源面板复用录音、音频导入和文字编辑 | 桌面文字保存仍待真实账号 UI 验收；手机链接处理尚未新增 |
| 会话恢复 | 桌面网络/401/退出区分、冷启动连接重试、账号切换立即清理内存、读取代次保护；App 先核验再恢复同步/交付 | authStore 6 项、内容响应隔离 3 项、模型配置 1 项通过；服务端会话撤销/注销/资料迁移未完成 |
| 录制准备 | 桌面实时麦克风音量测量，10 秒结束，不保存/上传；取消、关闭、切换设备、隐藏页面释放；禁止测试期间开会 | 4 项资源生命周期测试通过；实际麦克风/原生 WebView 权限测试未执行 |
| 插件 | Linear 远程地址配置预填，本人 Bearer 凭证、真实发现与逐次确认；Notion 标明需要 OAuth；飞书区分官方连接 | 未连接 Linear/Notion、未授予新权限；首方任务/日历/知识检索适配仍未实现 |
| 运行资源 | 复用 Tauri/Vite/Uvicorn、Metro，未重启或新建运行实例；编译测试串行、768 MB Node 上限、单测试进程 | 8900/3100/8081 原 PID 保持，手机 HMR 已生效；桌面进程仍存活，原生界面尚未逐页核验 |

## 验证命令与证据

- frontend 与 VINote-app：node --max-old-space-size=768 node_modules/typescript/bin/tsc --noEmit，均通过。
- frontend：vitest 四文件单 worker，14 项通过（会话/内容归属/模型/输入设备释放）。
- 后续扩大到设置、飞书与详情，七文件 32 项通过；文字保存与持久请求失败另三项通过，共 35 项。未提交状态保留原请求、稍后成功回执转为已保存入口；本机请求落盘失败不提交服务。
- App：jest FeishuSettingsScreen、RecordingWorkbenchScreen，runInBand，8 项通过。
- 实机截图：父仓库 ignored data/plan-review-2026-10-11/implementation/app-workspace.png。ADB 最近 120 条仅 ReactNativeJS:E/AndroidRuntime:E 无错误输出。
- 浏览器打开真实 Vite 3100；当前独立浏览器 Cookie 未登录，只核验登录页无 console error，不能声称内容页面已完成浏览器验收。

## 继续实施

账户安全与注销需真实服务端会话/撤销/归属迁移设计；访客草稿认领与团队邀请/只读角色尚未实现。继续对齐两端详情、版本/证据、交付与恢复；App URL 来源需要可恢复任务身份。MCP 适配与后台交付按真实服务能力落实，不加假开关。所有尚未验收项继续标记，不用本轮截图或编译通过代替端到端验收。
