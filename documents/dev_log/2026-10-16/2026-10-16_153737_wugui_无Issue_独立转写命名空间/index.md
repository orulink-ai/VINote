# 独立 operation 转写命名空间与 confirmed 前缀

- 创建：2026-10-16 15:37:37 Asia/Shanghai；作者：wugui；参与：Codex。
- 状态：已完成本地实施与针对性离线验证；无 Issue，无提交或部署声明。
- 授权：仅已持久确认并首次 claim 的独立 operation 可绑定新 namespace；旧 unknown、marker、媒体字节不变。
- 范围：new_generation、内部 binding、NoteService、TranscriptionService、VILabTranscriber、针对性离线 tests/docs/AGENTS；不改公共 API/schema，不操作手机，不调用云。
- 验收：DB 只读授权、ContextVar finally reset/copy_context、精确 WAV identity、donor OS lock、整数采样连续 confirmed 前缀、seed 先持久化再 plan/send、初始 confirmed 进度；真实 pipeline（只替换外部服务）及逆向反例。
- 历史：本任务落实之前只读审查的独立 operation 边界；沿用现有 P2 OS lock、fsync 及未知结果不可重放合同。

## TDD 与验证

- Red：先新增 DB 反例，原实现实际 4 failed / 1 passed：缺失 DB、reserved、错误 task/fingerprint 仍可 dispatch。随后实现 binding 变绿。
- 中间测试暴露 Windows pytest 默认临时目录过长（WinError206），专项 fixture 改用短临时目录；没有修改系统长路径/权限设置。另有 tone planner 本来就可能在预算末窗中点分段，修正测试预算为 64000，使剩余两秒合法单段，不改变 planner。
- Green：`.venv/Scripts/python.exe -m pytest tests/test_independent_asr_namespace.py tests/test_new_generation_operation.py tests/test_adaptive_asr_checkpoint.py tests/test_adaptive_asr_policy.py tests/test_asr_p2_recovery.py tests/test_transcription_service.py tests/test_note_service.py tests/test_task_model_source.py tests/test_speaker_diarization.py tests/test_asr_transport_diagnostics.py tests/test_asr_failure_context.py -q --tb=short`
- 结果：200 passed，17 subtests passed，1 既有 Starlette 弃用 warning，18.95 秒，exit0。真实 Note pipeline、ffmpeg/ffprobe、持久 artifacts 已走通；仅外部服务返回离线 stub。说话人 copy_context 分支另测时替换模型 readiness/推理，不计入真实模型验收。
- 最终补充：donor 安全失败用固定产品文案明确“原文件与记录已保留，未提交音频”，不用底层术语；新增覆盖 run_once 最终失败文案。上列 11 模块复跑 **201 passed / 17 subtests passed / 1 既有 warning，19.94 秒，exit0**。`py_compile` 检查 5 个改动 Python 模块及专项测试通过；目标 tracked diff 的 `git diff --check` 通过。
- 最后安全检查：将 operation 的 namespace 固定为 `transcription_chunks/vilab_stream`，WAV identity 放在不可替换 execution stamp；新增 unknown 后切换 WAV 仍不能换 namespace 的反例。避免同一 lease 内通过改变规范化 identity 绕过旧 inflight。
- 最终命令：上述 11 模块后追加 `tests/test_vilab_transcriber_retry.py tests/test_vilab_empty_speech.py tests/test_asr_wav_validation.py tests/test_task_recovery_failures.py tests/test_asr_stream_budget.py`，同一 pytest 进程执行。
- 最终结果：**16 模块 288 passed / 17 subtests passed / 5 warnings，20.25 秒，exit0**。warnings 为既有 Starlette 弃用与 4 个 legacy empty-speech 用例中的 SQLAlchemy NULL primary-key 提示。再次 py_compile 和目标 tracked diff whitespace 检查 exit0；不表示全仓测试或实际 provider 验收。
- 详细合同/反例：[审查证据](../../../../docs/reviews/2026-10-16-independent-asr-namespace.md)。真实 provider 验收仍未通过；无云调用、手机操作、安装、公共 API/schema 变更，无提交/部署。

## 实际变更与决策

- 新增内部 asr_execution_binding，只在首次 durable run_once claim 后用已有 DB getter 和 sessions 只读核验 receipt/fingerprint，finally revoke/reset。
- NoteService/TranscriptionService 缓存前校验 owner/task/source/frozen snapshot。VILabTranscriber 使用确定性 child namespace；confirmed-only seed 持久后才 plan/send。
- 根据用户补充，donor 忙/sentinel/损坏必须阻止，不允许降级从 0；同源 OS lock 保持到本次转写完成，防止 seed 读取后竞态。既有未知记录与 marker 不变。
- 用户追加已确认初始进度：原 callback 在覆盖校验后立即报告 saved prefix，未伪造 partial/final。

## 关联历史

- 补充并落实 [ASR 传输安全诊断的后续边界建议](../2026-10-16_150407_wugui_无Issue_ASR传输安全诊断/index.md)；旧诊断结论、未知结果不重放规则保持。
- AGENTS 新增独立 namespace 与 seed 合同，普通 UI 无底层术语。

## 父端复查收尾：完整 child 自身缓存

- 用户指出完整 child 仍无条件依赖 donor，导致其后来 busy/corrupt 时无法零调用复用。只在 `_transcribe_stream` 自身 stamp/inflight/严格 confirmed 覆盖检查后增加完整覆盖分支，直接走自身 `_transcribe_checkpoint`；partial 仍走原 donor 排他/校验。无新 donor 发现层次、API/schema 或其他接口改动。
- 专项追加 **4 个参数化测试**：busy/corrupt 两例同 active lease 完整 child cache 复用；wrong stamp/normalized identity 两例仍拒绝。Red 命令 `pytest tests/test_independent_asr_namespace.py -q -k complete_child_cache --tb=short` 实际 **2 failed / 2 passed**，确认为目标缺陷。
- Green：同上述最终 16 模块命令，实际 **292 passed / 17 subtests passed / 5 既有 warnings，20.21 秒，exit0**；相对上轮 288，准确追加 4。py_compile、目标 tracked diff whitespace 检查通过。零外部调用、未操作手机、未部署或提交。AGENTS/审查证据同步补充完整 child cache 例外。
