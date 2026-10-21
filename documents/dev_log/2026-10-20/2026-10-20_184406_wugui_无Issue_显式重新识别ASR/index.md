# 显式重新识别 ASR

- 作者：wugui；参与：本 agent、Hooke（会议版本适配器）。北京时间 2026-10-20。
- 分支：codex/meeting-delivery-formats-connections；状态：本地代码及定向测试冻结，未提交、未部署。
- 授权：用户明确选择 fresh 才创建新 ASR 任务；默认复用/原 LLM 由 Hooke 实现。
- 范围：新 task_fresh_asr 服务，既有 ASR lease/转写器限定扩展与离线测试。不改 15 个 LLM 冻结文件、VILab、UI、路由或运行实例。不实际调用模型/ASR。
- 历史依据：[独立命名空间证据](../../../../docs/reviews/2026-10-16-independent-asr-namespace.md)。v1/v2 行为保持，不修改历史正文；fresh 是另外明确确认且 accepted DB fingerprint 绑定的新契约。

## 方案与接口

FreshASRService.context/accept/run_once；context 只读，owner/原件/canonical hash/真实 ASR 来源追溯；accept 需要 fresh 单独同意及真实目录双模型冻结。reference 原件不复制。新 accepted receipt、一次 durable claim 和可撤销 ContextVar lease 才能派发。

fresh 固定本任务 namespace；不锁读 donor、不读父前缀、不复制旧 transcript/cache。自己的空 checkpoint fsync 后才规划完整音频。unknown 只查询原 operation，永不自动重放。既有缓存/伪造元数据不能 mint lease。

## TDD

- Red：tests/test_fresh_asr_execution.py 首轮 collection 明确缺新 task_fresh_asr 模块，1 error；尚未实现。
- 后续记录实际 focused 与历史回归结果，不将离线 stub 当 provider 验收。

## 实现与验证结果

- 新服务 `app/services/task_fresh_asr.py`：context 只读原件/真实 ASR 来源、支持 success/failed；accepted summary-only 父追溯 canonical 媒体任务并重核上游 context/DB snapshot SHA，不能靠 summary 快照中保留的 ASR ID 直接放行。独立 v1/v2 与 fresh 父核验其 accepted 指纹、claim、单跳原件关系。
- 契约 `meeting-fresh-asr-v1`：confirmed/extra_asr_consent 必须精确 true，asr_mode=fresh，llm_mode=select；由 Hooke 适配器核验 selection_revision 和外层 context_revision；本服务重核 fresh_context_revision/source_version、当前冻结连接与两个真实目录模型，并把 snapshot SHA、canonical ID 与所有确认选项纳入 accepted DB fingerprint。重复提交只查原回执，不 requeue。
- `asr_execution_binding.py` 增加受 accepted fingerprint＋持久独占 claim 约束的 fresh lease 分支，最终仍走既有 owner/task/hash/snapshot/Origin/model/reference 核验与 finally revoke；历史 v1/v2 stamp 不变。
- `vilab_transcriber.py` fresh 分支固定 child namespace，拒绝 seed、不锁读全局 donor/父前缀；空 checkpoint 使用既有 fsync 原语持久化后才读取 policy/发送。自身 unknown/inflight 不重播；完整自身 cache 仍须相同 execution/WAV identity。
- 独立 `_dispatch` 复用现有媒体准备与 `_run_pipeline`，真实传递 content_depth/presentation，preloaded_transcript=None。未修改冻结宿主。媒体呈现依据原 manifest.media_kind，audio-only WebM 不以扩展名冒充视频；未接通的漫画/信息图在 reserve 前拒绝。

实际离线验证（Windows，零真实网络）：

1. 首版 fresh + 既有独立执行三模块：117 passed。
2. 增补来源、unknown、fsync、真实 pipeline 等后 fresh 专项：43 passed；与当时 Hooke adapter 联测 68 passed（含后补 claim 反例共 44 项 fresh）。
3. 8 模块联测：`tests/test_fresh_asr_execution.py tests/test_independent_asr_namespace.py tests/test_new_generation_operation.py tests/test_parent_asr_prefix.py tests/test_parent_asr_resume_integration.py tests/test_vilab_transcriber_retry.py tests/test_asr_confirmed_empty.py tests/test_adaptive_asr_checkpoint.py`，271 passed，134.35 秒。该进程已导入之前 fresh 版本；最终增补 claim 和 audio-only WebM 后未重复全套，而针对 fresh 复验 45 passed，13.89 秒。
4. py_compile 四个本任务 Python 文件 exit0；限定 tracked diff --check 通过。唯一测试 warning 是既有 Starlette TestClient 弃用。

