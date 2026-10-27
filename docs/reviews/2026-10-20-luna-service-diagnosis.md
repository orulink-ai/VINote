# Luna 调用中断只读诊断

检查日期：2026-10-20。范围是本机既有日志、已授权 AWS 实例的容器元数据、限时脱敏日志及生产 SQLite 只读查询。未修改或部署 VILab/Magpie/Cloudflare，未提交新 ASR、LLM 或飞书写入。下面服务器时间均为 UTC；北京时间加八小时。本机与服务器的精确时钟偏移未校准，不能只凭本机终态时间绑定请求。

## 当前连接与存活状态

- 桌面冻结 Origin 为 `https://api.orulink.ai`，模型 `codex/gpt-6-luna`；请求 `/openai/v1/chat/completions`，`stream:true`。
- 实际只读 `/health`、已授权 `/v1/models` 均 HTTP200，约4.248/2.174秒；生产版本0.4.0、build `fe8288f717d12992f151e06387be0cffedbd50c0`，dirty=false。200只证明入口和目录可读。
- 生产DB当前路由为 provider `openai`、protocol `openai-compatible`、upstream `https://magpie.orulink.ai/v1`。当前配置不证明所有历史调用都使用同一地址；失败时段的用量与路由日志也记录同一模型/provider。
- DB `context_window=32768`、supports_streaming=1，是配置元数据，不是模型真实能力或本次超限证明。公开目录未向客户端提供对应限额，不能由此断言图片/上下文超限。
- VILab容器自2026-10-19T13:03:45.801573843Z运行，RestartCount=0、OOMKilled=false。模型目录“available”来自最近一次观察，不能当成长请求当前稳定性的证明。

## 故障一：上游502与Magpie重启高度吻合

| 生产证据 | UTC时间 | 结果 |
| --- | --- | --- |
| Luna路由 | 12:47:31.984393 | `chatcmpl-c54f392943d54c0abccd333ad8b7e1bf` |
| 用量事件 | 12:47:32.270 | status=error、usage_source=provider、error_code=502、latency_ms=285 |
| cloudflared | 12:47:32.270880 | unexpected EOF |
| HTTP入口 | 12:47:32.327969 | `b06690bf-3421-48e6-a2b7-f19c5348e67a`，HTTP502 |
| Magpie容器结束 | 12:47:32.425196521 | RestartCount=1、OOMKilled=false |
| Magpie容器启动 | 12:47:32.463810199 | 当前运行 |

这是网关实际收到直接上游502的证据，不是桌面端把ReadError包装成502；它与Magpie重启/隧道EOF集中在同一秒，支持共同链路故障。不能把它表述为最终模型厂商返回502、已确认OOM或已知人为维护。历史Docker events查询没有返回对应事件，重启触发原因尚未确认。

本机A-html-detailed-02在review阶段已收到响应头后RemoteProtocolError；B-infographic-concise-05在review阶段实际收到HTTP502，二者本机终态相差约0.22秒。与上述生产故障高度吻合，但HTTP UUID、chatcmpl ID及桌面task之间没有持久化映射；不伪造一一绑定或精确时钟校正。

## 故障二：三次约125秒的入口取消

| 请求ID | POST开始UTC | HTTP400结束UTC | elapsed_ms |
| --- | --- | --- | ---: |
| `353a0626-a090-4210-80a9-45d75c86981e` | 12:07:11.747612 | 12:09:16.766206 | 125018 |
| `6a51f816-45c7-4ab6-b562-283584208061` | 12:40:34.286256 | 12:42:39.298141 | 125011 |
| `26af3418-4c1d-45e3-bb39-04060fa5f608` | 13:33:48.100621 | 13:35:53.099974 | 124999 |

三个结束时刻均有cloudflared `Incoming request ended abruptly / context canceled`。对应窗口没有这些请求的模型解析/用量证据；并发的其他Luna请求有解析和HTTP200记录。此现象不同于12:47的Magpie重启，且与本机A11/A13/A14的反复未收到响应头、约165–171秒ReadError时段相符。

125秒高度接近[Cloudflare官方Proxy Read Timeout](https://developers.cloudflare.com/fundamentals/reference/connection-limits/)默认值，因此入口代理期限是优先假设；尚未取得此次边缘请求的超时分类/400拒绝类型，不能写成已完全证明的根因，也不能仅凭无用量记录认定模型绝未执行。源码先完整提取JSON，再进入handler、鉴权及模型解析；现有HTTP日志不足以区分具体读体拒绝、其他提前返回或日志缺失。保留操作不确定状态，不自动重发。

## 客户端与服务端的证据边界

- 本机默认HTTPX timeout=300秒，分别作用于I/O阶段，不是总墙钟期限；未见这些请求抛出ReadTimeout。165–171秒的ReadError不能解释成桌面300秒超时。
- 本机HTTPX明确trust_env=False，每次请求新Client，离线代理陷阱等55项检查通过；不证明系统TUN/VPN未参与。VILab外部upstream的reqwest代理策略与本机不同，不擅改代理。
- VILab网关流式用量的success/estimated_stream在收到成功响应头时写入，HTTP completed也不代表SSE完成。不能用服务端success行推翻桌面断流证据。
- 本轮未改SSE：离线发现其900秒检查只在线产出后执行，持续无换行字节可越过总期限。这是独立边界问题，不能解释本次165秒断流，待单独修复与验证。
- 原本28个已受理候选中，保存成功1个、事实/结构守卫失败15个、结果不确认9个、实际HTTP502一个、本地能力锁阻断一个、宿主字段错误一个。其间有实际HTTP524记录；不能把全部失败归为服务502。B06返回完整review后因模型证据错引被拒，是质量失败，非传输中断。

## 后续顺序

1. 先查Magpie重启触发原因和重启期间连接处理；不得以新模型请求来替代这项诊断。
2. 对125秒请求补边缘超时/拒绝类型证据；保留完整会议材料，不任意删上下文来凑成功，不盲目调大桌面超时。
3. 如需优化请求体，需同时衡量图片编码体积、整段材料覆盖及对应时间线，实际token/图片上限仍需可靠能力信息。改变传输/材料策略后以新的明确操作验收，旧unknown任务不重放。
4. 继续将模型语义质量与链路可用性分开验收。当前各形式100分、目标知识库最终交付、安装包发布仍未完成。

原始健康检查的白名单JSON保存在忽略目录 `.desktop-build/meeting-delivery-20261020/service-readonly-diagnostic.json`；生产日志在远端先按字段/类别脱敏后经现有EC2终端读取，未导出会议正文、密钥或完整错误body。此报告是证据摘录，不冒充原始日志归档。
