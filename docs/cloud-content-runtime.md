# 公网内容处理 runtime

此模式处理用户明确提交的内容，正文仍由客户端保存；它不是跨设备同步服务。源码与离线验证不能代替部署验收或真实 ASR/LLM 验收。

## 开关与部署

`VINOTE_CONTENT_CLOUD` 默认 false；只有同时启用 `VINOTE_WORKSPACE_CLOUD=true` 才可启动。现有 workspace 模式的 PostgreSQL、Supabase 验证、私有 Storage、服务端加密配置和禁止自代理要求继续生效。`VINOTE_CONTENT_UPLOAD_MAX_BYTES` 默认 134217728（128 MiB），允许 1 KiB 到 512 MiB。文档提取仍另限 20 MiB。

部署只通过审核过的 overlay 显式增加开关，不修改原 workspace Compose，也不写入客户端配置。保留现有环境、卷、网络、端口和镜像回滚点。以原 integration 镜像为 base 时必须覆盖同一不可变候选 HEAD 的完整 tracked Python 源码，不能将新 router 与旧 service 混用。增量依赖按该 HEAD 的 requirements.txt 核验；本改动没有新增 Python 三方包。单 Uvicorn worker，单提交/后台执行槽；反代同时配置上传大小和请求速率限制，不自动重放 POST。

本轮修改 Python 文件：

- `app/config.py`
- `app/__init__.py`
- `app/services/generation_auth_service.py`
- `app/services/vilab_cloud_service.py`

本轮新增 Python 模块：

- `app/routers/cloud_content.py`
- `app/routers/content_capabilities.py`
- `app/services/cloud_content_identity.py`
- `app/services/cloud_content_worker.py`

其依赖包括既有 note/source-request/source-job、task-artifact/model-source/origin/failure、NoteService、LLM/STT/transcription、ASR 检查点与 provider、文档提取、speaker readiness，以及 db/models/auth/workspace-bootstrap。源码快照应包含全部 tracked app Python 文件，不包含环境文件、数据库、媒体或 output。

## 身份、数据库与凭证

**这是 additive schema 变更**：新私有表 `content_cloud_identities` 以验证过的 `(issuer, subject)` 为复合主键，owner 为唯一 UUID 命名空间。模块在 create_app 注册路由时导入，先于 startup/init_db；表通过同一事务建表、启用 RLS，并从 PUBLIC、anon、authenticated 撤销直连权限。启动角色必须具备相应权限，不能因权限失败跳过保护。已有表列结构的兼容性仍需部署前核验，create_all 不代替旧表迁移。

先使用已验证 issuer/subject 的 CloudAccountDB 绑定；没有绑定则创建独立 UUID。绝不按邮箱猜绑，不创建 UserDB/password/session 记录。首次绑定后保持 owner，不因后来出现同邮箱或新的本地绑定迁移任务。来源回执、冻结模型和任务归属直接使用这个 owner；离线完整 pipeline 在开启 FK 的隔离数据库验证了无 UserDB 行的路径。

公网入口只接受 Supabase 验证的、已确认且非匿名 Bearer。Cookie 不能替代 Bearer。认证失效为 401；认证服务故障保留 502/503 语义，不冒充登录失效。

纯异步 ASGI middleware 在验证后建立 ContextVar lease，AnyIO 后台线程与现有并行执行复制该上下文。lease 覆盖响应发送及被等待的 BackgroundTasks；应用调用结束、失败或取消时撤销，并清空 token。复制过的 context 也因共享 lease 撤销而失效。VILabCloudService 和内容专用转写适配器均读取此 lease；不读取旧 refresh 会话、不轮换 refresh token，不把 Bearer 放入任务参数、JSON、数据库、模型快照或回执。token 过期不自动续期或重放，保留原任务供核验。

## 受控端点与客户端能力

