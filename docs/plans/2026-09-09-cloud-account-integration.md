# VINote 云端账号与模型调用闭环

## 已核实的基础

- VILab Server 仓库 `D:/projects/vilab/VILab-server` 的 dev 已执行 `git pull --ff-only origin dev`，当前提交 `3a27795`，远端无新增提交。
- 部署端 `http://192.168.1.143:9876` 管理员登录和 `/admin/status` 均返回 200；状态为 v0.4.0、cloud_shared。用户确认部署跟随最新远端 dev，管理状态版本号本身不能证明提交 SHA。
- `src/infra/supabase_auth.rs` 当前从一组 URL/Publishable Key 构造验证器，向固定 Supabase `/auth/v1/user` 验证用户令牌。
- `src/public_api.rs` 已支持外部 API Key 或用户 access token；用户按 `(issuer, subject)` 关联 business_accounts，禁用用户返回 403。
- 当前用户令牌映射到 DEFAULT_INTERNAL_PROJECT_ID；`/v1/me` 对有效启用账号返回云端转写和改写能力 true。尚不能将此视为完整的按产品授权、额度和项目隔离。
- VINote 当前使用自己的邮箱密码登录和 HttpOnly 会话 cookie，云端使用管理员共享密钥。此前提供的模型密钥实测返回 401。

## 目标链路

VINote 注册/登录 → VINote 独立 Supabase Auth → 当前用户访问令牌 → VINote 后端代理 → VILab Server 验证身份和产品权限 → STT → LLM → VINote 保存笔记。

用户不填写、复制云端密钥。access token 是短期个人凭证，自动刷新，不生成一个永不过期的个人 key。ViTalk 的用户和会话不被 VINote 复用。

## VILab Server 改动

1. 新增管理员配置的可信身份来源列表（例如新增 VILAB_AUTH_PROVIDERS_JSON，具体名称以实现为准），包含产品标识、Supabase URL、Publishable Key 和内部项目映射；保留旧环境变量兼容 ViTalk。
2. 使用令牌 issuer 仅选择白名单中的验证器，最终仍由固定 Supabase 地址验证身份；不得根据任意令牌中的地址发起请求。
3. 保留 `(issuer, subject)` 身份主键，增加产品/项目授权映射；不按邮箱合并不同 Supabase 项目的账号，不统一落入默认内部项目。
4. 模型列表、STT、LLM、历史、录音、笔记结果及用量按已验证身份和项目检查权限。新账号是否自动启用，由 VINote 产品策略决定；`/v1/me` 返回实际权限。
5. 管理页显示身份来源、账号状态、产品和模型权限，支持禁用账号。管理员密码仅用于管理，不能成为用户模型调用凭证。

## VINote 改动

1. 接入新 Supabase 项目的注册/登录/邮箱确认；由 VINote 后端维护上游会话，前端继续使用 HttpOnly VINote cookie。现有本地账号功能保留，本地模式不依赖云端认证。
2. 增加外部身份映射和加密存储的刷新令牌；验证当前本地会话和云端身份后绑定，不能仅凭邮箱自动接管旧账号和笔记。
3. 按用户获取并刷新 access token，将其用于 VILab Cloud Service；删除普通用户云端调用对共享 VILAB_API_KEY 的依赖。刷新串行化，避免并发刷新令牌轮换冲突。
4. 后台任务保存发起用户身份，调用每一阶段时获取仍有效的令牌。模型来源保持任务快照，但不把短期访问令牌永久冻结在任务里。
5. 云端入口显示登录状态、服务连接和模型就绪状态；调用 `/v1/me`、`/v1/models` 成功后选择 STT/LLM。错误区分未登录、无权限、配置缺失和服务不可用。
6. 退出清除该会话的上游凭证；本地/自定义地址永远不会收到云端用户令牌。转写等非幂等调用不因认证刷新无条件重试。

## 配置与实施顺序

