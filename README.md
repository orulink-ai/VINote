# VINote

分支约定：桌面端与后端从最新 `origin/dev` 创建功能分支，PR 合入 `dev`；`VINote-app` 子仓库从其最新 `origin/main` 创建功能分支，PR 合入 App 的 `main`。父仓库固定已审查的 App 提交，不会自动切换子仓库分支。查看 App 分支时，应在 Git Graph 中选择 `VINote-app` 仓库，或单独打开该目录；首次检出子仓库使用 `git submodule update --init VINote-app`。

公网内容处理的显式开关、Bearer 鉴权、私有表及能力边界见 [公网内容 runtime](./docs/cloud-content-runtime.md)。默认保持关闭；它不恢复跨设备同步。

[English README](./README.en.md)

VINote 是一个将视频或音频内容转换为结构化 Markdown 笔记的全栈工作台。

当前版本：`v0.3.0`

当前技术栈：

- 前端：React 18 + Vite + TypeScript
- 后端：FastAPI
- 数据库：PostgreSQL
- 认证：FastAPI 签发 JWT，并通过 HttpOnly Cookie 保存会话
- 部署目标：本地 Docker 与树莓派局域网 Docker

## 核心能力

- 从视频 URL、本地音频/视频文件或本地文字稿生成结构化 Markdown 笔记
- 已有文字稿时可直接跳过 STT，缩短生成链路并减少额外转写成本
- 笔记编辑器支持摘要与转写证据双视图，可切换原始/清洗文本、重命名说话人、跟随媒体时间轴并独立导出
- 上传媒体会保留浏览器或本地文件的原始字节，并由任务媒体清单安全定位；必要的音频规范化使用独立副本
- 支持多种总结模式：`default`、`accurate`、`oneshot`
- 按明确来源引用提供时间戳跳转；会议视频结合真实抽样画面，截图不凭章节顺序虚构时间
- 保存笔记并在内置编辑器中继续修改
- 支持公开只读分享链接
- 支持 LLM / STT 配置管理
- 模型设置分为「云端模型」和「本地 / 自定义」：云端直接使用部署的 VILab Server 模型，无需额外账号或用户密钥；本地模式支持本机 STT 与自行配置的兼容 API。
- 自定义配置的已保存密钥支持显示 / 隐藏，仅配置所有者可读取，失焦或 30 秒后自动隐藏。
- 同时提供独立文档站与 FastAPI Swagger / ReDoc
- 文档支持中英文双语，默认中文，英文入口为 `/en/`

## 输入入口

### 桌面与 App 工作台升级（开发中）

桌面和 App 的主入口均将会议、笔记分开，另有文件库和插件；启动默认进入会议。会议负责录制、导入音视频或逐字稿并生成纪要；笔记负责链接、PDF/Word 等文件整理与写笔记。文件库保留原文件的播放、导出与删除。飞书和 MCP 位于插件，模型与设备偏好位于设置。界面规范和实机验收约束见 [UI 设计](docs/ui-design.md)。

文件库先按「会议素材 / 笔记素材」归属分组，再按音频、视频或文档筛选；相同格式也可能属于不同内容。原文件可重新归类，删除原文件不会删除已生成的会议纪要或笔记。桌面 B 站链接由当前设备安全下载来源音轨，保留 BV/分 P 并将原件绑定到账号和任务，不远程拉取视频截图；音轨使用音频控件，仍可打开原视频来源；其他网页及视频链接若未保留原文件，仅在笔记来源与处理记录中展示。

当前产品关闭跨设备自动同步。会议、笔记与各版本由当前设备管理，原始音视频保留在来源设备；可从该设备回听或导出。历史 `/api/workspace` 接口保留兼容用途，不应在界面声称两端已同步。

桌面会议列表按已验证的账号及同一原录制身份显示一条主记录，默认打开最新保存的可读纪要，展开可查看各份纪要与原录制入口；每份保留实际标题、保存时间和全部历史版本。重新总结和独立生成的子任务通过服务端单跳 canonical 原件引用归组，未知关系不按标题或时间合并。鉴权 `GET /api/notes` 与单份详情可返回只读 `meeting_source {owner_id, canonical_task_id}`；该字段不授予原文件读取或生成权限，文件缺失不删除纪要关联。

MCP 工具管理使用 `/api/mcp-connections`，支持 HTTPS Streamable HTTP，新增或变化的工具默认关闭，执行前确认。飞书文档位置、权限与逐接收者交付状态见 [飞书接口约定](docs/feishu-api-contract.md)。未配置企业应用时界面显示配置状态，不模拟授权、建文档或消息成功。

