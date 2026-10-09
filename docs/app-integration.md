# App 与桌面端集成边界

[English](en/app-integration.md) · [App 中文说明](https://github.com/orulink-ai/VINote-app/blob/main/README.md) · [App 运行与打包](https://github.com/orulink-ai/VINote-app/blob/main/docs/build-and-deployment.md)

`VINote-app/` 是独立 React Native Git 子模块，远端为 https://github.com/orulink-ai/VINote-app ，主分支为 `main`；父仓库集成分支为 `dev`。首次拉取执行 `git submodule update --init --recursive`；不要使用 `--remote` 绕过父仓库固定的已审查提交。App 提交先推送，再提交父仓库 gitlink。

## 账号、来源和数据

当前 App 直接访问同一 Supabase 项目和 VILab 服务，不经过电脑 FastAPI；不需要运行桌面端即可使用。账号共用不意味着数据共用：App 录音、转写检查点和纪要保存在手机本机，按账号隔离，尚未与桌面笔记库同步。

父仓库 `auth_login_events` 记录经过 FastAPI 登录/注册验证接口的成功登录（用户、UTC 时间、白名单客户端及平台）。请求头为客户端自报备注，不参与鉴权。当前 App 的直接 Supabase 登录不进入该表，统一登录审计尚未闭环。普通退出只清除当前客户端凭证，不断开其他客户端仍使用的共享云端账号；已有 JWT 按到期机制失效，并非退出即全端撤销。

上传任务首次写入 `generation_client`，保存到 notes 时读取任务标记；编辑/重试不改原始来源。旧笔记或损坏/缺失标记显示未知，不用保存请求猜测。App 本机纪要写 mobile 来源，不能因此声称已支持跨端同步。数据库启动初始化兼容增加来源字段及审计表。

完整有效的已保存 ASR/LLM 选择直接使用，不依赖旧版默认模型接口；无效选择仍回退经验证的服务默认模型，不绕过个人账号认证。

## 运行与打包入口

父仓库既有 `yarn client:dev`、`yarn client:test:dev`、`yarn client:test`、`yarn client:production` 只针对桌面端，不会启动或打包 App；原命令语义不变。App 在子目录执行 `npm ci` 后，使用 `npm run android:test:debug` / `android:test:apk` 运行或打包内网 VINote Test，使用 `npm run android:vinote:debug` / `android:vinote:apk` 运行或打包公网 VINote。两个 Debug 模式连接 Metro；公网 Debug 使用独立包名以保护正式版本机数据。公网 APK 需要发布签名。详见子仓库双语打包说明；不把 APK、私有录音、令牌和密钥提交到任一仓库。

当前 Android 0.1.0 提供内网 VINote Test 和公网 VINote 两个独立包；测试包仍需访问内网服务，正式包使用公网 HTTPS VILab。两版共用 Supabase 账号入口，但手机本机数据互不共享。独立 APK 不依赖 USB/Metro。iOS 源码待 Mac/iPhone 编译和验证；生成需前台；说话人区分暂停。桌面端说话人能力不自动赋予 App。

## 合并与验证

App 合并 `main` 后，父仓库更新到准确提交，再合并 `dev`。不强推、不重写历史。`dev` 的 push 通常触发 `.github/workflows/deploy-pi-dev.yml` 部署 Pi 测试环境；需要仅合并、不部署时，在合并提交消息使用 GitHub 支持的 `[skip ci]`。这不修改工作流，也不部署 VILab。

本次 App 审查验证包含单测、类型、配置回归及 Android 双包构建。真机曾完成公网短语音生成和内网 28 分钟会议样例；0.1.0 包完成覆盖安装和启动检查。真机历史验收范围见 App 文档，不把这些结果表述为 iOS、长录音公网稳定性或后台生成均已验证。