1. 创建 VINote Supabase 项目，提供 Project URL、Publishable Key，设置邮件注册/确认方式；若采用邮箱验证码，配置可用于真实用户的 SMTP。
2. 新 Supabase 暂仅用于 Auth，不迁移 VINote 笔记数据库。数据库密码与个人模型访问令牌无关。
3. 先实现并部署服务端多身份来源及项目授权，保留 ViTalk 配置，再接入 VINote 登录和模型请求。
4. 使用实际新账号登录完成验证，不用管理员代替普通用户执行验收。

## 验收闭环

- VINote 新账号：注册、确认、登录、刷新、退出；重新登录仍关联同一业务用户。
- 实际请求 `/v1/me`、`/v1/models`，短语音转写、转写结果生成笔记并保存。
- 用户 A 不能读取用户 B 的任务、媒体或用量；ViTalk/VINote 相同邮箱不被自动合并。
- ViTalk 原有登录调用继续可用；错误项目、失效令牌、禁用账号被拒绝。
- 切换本地不依赖云端服务；自定义模型密钥功能保留。

当前文档为方案，尚未修改或部署上述认证功能；新 Supabase 项目信息仍待提供。


## 2026-09-09 本地实现与验证进度

两个仓库均已从与 origin/dev 一致的 HEAD 创建 `codex/vinote-cloud-accounts`，未提交。

- VILab Server 新增多 Supabase 来源白名单，保留旧配置兼容；认证测试 6 项通过。
- VINote 新增独立云端账号邮箱验证入口、加密会话、刷新、退出清理；本地账号仍保留。配置已指向新 VINote Supabase 项目，模型服务仅指向本机 9878。
- 已验证供应商模型通过本地 VILab Server 调用：火山 TTS 返回 WAV，阿里云 ASR 返回“这是一段语音转写测试。今天完成模型服务的连接。”。
- 修复 VINote ASR 上传格式，自动转换 16 kHz 单声道 PCM WAV。
- 笔记不使用 ViTalk 口述润色接口（会触发保留原文的回退），改为 VILab Server `/openai/v1/chat/completions`。使用 MiniMax 完成真实语音→转写→Markdown 笔记管线。
- 上述管线诊断使用隔离的本地服务外部测试 key 注入测试进程，没有将其作为用户登录凭证保存；个人 Supabase 令牌端到端验证仍未完成，不能将模型链路通过等同于账号链路通过。
- 新项目 SMTP 未配置，用户尚未收到验证码；还需完成 SMTP/邮件模板配置和真实邮箱验证。
- 19 个网关模型首轮测试：7 个成功，8 个权限拒绝，2 个 Kimi 温度参数不兼容，ox-alpha 上游 404；一个 embedding 模型不属于笔记生成接口，未作为聊天模型测试。Kimi 参数适配已修复，待重测。
- 当前业务用户继续进入服务端内部默认项目；按产品项目授权和额度管理未在本轮基础接入中完成。
- 未修改 192.168.1.143 部署端配置，后续等待用户部署再切换 VINote 云端地址。


### 真实账号验收完成

2026-09-09 已配置 VINote Supabase 的自定义飞书 SMTP 和注册/登录验证码模板，收到并验证用户提供的邮箱验证码。个人 access token 请求本地 VILab Server `/v1/me`、模型列表、阿里云 ASR、MiniMax M2.7 笔记生成均成功。强制刷新到期标记后，真实 Supabase refresh token 轮换成功，刷新后的令牌再次通过 `/v1/me`。

VINote API 生成返回 200，保存笔记返回 201，随后更新并读取内容返回 200。测试笔记 ID 为 `[个人标识已省略]`。Kimi 两个模型修复后也均实际返回 OK，共 9 个可用聊天模型。

本机配置默认选中阿里云 ASR 和 MiniMax M2.7。服务器 `192.168.1.143` 未修改；两个仓库仍未提交。按产品授权/额度管理的后续事项保持不变。