- 浏览器生成页支持三种模式：视频 URL、本地音频/视频文件、本地文字稿
- 会议录音悬浮窗会把浏览器录音作为本地音频上传，并将结果保存为 `meeting_recording` 类型笔记
- `POST /api/generate` 处理 URL 输入
- `POST /api/generate_from_upload` 处理浏览器上传的本地音频、视频和文字稿
- `GET /api/notes/{note_id}/transcript` 读取笔记对应的本地转写证据和来源元数据
- `PATCH /api/notes/{note_id}/speakers` 保存该笔记的说话人显示名称
- 上传文字稿时支持 `TXT`、`MD`、`SRT`、`VTT`、`JSON`，并直接跳过 STT

### 桌面重新总结与播放恢复

桌面 ASR WebSocket 显式关闭 websockets 的环境／Windows 用户代理自动发现，保留默认 TLS 证书与主机名校验；不修改系统代理，也不在失败后自动切换代理。系统 TUN/VPN 路由仍独立生效。故障诊断仅保留白名单异常类别、有效接收 close code 和 `ws_proxy_mode="disabled"`，不保存 reason 原文、URL 或凭证。

模型 HTTP／SSE 与账号刷新同样显式直连，保留默认 TLS 校验。总结超时或未收到完整终态时保留材料并停止，不自动重发；历史总结失败也不能通过原任务重试绕过确认。即使尚未保存纪要，会议任务页也可明确选择「仅重新生成纪要」，复用完整逐字稿、说话人和视频资料；成功后独立保存，未知操作只查询原回执。

已有完整转写的会议可明确确认「重新总结」，重新选择当前云端目录中的 LLM，创建独立结果，保留旧纪要、版本及原件；不会再次 ASR 或修改全局模型偏好。失败或成功的原任务均需通过账号、原件版本和完整转写核验；从子任务重新总结仍直接引用同一份原件，不复制媒体或形成引用链。

- 鉴权 `GET /api/task/{task_id}/summary-context` 只读确认上下文，返回 `context_revision`、`source.version`、`transcript_version` 和 `canonical_task_id`。
- 鉴权 `POST /api/task/{task_id}/regenerate-summary` 要求 `operation_id`（UUID）、`confirmed:true`、`context_revision`、`source_version`、`model_name`。只有首次持久接受且通过执行核验的任务会派发；已预留、已接受或结果未知时通过原提交回执和任务 GET 查询，不自动重发或调用旧重试入口。
- 失败的独立任务可通过鉴权 `GET /api/task/{task_id}/new-generation-context` 获取 `protocol:2` 上下文；明确确认的 `/new-generation` POST 还须提交该上下文的 `canonical_task_id`。新 operation 将直接父任务、canonical 原件、模型和版本绑定到 DB 回执；新任务仍一跳引用原件，仅复用直接父任务严格确认的连续 ASR 前缀（含重新核验的 typed empty），不复制旧 plan/inflight、不回退较短全局缓存、不自动重排未知操作。内部 `NewGenerationService.preflight_parent(owner, parent, normalized_wav)` 可用相同预处理得到的 WAV 离线核验采样边界和 checkpoint SHA，不创建 operation 或调用模型；实际执行仍重新核验、加锁并先 fsync 新 seed。v1 原件任务确认契约保持兼容。
- 笔记媒体与任务媒体 GET 的 `playback=true` 可为 WebM 准备可拖动的播放副本；FFmpeg 只做流复制封装，播放失败可重新加载，导出始终保留原始字节。播放恢复不触发生成。

会议视频从已保留原件准备有界的时间轴/变化画面及 OCR，连同完整原始 ASR 窗口供草稿和事实复核使用。只有所选模型的目录或实际能力核验允许时才发送图片，并遵守输入限制；纯文字模型只使用实际 OCR，不声称看过图片。抽样不代表逐帧理解；识别缺口、采样及技术诊断只约束内部推理，不生成技术报告章节，也不据此编造讨论、决定或待办。说话人时间窗不能确证某句话的身份。

v2 的 opaque `context_revision` 同时冻结父锁内核验的 checkpoint SHA-256 与精确确认采样边界，并通过该 revision 纳入 operation fingerprint；前缀快照由服务端写入新任务，客户端不能指定。GET 后、POST 后或 seed 前父记录发生任何变化均阻断，不能重新采用缩短后的前缀；修改磁盘 link 也不能覆盖 live lease 内冻结的快照。公开确认字段保持不变。

