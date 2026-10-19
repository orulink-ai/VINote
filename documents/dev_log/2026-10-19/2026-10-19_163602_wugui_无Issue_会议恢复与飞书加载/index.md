# 会议失败恢复与飞书个人发布设置加载修复

## 基本信息与边界

- 创建：2026-10-19 16:36:02 Asia/Shanghai；作者：wugui；参与：用户、Codex。
- 基线：fresh `origin/dev=b492a4362de80f8d6c9ea867f772662b39f9d70f`。
- 独立分支：`codex/fix-meeting-resume-feishu-loading-20261019`，worktree `D:/projects/VINote-ui-recovery-fix-20261019`。
- 需求：修复失败任务误发 retry/失败阶段丢失，以及飞书群列表拖住个人发布设置；按用户后续指示保留两个公开 ASR 空终态错误码。
- 状态：源码修复、TDD 和关联验证完成，准备提交与中文 PR；未合入/部署/打包。
- 已读取根 AGENTS、dev_log README/temp_log；检索既有档案未找到本次任务，按模板建立本目录。

本次只使用合成任务/账号/群与 mock 响应，不读取用户音视频、checkpoint 文字、安装版输出或运行端口；
不重启进程、重跑模型、改代理或操作主仓及其他 worktree。主代理负责实际故障调查/恢复与后续发布。
用户提供的实际失败背景仅用于确定测试合同，不在档案保存实际 session/task ID 或会议资料，
也不将服务端空终态推断为静音、无语音或允许跳过缺口。

## 目标与合同

1. `resumeMeetingTask` 读取到 failed + retryable=false 时只 GET，保留真实 failed_stage 与安全消息，不能 POST retry 或新建提交。
2. retryable=true 与缺省继续兼容原任务显式恢复；重试 HTTP 失败也保留原失败阶段；not_found 既有单独确认行为不变。
3. 飞书状态成功即可结束页面 busy；群列表仅打开选择时读取，独立加载/错误，不阻止本人、个人位置核验与保存。
4. 群选择保留，旧账号（包括切走再切回）、旧连接核验、授权过期后的迟到响应/清理不能覆盖当前界面。
5. `asr_empty_result` / `empty_result_unverified` 保留原码，不进入 transient，不变成功、不产生 no_speech 或重放授权；
   GET 状态文案说明空结果且区间完整识别尚未确认，POST retry 仍阻断。

## 实现与证据

- `meetingGeneration.ts` 共用终态错误构造，resume 在显式 false 时直接抛带阶段错误，retry HTTP 异常携带原阶段。
- `FeishuSettings.tsx` 分开状态/群请求序号，复用账号/Origin scope，卸载/换号及重新核验失效旧请求；
  群请求有同步去重 ref，不修改页面 busy；状态变更重验群权限，旧群请求不会清掉新请求 loading。
- `asr_stream_service.py` 仅扩展明确错误白名单；`task_failure.py` 显式安全空终态提示，仍非 retryable。
- 使用 UI Skills 最小交互合同、UI/UX Pro Max 加载反馈及既有 shadcn/Radix 控件指导；无视觉重设计。

## TDD 记录

Red（UI）：先补真实 resume/processing 和 React deferred-promise 行为测试，原实现 40 项中 6 失败、34 通过；
复现 failed=false 仍 POST、retry 异常丢阶段、群请求阻塞本人表单、账号 ABA/同账号旧核验覆盖。
Green（UI 初轮）：核心修复后 40/40 和 `tsc --noEmit` 通过；旧自动群读取测试按新按需合同调整，
保留加载、重复读取阻断、错误独立与草稿保存验收。

Red（空终态）：按用户新增服务端证据先补 6 项，全部失败，确认两个码变 unknown_error 及旧 true 未被强制阻断；
随后扩白名单和安全提示，并扩现有真实 framed transport 的 mock error 事件参数，始终抛错、无模型访问。

收尾补充：新增账号切换时旧 dirty/value 闭包会把原账号偏好当新账号草稿的反例，先失败后以 valueOwner 绑定修复；
另覆盖群读取挂起后授权过期、重新核验后只能读取新群。过期提示测试改为核对真实授权过期 Alert，
不依赖已有 authUrl 状态优先级下的 Badge 文案。没有为满足测试改变授权展示合同。

最终 UI 命令（frontend 目录）：

```sh
npx vitest run src/lib/meetingGeneration.test.ts src/lib/meetingProcessing.test.ts src/pages/FeishuSettings.test.tsx src/components/Settings/FeishuDestinationPicker.test.tsx src/components/Notes/RecordingRetryBar.test.tsx src/components/MeetingRecorder/MeetingRecorderDock.test.tsx src/lib/feishuPublishReceipt.test.ts src/lib/taskRecoveryView.test.ts --maxWorkers=1 --minWorkers=1 --reporter=dot
npx tsc --noEmit
```

2026-10-19 16:49 Asia/Shanghai，8 suites / 110 tests 通过，tsc exit 0。已有 Router future/act warning 不记为产品验收。
后端命令：`python -m pytest tests/test_task_recovery_failures.py tests/test_asr_stream.py tests/test_vilab_transcriber_retry.py tests/test_asr_failure_context.py -q`，
100/100 通过（仅框架弃用 warning）；所有 socket/provider 行为由 mock 替代，原媒体/检查点与 namespace 未读写。
`git diff --check` 通过。隔离 worktree 使用独立 npm ci --ignore-scripts 依赖，不复用/写入运行目录 node_modules。

没有运行全量服务、真实供应商/飞书交付或用户桌面；
源码/离线测试不能宣称安装版或真实长录音已修复。

## 关联与后续

本次是对当前代码缺陷的修复，未替代已有独立开发档案的决策；根 AGENTS 与实际 UI 复验记录补充源码验证边界。
需要中文提交/PR（base dev），不合并、不部署、不打包。实际音源、空终态覆盖恢复策略由主代理继续调查。
版本由后续统一发布单元处理，本次不更新打包清单或声明新版本已发布。

## 变更记录

2026-10-19 16:49:37 +08:00｜wugui / Codex：完成上述源码与回归，核对 diff 仅本任务文件；
包含用户追加的两种空终态白名单，不含后续区间恢复方案。等待主线程后续独立 commit/cherry-pick 与合并决定。
