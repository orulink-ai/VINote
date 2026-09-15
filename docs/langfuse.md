# VINote 桌面端 Langfuse 追踪

VINote 只追踪桌面端发起的生成任务。Tauri 请求携带 `X-VINote-Client: desktop`，后端据此创建 Trace；浏览器、树莓派部署和普通后端 API 调用不会初始化 Langfuse。源码桌面端、测试安装包和正式安装包均固定接入同一个 VINote 项目，环境分别为 `development`、`test` 和 `production`。

## 根 Trace

业务根 Trace 只使用两个名称，按用户进入的功能区分，与文件扩展名无关：

- `桌面端｜会议纪要`：会议录音、录屏及从会议页导入的录音或录像。
- `桌面端｜笔记整理`：视频链接、本地音频、本地视频、字幕和其他支持的文件。

构建时的连通性检查也使用 `桌面端｜笔记整理`，并带有 `workflow=synthetic`、`synthetic=true` 标记，不能作为真实业务请求验收。这样项目中的根名称始终只有上述两个。

根输入记录入口、媒体类型、文件名、文件大小、标题、总结模式、输出语言和媒体时长；URL 会移除查询参数。根输出记录完整逐字稿统计、最终 Markdown 和各阶段耗时。`sessionId` 对应 `task_id`，本地用户 ID 只记录加盐哈希。

## 可调试的子节点

实际执行到的阶段才创建 observation：

- `语音转写` 下的每次 `STT｜模型｜区间` generation 记录供应商、模型、音频格式、字节数、录音偏移、说话人上下文、完整识别文本、分段结果和真实耗时。普通长音频沿用 STT 的长音频能力；只有超过通用时长或文件大小阈值时才使用原有容错分块。
- 含音轨的桌面输入默认执行 `音频预处理`、`说话人检测`、`说话人聚类` 和 `说话人识别与逐字稿对齐`。完整预处理录音只发起一次长音频 STT，和本地说话人分析相互独立。ASR 有句级时间戳时按区间重合关联；只有全文时按检测到的发言有效时长顺序估算，并以 `speaker_alignment=estimated_by_speaking_duration` 明确标记。链路记录实际 STT 请求次数、sherpa-onnx 模型、阈值、自动聚类结果、重叠/未知轮次及各发言区间；用户界面不暴露人数和开关。
- `生成总结` 下的每次 `LLM｜…` generation 记录实际模型、system/user prompt、完整输出、供应商返回的 token 用量和真实耗时。一次生成、分块总结、合并和会议事实核对使用不同名称。
- `提取关键帧` 和 `保存结果` 记录是否跳过、关键帧数量及保存结果，不制造空的模型节点。

纯文本和字幕输入没有音轨，因此明确跳过 STT 与说话人识别。失败会记录在实际失败节点和根 Trace，保留安全的错误类型和脱敏消息。

## 数据边界

桌面端 Trace 为调试用途，固定记录完整转写、提示词和生成结果。不会记录原始音视频二进制、API key、Cookie/JWT、认证头、数据库密码、原始说话人 embedding 或本地绝对路径。异常正文会清除常见 token/key/secret 字段。网络或导出故障不阻断用户的生成任务，但不能视为追踪验收通过。

## 配置与安装包

本机 `.env` 配置：

```dotenv
LANGFUSE_BASE_URL=http://192.168.1.118:3000
LANGFUSE_PUBLIC_KEY=替换为VINote项目PublicKey
LANGFUSE_SECRET_KEY=替换为VINote项目SecretKey
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_RELEASE=0.5.1
```

`yarn client:dev` 会设置 `VINOTE_DESKTOP_RUNTIME=true`，缺少 Langfuse 项目配置时拒绝启动桌面后端。普通 `uvicorn` 后端可以不配置 Langfuse，因为非桌面请求不会上报。

测试与正式构建把构建环境中的同一项目配置写入冻结后端资源 `desktop-config.json`。安装包持有人可提取这些凭据，这是直接接入方案的分发边界。凭据不得进入 Git、前端资源、日志或 manifest；`.env`、模型 API key、用户会话和数据库密码不得打包。旧应用数据中的 `langfuse.env` 会被忽略。

两个构建渠道都运行冻结后端的合成 Trace 上报与 API 回读检查，并在 `manifest.json` 保存不含凭据的验收回执。

## 验证

```powershell
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe scripts/check_langfuse.py --send
.venv/Scripts/python.exe scripts/check_meeting_generation.py <音频> --live --workflow meeting --output data/meeting-trace.json
.venv/Scripts/python.exe scripts/check_meeting_generation.py <音频> --live --workflow note_organization --output data/note-trace.json
```

最后两条命令通过桌面 HTTP 身份调用真实 STT、说话人识别和 LLM，并从 Langfuse API 回读验证根名称、完整输入输出、模型与必需子节点。它们不操作 Tauri 界面或系统录音设备。
