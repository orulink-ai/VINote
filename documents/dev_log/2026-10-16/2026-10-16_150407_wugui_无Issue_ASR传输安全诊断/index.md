# ASR 传输安全诊断

- 创建：2026-10-16 15:04:07 Asia/Shanghai；作者wugui；参与Codex；无Issue。
- 状态：进行中，未提交。范围：app/services/asr_stream_service.py、task_failure.py、针对性tests及本档案。
- 背景：用户确认桌面任务失败且没有任务在跑；父端调查proxy。本任务不推断原失败根因，不进行额外云调用。
- 目标：区分client_deadline/audio_send_failed/connection_closed/session_ended，投影安全close code、本地send计数及耗时；本地send不是server ACK。
- 约束：ASRServiceError默认constructor diagnostic四字段保持；未知结果不可自动重放；不改App、手机、路由或全局checkpoint键/inflight；不扩大修改到显式新operation。
- 验证：新增离线Socket/时钟/真实sender线程测试，拒绝网络；覆盖默认兼容、四类首因、发送失败与完成差异、close reason/凭据/正文不泄漏、字段类型及边界、持久化投影、旧unknown仍不可恢复重放。
- 相关：docs/asr-stream-timeouts.md；旧档案中无本任务同主题进行中记录。只读检查当前asr_stream_service/task_failure均为已有未跟踪源码，保留现有实现。


## 已完成（本地修改，未提交/部署）

- `app/services/asr_stream_service.py`：新增安全transport白名单、严格接收帧close code检查、有界线程安全本地计数与终止快照；区分4类终止路径及显式service_error。默认ASRServiceError.diagnostic保持旧4字段，新transport参数仅接收白名单副本。send尝试/成功返回各自计PCM bytes/packets，未当成server ACK。没有read全音频或额外请求。
- `app/services/task_failure.py`：safe_asr_failure_context显式投影transport白名单，包括asr_attempts每项；真实transport无session也可私有落盘。前音频HTTPX异常保持原类型/retry分类，仅投影安全transport context，不造code/attempt。
- `tests/test_asr_transport_diagnostics.py`：新增27例参数化离线用例（默认兼容、真实sender线程四类终止与recv OSError、close标准码/非法码、元数据过滤/数值边界、前音频异常兼容、私有artifact落盘、计数饱和）。自动拒绝socket网络连接。用合成10ms WAV和fake clock，不读取用户录音/任务。
- `tests/test_asr_stream_budget.py`：只更新“真实transport失败必须恰好四键”的旧断言为旧四键保留+新增尝试计数/终止枚举断言；默认constructor四键仍由旧/新增用例原样检查。旧send fixture同时触发recv关闭，允许两种先观察到的路径；sender-only新用例明确验证audio_send_failed。
- `docs/asr-stream-timeouts.md`：记录字段、时间语义、范围和非ACK含义，改正旧“诊断字段不增加”说明。

## TDD / 验证

- Red：新增测试修改前运行：1passed/2failed（--maxfail=2），真实deadline/send路径缺少transport_event，符合目标缺陷。
- 中间回归：新测试误把packets中的字符串ack当成ACK字段，修正为只拒绝ack_/server_ack_/provider_ack_前缀；没有为满足断言更改产品计数含义。原budget5项因新增字段旧精确集合断言失败，按上述新合同更新。
- 补充前音频2例实际暴露failure_details未投影通用HTTPX transport context，补齐白名单分支后通过，保留异常类型与既有retry分类。
- Green命令：`.venv/Scripts/python.exe -m pytest tests/test_asr_transport_diagnostics.py tests/test_asr_failure_context.py tests/test_asr_stream.py tests/test_asr_stream_budget.py tests/test_task_recovery_failures.py tests/test_vilab_transcriber_retry.py tests/test_asr_wav_validation.py tests/test_adaptive_asr_checkpoint.py -q --disable-warnings --tb=short`。
- 结果：**150 passed / 1 warning，4.32s，exit0**。未跑全项目/云端/设备或重新处理失败任务；该结果不证明proxy或历史task f8c88045-2b5d-4ff5-ba85-784bec481c59的实际根因。
- 测试覆盖原真实发送线程、超时LAST窗口、非LAST失败不重放、旧unknown/checkpoint保护、attempt私有落盘和未知恢复状态。没有新增模型/provider调用，Langfuse已由既有tests/conftest禁用。

## 后续显式新operation边界建议（只读分析，未实现）

已只读确认VILabTranscriber全局目录仍按Origin+owner+model+音频指纹定位，recognition.json的inflight会阻止同音频的新operation。此次不改目录键、不删/迁移marker、不更新历史unknown或复用其不确认区间。

后续须由服务端显式确认并durably reserve新的owner-scoped operation后才允许独立执行命名空间，绑定operation ID、canonical原件引用/来源指纹、规范Origin和不可替换模型snapshot；客户端随意提供新UUID不构成新调用授权。同一operation的接受回执未知/执行unknown仍只读查询，不能借换ID自动重放。旧unknown记录须不可变、可追溯保留；新operation明确告知可能重复计费/处理，只由用户确认授权创建。若复用同源已确认成功区间，应有显式、可验证的来源与模型匹配和不可变引用，绝不复制/清除旧inflight来伪造新任务安全性。该变更必须单独设计owner/媒体保护、排他锁、receipt恢复和离线反例后实施，不在本次范围。

## 边界与交付

源码文件开始时已存在且未跟踪，未覆盖他人工作区；无App/手机/路由/proxy/Server代码修改，无commit/push或部署。本次用户已另行授权根仓库这项独立小任务，原App写集限制不适用于本项。父端实际任务已失败/无任务运行的描述由用户提供，本次未主动查询/恢复或提交任务。新诊断仅对随后执行的失败生效，历史不回填。

## 后续变更

2026-10-16｜wugui｜[独立 operation namespace 与 confirmed 前缀实施](../2026-10-16_153737_wugui_无Issue_独立转写命名空间/index.md)：另获用户授权后落实上述只读建议；不改变本档案的 transport 诊断与旧 unknown 保护结论。详见新档案的离线证据，未进行云端或手机验收。
