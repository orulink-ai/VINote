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
- 同一批测试增加进程级离线守卫，禁止真实 DNS/socket，并以 `-p vinote_offline_guard` 重新运行：103 项通过。守卫只存在忽略的审查工具目录，不作为产品依赖。
- `node --test scripts/desktop-build-profile.test.mjs scripts/desktop-dev-profile.test.mjs scripts/project-scripts.test.mjs`：18 项通过；只执行离线配置/启动契约，不调用提供方。
- 主线程报告的通知/交付相关 **136 项**测试及实际创建/本人通知/新版卡片实收，属于独立证据，详见 [飞书修复验收](../../../../docs/reviews/2026-10-16-feishu-publish-repair.md)。不与本候选 103 项相加冒充不重复用例数。
- 目前 App agent 正在串行 tsc/Jest，本候选未并行运行前端大测试或 build。桌面重开 completed/selfsent、App 重开同任务 count=1 的证据以最新主线程记录为准；没有为验证候选再次创建文档或通知。

## 后续修复与验证

在后续独立提交追加：连接绑定公网 IP，保留 Host/SNI/证书校验；删除测试迁移当前 StorageSettings；账号持久删除账本泛化、幂等别名、缺失账本失败关闭，以及合成测试。具体实现和验证结果在提交前追加，不预先声明通过。

原电脑的历史清理仍由原代码完成；部署泛化版本前需确认原账号删除 keys 已持久化。候选不会读取或改变原电脑缓存，不会通过公共包重建个人映射。

交付状态：基础产品候选已组装并完成上述验证，准备本地基础中文提交；尚未 push/PR/部署。