流式 ASR 只有在本机完整发送当前区间、服务返回匹配会话的协议化空终态证据时，才记录「已提交但未识别出文字」并继续；这不代表静音或完整识别。缺少证据、旧错误码和网络未知结果仍保持失败、禁止自动重放；整份录音无识别文字不会冒充纪要成功。该能力需要对应服务部署支持；源码、离线测试和真实设备/供应商验收分别记录。

## 文档说明

项目包含两层文档：

- 使用文档站：位于 `docs/`，由 VitePress 构建
- API 参考：由 FastAPI 自动生成 Swagger / ReDoc

文档站：

- 中文默认入口：`/`
- 英文入口：`/en/`
- 本地默认地址：`http://localhost:3101`

API 参考：

- Swagger：`http://127.0.0.1:8900/docs`
- ReDoc：`http://127.0.0.1:8900/redoc`

如果文档站和 Swagger 描述不一致，以 Swagger 为准，然后再修正文档。

## 本地开发

### 云端模型部署配置

账号等配置仍由部署管理员在根目录 `.env` 设置。源码入口明确选择内网或公网；正式包固定连接 `官方公网服务`，测试包固定连接 `http://192.168.1.143:9876`，这些入口不接受 VILab 地址环境变量覆盖。独立后端仍读取 `VILAB_SERVER_URL`。详见[运行脚本规范](docs/running-scripts.md)。Supabase 配置与模型供应商密钥管理保持原有方式。

「设置 → 模型服务」提供云端与本地/自定义运行模式切换，并按 VINote 用户保存。视频链接、文件上传、文字稿和会议录音统一遵循该模式；进行中的任务保持开始处理时的配置，切换只影响后续任务。

新 URL/上传请求可成对提供 `asr_model` 与 `model_name`，经模型目录校验后只冻结当前云端任务；本地模式拒绝该模型对，不改全局偏好或已有快照，旧 `model_name` 单项行为保持兼容。

用户在设置中选择云端 STT 与 LLM 模型并保存。转写使用 `/v1/asr/transcriptions`，总结使用 `/openai/v1/chat/completions`。VILab 返回整段转写时仅标记文件级时间范围，不提供虚构的逐句时间戳。云端返回 401/403 时需要管理员修复服务鉴权，用户仍可直接切换本地模式；切换模式本身不依赖云端在线。

新增 VINote API 均要求登录：`GET/PUT /api/vilab/config`、`PUT /api/vilab/mode`、`GET /api/vilab/models`。自定义密钥按需读取接口为 `POST /api/model-profiles/{id}/reveal-key`、`POST /api/stt-profiles/{id}/reveal-key`，响应禁用缓存。

依赖要求：

- Python 3.10+
- Node.js 18+
- FFmpeg
- Docker Desktop 或 Docker Engine

后端：

```bash
pip install -r requirements.txt
cp .env.example .env
python main.py
```

如果需要本地 `faster-whisper`：

```bash
pip install -r requirements.local-transcribers.txt
```

热重载模式：

```bash
uvicorn main:app --host 0.0.0.0 --port 8900 --reload
```

前端：

```bash
cd frontend
npm install
cp .env.example .env.local
npm run web:dev
```

建议统一从仓库根目录运行；完整命令、配置优先级和兼容入口见[运行脚本规范](docs/running-scripts.md)：

```bash
yarn setup        # 首次初始化依赖、配置和说话人模型，不启动应用
yarn dev:desktop:lan    # 桌面源码，内网
yarn dev:desktop:public # 桌面源码，公网
yarn dev:web:lan        # 网页源码，内网（同时启动后端）
yarn dev:web:public     # 网页源码，公网（同时启动后端）
yarn package:release    # 正式安装包，公网
yarn package:test       # 测试安装包，内网
yarn dev:api      # 仅后端
yarn dev:web      # 兼容入口：内网网页，自动启动后端
yarn verify        # 后端、前端、脚本和文档的合并前检查
yarn check         # 前端生产构建 + 桌面脚本检查
```

