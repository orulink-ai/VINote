# Python ASR 流式等待预算

`asr_stream_service.py` 对每个已选定音频区间分别使用两个有界阶段，区间时长为 D 秒：

- 上传预算仍为 `1.5 × D + 90` 秒，从连接开始前计时，包含连接和等待 session.started。
- 只有 LAST 的 `ws.send()` 成功返回，且记录时尚未到达原上传期限，才原子、一次性记录完成时刻。收尾期限为该时刻加同一动态预算 `1.5 × D + 90` 秒。
- partial、重复确认、LAST 开始发送、发送抛错或超上传期限后的成功返回都不能延长期限。到期决定与完成发布使用同一锁，已经到期的操作不能被迟到 sender 恢复。

`recv(timeout≤1)` 只用于轮询，不是整体收尾限制；每次等待受当前阶段剩余预算约束。未知结果仍不可自动重试；原 sender join、停止事件及 WebSocket 上下文清理保留。本次不改变音频发送节奏、模型或会话分段，也不代表已通过真实提供方长录音验收。

每次 binary send 前先记录已尝试音频。此后发送失败、断开或期限耗尽均为不可自动重放的 `unknown_result`，不要求已经发送 LAST；服务端明确 error 保留原 code，但已尝试音频后禁用自动重试。尚未尝试音频的连接失败仍沿用原有限重试政策，服务明确给出的 `ASRSessionLimit` 续接保持不变。诊断字段只按下述明确白名单增加，不保留上游任意文本。


## 内容无关的 transport 诊断（2026-10-16）

不改变deadline、帧节奏、模型、checkpoint键或重放规则。默认构造 `ASRServiceError` 的 diagnostic 仍只有 code/session_id/stage/sent_all 四字段；真实transport失败才添加观察快照。

- transport_event：client_deadline（本机预算到期）、audio_send_failed（sender观察到二进制send抛错）、connection_closed（recv观察到ConnectionClosed或OSError）、session_ended（无final的completed/cancelled），以及service_error（显式服务error）。并发sender/recv错误以本机首先处理的终止路径记录，不能据此断言proxy/provider根因。
- ws_close_code：只提取收到的close帧的合法整数代码。没有收到close帧时省略；不从本机发送close或库的合成1005/1006推断远端代码。不保留reason、异常文本、正文或URL。
- local_send_attempt_bytes/local_send_attempt_packets：已开始尝试binary send的PCM字节/包数；local_send_bytes/local_send_packets：ws.send在本机成功返回的PCM字节/包数。均不含VLA2头和session.start，不是server ACK、provider已接收或已确认转写。
- elapsed_ms：连接前起算至终止判定；last_send_age_ms：距最后一次本机send返回；last_send_attempt_age_ms：距最后一次开始尝试send。没有对应本机事件就省略age，不编造0。快照不随cleanup或迟到sender完成而更新。
- 字节最多2^40，包数最多2^31-1，毫秒最多604800000（7天）；运行中计数饱和，上述输入投影仅接受范围内的真正整数，拒绝bool/float/string/NaN/负数和越界值。safe_asr_failure_context对顶层及最多3条attempt使用同一白名单，不复制任意metadata。
- 音频前连接/等待故障继续使用既有httpx异常与有界重试分类，只补安全上下文，不伪造provider code、session或attempt。音频开始尝试后的unknown仍不能自动重放。

这些字段用于后续失败的安全取证，不能为历史缺少诊断的任务反推原因，也不构成新operation可绕过旧inflight的授权。
