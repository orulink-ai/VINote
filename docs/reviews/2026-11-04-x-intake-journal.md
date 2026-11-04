# X / Twitter 单帖学习笔记 · 2026-11-04

## 来源与范围

- 官方 oEmbed 文档：https://docs.x.com/x-for-websites/oembed-api 。使用固定 `https://publish.x.com/oembed`，无登录或 Cookie，不执行脚本。
- 输入仅接受 HTTPS 的 x.com / twitter.com（含 www/mobile）标准 handle/status/numeric-ID 单帖链接；去掉跟踪参数后使用 canonical x.com URL。
- 仅提取响应中匹配 post ID 的单个 blockquote 主体段落，附作者、原帖来源和读取范围；不读取线程、外链落地页、图片内容或视频，不声称嵌入文本等于完整长帖。

## 实现

- 新增 `app/services/twitter_source_service.py`，导出 `is_twitter_url` 与 `twitter_text`。JSON/HTML 类型、帖子 ID/正文链接、正文非空、大小和时间均有边界，深层畸形 JSON 转为安全错误。短帖无需满足通用文章 40 字阈值。
- `document_source_service.webpage_text` 在通用 HTML GET 前分流 X 域名；非法 X 路径不退回登录页正文提取。保留 `webpage` 类型契约，亦覆盖 text_extraction_service 现有 API。
- DNS 仅复用 Bilibili 的固定 TLS AliDNS bootstrap，增加默认关闭的 `allow_x_publish` 参数，仅 True 且目标精确为 publish.x.com 时额外允许。只在所有系统 DNS 答案都是 benchmark fake IP 时启用；混合/内网答案不回退。连接保持公开 IP pin、原 Host/SNI、无代理、无重定向。
- `source_note_job` 复用 document_text.json 来源缓存与现有一次性整理，只有 X URL 增加核心观点、原文论据/例子、关键概念、复习重点提示。要求区分作者宣称与依据，没有论据不补写。会议与普通网页提示不变。
- 飞书沿用已保存普通个人笔记的手动发布入口及来源/账号校验，不新增自动发送。

## 验证

- staging 最初 34 个离线提取测试通过；集成前新增回归先 RED：4 个挂接失败；深层 JSON 独立 RED 后补安全转换。
- 最终命令：`.venv/Scripts/python.exe -m pytest tests/test_twitter_source_service.py tests/test_bilibili_fake_dns.py tests/test_bilibili_source_service.py tests/test_document_sources.py tests/test_document_source_network.py -q`，**152 passed in 8.34s**。
- 实际只读调用正式 `twitter_text` 读取用户链接 `https://x.com/reasonmachines/status/2117075693226136046` 成功：作者 Reason Machines，返回正文/来源/范围合计 381 字符，来源 URL 和单帖范围保留。该次经过正式固定连接与 fake DNS 回退，不是绕过产品校验的诊断请求。
- 无真实模型提交、无飞书发布、无凭据读取或修改。Bilibili 原任务已完成并保存后才将暂存 Python 文件集成，未中断其处理。模型生成与保存验收由主线程另行执行，不将提取成功扩大为摘要或发布成功。
