# 根桌面会议、笔记与飞书交付候选

## 身份与边界

- 日期：2026-10-17，Asia/Shanghai；建档作者：wugui（仓库 Git 配置），实施：Codex。
- 用户授权：在独立 worktree 的 codex/desktop-meeting-notes-feishu 分支交付；基础产品中文提交后，独立追加 DNS/测试/账号删除账本泛化修复；不 push、不建 PR。
- 基线：本轮 fetch origin main 确认为 432ad2490fee8643b3571a1cb4d83d39af0eb6af。没有以原运行 checkout 的 HEAD 或其 150 个历史提交作为交付分支基线。
- 原运行 checkout 和 App 不切分支、不修改业务代码或账号缓存；App 子模块保持原根仓库 gitlink，等待独立 App PR。

## 基础产品范围

设备内会议/笔记正文及版本、文件库与原件、录制停止后显式生成、来源请求与独立重新生成回执、ASR 安全执行/检查点、说话人分析、账号模型配置、插件/MCP 翻译、飞书发布和阅读授权/通知回执，以及对应前端、后端、Tauri 和启动/打包依赖共同交付。

包含本轮冻结的 feishu_notification_card.py、其测试及最新飞书修复验收文档。复制后核对飞书服务/helper 与冻结源码的内容一致；不在候选中修改飞书服务实现，也不触碰 VILab。

一次产品版本为 0.4.0：原开发状态 0.3.2 → 0.4.0 已构成 minor 升级，本 PR 不重复增加；运行依赖包、模型和服务 runtime 版本不为交付随意更改。

## 过滤与提交边界

- 以 manifest 明确逐路径复制，排除 data/output、原录音/视频/数据库、构建与模型目录、私有截图/回执、独立部署/agent 工具和无关开发档案。
- 与本任务有关的计划、审查和开发记录只带文字，移除个人账号/对象 UUID、接收者 token 和私有摘要；镜像 sha256 保留为部署来源证明。私人材料只保留路径说明，不复制附件。
- 个人清理清单从任何提交中排除。基础产品仅保留空的兼容 adapter，不带真实 owner/key/digest；后续修复提交彻底移除 adapter，改用账号缓存已有删除账本。
- 旧的 SyncSettings 删除测试及含个人 fixture 的旧 workspaceItemSync 测试不放入基础提交；独立修复提交增加已迁移/合成的行为用例。基础提交不是对原运行目录的可部署替代物，使用最终包含修复的分支状态。
- DNS/删除测试修复以独立 patch 保存；账本泛化另有独立 patch。原运行 checkout 的两项已授权修复维持原状。

## 基础候选验证

- manifest：721 个产品/支持/文字记录文件，另 4 个文件安排在修复提交中新增；其余候选路径明确记录排除/保留基线决定。
- 静态检查：729 个当前候选文件中，222 个 Python 文件语法解析和 274 个 TS/TSX 本地导入检查通过；已知个人清理标识和高置信凭据形态扫描无命中。这是静态范围检查，不代替全面安全审计或真实运行。
- `node --input-type=module -e "import { assertProjectVersion } from './scripts/project-version.mjs'; console.log(assertProjectVersion())"`：通过，0.4.0。
- `python -m pytest tests/test_feishu_notification_card.py tests/test_feishu_recipient_access.py tests/test_feishu_delivery.py -q -p no:cacheprovider`：**103 passed，23.34s**；仅有 Starlette/AnyIO 弃用提示，单进程无模型/设备/云调用。
- 同一批测试增加进程级离线守卫后的首次结果为 **102 passed / 1 failed**：Windows 标准库 socketpair 构造事件循环 self-pipe 的内部 loopback 被守卫误拦，并非发起了提供方请求。基础提交写入日志时该次运行尚未结束，提前写成 103 项通过有误，本条更正。守卫现仅放行标准库 socketpair 精确调用帧的本机配对 IPC，业务 DNS/连接仍全部禁止；最终复核结果待下方追加。守卫只存在忽略的审查工具目录，不作为产品依赖。
- `node --test scripts/desktop-build-profile.test.mjs scripts/desktop-dev-profile.test.mjs scripts/project-scripts.test.mjs`：18 项通过；只执行离线配置/启动契约，不调用提供方。
- 主线程报告的通知/交付相关 **136 项**测试及实际创建/本人通知/新版卡片实收，属于独立证据，详见 [飞书修复验收](../../../../docs/reviews/2026-10-16-feishu-publish-repair.md)。不与本候选 103 项相加冒充不重复用例数。
- 目前 App agent 正在串行 tsc/Jest，本候选未并行运行前端大测试或 build。桌面重开 completed/selfsent、App 重开同任务 count=1 的证据以最新主线程记录为准；没有为验证候选再次创建文档或通知。

