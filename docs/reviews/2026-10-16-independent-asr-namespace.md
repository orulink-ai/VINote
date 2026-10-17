# 独立 operation 转写命名空间：源码与离线证据

> 本页为历史审查记录。仓库源码位置以路径标注，不作为文档站页面链接；历史行号可能随修改变化。

2026-10-16，Windows，根仓库本地修改。未提交、未部署；零云调用、未操作手机。用户提供的 public health/部署状态不作为本实现的 provider 验收证据。

## 授权与执行

`NewGenerationService.run_once` 先以 `open('x')`、flush/fsync（POSIX 加目录 fsync）持久 claim，再进入内部 `_claimed_execution`。后者复用 `SourceRequestService.get`，并在同一已有 sessions 机制中只读核对 `SourceRequestDB` 的 owner、operation、accepted 状态、task、submission fingerprint；不调用 reserve，不添加 DB schema 或公共 API 字段。fingerprint 绑定原 parent/source/context revision；服务端重新核验 parent 冻结上下文及 child snapshot 的精确一致性。

只有此入口设置 ContextVar。NoteService 在使用逐字稿前、TranscriptionService 在缓存前，以及 VILabTranscriber 在使用命名空间前核对实际 owner/task/目录/原件指纹/Origin/具体模型。独立 task 没有运行期 lease 时不能回退全局 checkpoint；磁盘 JSON 不是授权。`finally` 同时 revoke lease 和 reset ContextVar，因此之前复制但延迟执行的 context 也失效。说话人分析既有 `copy_context().run` 无需修改。

子目录固定为 `<child task>/transcription_chunks/vilab_stream/recognition.json`，不能按每次传入的 WAV 再换子目录来绕过 unknown。identity 沿用全局算法：SHA256(JSON([Origin, owner, selected ASR model]) + 完整规范化 WAV 字节)，流式读取；不能用原文件 hash 或时长替代规范化 WAV identity。operation 与 task 不在每次尝试时随机更新，execution stamp 包含 owner、operation、task、parent、source/context revision、冻结 snapshot digest 和规范化 identity；该 identity 改变时也失败关闭。

## 前缀复用与排他

新记录只能从相同 identity 的原全局目录读取 donor；用既有 OS lock，且保持到本次转写返回，防止取完前缀后旧入口并发收费。旧 recognition.json、plan、inflight、legacy marker 字节不变；只允许既有锁原语创建/保留锁 backing file。

持锁后检查无 `recognition.lock`（含 symlink）、无未提交 `recognition.tmp`；donor JSON 最大 16 MiB、最多 65536 个已确认区间。区间必须从 0 连续覆盖、起止可精确表示为整数采样位置（只容忍浮点表示舍入误差）、文本类型正确、不超出 WAV 末尾。inflight 仅核对不能与已确认前缀相交，绝不复制或当成确认结果。只投影 confirmed 的文本、语言和有效原始 segment 证据，不制造词时间。plan 一律不导入。

锁忙、legacy sentinel、损坏/超限/缺口/半采样/重叠/未提交记录均阻止提交，保留证据，不静默从 0 重跑。完全不存在记录且能取得同源 OS lock 时才允许空前缀。确实不同的 normalized WAV identity 不能借用该前缀。

完整 child cache 是例外：在 child 自身 stamp/normalized identity、无 inflight/legacy sentinel、严格连续采样覆盖至末尾全部核验后，直接读取自身结果，不读/锁 donor，不请求 token/catalog/ASR。donor 后来忙或损坏不影响这次零调用复用；partial child 仍受上述全部 donor 门禁保护。

新 recognition.json 先写入 confirmed 前缀、execution stamp 和 donor digest provenance，通过 flush/fsync/replace（POSIX 加目录 fsync）后，才从前缀结束采样规划剩余音频。分段仍由现有 service-budget pause planner 决定；模型不替换。验证已保存覆盖后，原 progress_callback 立即收到 `(prefix_end, duration, prefix_end)`，这是保存覆盖，不是新 partial/final。全长 confirmed 前缀不请求 token、catalog 或 ASR。

