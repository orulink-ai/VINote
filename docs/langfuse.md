# VINote Langfuse tracing

VINote 使用独立 Langfuse 项目，记录后端笔记生成任务。实现参考 ViTalk 桌面端远端 `dev` 提交 `33111e5dfa8f7dc71bc6259a4377ab799d736be0`（0.6.4）：中文步骤名、真实父子链路、环境和版本标签、用户标识加盐哈希、输入输出脱敏摘要、实际模型请求参数及供应商用量。使用 Langfuse Python SDK 4 的 OTLP 导出。

## 本机开发配置

在根目录 `.env` 配置项目凭据，然后重启后端：

```dotenv
LANGFUSE_ENABLED=true
LANGFUSE_BASE_URL=http://192.168.1.118:3000
LANGFUSE_PUBLIC_KEY=替换为VINote项目PublicKey
LANGFUSE_SECRET_KEY=替换为VINote项目SecretKey
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_RELEASE=0.4.0
LANGFUSE_CAPTURE_CONTENT=false
```

默认关闭；缺少配置或 SDK/导出出错时继续生成笔记。开启后，后台批量上报，正常关闭后端时清空队列；强制终止进程可能丢失尚未上报的记录。项目密钥只放后端或本机配置，不放前端、版本库和安装包。

`LANGFUSE_CAPTURE_CONTENT=false` 记录脱敏标记和字符数；设为 `true` 后记录提示词、识别文本和生成笔记。不会记录原始音视频、API key、认证头、本地文件路径或来源 URL。错误记录异常类型，不复制可能含凭据的供应商错误正文。用量仅记录供应商返回的数据；不估算缺失 token，不伪造非流式请求的首 token 时间。模型费用由 Langfuse 对支持的模型定价计算，自定义模型需配置价格。

## Trace 层级

一次 URL、本地音视频或字幕生成对应一条「笔记生成全链路」chain，`sessionId` 对应 `task_id`，metadata 标记输入类型。实际执行到的步骤才产生 observation：

- 下载源媒体 / 准备本地媒体 / 准备上传字幕。
- 获取识别原文：缓存命中、字幕跳过 STT，或提取音频分块、调用语音识别、合并识别分块。
- 生成结构化笔记：一次性总结，或分块总结与全局合并；每次 LLM 请求对应 generation，记录模型、实际参数、prompt 哈希版本和用量。
- 处理时间戳与截图、保存 Markdown 笔记、保存生成结果。

失败记录在实际失败步骤及父链路上。任务 `status.json` 和任务状态 API 返回可选 `langfuse_trace_id`，可以在 Langfuse 搜索定位。这条链路从后端生成入口开始，不包含浏览器上传耗时或前端保存笔记到库的请求；VILab 云端仅记录 VINote 调用边界，未接入服务端内部 span 的跨服务传播。

## 安装版

安装版从 `VINOTE_DESKTOP_DATA` 对应的应用数据目录读取 `langfuse.env`，与 SQLite/`desktop-secrets.json` 同级。文件仅需 BASE_URL、PUBLIC_KEY、SECRET_KEY 三项以及可选 `LANGFUSE_CAPTURE_CONTENT`；凭据齐全自动启用；可在该文件设置 `LANGFUSE_ENABLED=false` 显式关闭。已有文件是独立配置集，不与源码 `.env` 混用；文件不完整或无法读取时禁用 tracing。安装版环境默认 `production`，开发默认 `development`，测试部署可通过 `LANGFUSE_TRACING_ENVIRONMENT=test` 指定。重新打包后才包含此能力，现有安装包不会自动更新。

## 验证

```powershell
$env:LANGFUSE_ENABLED='false'
.venv/Scripts/python.exe -m pytest tests -q
Remove-Item Env:LANGFUSE_ENABLED
.venv/Scripts/python.exe scripts/check_langfuse.py --send
```

第二条 Python 命令会使用合成字幕与模拟 LLM 响应执行真实 NoteService 管线，并向配置的 Langfuse 发送记录，再通过公共 API 读回检查 session、模型与 token。它验证接入和字段落库，不验证真实 STT/LLM 效果；普通单元测试应关闭对外 tracing。
