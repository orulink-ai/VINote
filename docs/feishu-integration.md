# 会议工作台与飞书交付

手机和桌面入口统一为记录工作台，可搜索录音与会议、筛选未生成/处理中/需处理状态。停止录音后先保存原始媒体，再明确选择生成纪要或稍后处理。会议详情提供纪要、逐字稿、对话、编辑历史和飞书交付。桌面包、网页标识与手机沿用 `VINote-app/assets/branding/vinote-app-icon.png`。

## 用户连接流程

在设置中点击“连接飞书”，浏览器打开飞书 OAuth 用户授权，完成后返回 VINote 点击“我已完成授权”。第一版只接受管理员配置的同公司租户。支持本人和指定群同时通知；可用群是用户与机器人共同加入的群。机器人需要先加入目标群。

核验授权时保留未保存的通知设置，核验成功后仍需点击保存。群列表读取失败只影响群选择，账号状态和已选对象继续保留，可单独刷新；设置保存失败保留输入供重试。搜索群忽略两侧空白与英文大小写，无匹配时可以调整关键词。

默认以用户身份创建原生飞书 Docx 文档，保存到个人云文档。文件夹和知识库目的地尚未开放。用户授权不等于已经部署企业应用：管理员须先配置应用和集成服务，客户端不填写 App Secret。

自动交付是可选设置。首次完成纪要自动提交；编辑后需手动发布已保存版本。文档创建、正文写入、群阅读权限和每个接收对象的消息分别记录检查点；单个群失败不会使本机纪要生成失败，重试只继续未成功步骤。消息卡片包含原生飞书文档链接。

若创建请求超时，无法确认飞书是否已创建文档，系统暂停再次创建。用户在个人云文档查找同名空白文档，将链接填入交付面板关联后重试；确实未创建时，可先在飞书新建同名空白文档。只允许关联本公司、可访问、标题相同且没有正文的文档。中断任务的租约到期后显示可重试状态。

## 管理员配置

在受控服务端部署本仓库 FastAPI API，使用与 VINote 手机/桌面相同的 `VINOTE_SUPABASE_URL` 和 publishable key 校验账号。服务端配置：

| 环境变量 | 用途 |
| --- | --- |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 公司企业自建应用，Secret 仅在集成服务端保存 |
| `FEISHU_REDIRECT_URI` | 飞书允许的完整 OAuth 回调，例如 `https://你的集成域名/api/feishu/callback` |
| `FEISHU_TENANT_KEY` | 限定公司租户 |
| `FEISHU_DOC_BASE_URL` | 本公司飞书 Origin，例如 `https://公司域名.feishu.cn` |
| `MODEL_PROFILE_ENCRYPTION_KEY` | 加密持久保存的用户飞书 access/refresh token；保持稳定并备份 |
| `FEISHU_SCOPES` | 默认 `offline_access docx:document docs:permission.member:create docs:permission.member:auth docs:permission.setting:read docs:permission.setting:write_only drive:drive.metadata:readonly wiki:space:read wiki:node:read wiki:node:create im:chat:read docx:document.block:convert contact:user:search`；显式环境值完整覆盖默认值 |
| `VINOTE_INTEGRATION_URL` | 桌面本地 API 转发到共享集成服务的 Origin；集成服务本身留空以免转发循环 |

企业应用开启机器人能力、用户文档创建/编辑、文档权限成员管理、用户/机器人群列表读取，以及机器人 `im:message:send_as_bot` 权限，并发布至公司允许使用的人员范围。应用权限与用户 OAuth 授权都需完成。反向代理必须隐藏 `/api/feishu/callback` 查询串，避免记录授权码；应用已为 Uvicorn access 日志过滤该查询串。

手机 `config/deployment.{test,public}.json` 的 `integrationBaseUrl` 指向共享集成服务；公网配置要求 HTTPS Origin。2026-10-12 当前开发两端已使用 `https://supabase-vinote.orulink.ai/vinote-api`。用户选择既有「阳晓冰的智能助手」，新增公网回调后完成真实 OAuth，两端均读取“阳晓冰／已连接”。企业应用密钥由 `/api/feishu/application` 验证后按 VINote 账号加密保存，客户端不持久保存；应用管理在页面底部折叠，日常账号连接在顶部。桌面与手机按经验证的同一个 Supabase subject 关联飞书，不根据客户端声称的用户 ID 授权。公司默认应用仍需管理员统一配置，不能将某个用户的飞书 OAuth token 复制给其他用户。

