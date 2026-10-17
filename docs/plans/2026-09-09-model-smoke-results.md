# 本地 VILab Server 模型联调结果

所有模型请求通过本地 VILab Server（127.0.0.1:9878），供应商凭证仅配置于该服务。

| 模型 | 结果 |
|---|---|
| deepseek-v4-flash-0731 | 上游拒绝模型权限 |
| deepseek-v4-pro | 上游拒绝模型权限 |
| deepseek-v4-pro-0813 | 上游拒绝模型权限 |
| glm-5.2 | 上游拒绝模型权限 |
| gpt-5.6-luna | 成功（实际返回 OK） |
| gpt-5.6-sol | 成功（实际返回 OK） |
| gpt-6-astra | 成功（实际返回 OK） |
| kimi-k2.6 | 成功（实际返回 OK） |
| kimi-k3 | 成功（实际返回 OK） |
| minimax-m2.7 | 成功（实际返回 OK） |
| minimax-m3 | 成功（实际返回 OK） |
| ox-alpha | 上游 404 / 模型已不可用 |
| qwen3.6-flash | 上游拒绝模型权限 |
| qwen3.7-flash | 成功（实际返回 OK） |
| qwen3.7-max | 上游拒绝模型权限 |
| qwen3.7-plus | 上游拒绝模型权限 |
| qwen3.7-text-embedding | 向量模型，不适用聊天生成接口 |
| qwen3.8-max | 上游拒绝模型权限 |
| qwen3.8-max-dashscope | 成功（实际返回 OK） |

阿里云 ASR：成功识别火山 TTS 生成的测试音频。火山 TTS：成功返回 WAV。

VINote → 本地 VILab Server → 阿里云转写 → MiniMax 笔记生成：模型诊断链路成功。使用隔离服务端临时外部测试凭证，不代表个人账号令牌联调完成。

个人账号验证状态：已配置新 Supabase SMTP 和验证码模板，等待邮箱验证码完成真实登录。


### 真实账号验收完成

2026-09-09 已配置 VINote Supabase 的自定义飞书 SMTP 和注册/登录验证码模板，收到并验证用户提供的邮箱验证码。个人 access token 请求本地 VILab Server `/v1/me`、模型列表、阿里云 ASR、MiniMax M2.7 笔记生成均成功。强制刷新到期标记后，真实 Supabase refresh token 轮换成功，刷新后的令牌再次通过 `/v1/me`。

VINote API 生成返回 200，保存笔记返回 201，随后更新并读取内容返回 200。测试笔记 ID 为 `[个人标识已省略]`。Kimi 两个模型修复后也均实际返回 OK，共 9 个可用聊天模型。

本机配置默认选中阿里云 ASR 和 MiniMax M2.7。服务器 `192.168.1.143` 未修改；两个仓库仍未提交。按产品授权/额度管理的后续事项保持不变。
