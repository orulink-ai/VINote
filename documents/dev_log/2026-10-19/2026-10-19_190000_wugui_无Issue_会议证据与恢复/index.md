# 会议证据、空片段与交付恢复

- 创建日期/时区：2026-10-19，Asia/Shanghai；作者：wugui（Git 配置）。时间目录为任务标识，不作为精确执行时间证据。
- 分支：codex/meeting-context-recovery-20261019；基点 origin/dev b492a43。
- 状态：功能分支交付中，PR #61 保持草稿；VILab-server 协议修复已正常合并及公网核验。两份真实链路完成，内容质量未通过，不发布安装包。
- 需求：[范围与边界](../../../../docs/plans/2026-10-19-meeting-evidence-and-recovery.md)。

## 目标与边界

最新验收见 [两份真实录屏结果](../../../../docs/reviews/2026-10-20-meeting-acceptance-results.md)：最新 A 81/100、B 71/100，保留此前 A 83/B 67 及所有原稿；覆盖改善但事实准确性回退，不能认定全面质量验收通过。实际 summary-only、保存、重开及末段播放已验证，无新增 ASR；准备阶段只读目录失败的候选不评分。后端全量 1797、前端全量 919，后续提示相关 100 与标题相关 111 回归、最终构建通过。下文阶段性记录保留原时间语义，以最新结果为准。

修复空识别阻断、长视频播放、音视频证据组织、总结与详情恢复。保留原件、账号隔离和确认记录；不自动换模型，不盲目重试未知请求。两个真实录屏作为固定私有测试集，源文件及产物不提交 Git。

用户最新指定测试 LLM 为目录中实际可用的 gpt-6-luna；ASR 可选择阿里云或豆包，冻结后不得失败自动切换。已有确认识别优先复用。视觉模型兼容性需实际核验，不能假称文本模型读取了图片。

## 发现

- 源码 prepare_meeting_audio 已使用高低通及轻度 afftdn，不是完全没有预处理；滤波不等于能区分背景闲聊。
- 两份原录屏 ffprobe 均未报告容器 duration。此为播放索引候选问题，需 remux、末段解码与浏览器拖动证据确认，不能提前宣称根因。
- 当前流式空终态错误码在客户端白名单缺失；安全处理须依赖上游明确终态及覆盖证据，不将 unverified 泛化为成功。
- 前一轮 PR #60 尚未合入；选择性审查恢复与飞书加载改动，避免重复代码。

## 验收

- [ ] 空识别终态离线正/反例与恢复测试。
- [ ] 原件不变，预览可覆盖结尾并支持 Range/拖动。
- [ ] 全程画面材料与逐字稿/说话人对应，动态纪要结构。
- [ ] 实际新模型目录核验与固定两样本总结。
- [ ] 100 分证据评分，记录扣分及观察范围。
- [ ] 实际桌面完整流程及失败/返回/恢复，区别源代码与安装包。

## 评分规则

事实准确35、重要议题覆盖25、音视频融合15、提炼组织15、阅读与可执行性10，共100。
对候选方案、数量、负责人和期限的编造计入事实扣分；关键决定编造属于不可验收，不由总分掩盖。
不存在行动项的会议不强迫生成行动项；能准确说明无明确承诺即可。
只做抽样画面核对或语音覆盖不足时标明评分范围，不冒充全片完整独立审阅。

## 验证记录

开始阶段仅完成文件/源码检查，未新增 ASR/LLM 调用。后续真实命令与结果追加于此，不预填通过。

### 源码、离线与实际证据（进行中）

- 后端全量：1,676 passed；前端全量：100 文件、872 passed。前端类型与构建通过；浏览器合成素材烟测覆盖横竖视频、首中尾播放、重载保位及窄屏溢出，不能替代真实会议验收。
- 服务端空识别终态修复已通过正常 PR #152 合入 VILab-server dev，合并提交 fe8288f7，CI 成功。公网部署与实际 ASR 验收独立记录，不以 CI 通过代替部署。
- 私有样本 A：使用明确选择的 Luna，复用已完成转写。三轮实际输出按相同维度分别为 80、79、83 分，保留回归与扣分；不是满分能力。最新输出修正了关键物料误读，但重要候选比较和安排仍有遗漏。
- 最新 A 已在真实浏览器生成、自动保存、重开；标题保留原始录制时间。实际媒体时长 1712.53 秒，末段 1705.66 秒可播放，503 像素视口无横向溢出。原件保持不变。
- 私有样本 B 已离线验证可复用 12 个确认片段、750.236 秒；等待服务端新契约部署及前置检查通过后，才允许剩余部分实际识别。旧未知请求和原始检查点保留。
- 图像兼容性只用合成图片验证明确选择的模型；回执绑定 owner、Origin、model。截断、拒绝、工具调用和未知响应不得缓存为成功或自动重放。本轮未发布的 completed v1 测试回执由受控手工归档保留，再做一次 v2 前置检查；这不是产品自动迁移策略。
- 真实素材、产物、逐帧评价和私人链接仅存忽略目录；仓库中只记录匿名结果和验证范围。以上均为功能源码运行证据，尚非新安装包发布验收。

### 直接父独立任务前缀恢复（同轮后续）

