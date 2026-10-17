# Cloud chat 调用者与上游拒绝分类

- 2026-10-16 Asia/Shanghai，作者 wugui，参与 Codex，无 Issue；进行中，仅本地修改。
- 用户授权仅 cloudservice 相关 Python/tests/docs，不改 UI、模型、恢复路由、ASR 或 server；不执行云推理或自动重放。
- 协议只读来源：VILab-server `src/llm_gateway.rs` 的 authorize_gateway_token_with_identity/openai_error/provider_response_from_reqwest；`docs/zh-CN/account-auth.md`、`model-availability.md`。Gateway 自身错误为 `error.type=vilab_error` + `unauthorized/account_disabled/authentication_unavailable`；provider 错误保留 HTTP 与原正文，不能以 HTTP401/403 推断用户登录问题。
- 实现目标：chat streaming/non-streaming 共用有界白名单诊断；不记录任意 body/message/模型/token/URL。chat 发送或流中断不自动重试推理。
- 只读真实证据：child [个人标识已省略] status failed_stage=summarizing；checkpoint 22 completed、end=1376.5485625、无 inflight；transcript 存在，235 segments、analysis_parallel/asr_evidence/speaker_evidence 齐全。未输出正文。
- 恢复限制：现有 retry_media_task 在任何处理前拒绝 new_generation.json（409 independent_operation_query_only）；旧 run_once marker 不能重 claim。完整 transcript 可缓存复用不等于此独立任务现有 API 已支持 summary-only retry。本次不扩大路由/binding 写集。

## 测试记录

- Red：新增15例实际14 failed/1 passed，旧chat401/403均误报身份且无安全投影。
- 实现已结束：仅backend `app/services/vilab_cloud_service.py`；增加有界白名单分类，chat一次发送不自动重放。未改ASR、路由、UI、任务产物、snapshot或guard。
- 测试：新增 `tests/test_cloud_chat_failure_classification.py`（21例）；调整 `tests/test_cloud_chat_stream.py` 旧“断流重试”断言为一次失败不重放。7模块最终 **154 passed / 17 subtests passed / 5既有warnings，3.41秒**。
- 命令与已发现旧冲突详见 [验证证据](../../../../docs/reviews/2026-10-16-cloud-chat-failure-classification.md)。扩大回归曾见test_vilab_integration的5个旧HTTP/自动模型替换合同冲突，未扩大修改；未声称全仓通过。
- 用户后续授权父端DeepSeek transcript-only总结。已告知既有generate_from_transcript/needs_stt=false路径及review模型边界；父端实际操作独立进程33526、task aea7d030-f0e2-4554-ba21-52b829db9970由用户提供。本代理没有触发该调用，没有调用其artifact.get_status，没有编辑该任务或手机。backend源码收尾后冻结，仅测试/docs收尾，避免实际运行期reload。
- 交付状态：本地修改、未提交/部署；已完成所授权cloudservice补丁与离线验证。当前运行summary实际成功与否未由本代理核验。