同 operation 的 inflight 立即 unknown，不能重新 seed、换 namespace、清 marker 或重新 claim。另一个经过服务端真实确认、独立 accepted 的 operation 才能有另一个 child namespace，并仍受 donor 排他与证据核验约束。

## 离线验证

专项：`tests/test_independent_asr_namespace.py`。所有专项测试禁止 socket 连接；外部返回均为离线 stub。真实 pipeline 用真实 `run_once → NoteService.generate_from_file → _run_pipeline → TranscriptionService → ffprobe/ffmpeg → VILabTranscriber → planner → artifacts`，仅替换外部认证/目录就绪检查、ASR 和 chat 返回；未把 `_run_pipeline` 或转写编排整层 stub。3 秒 WAV 复用前 1 秒确认结果，唯一 ASR stub 提交 `[1,3)`，保存完整 transcript/note/result，原件不复制、旧 donor 字节不变；真实 LLM prompt/review 路径使用冻结模型的 chat stub。

另有实际 `SpeakerDiarizationService` 并行分支测试：真实预处理、WAV 生成、`copy_context` 线程提交、VILab ffmpeg 与 checkpoint；仅在该分支测试中替换说话人模型 readiness/推理，不冒充真实说话人模型验收。

| 逆向/恢复情形 | 离线断言 |
| --- | --- |
| 仅伪造 JSON、DB 缺失/reserved/错误 task/fingerprint | dispatch 前阻止；无 reserve/新 DB 写入 |
| operation/parent/revision/source version/ASR 或 LLM snapshot 不符 | 不 mint 可用 lease，不提交 |
| pipeline owner/task/路径/原件/snapshot/reference 改变 | 缓存或 ASR 前阻止 |
| adapter owner/Origin/model 不符 | 不读其他身份缓存或提交 |
| donor legacy marker、实际 OS lock 忙 | 阻止提交；marker/原记录原字节保留 |
| donor JSON 损坏、超限、gap/overlap、bool/NaN/半采样、inflight overlap、未提交 tmp | 失败关闭；无从 0 降级 |
| child execution stamp 不符 | 原记录保留，不重置 namespace |
| 同 operation unknown / 二次 run_once | ASR stub 总数不增加；inflight 不变 |
| unknown 后改用另一个 normalized WAV | 固定目录的 execution stamp 不符即阻止，不能换 identity 子目录逃逸 |
| 新 accepted operation | 新 child namespace，只复用 confirmed；旧 unknown 原字节不变 |
| seed fsync 失败 | 无 catalog/ASR 调用 |
| 全 confirmed 前缀 | 无 token/catalog/ASR；回调立即显示已保存覆盖 |
| 同 active lease 的完整 child，donor 后来 busy/corrupt | 直接自身 cache，donor read 零次，token/catalog/ASR 零次 |
| 完整 child 的 wrong stamp / 不同 normalized identity | 仍拒绝，child 字节不变，无调用 |
| copy_context 正常/异常退出/延迟 context | 运行中绑定一致；退出后复用旧 context 被拒绝 |
| 同原件但不同 normalized WAV | 不导入错误前缀 |

完整 child cache 收尾追加 **4 个参数化用例**；Red 2 failed / 2 passed，修复后同一 16 模块 union 为 **292 passed，17 subtests passed，5 既有 warnings，20.21 秒，exit0**（此前 288 passed）。warnings 为 Starlette 弃用和 4 个 legacy empty-speech 用例中的 SQLAlchemy NULL primary-key 提示。包括 unknown 后更换 normalized WAV 的 namespace 逃逸反例。改动 Python 文件的 py_compile、目标 tracked diff 的空白检查通过。回归命令及过程记录于 开发档案（源码位置：`documents/dev_log/2026-10-16/2026-10-16_153737_wugui_无Issue_独立转写命名空间/index.md`）；只说明离线源码行为，实际 provider acceptance 仍未通过。
