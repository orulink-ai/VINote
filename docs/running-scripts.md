# 运行与打包命令规范

所有日常命令从 VINote 仓库根目录执行。参考 ViTalk README 的“先选对命令”约定：`client:*:dev` 为源码热更新，`client:test` / `client:production` 为安装包构建。

## 正在运行 / 开发调试

| 命令 | 用途 | 模型服务 |
| --- | --- | --- |
| `yarn client:test:dev` | 测试开发版桌面窗口，前端热更新、Python 热重载、Rust 自动重编译 | 默认 `http://192.168.1.143:9876` |
| `yarn client:dev` | 普通开发版桌面窗口，使用本地开发配置，同样支持热更新 | 默认 `http://127.0.0.1:9878` |
| `yarn dev:web` | 仅浏览器预览，不启动桌面或后端 | API 代理到本机 `8900`，需另开 `dev:api` |
| `yarn dev:api` | 仅 VINote Python 后端 | 读取 `.env` 中的 `VILAB_SERVER_URL` |
| `yarn setup` | 准备依赖、配置和说话人模型，不打开应用 | 不启动模型服务 |

桌面命令自行启动 VINote API（8900）、Vite（3100）和 Tauri。这两个本机地址不等于模型服务地址。VINote 不启动或打包 VILab Server；普通开发模式需要自行启动本地 VILab Server。

测试开发版使用 `app.vinote.desktop.test.dev`，普通开发版使用 `app.vinote.desktop.dev`，与安装版身份分开。WebView 登录与本地录制存储随应用身份区分，因此新身份首次需要登录。源码后端仍使用仓库 `.env` 的数据库和文件目录，**不代表两套独立后端数据库**。

两种源码模式不同时运行。切换前在原终端按 `Ctrl+C`；如果端口被其他服务占用，启动器会明确报错，不复用不明后端、不结束其他项目的进程。Windows 只保留原启动终端和桌面窗口，后端信号隔离控制台隐藏。

## 配置与只读预览

通用数据库、账号、Langfuse 配置仍读取根目录 `.env`，脚本不覆盖已有文件。桌面渠道显式选择模型服务，避免旧的通用 `VILAB_SERVER_URL` 让两个模式串线：

- 测试开发与测试打包：`VINOTE_TEST_VILAB_SERVER_URL`，未设置时连接内网默认地址。
- 普通开发：`VINOTE_DEV_VILAB_SERVER_URL`，未设置时连接本机 `9878`。
- 正式打包：`VINOTE_RELEASE_VILAB_SERVER_URL`，未设置时连接内网默认地址。

可写入 `.env` 或当前终端环境变量；终端环境变量优先。设置后重启命令。启动器会打印实际地址、渠道和 Langfuse 环境；测试开发记录在 `test`，普通开发记录在 `development`，正式安装包记录在 `production`。

```powershell
yarn client:test:dev:plan
yarn client:dev:plan
yarn client:test:plan
yarn client:production:plan
```

预览只校验并显示配置，不安装依赖、不打开窗口、不调用模型、不打包；不代表服务器连通性验证。打包预览仍要求完整的打包配置。

## 生成安装包

| 命令 | 结果 |
| --- | --- |
| `yarn client:test` | 测试安装包，连接内网服务，供同事安装 |
| `yarn client:production` | 正式安装包，使用正式渠道配置 |
| `yarn client:check` | 检查渠道、命令映射和配置隔离，不实际打包 |
| `yarn verify` | 合并前的后端、前端、脚本和文档检查 |

打包不自动上传或发布。Windows / macOS 分别在对应系统构建，两个渠道按顺序打包。产物位于 `.desktop-build/artifacts/<channel>/<version>/<buildId>/`；资源、追踪校验及签名要求见[桌面打包](desktop-packaging.md)。

## 旧入口兼容

旧入口只转发同一实现，不维护另一套启动流程：

| 旧命令 | 对应常用命令 |
| --- | --- |
| `yarn dev`、`yarn dev:desktop`、`start-dev.*` | `yarn client:test:dev` |
| `yarn package:test`、`yarn desktop:build:test` | `yarn client:test` |
| `yarn package:release`、`yarn desktop:build`、`yarn desktop:build:release` | `yarn client:production` |
| `yarn desktop:check` | `yarn client:check` |

VINote 的 `yarn dev` 保持已有桌面启动行为，与 ViTalk 的网页预览含义不同。日常使用明确的 `client:*` 命令即可。`yarn build` 只构建前端，不生成安装包。

脚本职责：`dev-desktop.mjs` 管理开发进程，`desktop-dev-profile.mjs` 解析开发渠道，`bootstrap-dev.mjs` 准备依赖，`windows-backend-dev.py` 隔离 Windows 后端信号，`ensure-web-dev.mjs` 启动或复用 Vite；`build-desktop.mjs` / `desktop-build-profile.mjs` 负责安装包构建及身份配置。