不要将企业应用 Secret 写入手机配置、Tauri 包或 Git。桌面安装包需通过运行环境配置共享服务 URL；当前打包默认值未包含企业配置。所有飞书调用均由受控服务持有凭证完成。

## API 与持久化

`/api/feishu` 提供 `GET /status`、`POST /authorize`、`GET /callback`、`DELETE /connection`、`GET /groups`、`PUT /preferences`、`POST /deliveries`、`GET /deliveries/{note_key}`、`POST /deliveries/{job_id}/retry` 和 `POST /deliveries/{job_id}/document`。除 OAuth 回调外均要求 VINote Cookie 或服务端验证的云账号 Bearer。数据库启动建表：`feishu_connections`、`feishu_oauth_states`、`feishu_deliveries`，不需要客户端持有飞书凭证。

桌面新增 `GET /api/notes/{note_id}/versions` 与 `POST /api/notes/{note_id}/ask`，沿用笔记访问权限。`note_versions` 保存编辑前快照；手机在账号隔离的本机存储中保存编辑快照。生成历史与编辑历史相互独立。对话根据已保存资料回答，不执行资料中的指令。

手机自动交付提交持久保存，应用启动/回到前台可补交；桌面原录音历史保留提交标记。交付消息使用固定任务/对象 UUID，正文批次使用稳定 client token。服务没有持续后台队列调度器，因此两端不提供可开启的持续后台自动交付；进程中断后通过详情重试继续。飞书文档/通知配置由公网服务共享；VINote 正文与版本另由 workspace 同步，本机原始音视频不参与同步。

## 验证边界

自动化测试覆盖部分失败后的恢复、重复提交、账号隔离、OAuth 单次 state、其他公司拒绝、创建结果不确定时关联恢复、工作线程中断及授权码日志过滤。开发窗口和 USB 手机运行的是公网渠道源码，前端 Vite/Metro 热更新，后端 Uvicorn 自动重载。

未配置真实企业应用与共享服务时，不能完成真实授权、创建文档及机器人通知的端到端验收。手机现有逐字稿只有分钟分段起点，没有逐句说话人证据，界面如实说明。iOS 构建仍需 macOS/Xcode；不能用 Android 检查代替。


### OAuth scope 的配置归属（2026-10-14）

`POST /api/feishu/authorize` 由实际集成服务生成授权 URL，使用该服务的 `Settings.feishu_scopes`。默认值补齐 `docx:document.block:convert` 和 `contact:user:search`，分别用于原生 Markdown 转换和联系人搜索；没有添加员工 ID 或额外机器人消息权限。`FEISHU_SCOPES` 显式值完整覆盖默认值，不偷偷并入额外权限。账户自定义应用目前只覆盖 App ID/Secret、租户和文档域名，scope 仍来自服务配置。通过 `VINOTE_INTEGRATION_URL` 代理时，桌面/手机的配置不能替代公网服务配置。

已部署旧代码的服务可先在其 `deploy/workspace/cloud.env` 增加完整 `FEISHU_SCOPES` 非密钥列表（见上表），仅重新创建 workspace 服务使环境生效。父任务确认的公网目录为 `/home/ubuntu/vinote-workspace/releases/feishu-contacts-20261013/deploy/workspace`，使用 `compose.yml` 与 `existing-networks.yml`。该环境修正不需要传输源码、修改数据库或应用凭证；之后从 VINote 重新连接，必须使用新生成的 URL。应用后台权限发布、OAuth 请求包含 scope、用户实际授权及接口成功是不同证据；旧 token 刷新不等于补齐用户授权。

未来源码默认更新只需 `app/config.py`；格式转换功能部署另需当前 `app/services/feishu_service.py` 和新增 `app/services/feishu_markdown.py`，不能只复制 service 而遗漏 helper。本次源码和离线测试不代表已部署、已授权、已转换或收件人可读。
