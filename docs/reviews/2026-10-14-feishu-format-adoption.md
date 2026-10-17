# 飞书格式转换采用核对（2026-10-14）

已审查并采用 data/feishu-format-staging-20261014/source.patch 的后端候选，另修正图片前置阻断；实际差异记录在同目录 adopted-source.patch。未采用 ui-adoption.patch，未修改 App、权限配置或远端服务，未调用真实飞书转换、授权、发布或消息接口。

新操作冻结格式选择及原正文分段。表格、代码、复杂行内样式使用官方 POST /open-apis/docx/v1/documents/blocks/convert，仅使用原账号 user token 和实际已授予 docx:document.block:convert；配置 scope 不等于用户授权，更不证明应用权限或接收者阅读权限。转换计划、正文 SHA256、计划完整性指纹及 UUIDv4 批次 token 在创建文档前持久化。写入使用官方 descendant 完整树，批次回执绑定原目标/API/token/body。确认批次可在检查点丢失后跳过；dispatching/unknown 不重放。纯转换未编辑目标文档，失败可显式重试。

保留现有 operation/source/version/destination/recipient 冻结、owner 验证、联系人阅读权限核验、通知及未知结果查询语义。重复 operation 在格式分类前返回原任务。缺 body_format 的历史任务保留原 children 写入协议，不自动修复旧文档或替换回执正文。

采用版本比 staging v2 更严格：新格式任务中的真实 Markdown/HTML/引用式图片在任何创建、正文写入或通知前以 format_unsupported 失败；代码内图片字面量仍属于代码。转换响应出现不支持的图片/素材块同样提前失败。图片格式回执为 unsupported，images_embedded=false，不能冒充图片已发布。历史缺格式元数据的回执保持 legacy-unknown。

状态新增 formatting_protocol=2、markdown_conversion_preflight（required_scope、user_grant_available、app_permission_verified=false、needed_only_for、image_mode=unsupported_before_write）。交付回执新增 formatting，保留旧字段：protocol/native_required/status/message/image_source_preserved/native_write_confirmed/images_embedded。image_source_preserved 表示原正文含图片引用，采用版本不允许将其作为图片完成结果。native_write_confirmed 仅在任务 completed 且存在冻结原生计划时为真；通知失败可能保守显示未确认。

测试：五个 Feishu 文件串行 pytest 共 152 项通过，另新增转换响应图片前置阻断补测 1 项通过，总计 153 项。全部使用临时数据库及 mock 请求；官方表格例子的 13 块树作为公开测试 fixture 留存。联系人身份/通知/重试方法、现有 receipt 服务未修改。单项已知 Starlette/AnyIO 弃用警告不影响结果。

局限：分段器不是完整 CommonMark AST；复杂嵌套/扩展语法需实文档验证。单个完整子树超过 1000 块、合并单元格、不支持素材会拒绝，不静默裁剪。0.35 秒是每任务写入节流，多个任务仍可能达到应用总限额。转换后的逐元素语义/视觉等价没有实机证据。此次未部署，远端不会因根源码采用而自动具备新 helper；未来部署需同时包含 feishu_service.py 和 feishu_markdown.py。用户浏览器授权与权限配置由父任务处理，不能把本地测试当作授权/消息送达/收件人可读验收。


## P2 行内样式核验与最终上传补丁

按每段支持的 Markdown 提取 italic、bold、inline_code、strikethrough、link 所需类别，逐类验证；布尔样式必须 true，链接必须带非空字符串 URL。代码字面量与链接目标字符不冒充其他样式。已冻结 selective 计划按原段 ID 前缀只读复核，缺样式 fail-beforewrite，不重新转换或改指纹。此核验是逐类存在证据，不是每处样式/URL 目标/完整 CommonMark 视觉等价证明。

六文件 backend 单 worker 回归共 176 项通过。data/feishu-format-deploy-20261014/source.patch 只包含 config.py（默认两 scope）、feishu_service.py 及新增 feishu_markdown.py，gzip-base64 10,964 字符，manifest/SHA256SUMS 保存基线、目标和包 hash。已在精确联系人包 service 与已核验 archive config 的隔离副本实际 apply/check，三个重建 LF hash 与根源码匹配、内存编译通过。父任务仍须核对目标 release 副本 hash；本 worker 未部署。


## 桌面格式回执与实际验收素材

桌面新增 feishuFormatting helper 和 Delivery.formatting 可选类型，发布面板与文档页只展示回执格式证据；原生确认需要支持的协议、status=written、native_write_confirmed=true 和交付 completed。缺证据、旧协议、图片 unsupported/partial 分别准确展示，不使用 document_url 或通知送达推断格式成功。文档页通用失败标签改为“交付需处理”，避免正文失败被称为仅通知失败。未修改任何 App Panel、后台或重试流程。

五套单 worker 桌面相关测试 43 项通过、TypeScript noEmit 通过。data/feishu-format-acceptance-20261014/simple.md 和 rich.md 为虚构无图片样本，静态分类分别基础正文和 code/inline/table；rich 包含五类行内样式。README 明确父验收前关闭本人通知并清空群/联系人；worker 未进行任何创建、发布、通知、浏览器实际操作。UI 测试和离线样本分类不代表实文档格式验收。部署切换及网络验核由父任务独立记录。
