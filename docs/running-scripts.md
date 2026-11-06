# 运行与打包命令规范

所有日常命令从 VINote 仓库根目录执行。源码选择桌面或网页，安装包分正式版与测试版；所有入口均使用固定公网模型服务。旧 lan 名称仅保留独立开发身份，不切换服务。

## 常用入口

| 用途 | 命令 |
| --- | --- |
| 启动桌面开发版 | `yarn start` |
| 启动网页开发版 | `yarn start:web` |
| 构建测试安装包 | `yarn package:test` |
| 构建正式安装包 | `yarn package:release` |
| 查看正式发布计划 | `yarn release:plan <产物目录>` |
| 发布已验证的正式包 | `yarn release:publish <产物目录>` |

发版入口读取已构建产物，验证版本、已合并的源码提交、签名与哈希，然后上传至 VINote 源仓库和公开下载仓库。正式版使用 `v<版本号>` 标签；测试包独立安装，不写入正式 OTA 源。多平台产物可依次传入多个目录；详见[桌面 OTA 发版](desktop-ota-release.md)。

## 底层入口与兼容身份

| 用途 | 命令 | 固定 VILab Server |
| --- | --- | --- |
| 桌面源码·兼容测试身份 | `yarn dev:desktop:lan` | `https://api-hk.orulink.ai` |
| 桌面源码·公网 | `yarn dev:desktop:public` | `https://api-hk.orulink.ai` |
| 网页源码·兼容测试身份 | `yarn dev:web:lan` | `https://api-hk.orulink.ai` |
| 网页源码·公网 | `yarn dev:web:public` | `https://api-hk.orulink.ai` |
| 正式安装包 | `yarn package:release` | `https://api-hk.orulink.ai` |
| 测试安装包 | `yarn package:test` | `https://api-hk.orulink.ai` |

地址集中定义在 `scripts/service-environments.mjs`，这六个入口忽略 `VILAB_SERVER_URL` 及旧 `VINOTE_TEST_VILAB_SERVER_URL` / `VINOTE_DEV_VILAB_SERVER_URL` / `VINOTE_RELEASE_VILAB_SERVER_URL` 的覆盖。后端 `app/config.py` 同样固定该地址，不接受 `.env` 覆盖，也不提供外部地址编辑或切换。

## 源码运行

四个源码入口均准备依赖、启动本机 VINote API（`127.0.0.1:8900`）和 Vite（`127.0.0.1:3100`）。桌面模式再启动 Tauri；网页模式自动打开浏览器，不检查 Rust 工具链。两者均支持前端热更新和 Python 热重载，桌面额外支持 Rust 自动重编译。

界面通过本机 VINote 后端调用固定公网 VILab Server。入口强制前端使用同源 API 代理，忽略旧 `VITE_API_BASE_URL`；连接公网并不把笔记数据库和录制文件迁移到公网。VINote 不启动或打包 VILab Server。

兼容测试桌面源码身份为 `app.vinote.desktop.test.dev`，公网为 `app.vinote.desktop.dev`，名称分别是 VINote Test Dev / VINote Public Dev。桌面源码追踪统一属于 `development`，网页不启用桌面追踪。测试包属于 `test`，正式包属于 `production`。

源码后端数据库和文件目录仍遵循仓库配置；切换服务地址不会创建独立数据库。桌面登录与录制存储随应用身份区分；网页两种模式使用相同浏览器 Origin，因此共用浏览器存储。

一次只运行一个源码实例。切换前在原终端按 `Ctrl+C`。启动器检查 8900 和 3100 端口，不复用不明服务、不结束其他项目进程；退出时清理自己启动的进程树。Windows 后端信号隔离控制台保持隐藏。

首次运行需要 Node.js 22+、Python、FFmpeg/FFprobe；桌面额外需要 Rust 和平台编译工具。`yarn setup` 只准备桌面开发依赖、配置和说话人模型，不打开窗口。已有 `.env` 保留。

## 配置预览与验证

六个入口均可追加 `:plan`，例如：

```powershell
yarn dev:desktop:lan:plan
yarn dev:desktop:public:plan
yarn dev:web:lan:plan
yarn dev:web:public:plan
yarn package:release:plan
yarn package:test:plan
```

预览只显示配置，不初始化依赖、不启动服务、不调用模型、不打包。打包预览仍校验账号与 Langfuse 配置。`yarn client:check` 验证脚本契约，`yarn verify` 执行项目检查。

数据库、Supabase 账号、Langfuse 等仍读取原有配置。正式包改连公网 VILab 不改变 Langfuse 的地址；其默认内网地址在外网可能不可达，运行时追踪网络失败不阻断业务，构建仍要求追踪写入和读取验证。

## 打包与低层工具

四个源码入口均使用 Vite HMR；前端修改自动同步到已打开的网页和桌面窗口。Python 后端由 `scripts/backend-dev.py` 管理 Uvicorn 热重载，仅每秒监听 `app/`、`main.py`、`mcp_server.py`，避免扫描音频、模型和客户端构建目录，Rust 由 `tauri dev` 监听并重新编译。修改后端会重载工作进程，进行中的生成任务可能中断；安装包是固定构建产物，不具备源码热更新。

接口脚本发起的本地测试可在被 Git 忽略的 `data/dev-tasks.json` 登记 `[{"taskId":"任务 UUID","label":"音频测试"}]`。源码界面显示“会议处理进度”，有活动任务或读取错误时每两秒通过当前登录会话读取真实任务状态，全部结束后放缓至每三十秒，包括错误、转写时长和服务端提供的预计剩余时间。任务注册接口仅存在于 Vite 开发服务，不包含媒体、凭证或转写内容，安装包不加载此面板。删除登记文件即可隐藏面板。

正式与测试包保留独立安装身份和应用数据目录，可同时安装。两个渠道按顺序构建；产物位于 `.desktop-build/artifacts/<channel>/<version>/<buildId>/`，不自动上传或发布。Windows/macOS 须在对应系统构建，详见[桌面打包](desktop-packaging.md)。

`yarn dev:api` 仅启动后端，同样忽略 `VILAB_SERVER_URL`，固定使用上述公网服务。`cd frontend && npm run web:dev` 仅启动 Vite；`yarn build` 只构建前端。它们不是上述六个完整入口。

## 旧入口兼容

| 旧命令 | 新入口 |
| --- | --- |
| `yarn dev`、`yarn dev:desktop`、`yarn client:test:dev`、`start-dev.*` | `yarn dev:desktop:lan` |
| `yarn client:dev` | `yarn dev:desktop:public`，不再连接本机 9878 |
| `yarn dev:web`、`yarn web:dev` | `yarn dev:web:lan`，现在同时启动后端 |
| `yarn client:test`、`yarn desktop:build:test` | `yarn package:test` |
| `yarn client:production`、`yarn desktop:build`、`yarn desktop:build:release` | `yarn package:release` |

旧开发和打包入口会打印替代命令；已有预览别名继续支持。`scripts/dev-desktop.mjs` 保留直接调用兼容，旧 `--channel test` 和 `--channel development` 保留各自开发身份，两者均使用固定公网服务。

实现由 `dev.mjs` 共用启动与清理，`desktop-dev-profile.mjs` 解析源码身份，`service-environments.mjs` 提供固定地址，`bootstrap-dev.mjs` 准备依赖。`build-desktop.mjs` / `desktop-build-profile.mjs` 负责打包；`windows-backend-dev.py` 保留 Windows 信号隔离。
