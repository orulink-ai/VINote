# Cloud chat 拒绝分类与离线证据

2026-10-16，根仓库本地修改；未部署或云推理。仅修改 `app/services/vilab_cloud_service.py`、对应测试与文档，不修改 UI、ASR guard、恢复路由、冻结模型或真实任务产物。

## 协议与处理

只读核对独立 VILab-server 的 `src/llm_gateway.rs`：`authorize_gateway_token_with_identity`、`openai_error` 生成网关自身 `vilab_error + unauthorized/account_disabled/authentication_unavailable`；`provider_response_from_reqwest` 保留上游 HTTP 状态和正文。另核对其 account-auth/model-availability 文档。因此 HTTP401/403 本身不能证明 VINote 账号登录失败，未知403也不能证明欠费。

chat streaming/non-streaming 共用 `_chat_failure`：最多检查64KiB错误 JSON（溢出最多额外一个4096字节块即停止）。只投影 HTTP 数字、固定 category、明确枚举的 error.code/type；忽略任意 message、URL、token、body、模型或供应商自报附加字段。异常仅使用固定产品文案，日志只记录该白名单诊断。

明确网关 envelope/status 对应调用者鉴权、停用或认证服务异常；明确 provider code 可对应模型鉴权、权限、额度；未知/HTML/损坏/超限/不匹配 envelope 使用中性 HTTP 拒绝说明，不要求用户重新登录。异常附带私有 `cloud_failure_context`，不新增公共响应结构、查询目录或模型 fallback。

chat 流请求改为单次发送：连接失败、期限耗尽、收到 headers/partial 后断开均不自动重放推理。HTTP拒绝和不完整结果也不会自动重试。旧流中断重试测试改为单次失败且不保存 partial。

## 完整逐字稿与恢复边界

只读检查 [个人标识已省略]：ASR checkpoint 22 completed、end=1376.5485625、无 inflight；transcript 有235 segments，diarization/parallel/ASR/speaker evidence 齐全，任务失败阶段 summarizing。未输出内容或改写原产物。

已有完整 diarized transcript 的 TranscriptionService 缓存短路由离线用例验证：不 resolve STT config、不创建 transcriber、不准备音频。但独立 operation 的既有 `/retry` 在恢复前直接409，run_once不能重新claim；不能将此缓存能力冒称该任务已有“只summary retry”API。本次不放宽 guard。用户随后明确授权 DeepSeek 后，父端另建 transcript-only 任务；本补丁没有执行该调用、改原snapshot或操作其任务状态。

## 验证

- Red：新增分类与缓存15例，实际14 failed / 1 passed，匹配旧401/403误报缺陷。
- 最终：`pytest tests/test_cloud_chat_failure_classification.py tests/test_cloud_chat_stream.py tests/test_vilab_model_public_metadata.py tests/test_vilab_empty_speech.py tests/test_note_service.py tests/test_transcription_service.py tests/test_new_generation_operation.py -q --tb=short`，**154 passed / 17 subtests passed / 5 warnings，3.41秒**。覆盖普通/stream envelope、秘密字段剔除、未知403、64KiB上限、headers前失败不重放、partial后断开不重放、完整 transcript 缓存不重ASR。5个warnings为既有Starlette弃用和4个legacy empty-speech SQLAlchemy NULL-key提示。
- 曾扩大到 `test_vilab_integration.py`，另见5个旧合同冲突：2例向 framed WAV 路径提供伪音频却仍期望旧HTTP路径；3例要求不可用模型自动换default。相关旧行为不在本次修改函数内，且自动换模型违反当前合同；没有为通过旧断言扩大实现或改模型。初次新增bounded-read测试误用Response contextmanager，修正测试为try/finally close后通过。未声称全仓测试通过。
- 测试使用MockTransport/离线stub，无真实云请求；无新summary执行、手机操作或后台恢复。