真实 NoteService → TranscriptionService → ffprobe/ffmpeg → VILab checkpoint/planner → 两步总结 → artifacts 离线测试保留真实编排，仅模拟外部认证/目录、ASR 和 LLM 返回。覆盖从 0 连续提交完整音频、原件不复制、不含旧 donor 文本、所选 LLM 到达实际请求。并行更新后的 LLM protocol3 要求让旧 Markdown stub 一次失败；仅本任务测试替换为合成合法两步返回后通过，未改任何 LLM 产品文件，未增加调用或修补实际响应。

## 交接与未验收

- Hooke 接 `FreshASRService(summary.receipts)`，负责适配器 selection_revision／UI／路由显式确认。`_submission(link)` 导出供其 accepted 父版本核验。默认 reuse 不由本服务替换。
- context 对不可信来源抛 HTTP409；宿主应仅将 fresh 能力置 unavailable，不破坏本来可用的 summary reuse。
- 没有真实 ASR/模型/设备/公网验收，没有启动/重启服务。没有编辑 UI、入口路由、15 个 LLM 冻结文件、VILab 或原任务/用户音视频。当前只说明源码及离线契约通过。

## 独审 P2：ASR 目录 HTTP 代理策略

独审报告 `_recorded_audio_policy` 的目录 GET 未禁环境/系统代理。最小修复仅为该 `httpx.get` 添加 `trust_env=False`，保持 TLS 默认验证、超时、Origin、凭据与错误策略不变，不修改系统设置。

正式反例加在 `tests/test_asr_direct_transport.py`：保留实际 httpx.get → Client → HTTPTransport 初始化，只替换传输 I/O；植入代理发现返回和代理 transport 陷阱。修前正常响应/TLS失败/超时三例均在代理初始化陷阱红失败（3 failed）。修后直接 transport 仅一次 GET，代理发现/初始化均零次；验证 SSLContext check_hostname=true、verify_mode=CERT_REQUIRED，失败无第二次连接或代理 fallback。

最终定向 `test_asr_direct_transport.py + test_adaptive_asr_checkpoint.py + test_fresh_asr_execution.py`：**67 passed**，26.96 秒，仅既有 Starlette 弃用警告。py_compile、限定 diff --check 通过。修后再次冻结。测试零真实网络/ASR，未提交。

## 历史完整父任务的 fresh 来源兼容

用户明确允许复用 Hooke 的严格旧 Origin 证明；未读取真实录音或操作运行任务。新增合成旧八字段 link、按原算法计算 context revision，并在合成 accepted DB 中保存相同 fingerprint。修前成功反例因缺少新 summary_snapshot_sha256 红失败（1 failed/7 passed）。

修复仅 task_fresh_asr.py：在 claim、owner/task/accepted fingerprint 前置全部通过后，且 summary snapshot 摘要确实缺失时，局部调用既有 MeetingVersionService._legacy_origin_proof（summary 同一 receipt store，不注入 fresh，避免调用环）。该 helper 的精确旧形状与旧上下文 hash 成功，才取代本来与旧算法不兼容的 revision 比较；canonical/source hash 校验保留。存在摘要却不匹配仍硬拒绝，现代形状缺摘要也不能走旧例外。不回填或改写旧 receipt。

8 个兼容反例先红后绿：完整旧回执可 context/accept/lease dispatch；变更 Origin、原请求、原模型、owner、accepted fingerprint、现代 link shape 或摘要冲突仍拒绝。另补现代 missing-digest 反例。

并行产品已启用部分呈现形式，旧测试将漫画/信息图永久视为非法会产生无关失败；本任务仅把“不可用形式阻止预留”测试改为显式注入 unavailable capability 并重算上下文，断言准确 fresh_presentation_unavailable，不修改呈现产品规则或降低 parser 门槛。

最终 fresh + meeting_version_context + asr_direct_transport 联测 **107 passed**（77.53 秒）；py_compile、限定 diff --check 通过。fresh 服务与本任务测试再次冻结；未改 Hooke helper/adapter/UI、未提交、零真实 ASR/provider 调用。真实历史 A/B 的 GET 能力验证由主线程执行，此处不冒称实机通过。