四个源码入口统一管理后端与前端，8900 或 3100 已占用时会报错，不复用已有服务；切换模式前先退出原实例。
`yarn dev` 使用跨平台 Node.js 脚本，可在 Windows PowerShell 和 macOS 终端中运行，不依赖 Bash；会自动启动并等待 VINote 后端就绪。桌面开发需要 Rust 工具链，以及 Windows C++ 构建工具或 macOS Xcode Command Line Tools。
`yarn dev` 会自动选择已安装后端依赖的 Python；如需手动指定，可设置 `VINOTE_PYTHON=/path/to/python`。
后端使用 `.env` 的数据库配置；未配置时使用本地 SQLite。已配置数据库无法连接时会明确报错，不会悄悄切换到另一份数据库。

文档站：

```bash
cd docs
npm install
npm run docs:dev
```

兼容启动器会直接转发到 `yarn dev`，不再单独管理端口或启动另一套服务：

```powershell
.\start-dev.ps1
```

## 桌面 App

桌面端基于 Tauri 2，复用现有 React/Vite 前端界面。安装包内置 FastAPI 后端、SQLite 与 FFmpeg，安装后无需 Python/Node。后端由桌面壳首次选择可用本机端口并持久保存，退出时一并停止；数据和加密密钥保存在用户应用数据目录。开发模式通过 Vite 代理访问 8900 后端。

首次开发桌面端前需要安装 Rust 工具链：

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

如果本机没有 Yarn，可以先启用 Corepack：

```bash
corepack enable
```

桌面热更新开发模式：

```bash
yarn dev
```

打包前只查看渠道配置，不构建：

```bash
yarn client:test:plan
yarn client:production:plan
```

生成测试版或正式版安装包：

```bash
yarn client:test
yarn client:production
```

构建产物按渠道和版本归档到 `.desktop-build/artifacts/<channel>/<version>/<buildId>/`，包含校验清单；详见 [桌面打包](docs/desktop-packaging.md)。

## Docker

启动本地容器栈：

```bash
docker compose up --build
```

会启动：

- `postgres`
- `backend`
- `frontend`
- `docs`

默认端口：

- 前端：`http://localhost:3100`
- 后端：`http://localhost:8900`
- 文档站：`http://localhost:3101`

## 树莓派部署

VINote 现在支持两条树莓派部署路径：

- 开发机手动部署
- GitHub Actions 驱动的树莓派 self-hosted runner 自动部署

### 手动部署

推荐顺序：

1. 从 `.env.example` 生成根目录 `.env`
2. 从 `deploy/pi/local.env.example` 生成 `deploy/pi/local.env`
3. 先运行 bootstrap，准备 Docker、Docker Compose 和远程应用目录
4. 再运行 deploy

Bootstrap：

```powershell
.\deploy\pi\bootstrap-pi.ps1
```

```bash
./deploy/pi/bootstrap-pi.sh
```

Deploy：

```powershell
.\deploy\pi\deploy-pi-interactive.ps1
```

```bash
./deploy/pi/deploy-pi-interactive.sh
```

```powershell
.\deploy\pi\deploy-pi.ps1
```

```bash
./deploy/pi/deploy-pi.sh
```

手动脚本继续保留，作为紧急重部署和调试时的 fallback。

### `dev` 自动部署

共享测试环境的推荐流程是：

1. PR 合并到 `dev`
2. GitHub Actions 收到 `push`
3. 树莓派 self-hosted runner 在本机 checkout 合并后的 commit
4. 树莓派直接基于当前 checkout 重建并启动服务

关键配置：

- Workflow：`.github/workflows/deploy-pi-dev.yml`
- 触发条件：`push` 到 `dev`，以及 `workflow_dispatch`
- Runner 标签：`self-hosted`、`linux`、`arm`、`pi`、`vinote-test`
- GitHub Environment：`pi-test`
- Runner 使用的本机部署脚本：`deploy/pi/deploy-from-checkout.sh`

### 树莓派一次性准备

在树莓派上完成以下初始化：

1. 安装 Docker 和 Docker Compose
2. 在独立目录中安装 GitHub Actions runner，例如 `/home/zouyu/actions-runner`
3. 注册 runner，并打上 `self-hosted,linux,arm,pi,vinote-test` 标签
4. 将 runner 安装为系统服务
5. 将 runner 用户加入 `docker` 组
6. 保持应用部署目录为 `/home/zouyu/vinote`

不要把应用目录直接拿来当 runner 工作目录。

### GitHub Environment `pi-test`

在 GitHub 中配置：

- Secret `PI_TEST_ENV_FILE`
  - 内容为树莓派测试环境使用的完整根目录 `.env`
- Variable `PI_REMOTE_DIR`
  - 默认值：`/home/zouyu/vinote`
- Variable `FRONTEND_PORT`
  - 默认值：`3100`
