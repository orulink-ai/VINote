# VINote Langfuse tracing

VINote 使用独立 Langfuse 项目，记录后端笔记生成任务。实现参考 ViTalk 桌面端远端 `dev` 提交 `33111e5dfa8f7dc71bc6259a4377ab799d736be0`（0.6.4）：中文步骤名、真实父子链路、环境和版本标签、用户标识加盐哈希、输入输出脱敏摘要、实际模型请求参数及供应商用量。使用 Langfuse Python SDK 4 的 OTLP 导出。

## 本机开发配置

在根目录 `.env` 配置项目凭据，然后重启后端：

```dotenv
LANGFUSE_BASE_URL=http://192.168.1.118:3000
LANGFUSE_PUBLIC_KEY=替换为VINote项目PublicKey
LANGFUSE_SECRET_KEY=替换为VINote项目SecretKey
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_RELEASE=0.5.0
LANGFUSE_CAPTURE_CONTENT=false
```

源码、测试安装包与正式安装包固定启用，旧 `LANGFUSE_ENABLED=false` 不再关闭追踪。源码缺少项目凭据会在启动时明确报错；两种安装包缺少凭据会阻止构建。SDK/网络导出故障不阻断笔记生成，但不视为追踪验收通过。后台批量上报，正常关闭后端时清空队列；强制终止进程可能丢失未上报记录。默认地址为 `http://192.168.1.118:3000`，构建者可通过后端配置迁移地址。

`LANGFUSE_CAPTURE_CONTENT=false` 记录脱敏标记和字符数；设为 `true` 后记录提示词、识别文本和生成笔记。不会记录原始音视频、API key、认证头、本地文件路径或来源 URL。错误记录异常类型，不复制可能含凭据的供应商错误正文。用量仅记录供应商返回的数据；不估算缺失 token，不伪造非流式请求的首 token 时间。模型费用由 Langfuse 对支持的模型定价计算，自定义模型需配置价格。

## Trace 层级

一次 URL、本地音视频或字幕生成对应一条「笔记生成全链路」chain，`sessionId` 对应 `task_id`，metadata 标记输入类型。实际执行到的步骤才产生 observation：

- 下载源媒体 / 准备本地媒体 / 准备上传字幕。
- 获取识别原文：缓存命中、字幕跳过 STT，或提取音频分块、调用语音识别、合并识别分块。
- 生成结构化笔记：一次性总结，或分块总结与全局合并；每次 LLM 请求对应 generation，记录模型、实际参数、prompt 哈希版本和用量。
- 处理时间戳与截图、保存 Markdown 笔记、保存生成结果。

失败记录在实际失败步骤及父链路上。任务 `status.json` 和任务状态 API 返回可选 `langfuse_trace_id`，可以在 Langfuse 搜索定位。这条链路从后端生成入口开始，不包含浏览器上传耗时或前端保存笔记到库的请求；VILab 云端仅记录 VINote 调用边界，未接入服务端内部 span 的跨服务传播。

## 安装版

测试与正式安装包从构建环境的 `.env` 或进程环境读取同一 VINote Langfuse 项目配置，写入后端资源 `desktop-config.json`。安装后无需手动创建文件；旧应用数据目录中的 `langfuse.env` 不再参与配置，父进程中的其他项目凭据也不能覆盖包内项目。环境分别为 `test`、`production`，源码为 `development`。旧安装包必须重新构建更新。

用户要求三种运行方式统一直接接入，因此安装包包含 Langfuse 项目凭据，安装包持有人可提取这些凭据。这是明确的分发边界，不能把冻结资源当成加密保管。凭据不得进入 Git、前端资源、日志和 manifest；开发 `.env` 整体、模型 API key、用户会话、数据库密码仍不得打包。

两个渠道构建都必须运行冻结后端的 `--langfuse-smoke-test`：上报合成笔记链路并通过 Langfuse API 读回，确认 environment、模型、用量与父子关系后才生成安装包。manifest 的 `langfuse` 字段保存不含密钥的验收回执。此检查需要构建机能访问 Langfuse；缺依赖、认证失败或读回失败会阻止产物生成。

## 验证

```powershell
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe scripts/check_langfuse.py --send
```

第二条 Python 命令会使用合成字幕与模拟 LLM 响应执行真实 NoteService 管线，并向配置的 Langfuse 发送记录，再通过公共 API 读回检查 session、模型与 token。它验证接入和字段落库，不验证真实 STT/LLM 效果；`tests/conftest.py` 仅在测试进程中关闭对外 tracing，不依赖产品关闭开关。