## 后续修复与验证

在后续独立提交追加：连接绑定公网 IP，保留 Host/SNI/证书校验；删除测试迁移当前 StorageSettings；账号持久删除账本泛化、幂等别名、缺失账本失败关闭，以及合成测试。具体实现和验证结果在提交前追加，不预先声明通过。

原电脑的历史清理仍由原代码完成；部署泛化版本前需确认原账号删除 keys 已持久化。候选不会读取或改变原电脑缓存，不会通过公共包重建个人映射。

交付状态：基础产品候选已组装并完成上述验证，准备本地基础中文提交；尚未 push/PR/部署。

## 独立审查修复（2026-10-17）

基础提交初版为 1f88528（未发布，后续隐私清理与 gitlink 补全后的最终编号见下文）。后续修复仅发生在独立 candidate，原运行目录及 App 未切分支、未修改，飞书服务/helper/tests 与冻结来源保持一致。

- DNS：实际连接绑定一次已验证的公网 IP，按原域名保留 Host/SNI 和证书校验；逐跳 Client 隔离，防止同 IP 的不同域名复用 TLS/Cookie。连接失败不回退原域名重试。
- 删除测试：迁移到当前存储回收站、独立删除按钮、失败保留和显式重试。没有恢复已取消的 SyncSettings 页面或同步门槛。
- 永久清理：删除空 adapter，运行时代码不再导入任何个人回执。只使用现有账号持久化的 clearedContentKeys，保留旧 marker 与已存在别名；映射/旧操作别名收敛，重复重启不增长 recovered 前缀。删除对象不会从正文、历史 baseline、pending restore 或旧设备数据库列表恢复；普通回收站仍可恢复。
- 兼容失败关闭：有 appliedContentResets 却没有 keys 的缓存显示“历史内容整理尚未完成，请在原设备重试；已有资料已保留”，保留原缓存且不设 ready。普通账号没有 marker 时仍可初始化；不通过公共包重建个人清单。部署前原设备仍需核验真实持久化账本。
- workspaceItemSync 的原个人 fixture 改为合成数据，增加持久重启、别名、账号分区、缺失账本和落盘失败回归。
- 历史共享文档增加显式归档说明，避免将已经取消的同步方案当作当前客户端契约。

### 修复后已完成验证

- 严格离线守卫修正后：DNS/文档提取 + 飞书通知卡片/阅读授权/交付，**126 passed，22.23s**；单进程，仅 AnyIO 弃用提示。禁止业务网络，只有 Windows 标准库事件循环 socketpair 的精确内部调用帧允许配对 IPC。
- 轻量 Node 直接执行候选真实 workspaceStore 和 useLibraryNotes 投影，mock 账号/缓存/HTTP：**9 项通过**，没有 React/Jest worker、真实网络或设备缓存。覆盖多次重启幂等、旧映射/双重 recovered 别名、读取/保存/恢复拒绝、后端旧列表过滤、普通回收恢复、缺账本错误、落盘失败、跨账号及迟到旧账号读取。
- 合成 Vitest 文件已准备，候选前端 Vitest/tsc/build 尚未运行，以避免与 App agent 的 Node 检查争用内存；轻量 transpile/真实函数验证不等于 TypeScript 类型检查。
- 完整后端 tests 正在对最终候选以单进程、离线守卫运行。结果在结束后追加，不提前声称通过。

所有 raw 截图/操作与消息 ID 留在私有验收材料，产品代码/公开 journal 不带入个人 owner、对象映射或正文 digest。App gitlink 保持 0f698a4939735a210bef5500ca12d256eef6ae0a，新 App PR 独立关联；没有 push 或创建 PR。

## 泛化与前端回归修复进展

