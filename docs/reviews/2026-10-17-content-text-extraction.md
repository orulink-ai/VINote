# 内容服务纯文字提取协议1

## 目的与范围

App 两通道共用账号/飞书及安全来源提取，模型调用仍由客户端发往当前通道固定的 VILab Origin，内网/公网不回退。本补丁提供纯提取接口，既有 generation 路由与 caps 的模型字段保持原合同；不修改 App、版本0.3.3、模型选择或默认值。

## API 合同

- `POST /api/content-service/extract-url`：JSON 对象仅 `{url}`，链接最长8192字符，请求体最多32768字节。支持公开 HTTP/HTTPS 网页、PDF、DOCX；视频站和音视频后缀在每次跳转前拒绝。B站音轨下载由 App 设备路径负责。
- `POST /api/content-service/extract-file`：multipart 只允许一个 `file`，拒绝额外字段/重复文件。PDF/DOCX、UTF-8 TXT/MD/SRT/VTT/JSON；文件非空且不超过20MiB，整个multipart请求最多20MiB+64KiB（含分隔符/头部）。无 Content-Length 时同样累计限制输入，解析后复核文件长度。
- 响应严格为 `{extraction_protocol:1,title,text,source_sha256,source_type}`；不返回task、operation、model URL、凭证或设备路径。成功响应 `Cache-Control: no-store`。
- `text` 为复用既有解析器后去掉首尾空白的正文，非空、无NUL且最多600000字符。文字文件在解析前也有该字符上限。字幕保留解析出的文字，JSON复用既有full_text/segments规则；不做推理、OCR或正文补全。
- `source_sha256` 是**响应中精确 text 字符串的 UTF-8 字节 SHA256**，小写64位十六进制；不是原文件或URL哈希。`title` 是有界可显示标题。`source_type` 为网页 `webpage`、PDF/DOCX `document`、文字/字幕 `transcript`；URL重定向到PDF/DOCX按实际解析结果标为document。
- 已验证用户可从 caps 读取 `text_extraction_protocol:1`；原有模型能力字段不变。文件大小超限413；来源/格式/字段无效422（multipart结构错误也可能400）；云端未登录401、身份服务故障保持502。

## 鉴权与副作用

cloud ASGI 的 ContentCredentialMiddleware 明确保护两个新路径，使用现有已验证 Bearer；Cookie不回退。`/content-service/*` 的身份验证使用 provision=false，不建立映射。提取不占 generation submission slot、不预建状态、任务、操作记录或原件库。临时上传spool随请求关闭。device 使用同一router和generation_auth；仍不扩大共享workspace-only runtime暴露面。

路由仅接受来源，不接受任意 modelURL/base_url/API key。正文、凭证、异常源内容与本机路径不进入错误消息。网页复用每hop公网DNS整组校验及TCP固定IP、原Host/SNI；不发送VINote Bearer/Cookie，不使用环境代理或自动跟随跳转。明确拒绝多播/保留/IPv6 site-local地址，不能只凭Python is_global断言安全。文件解析复用20MiB、PDF200页、DOCX解压/XML和正文长度限制。

## 离线证据与边界

`tests/test_content_extraction.py` 经真实 cloud ASGI 测试鉴权/无映射、精确响应与hash、HTML/DOCX/字幕/JSON解析、重复/恶意/超限输入、有/无Content-Length、私网/混合DNS/恶意重定向、视频拒绝、generation槽独立性；对模型目录/请求、ASR、NoteService生成、任务创建和receipt reserve设失败守卫。HTTP/DNS全部替身，无真实网络和付费推理。device测试验证generation_auth入口及同响应合同。

相关回归还包括既有文档解析、DNS固定连接与云端generation离线测试。源码及离线通过不证明公网部署或App端已经改走指定VILab；本次不部署、不构建、不变更版本、不调用ASR/LLM。共享服务的实际部署和App两通道路由验收由后续工作完成。

本地命令：`.venv/Scripts/python.exe -m pytest tests/test_content_extraction.py tests/test_document_sources.py tests/test_document_source_network.py tests/test_cloud_content_runtime.py -q --disable-warnings --maxfail=1`，101项全部通过。提交前fetch确认origin/dev仍为15e1d1c；功能分支正常提交并向dev开PR，CI审查通过后由用户合并，部署必须使用合并提交，不能直接改服务器或部署未合入分支。