- Variable `BACKEND_PORT`
  - 默认值：`8900`
- Variable `DOCS_PORT`
  - 默认值：`3101`

workflow 会先把 `PI_TEST_ENV_FILE` 写入 checkout 目录中的 `.env`，然后 `deploy-from-checkout.sh` 会刷新 `/home/zouyu/vinote`，并把这份 `.env` 同步到部署目录。

### 自动部署行为

workflow 会：

1. 在树莓派 runner 上 checkout 当前触发 commit
2. 从 `PI_TEST_ENV_FILE` 写入 `.env`
3. 检查 Docker、Docker Compose、`curl` 以及 docker 组权限
4. 调用 `deploy/pi/deploy-from-checkout.sh`
5. 以 `docker compose up -d --build --remove-orphans` 重建并拉起服务
6. 对 `127.0.0.1` 上的 backend、frontend、docs 做 smoke check
7. 输出 `docker compose ps`
8. 失败时输出 backend / frontend / docs 日志

部署时会保留树莓派上的 `data/` 与 `output/` 目录。

更多树莓派部署说明见 [deploy/pi/README.md](./deploy/pi/README.md)。

## 验证建议

常用检查项：

- 文档站构建：`cd docs && npm run docs:build`
- 后端健康检查：`GET /healthz`
- Swagger：`http://127.0.0.1:8900/docs`
- 浏览器上传冒烟：分别测试 URL、本地音视频、本地文字稿三种生成入口
- 前端测试：`cd frontend && npm run test`
- 前端构建：

```bash
cd frontend
npm run build
```

## 说明

- 浏览器认证使用后端签发的 HttpOnly Cookie
- 侧边栏 `Document` 可通过 `VITE_DOCS_BASE_URL` 指向独立文档站
- 如果文档和代码不一致，以代码为准，并在同一改动中修正文档

### VINote 独立云端账号（本地联调）

云端账号接口为 `GET/DELETE /api/vilab/account`、`POST /api/vilab/account/code`、`POST /api/vilab/account/verify`，需要当前 VINote 登录。通过邮箱验证后关联独立云端身份，不按相同邮箱自动合并历史账号。当前本地账号登录保留，云端在设置页单独连接。Supabase 需要配置 SMTP，并把注册确认和 Magic Link 邮件模板设为显示 `{{ .Token }}` 验证码。

模型请求只发送到 `VILAB_SERVER_URL`，不会从 VINote 直接请求供应商。云端 ASR 上传前会用 ffmpeg 转成 16 kHz 单声道 PCM WAV。短期令牌与刷新令牌加密保存在 `cloud_accounts`，不返回浏览器。退出会清理该用户的云端会话；数据库使用 SQLite 时请使用单个后端 worker。

本地服务端启动及联调结果见 `docs/plans/2026-09-09-cloud-account-integration.md`。当前开发渠道与发行默认地址以[运行脚本规范](docs/running-scripts.md)为准。


### VINote 统一云端登录

配置 `VINOTE_SUPABASE_URL` 和 `VINOTE_SUPABASE_PUBLISHABLE_KEY` 后，登录页区分登录和注册：`/api/auth/sign-in` 使用 Supabase 邮箱密码认证；注册通过 `/api/auth/register/code` 设置密码并发送验证码，再经 `/api/auth/register/verify` 验证邮箱。邮箱与用户身份的权威绑定保存在该 Supabase 项目的 `auth.users`，个人访问凭证由 Supabase 签发（JWT 的 `sub` 对应该用户），不是另建一份固定模型 API Key。验证成功同时建立 VINote HttpOnly 会话并加密保存可刷新的 Supabase 会话；模型页不再提供第二次登录。访问令牌与刷新令牌不写入公开用户资料表。VILab Server 验证此项目的用户令牌后，按 `(issuer, subject)` 解析业务账号；模型供应商密钥仅保存在 VILab Server。配置 Supabase 后只显示统一账号的登录/注册入口；本地/云端是模型运行模式，不是两套账号。未配置 Supabase 的独立部署保留原有密码认证。

### 云端当前模型