- 只在候选修复：历史清理标记存在但没有持久删除 keys 时继续失败关闭；错误文案改为“历史内容整理尚未完成，请在原设备重试；已有资料已保留”，不向用户暴露技术账本词。
- 定向回归发现 Zustand 合并 reset 时可选字段未被 blank 显式覆盖，导致上一账号的清理标记残留。现显式清空 serviceId、appliedContentResets、clearedContentKeys 和清理版本；新增有标记账号 → reset → 无标记账号的回归，不读取原设备缓存。
- 泛化 store 22/22、WorkspaceNote.read 36/36、Notes.layout 8/8、Tasks.sync 3/3，共 69 项通过；离线守卫、单 worker。测试改为设备正文/版本读取，不恢复同步状态门槛。保留原请求、草稿、账号切换、迟到响应、缓存落盘失败、重名版本和 MCP 返回保护。
- 主线程 NoteEditor 单文件 25/25；Darwin 三个前端文件 19 项通过，均只改过期测试契约。主线程三个后端文件 40/40、Darwin 四个后端文件 61/61，分别解决此前全量 27 失败；其报告与本代理全量复验分开记录。
- tsc --noEmit 已通过；最终完整 Vitest/pytest 正在带离线守卫复跑，此刻不宣称全量通过。
- 首次完整回归：后端 1187 passed / 27 failed / 17 subtests passed；前端 88/96 文件通过，754 passed / 56 failed。七文件错误复现日志保存在忽略 data，27 failed / 71 passed；未使用真实 ASR/LLM 或业务网络。
- 未发布基础历史先去除四份文字记录中的私有飞书资源链接；之后发现组装时 git add -A 丢失未初始化的 App gitlink，已在临时索引中补齐两个未发布提交树，并保留全部未提交修复。最终基础 925c401，DNS/删除测试 3a97e68；父提交仍为 432ad2490fee8643b3571a1cb4d83d39af0eb6af。App 仅固定既有 0f698a4939735a210bef5500ca12d256eef6ae0a，没有初始化、复制源文件或使用新 PR head。
- 重新静态检查 733 个候选文件，223 Python 语法和 275 前端本地导入闭包通过；已知私人清理值、高置信密钥形态、原媒体/数据库扫描无命中。此项不等于完整安全认证。

### 最终候选验证（2026-10-17）

- 完整后端：1217 passed、17 subtests passed，0 fail，167.91s；单进程、严格离线守卫。14 条提示为既有依赖弃用警告。
- 完整前端：96 文件、811 passed，0 fail，205.00s；单 worker、严格离线守卫。已通过 tsc --noEmit，不重复执行相同检查。
- Vite 生产构建：Node 512MB 上限并预载禁止业务网络守卫，22.94s 成功。Browserslist 数据陈旧和较大 chunk 提示保留，本轮不更新依赖或扩大拆包范围；dist 不纳入提交。
- 用户授权后最终前后端回归部分并行；观察可用内存最低约 1.78GB，未跌破 1GB，未并行启动多份编译。tsc 已在此之前串行完成。
- 通知 helper、其测试及最新实际验收文档与冻结来源字节一致；feishu_service.py 仅换行符归一化，代码内容一致，无本轮新修改。
- 主线程独立隐私复核发现两份历史文字记录含设备序列号，现统一替换为 验收设备（标识已省略），并修正全部未发布提交树，不改原目录。公开客户端 sb_publishable_ 配置按授权保留。
- 当前基础提交为 a8eac51，DNS/删除测试为 4dfe93b；替代前述未发布编号。私人资源链接、个人清理映射和设备序列号均不能出现在最终可达交付历史中。App 指针保持 0f698a4939735a210bef5500ca12d256eef6ae0a。

### 文档构建补充

使用已有 docs 依赖 junction、Node 384MB 和离线守卫执行 VitePress。脱敏设备文案改为普通文字，旧记录 Option 类型使用行内代码，Vue 解析错误已消除；后续构建仍失败于 29 个死链（含既有本机源码绝对路径、跨目录引用）。没有修改 ignoreDeadLinks 或排除 reviews；此轮不宣称完整 yarn verify 通过。Tauri/Rust 原生构建未运行，按授权由后续发布流程处理。产品代码测试不重复运行。