- v2 将 selected parent 和 canonical 原件分别绑定进确认、DB fingerprint 与 live lease；原件引用不形成链。新增 `parent_asr_prefix.py`，并接入 context、accept、lease 和 transcriber；保留 v1。
- TDD：先写独立 helper 正反例（模块缺失），再写真实 operation/lease/transcriber 集成测试；集成前因 context 不支持 receipts 参数失败。修正 Windows TestClient 的本机事件循环 socket 夹具后，针对性回归 217 passed。
- 集成反例验证 donor 损坏、未提交记录、stamp/typed-empty/WAV/DB 不匹配均不能提交或退回全局前缀；正例通过真实首次 claim 生成合成失败父任务，验证新 seed fsync 在策略读取和剩余提交之前、旧记录字节不变、重复 POST 不排队。
- 私有运行态已通过只读 DB、同一预处理/FFmpeg 的离线 preflight；没有创建 operation、claim 或模型调用。该检查不是实际剩余 ASR/总结验收；具体私有身份与内容不入库。
- 全量后端：`python -B -m pytest -p no:cacheprovider tests -q --tb=short`，1,747 passed、19 subtests、358 warnings，187.13 秒。合成集成测试只使用模拟 provider 响应，不代表实际剩余处理已完成；此后并行加入的测试需单独核验。

### P1：冻结所选父 checkpoint 版本

- 独立审核指出旧 v2 只绑定父身份；GET 后同一 stamp/DB 下缩短 confirmed prefix 不改变 revision，可能重复已完成部分。新增反例复现 GET→截短→POST、POST→截短→claim、lease→截短→seed 三个窗口，修复前均失败（其余 16 项通过）。
- 服务端在父锁内严格读取 prefix，将完整 checkpoint SHA-256 与精确 end frame 纳入 opaque revision，因此纳入 accepted fingerprint；server-only link 与 live lease 冻结快照。worker 重算以及 seed 前父锁内复核均须相同。公开 GET/POST 字段不增加，v1 不变。
- 增加同 end frame 改文字、伪改 child link、缺失/撤销 lease、seed fsync 失败反例；客户端传 parent_prefix 返回 422。针对性回归 225 passed；最终全量回归 1,758 passed、19 subtests、358 warnings，180.10 秒（同前述 pytest 命令，包含并行新增时长测试）。
- 修复后再次用只读私有 DB 与相同预处理/FFmpeg 执行离线 preflight，冻结 prefix 匹配、原 checkpoint 字节未变；未创建 operation/claim，没有实际 ASR/LLM 调用。实际剩余处理仍待用户明确确认，不以离线检查冒充供应商验收。

### 公网与样本 B 的实际结果（未完成验收）

- VILab-server 合并提交 fe8288f7 已在公网构建、切换并健康核验。完整源码树 624 个文件与目标提交相同；为目标机源码构建，不冒充 CI OCI 字节。旧镜像与冻结配置保留，仅 image 改变，环境、挂载、网络及账号配置一致。
- 首次部署核验工具错误地把启动时随机 serviceId 当成跨重启固定值而回滚；从源码确认该 ID 的语义后，修正版验证合法 UUID、镜像、构建提交、稳定容器及配置一致性。修正版部署回执成功，未因部署重跑 ASR。
- B 实际复用先前 750.236 秒；继续保存至 1247.07 秒、20 个确认区间，其中 3 个可验证正常空终态均继续后续识别。这验证的是空终态契约，不是完整转写成功。
- 后续新会话在约 4.5 秒收到上游 55000000：本地诊断最大写间隔 201ms、8 秒等包空档 0、写失败 0；与 EOF/长会话收尾无关。官方错误表定义为临时服务问题，尚不能确定提供方内部原因，也不能宣称调用链全部修好。
- 失败未自动重试或更换模型，20:47 已确认材料和原件保留。B 尚无最终纪要及内容总分；不以不完整材料生成完整验收结果。
- 真实页面另发现 bare `?task=` 缺少流程上下文时默认显示笔记。前端改为中性处理记录和任务页返回；已知会议入口保留 `meeting=1`，未知类型不猜分类或显示笔记六步流程。新增回归零 POST，关联 149 项与类型检查通过。

### ASR WebSocket 显式关闭隐式代理（离线修复）

- 当前固定 websockets 15 的 `proxy=True` 会在空代理环境下继续通过 urllib 读取 Windows 用户 Internet Settings；WinHTTP direct 不能排除该路径。仅 `open_recognition` 改为显式 `proxy=None`，保留默认 TLS、原心跳/deadline/分段/重试分类，不修改系统设置。
- 新增 `test_asr_direct_transport.py`，使用真实 websockets connect 代码和离线 Windows registry/proxy trap，验证只连接目标、Authorization 仅交给目标握手、默认 TLS 验证开关保留，以及 TLS 失败无代理 fallback/第二次连接。
- 新增白名单 `transport_exception_class`、`ws_proxy_mode="disabled"`，延续有效 received wire close code；异常类别/关闭码通过真实故障分类和临时 status.json 往返，reason/URL/凭证及任意类别被丢弃。该 marker 不表示绕过 TUN/VPN。
- TDD：修改前 7 failed、6 passed，失败对应隐式代理路径和缺失新诊断字段；修复后 `python -B -m pytest -p no:cacheprovider tests/test_asr_direct_transport.py tests/test_asr_transport_diagnostics.py tests/test_asr_stream.py tests/test_asr_stream_budget.py tests/test_vilab_transcriber_retry.py -q --tb=short`，128 passed，4.99 秒。未修改其他测试源码；未跑云、未提交，实际长流效果仍待另行明确确认。