会议说话人区分先在临时副本上降噪，再对同一完整录音执行覆盖完整录音的分段 STT 和本地 sherpa-onnx 说话人分析，不会按每个发言轮次重复调用 STT。STT 有句级时间戳时按区间重合关联说话人；只有全文时按发言有效时长顺序估算，并在任务元数据中标明。自动模式以持续发言的声音特征进行平均链接聚类和轮廓评分选组，不把每个短片段当成新人；证据不足与重叠发言单独标注。`yarn dev` 会自动检查并准备依赖和模型，也可用后端 Python 手动运行 `python scripts/setup_diarization.py`；`DIARIZATION_MODEL_DIR` 可覆盖模型目录。编号仅在同一次录音中保持一致，真实姓名需人工确认；分组数量不代表逐段身份判断已完全准确。`DIARIZATION_CLUSTER_THRESHOLD` 仅用于初始聚类诊断。

会议纪要按问题、主题、确认决策和明确行动整理；没有依据的负责人、期限和未决问题不补写，时间线仅辅助回听。实际会议起止时间只采用明确提供的信息；累计录音时长不包含暂停，不能用来推算会议结束时间。短会议和长会议的分段合并均遵循这项规则。

会议默认将完整来源提交一次生成草稿，再由同一冻结模型对照完整来源复核，增加一次模型调用；不会因为会议较长自动分块。只有显式旧 `accurate` 模式使用分块合并，视频证据不接受该模式。历史 `MEETING_REVIEW_MODEL` 不再决定复核模型；视觉、上下文或服务错误不会自动换模型、改用分块或重放推理 POST，未知结果只查询原记录。复核失败不静默返回未复核稿；复核不能恢复缺失信息或保证所有识别错误都已消除。

正式版使用 `yarn package:release`，固定连接 `官方公网服务`；测试版使用 `yarn package:test`，固定连接 `http://192.168.1.143:9876`。测试版保留独立安装身份和数据目录。产物与校验清单位于 `.desktop-build/artifacts/`，详见[打包说明](docs/desktop-packaging.md)。

真实会议生成验证可运行 `python scripts/check_meeting_generation.py data/diarization-four-speakers.wav --live --speakers 4 --output data/meeting-live-report.json`。它调用桌面端共用的上传、任务、保存、逐字稿和媒体接口，真实消耗云端 STT/LLM，并在当前唯一关联账号的个人空间保存一条标注「测试」的笔记；多账号需传 `--user-id`。该后台检查不验证原生麦克风、录屏权限或桌面窗口交互。

### Windows / macOS 统一启动与打包

需要 Node.js 22+、Rust，以及 Windows C++ Build Tools/WebView2 或 macOS Xcode Command Line Tools。两个项目分别运行，VINote 不启动或打包 VILab Server。

1. 源码选择桌面或网页、内网或公网入口；不需要在本机启动 VILab Server。
2. 运行 `yarn dev:desktop:lan` / `yarn dev:desktop:public`，或 `yarn dev:web:lan` / `yarn dev:web:public`。首次自动准备依赖、`.venv` 和 `.env`（不覆盖已有文件），启动本机后端与前端。桌面打开 Tauri，网页打开浏览器。
3. 源码桌面统一使用 development 追踪环境，网页不启用桌面追踪；账号配置仍使用 `VINOTE_SUPABASE_URL` 和 `VINOTE_SUPABASE_PUBLISHABLE_KEY`。
4. 安装 FFmpeg/FFprobe 并加入 PATH，然后运行根目录 `yarn client:production` 或 `yarn client:test`，脚本会自动初始化依赖和安装 PyInstaller。Windows 生成 NSIS `.exe`，macOS 生成 `.app` 和 `.dmg`，归档到 `.desktop-build/artifacts/`。必须在对应系统上构建；签名/公证需要各平台的发布证书。
5. 固定地址集中在 `scripts/service-environments.mjs`，不接受旧渠道地址变量覆盖。打包保留公开账号配置和构建管理的 Langfuse 配置，不打包 `.env`、模型密钥或个人数据。

`VINOTE_PYTHON` 可指定 Python；`VINOTE_FFMPEG_PATH`、`VINOTE_FFPROBE_PATH` 可指定打包用的二进制文件。macOS 请使用可分发的同架构 FFmpeg（其动态依赖也须可分发）。
首次运行检查可用：yarn setup（只初始化依赖/配置，不打开额外桌面窗口）。邮箱公共配置来自 config/desktop-public.json，用户不需要填写云端模型 API Key；自托管版本可通过 .env 覆盖公开账号配置。源码处理音视频需要 PATH 中的 FFmpeg 和 FFprobe。

### 账号登录与密码恢复（桌面端）

