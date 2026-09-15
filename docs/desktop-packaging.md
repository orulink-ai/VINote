# 正式版与测试版打包

## 入口与默认服务

| 运行方式 | 命令 | 默认 ViLab 地址 | 数据位置 |
| --- | --- | --- | --- |
| 源码开发 | `yarn client:dev` | `http://127.0.0.1:9878` | 开发配置指定的位置 |
| 正式安装包 | `yarn desktop:build:release` | `http://192.168.1.143:9876` | `app.vinote.desktop` 对应应用数据目录 |
| 测试安装包 | `yarn desktop:build:test` | `http://192.168.1.143:9876` | `app.vinote.desktop.test` 对应应用数据目录 |

`yarn desktop:build` 保持兼容，等同于正式版。测试安装包同样连接已部署服务，不能自动继承源码 `.env` 的本地 `VILAB_SERVER_URL`。确有需要时，分别使用 `VINOTE_RELEASE_VILAB_SERVER_URL`、`VINOTE_TEST_VILAB_SERVER_URL` 显式覆盖，值必须是没有账号密码、路径和查询参数的 HTTP(S) Origin。

测试版显示为 **VINote Test**，版本为基础版本加 `-test`，主程序和后端分别为 `vinote-test`、`vinote-test-backend`。正式版继续使用 `VINote`、`vinote`、`vinote-backend`。安装身份、笔记数据库、登录状态、后端端口记录独立；首次使用测试版需单独登录。Windows 安装器按当前渠道的程序名检查占用，不关闭另一渠道的后端。

## 构建检查与产物

```powershell
yarn desktop:check
yarn desktop:build:release --plan
yarn desktop:build:test --plan
yarn desktop:build:test
```

`--plan` 仅显示渠道、版本、安装身份及默认服务，不安装依赖或启动应用。`--build-id <标识>` 可覆盖构建标识，默认使用 UTC 时间。

构建过程准备前端、Python 后端、FFmpeg/FFprobe、说话人模型和本地运行库，先运行冻结后端的烟雾检查，再构建 Windows NSIS 或 macOS app/dmg。烟雾检查实际初始化说话人模型、执行短音频推理和降噪过滤，避免只检查模型文件名。

- 中间目录：`.desktop-build/release/` 或 `.desktop-build/test/`。
- 发布候选产物：`.desktop-build/artifacts/<渠道>/<版本>/<构建标识>/`。
- 同目录 `manifest.json` 记录版本、渠道、服务地址、代码提交、工作区是否有未提交改动，以及安装文件 SHA-256。

这两个命令生成可分发安装包，不自动上传 GitHub、对象存储或应用商店。请依次执行构建命令，不同时启动两个渠道构建；前端构建输出仍共用 `frontend/dist`。macOS 产物必须在 macOS 构建，签名、公证仍需相应凭证。

## 源码与安装包的说话人功能

源码首次启动会检查 sherpa-onnx / NumPy 以及模型，缺失时运行 `scripts/setup_diarization.py` 准备。可用 `yarn client:dev --setup-only` 初始化而不打开桌面窗口。首次模型下载需要网络；后续复用本地文件。

安装包携带模型和原生运行库，终端用户无需安装 Python、pip 或手动下载模型。打包时复用源码模型缓存，模型放在后端资源目录。原始音频保持不变，降噪及识别仅处理临时副本，并保留时间轴。真正的 STT 和 LLM 仍需连接上述 ViLab 服务；模型内置不代表云端识别可以离线使用。

录制失败、取消启动、关闭并丢弃或组件退出时会释放麦克风与屏幕共享；授权等待超过 20 秒会结束请求，随后才返回的音频流也会立即停止。停止录制先释放设备，再完成本地文件保存。暂停仅暂停录制写入，保留设备供继续录制。相关释放逻辑由源码与两种安装包共用。

包内保存服务 Origin、Supabase publishable 配置，以及按用户要求固定接入的 Langfuse 项目配置。Langfuse 凭据由构建环境注入后端资源，可被安装包持有人提取，不进入 Git、前端或日志。不保存开发 `.env`、个人会话、模型 API key、JWT 密钥或会议音频。每个安装身份独立初始化本地密钥。

两种渠道必须提供 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`，地址默认 `http://192.168.1.118:3000`。构建时使用冻结后端发送合成链路并从 Langfuse API 读回，失败即阻止打包；manifest 保存 `langfuse` 回执。两种包分别标记 `test`/`production`，均无需额外 `langfuse.env`，详见 [Langfuse 接入说明](langfuse.md)。

会议事实复核的模型偏好 `MEETING_REVIEW_MODEL` 也会写入公开配置，默认 `gpt-6-astra`；两种包一致。构建环境可显式覆盖（空字符串表示沿用当前模型）。只在云端目录确认模型可用后使用，不会切换用户的全局模型。复核会增加真实 LLM 调用，当前模型仍负责初稿；本地/自定义模型复核复用当前提供方。

## 会议设置与云端模型

会议录制以及桌面端导入的音频、视频和视频链接均自动区分发言人、自动判断人数；开始会议前只需选择麦克风和是否录屏。默认尝试采集电脑声音；环境不支持时，明确提示并提供“仅录麦克风继续”。转写后可修改发言人姓名，无需配置说话人开关或人数。会议页、笔记整理和设置页提供已部署的语音转写、内容总结模型，选择后按账号自动保存，下一次生成生效；空选项跟随服务默认。不可用模型不能用于新任务，已经开始的任务保留原有模型。

## 录制文件与会议历史

点击停止后，录音或视频立即保存在当前设备的会议历史，无需生成纪要。历史卡片可播放、下载、确认删除，或之后再生成纪要。关闭页面或重启应用后仍可查看；本机录制不跨设备同步。清除应用数据会清除这些本机文件，请按需下载备份。

生成纪要后，详情页提供原始录制的下载及单独删除入口。删除文件保留文字纪要、转写和截图，停止回放后执行；只有已验证归属的创建者可以删除，旧版未记录归属或被多篇纪要共用的录制只提供下载。导入时用户自己的原始文件不会被删除。

录制停止时间和累计时长独立保存，延后生成纪要不会把生成时间当作录制结束时间，录制起止也不自动等同于实际会议起止。

流程参考：[腾讯会议本地录制](https://meeting.tencent.com/support/topic/420/)与[录制文件管理](https://meeting.tencent.com/support/topic/1841/index.html)。