| 端点 | 行为 |
| --- | --- |
| GET `/api/content-service/capabilities` | 验证 Bearer；返回协议和能力，不创建身份映射/任务，不查询模型 |
| POST `/api/generate` | 公开网页/文档及 B 站 BV、av、b23 视频链接；模型快照与提交回执冻结后处理 |
| POST `/api/content-service/video-source` | 只读 B 站元数据预检，不创建任务/身份映射、不查询或调用模型，不返回签名 CDN 地址 |
| POST `/api/generate_from_upload` | 有界文档、逐字稿和媒体上传；禁止客户端服务地址、临时密钥、本机路径/文件 ID |
| GET `/api/source-requests/{operation_id}` | 只读当前 owner 的 durable 原提交 |
| GET `/api/task/{task_id}` | 严格归属后读取状态/结果；缺失 owner marker、标记不符或链接文件均失败关闭 |

协议包含 `content_service_protocol:1`、`generation:true`、`sync:false`、`max_upload_bytes`。预检仍需真实 Bearer，只说明身份和本机配置能力，不表示模型或 ASR 已验收。

**公网视频链接按平台声明能力**：`video_url:true`、`video_url_platforms:["bilibili"]` 仅表示支持 B 站专用协议，不保证当前网络可访问平台；其他视频平台仍拒绝。B 站入口先校验 HTTPS、严格域名、BV/av/分 P 或 b23 短链。`bilibili_source_service.py` 只访问固定公开 API 和允许的音频 CDN；每次跳转重新校验域名及全部 DNS 结果，TCP 绑定已验证公网 IP，保留原 Host/SNI 与 TLS 校验，禁止环境代理、Cookie 和账号凭证转发。流式下载有字节与时间预算，临时文件完整校验后才提交，不覆盖已有文件。不会回退通用 yt-dlp/curl 或联网 FFmpeg。

视频处理依次解析来源、下载 AAC 音轨、规范化音频、冻结模型下转写与总结、保存结果。保留 BV/分 P、原链接与标题；下载签名不持久化。原媒体来自 DASH 音轨，不需要为纯文字总结下载完整画面。公网暂不启用视频截图富化，避免通用下载器形成第二条不受控网络出口。模型阶段只在真实媒体完整准备后发生；失败不换模型、不重放任务。401/403/412/429 返回固定安全的来源受限提示，不误报为 ASR 失败。

媒体固定 demuxer、只允许 file/pipe 协议规范化为 WAV，MOV 禁止外部 data reference。规范化仍受资源限制，不能偷偷截断后继续转写。支持 WAV、MP3、MP4/M4A、WebM、FLAC、Ogg。客户端可直接导入已有媒体；公网能力不是同步功能。

普通设备模式提供相同 capabilities 路径，使用现有 generation 鉴权；`video_url:true`，2 GiB 产品选择上限，文档 20 MiB。其设备生成行为不因公网模式而改变。

本轮不注册设备文件、本地账号、笔记库、sync/workspace、同步生成、本机路径生成、旧 retry 或原件下载路由；不注册整个 note.router。其他既有 Feishu/MCP/plugin 路由保持原边界。

所有提交要求 `X-VINote-Operation-Id`，服务端从实际上传字节计算 SHA256 并复用 SourceRequestService。只有新预留操作能排队；已有 reserved/accepted 仅返回原回执，变更同一操作的来源或选项返回 409。中断或失败不自动重启；本轮公开状态始终不提供旧 retry 派发能力。后台复用 NoteService、冻结模型、正文生成/复核和 ASR 检查点，不恢复跨设备同步。

## 验证边界

专项测试为离线 mock：真实来源 POST、durable 回执、NoteService、FFmpeg 音频准备、转写/LLM 编排和结果读取；替换外部认证、目录、ASR 和 LLM 返回。覆盖 owner 隔离、缺标记拒绝、重复操作无重发、请求凭证隔离/撤销、只读预检、新表 RLS/grant SQL 契约。SQLite FK 检查不是实际 PostgreSQL 部署证明；mock ASR 不是实际提供方验收。Windows 测试使用短临时目录避免 MAX_PATH，不改分段或跳过真实链。

实际镜像、服务器 schema/权限、内存和磁盘配额、鉴权预检、回滚及真实提供方证据由部署持有人后续补充。不要仅凭 capabilities 或健康检查宣称内容生成实测成功。