启用 VINote Supabase 后，注册使用邮箱、密码与注册验证码；日常登录使用邮箱密码。历史验证码账号若尚未设置密码，可使用“忘记密码 / 首次设置密码”，通过邮箱恢复验证码设置密码，原账号和笔记保持不变。后端 `/api/auth/password/code` 发送恢复邮件，`/api/auth/password/reset` 验证 recovery OTP 后更新密码，不向前端返回 Supabase 令牌。配置云端认证时，旧本地注册接口拒绝另建本地账号。

Supabase 的 Reset password 邮件模板须包含 `{{ .Token }}`，用户在桌面端输入验证码，无需跳转 localhost 登录链接。密码不正确、邮箱未验证、验证码过期、服务暂不可用分别显示可操作的错误提示。

安装包云端依赖服务器已部署支持多身份来源与 `/v1/default-models` 的对应分支。服务端保留 ViTalk 的身份来源，并在 `VILAB_AUTH_SUPABASE_SOURCES_JSON` 添加 VINote 的 Project URL 和 publishable key；安装包构建成功不代表远端部署已经升级。

Windows 覆盖安装/卸载会检查并关闭 VINote 主进程及其 `vinote-backend.exe` 后端，避免旧进程占用 DLL。打包后端监视桌面父进程，即使安装器强制关闭主窗口，后端也会自动退出；用户数据保存在独立应用数据目录，不随安装文件覆盖。

# Langfuse 追踪

VINote 桌面端使用独立 Langfuse 项目追踪生成链路，业务根名称固定为「桌面端｜会议纪要」和「桌面端｜笔记整理」。Trace 记录完整 STT/LLM 输入输出、实际模型、用量与耗时，并覆盖说话人检测、聚类、关键帧和保存结果；浏览器、Pi 和普通后端请求不上报。配置、安装版接入、数据边界和真实上报验证见 [Langfuse 接入说明](docs/langfuse.md)。

### 会议录制管理

会议停止后自动保存到本机历史，无需先生成纪要；支持播放、下载、确认删除及稍后生成纪要。录音采集所选麦克风；录屏额外保存所选窗口或显示器的画面。已生成纪要的原始文件可在详情页单独管理，删除录制不会删除文字纪要。详见 [桌面端使用与打包](docs/desktop-packaging.md)。

## 会后统一处理（2026-09-21）

会议页只确认麦克风；点击“开始会议”后再选择是否共享屏幕，选择共享才打开系统选择器，不预选是否生成纪要。录制期间不调用 ASR 或总结模型；结束后先保存完整原始媒体、释放设备并关闭控制，再由用户选择“生成会议纪要”或“暂不生成”。暂不生成时保留本地历史，之后仍可手动生成。说话人区分继续使用本地模型，VILab 负责完整音频转写和总结，结果按时间戳对齐。视频使用实际代表帧证据，不代表逐帧理解。

转写分别展示实际送交识别的音频位置和已确认保存的转写区间；发送到末尾不代表最终识别成功，没有中间结果时不虚构进度。VILab 会话限制只能来自服务明确声明，不能按模型名称设置固定秒数。只对明确瞬时错误有界重试同一模型，未知最终结果不自动重放。所有进度采集仅在录制结束后运行。

本地历史持久化任务 ID、草稿 ID、失败阶段和进度。POST /api/task/{task_id}/retry 校验录制所有者与媒体后复用任务和有效产物。旧进程中断任务显示可重试。保存笔记后保留本地原始媒体直到用户明确删除。

App 独立仓库、账号与本机数据边界、运行/打包入口及验证限制见 [App 集成说明](docs/app-integration.md)。手机端在 `VINote-app` 子目录提供四个 Android 入口：`android:test:debug`、`android:test:apk`（内网 VINote Test）和 `android:vinote:debug`、`android:vinote:apk`（公网 VINote）。

会议标题默认采用 `YYYY-MM-DD HH:mm｜内容`：以已记录的录制开始时间创建“待生成纪要”占位，完成后从最终纪要主题生成标题；不使用生成时间冒充会议时间。本地录制支持改名，纪要详情支持编辑标题；生成时保留手动改过的录制或草稿标题。

## 记录工作台与飞书

独立的“笔记”入口直接提供 **粘贴链接**、**导入文件**，标题区提供 **写笔记**。两端支持 B 站分享文字与其他公开视频、普通公开网页、PDF/DOCX 链接，以及本地音视频和文字文件生成 Markdown。PDF/DOCX 最大 20 MB，PDF 最多 200 页；扫描 PDF、加密文件、旧 DOC 和需要登录的网页会明确提示替代导入方式。文档提取不调用转写、不伪造说话人或音频播放器；失败可恢复原任务。会议录制与会议文件导入保留在会议页，不按文件扩展名混入笔记列表。

