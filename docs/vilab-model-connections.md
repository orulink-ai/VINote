# 桌面模型连接

模型设置保留本机/自定义模式，以及通过 VILab 服务处理的模式。“管理连接”可以选择内置默认、已保存连接或添加服务根地址。启动和发行配置的固定地址继续作为默认值，用户保存的连接可明确覆盖它。未改发行地址或 VILab-server。

“检查连接”仅 GET `/v1/models`，不推理、不写入偏好、不自动选择首个模型。“保存并使用”才切换；检查失败、取消均保留当前连接。公网要求 HTTPS；本机、解析确认为内网的地址可用 HTTP。拒绝地址中的账号、密码、路径前缀、查询参数和片段。请求禁止重定向、忽略系统 HTTP 代理，HTTPS 保留默认 TLS 校验。

VINote 登录账号保持不变。内置连接沿用原账号认证/部署凭据。外部连接明确选择“已登录的 VINote 账号”或“此连接的 API key”。账号模式在用户输入/选择地址并点击“用已登录账号检查”后，才向该精确 Origin 发送当前共享会话 token；内网 `http://192.168.1.143:9876` 与官方公网 `https://api.orulink.ai` 支持这一显式操作，其他地址额外展示确切 Origin 的授权确认。catalog 可读本身不构成凭据共享授权。

账号连接保存认证方式及共享账号的 issuer/subject 绑定，不复制 token；执行时通过原有 shared-account helper 获取/刷新当前 token，身份绑定变化时失败关闭。API key 模式不继承其他服务的账号 token 或部署密钥；密钥使用现有设备加密配置存储，不回传明文、不进入任务 JSON 或浏览器持久存储。账号模式不使用 API key，也不在认证失败时切换认证方式。

## 接口

- `GET /api/vilab/connections`：当前账号的内置/已保存连接及非敏感状态。
- `POST /api/vilab/connections/check`：接受 `{server_url, api_key?}` 或 `{connection_id, api_key?}`；账号模式明确附 `auth_mode:"account", account_consent:true, authorized_origin:"<确切 Origin>"`，且不能提供 API key。缺少同意或地址不匹配时，在读取 token、请求 catalog 之前拒绝。返回 `{check_id, server_url, auth_mode, models, expires_in, asr_model, llm_model}`。`connection_id: "default"` 表示内置服务。地址变化不能借用旧 ID 的凭据。
- `PUT /api/vilab/connection`：接受 `{check_id, asr_model, llm_model}`。检查绑定账号、地址、凭据和连接修订，十分钟有效，保存成功后消费。过期、账号或连接变化需重新检查。
- 原 `GET /api/vilab/config` 增加 `connection_protocol: 1`、`connection_revision`，外部连接另带 `connection_id`、`connection_auth_mode`。原模型选择 PUT 可附当前 `connection_id`、`connection_revision`，拒绝 catalog 读取期间的切换竞态。

新增连接管理接口不在共享云运行时提供。`vilab_connections` 保存各账号不可变的地址/凭据绑定和独立模型选择；`vilab_connection_states` 保存活动指针与修订；新增 `vilab_connection_auth` 仅记录账号授权元数据，缺失记录的旧连接仍为 API key 模式，不自动获得账号授权。新表由既有初始化创建，不改变旧表列。原 `vilab_preferences` 的运行模式和内置模型选择继续兼容。

## 已有任务

`VILabCloudService.connection_snapshot(owner)` 只读当前已保存配置，不读 catalog、不推理、不导出密钥。任务冻结具体模型、Origin、连接 ID 和 `connection_auth_mode`；HTTP、SSE、PCM ASR 与旧兼容 HTTP ASR 都解析原账号的原连接。换密钥或认证方式建立新 ID，旧记录继续服务原任务。历史无 ID 的快照仅匹配原内置 Origin；缺失、篡改、其他账号的绑定失败关闭，不回退。

summary-only 等调用方在受理时从该函数读取连接并保留 `connection_id`、`connection_auth_mode`；严格快照不保存 `configured` 等界面字段。执行使用 `validate_source(snapshot, owner)` 校验已持久连接，再进入 `task_snapshot(owner, snapshot=snapshot)`；不能通过再次读取当前选择来替换或否决已受理任务，受理快照完整性须由原操作持久回执绑定。对应 summary 集成由其模块独立测试。本协议不改变 unknown 或 ASR 检查点重放策略。

连接身份 epoch 模块不依赖任何 store。`authStore` 完成创建后同步发布账号变化，避免连接模块初始化时读取尚未完成初始化的 auth store，同时保留同批 A→B→A 失效保护。

## 验证边界

`tests/test_vilab_connections.py` 用合成 DB、HTTP 桩覆盖只读检查、显式保存、账号/地址/凭据隔离、轮换、快照、HTTP ASR 绑定和切换竞态。设置组件测试覆盖取消、失败、地址改变及账号 ABA 迟到响应。离线通过不代表外部服务、实际推理或原生桌面交互已验收。