App 生成入口先在本机保留选中文件，再显式上传处理；已接收任务会保存编号，返回再进入查询同一任务。处理或本地保存失败提供原任务恢复，不自动重复生成。开发版经 USB 转发到当前电脑内容服务；正式包还需要配置具备生成能力的 HTTPS 集成服务。移动 Bearer 必须由 Supabase 验证并已与当前服务的 VINote 用户绑定，未绑定时给出明确提示。

会议与笔记分别作为一级入口；文件库管理来源文件，插件管理飞书内置连接与 MCP 工具，设置和账号独立。会议详情提供正文、逐字稿、说话人、全部版本与飞书交付。桌面飞书通过本机官方 CLI 扫码连接用户自己的应用，凭据由 CLI 管理，不经过共享飞书代理；App 现有接入保持独立。完整配置、API、恢复流程和验证边界见 [飞书接入说明](docs/feishu-integration.md)。

桌面可在“插件 → 飞书”明确设置文档位置与通知联系人，开启后仅自动发布后续新生成并保存的个人会议纪要。默认关闭，历史纪要与编辑不补发；交付失败不影响纪要保存，响应未知时查询原结果，避免重复建文档或通知。此能力在桌面执行，无需增加公网后台；对象热词可绑定真实联系人与群，详见 [会议纪要自动交付](docs/feishu-auto-delivery.md)。


### 会议处理与失败恢复

桌面与 App 将完整转写和本机说话人分析同时进行，分别保存进度后再交给已选总结模型。某一路失败时保留另一份成功结果及原录音，重试复用有效检查点。分段转写和独立声音时间轴都有录音偏移；分钟级转写不等于精确逐句归属，详情中可回听核对和为本次录音改名。

桌面详情支持左侧原媒体、右侧纪要/逐字稿/对话与固定播放区；App 使用固定播放器和底部操作面板。飞书设置失败保留修改；桌面导航后可恢复本账号草稿。删除录音失败保留播放源。App 本机推理需要包含原生模块的新安装包，不能仅通过 JS 热更新安装模型；Android 已有实现，iOS 需在 macOS 构建验证。见 VINote-app/README.md 的运行与打包说明。

纪要中的录音时间引用可以点击回听；桌面逐字稿提供“跟随播放”开关，加载失败可单独重试。两端详情返回进入时的内容或录制工作台。数据库中的 UTC 创建时间返回带时区标记，客户端按本地时区展示，避免 SQLite 丢失时区后的八小时偏差。

桌面支持一条引用中的多个时间区间分别回听，并显示转写服务未识别出文字的区间；这些区间不能据此认定静音，总结也不得推断缺失发言。两端飞书交付先读取已有状态，再允许提交；状态读取或群列表刷新失败可独立重试，已有通知对象与输入继续保留。

声音组需重复且持续的发言证据：至少两段代表发言、累计有效特征时长六秒；孤立短声音保持待确认，重叠保留。特征分析最多 128 个代表和 128 个补充窗口、每窗八秒。组数不是参会人数或身份准确率。工作台空筛选可一键清除，读取失败在列表提供重试；飞书授权核验保留未保存设置，会议对话空白回答保留问题供重试。

会议和笔记列表直接打开各自详情；文件库管理原文件播放、导出、稍后整理和独立删除。桌面侧栏只保留会议、笔记、文件库、插件与底部设置/账号；App 底栏为独立的会议、笔记、文件库、插件，头像进入账号与设置。统一布局、字阶、状态与旧组件清理边界见 [界面规范](docs/ui-design.md)。原录音波形通过鉴权接口按需生成并缓存，不需要重新转写或总结。

跨设备自动同步已按用户决定从当前产品入口撤下。共享 API 的历史方案见 [跨设备内容同步](docs/shared-workspace.md)，不得当作现行可用功能展示。

第一方中英翻译通过真实 HTTPS Streamable HTTP MCP 提供。插件页连接 VINote 云翻译后，需要发现工具并明确启用；从内容详情选择正文，预览本次参数，再确认执行。完整译文先预览，由用户保存新版本，不自动发布飞书。连接使用当前云会话，不要求用户粘贴地址或密钥；服务端需要配置现有 VINote 云模型 Origin。部署与实际翻译结果必须另行核验，不能用本地测试代替。
