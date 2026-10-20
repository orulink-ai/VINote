# 会议证据、空片段与交付恢复

- 创建日期/时区：2026-10-19，Asia/Shanghai；作者：wugui（Git 配置）。时间目录为任务标识，不作为精确执行时间证据。
- 分支：codex/meeting-context-recovery-20261019；基点 origin/dev b492a43。
- 状态：功能分支交付中，PR #61 保持草稿；VILab-server 协议修复已正常合并及公网核验。两份真实链路完成，内容质量未通过，不发布安装包。
- 需求：[范围与边界](../../../../docs/plans/2026-10-19-meeting-evidence-and-recovery.md)。

## 目标与边界

最新验收见 [两份真实录屏结果](../../../../docs/reviews/2026-10-20-meeting-acceptance-results.md)：最新 A 78/100、B 81/100，保留此前各轮原稿及评分，不能认定全面质量验收通过。实际 summary-only、保存、重开及末段播放已验证，无新增 ASR；准备阶段只读目录失败的候选不评分。前一轮后端全量1797、前端919，本轮回归结果另追加。下文阶段性记录保留原时间语义，以最新结果为准。

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

### 2026-10-20 01:20 Asia/Shanghai｜wugui / Codex

- 本轮补系统保存选择器与有界原件写入、完整媒体预览校验、真实生成确认；补全文来源命题工作稿候选和私有产物路由隔离。未更换默认模型、未重跑ASR。
- 后端全量1833 passed、2 skipped、19 subtests；前端完整103文件首次951 passed/5 failed，旧确认名称反例修复后相关18项通过，其他102文件已通过；TypeScript和生产构建通过。Rust9项此前通过；原生开发窗口实际验证A/B末段至ended、系统导出选择/取消及完整原字节hash一致。
- VILab-server 公网/LAN 均核验最新dev fe8288f7、dirty=false、同一用户目录200；部署检查不等于模型调用验收。
- 最新质量A78/B81，工作稿定位仍有角色/状态升级、漏项和事件关系错误；不合并、不发布、不继续盲目付费追分。私有WinRT OCR原型发现真实错漏，未接产品。详见主复验报告，历史评分保留。
- App独立分支原件/确认修改经源码复核与221项回归，候选原生CI和真机尚待；父gitlink不提前修改。原运行态及热更新保留，本轮工作树修改拟提交到功能分支，提交hash以实际Git为准。

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

### 2026-10-20 上午｜wugui / Codex：实际候选失败与平台范围收口

- 用户明确：视频保留/播放/导出、录屏和画面分析仅桌面；App会议仅录音和分析录音。根规则补充此边界，App独立功能分支完成移除新增视频支持、保留历史数据与录音导出反馈修复。主线程22 suites/276 tests与TypeScript通过，独立审查后提交eace563推送PR #13；CI及手机最新包另验，不提前更新gitlink。
- 本轮先做源事实中间稿与第二调用私有逐项去向审计，完整原始资料和最终自由Markdown结构不变。结构测试260项通过后，实际A只做了一次Luna初稿调用，返回摘录字段形态错误的JSON，立即停止。原始响应及旧纪要保留，无ASR、无自动重试、无第二调用/B样本。不能将原样失败响应的诊断性内存处理当成功。
- 独立审查指出该原始工作稿仍有关键条件遗漏、引用错位、坏转录语义化和逐来源凑事实的问题。仅去可选摘录歧义不足以支持再次付费；正在收敛首阶段为有用观察，由程序派生机械索引、允许无关来源零条/重要来源多条，保留唯一形态的错窗检查。该候选尚未完成实际总结验收，不部署/合并/发布，不虚报100分。
- 完整后端首次1969 passed、2 skipped、19 subtests、1 failed；旧ASR集成mock未随总结契约更新，随后仅改测试夹具，原文件63项通过。源码及模拟/真实证据分开保留；原ASR提交和供体保护断言不变。

### 2026-10-20 Asia/Shanghai｜wugui / Codex：撤回未验收的强制事实契约

- 实际首个结构化候选在首轮因摘录字段 JSON 语法错误失败；后续 observations 候选返回合法 JSON、13 条观察，但 ASR quote 不是对应原窗口的字面子串，严格校验再次阻断。两者均未进入第二轮审核，没有产出可交付的新成稿；未重跑 ASR、未自动重试、未启动 B。离线结构测试通过未能证明实际模型稳定遵守契约，更未证明事实质量改善。
- 本轮将尚未实际验收的契约直接替换 meeting default/oneshot，扩大了生成失败面。在用户已授权的修复范围内撤回默认接线及其测试适配；保留失败原始响应与原任务，不修补 quote、不重新寻址、不将诊断处理当作生成成功，也不恢复或重播失败任务。
- 撤回前已将限定的 10 个已跟踪 app/tests 文件完整快照、相对 a69112c 的二进制兼容 patch、基线内容及 4 个新增 helper/test 完整归档到私有忽略目录，逐文件核验 SHA-256 后才恢复。归档不含 AGENTS、验收报告或其他无关 diff；私有绝对路径和实际会议内容不写入本档案。
- 仅恢复经逐项核对的契约改动，10 个文件按 Git 工作区换行规则还原，经逐项 Git blob hash 校验，规范化内容与 a69112c 相同；4 个新文件从产品/测试树移除，实验代码不残留。此前 source references、working draft 原子保存、原件/媒体、显式 HTTP/WS 直连及未知结果禁止重播等已有修复继续保留。meeting default/oneshot 恢复同模型、完整来源/图片的正常工作稿与全文审核两调用路径，无自动 fallback、模型切换或额外调用。
- 这是恢复既有可用路径，已知事实遗漏、关系混淆及历史质量扣分仍未完成验收。内容 A/B 与独立评审继续由主线程协调；不以回归测试或撤回行为冒充新成稿交付。本轮未调用云端/ASR、未部署、未提交。恢复后的针对性回归结果另行追加，不预填通过。

#### 撤回后验证

- 执行 `python -B -m pytest -p no:cacheprovider tests/test_private_meeting_artifacts.py tests/test_summary_modes.py tests/test_default_full_summary.py tests/test_meeting_review.py tests/test_meeting_source_references.py tests/test_video_summary_materials.py tests/test_anthropic_llm.py tests/test_meeting_summary_regeneration.py tests/test_meeting_parallel_analysis.py tests/test_meeting_evidence.py tests/test_meeting_result_duration.py tests/test_summary_failure_recovery.py tests/test_independent_asr_namespace.py -q --tb=short`：186 passed、1 条既有 Starlette 弃用警告，33.34 秒，退出码 0。
- 覆盖默认全文/同模型两调用、legacy accurate、原始来源引用与工作稿隔离、实际图片输入/能力限制、summary-only 无 ASR、失败禁止旧 retry、独立 ASR seed 仅提交剩余合成音频及供体原样保留。外部模型/ASR 使用离线 mocks，不代表新真实成稿或事实质量验收。
- 归档 14 份当前快照再次通过 SHA-256 校验，4 个新文件均不存在于源码树，`app/tests` 的 Git 状态干净且相对 a69112c 无差异；AGENTS/验收报告等既有用户修改保持原样，journal 仅追加本节。完成后冻结产品 Python/tests 写入，交主线程审查。

- 后续常规回归执行 `python -B -m pytest -p no:cacheprovider tests -q --tb=short`：1833 passed、2 skipped、19 subtests passed、358 条既有警告，367.17 秒，退出码 0。运行前再次核验 14 份快照及 patch；完整日志仅保存在私有归档目录。此结果对应撤回后的旧路径、尚未开始下面回收站独立修改的源码。

### 2026-10-20 Asia/Shanghai｜wugui / Codex：桌面回收站永久清理（进行中）

- 用户新增反馈：回收站不能清理。当前源码 StorageSettings 仅提供恢复；本机内容 store 也没有永久清理 action。正在以隔离内容、DB 和 API 反例复现单条永久删除、清空、失败后重试及账号切换，禁止触碰真实用户回收站/原件。
- 本任务仅修改回收站页面/store、必要的个人 owner 删除保护及对应测试；不写 MeetingWorkbench 或 notes projection，不改其他 agent 负责的会议聚合。若现有 DELETE 接口需调整，只增加兼容的 personal_only 限制，团队既有调用保留，删除正文与版本不派发录音/视频/文件删除。
- 使用 ui-skills-root 选择 diagnosing-bugs，并读取 shadcn/Radix AlertDialog 与 Button 约定；复用现有确认组件，不改无关视觉。无 ASR/LLM、无云端调用、无提交；TDD 与验证结果完成后追加，不预填通过。

#### 回收站修复与最终验证

- 根因：StorageSettings 原来只有恢复按钮，内容 store 缺永久清理 action；单删 UI 入口、批量确认与失败反馈均未接线。仅隐藏缓存又会留下本机数据库正文与版本，刷新可能重现。既有 DELETE 兼容团队成员可访问内容，不能无条件作为个人回收站删除依据。
- 新增单条永久删除和清空回收站：确认冻结当前 owner、内容 key、revision 与所选集合；后出现的回收站条目不被本次批量清理，部分失败仅手动重试剩余项。取消不派发请求，同一渲染双击、换账号、换路由和旧异步响应受保护，反馈与焦点不回绑旧选择。
- 后端 DELETE 增加可选 `personal_only=true`，保留旧调用；原件 retain 前及最终 DB 删除前分别验证个人 scope 与 created_by，最终事务锁定匹配行后只删正文/版本。缺失、外部未知 ID、owner/scope 拒绝继续一致返回 404，不暴露他人存在性。不调用文件/录音删除接口，合成音频和视频实字节、转录、其他用户内容均保留。
- Laplace 独立审查指出的两个 P2 已补反例关闭：历史 pending/retained 明确 localId 无 mapping 时也纳入 owner-bound DELETE；不再将二次 scope 变化导致的 404 吞成清理成功。ID 只来自明确 mapping、历史 localId 与现有 desktop 前缀，不猜 task/media metadata 或路径。
- 仅实际 `Response.status === 204` 产生本次运行内存完成证明，绑定 owner、epoch、key、revision 和确切 DB ID 集合，逐 ID 记录成功。若之后缓存写失败，显式手动继续只完成缓存写入/未确认项，不重复删除已确认项；证明不持久化、不读取任意 cache 字段，reset/重新初始化变更 epoch 后撤销，缓存提交成功后清除。200/202/205、404 和超时均不得授予成功；重载后无证明的模糊 404 保留正文与版本，不宣称已清理。本轮不扩跨重载删除 receipt。
- TDD 先复现 store 缺 action 的 10 项失败、UI 缺入口的 4 项失败；独立审查的 no-mapping localId 反例修复前 2 failed。失败未用 mock skip 或生产 fallback 吞掉。所有 API 操作均使用隔离 SQLite、合成正文/版本/媒体和真实 FastAPI TestClient；未清理真实用户回收站/原件。
- 最终后端命令：`python -B -m pytest -p no:cacheprovider tests/test_trash_purge.py tests/test_note_library_router.py tests/test_local_files.py -q --tb=short`：57 passed、5 条既有弃用警告，54.75 秒，退出码 0。新回收站文件包含认证、跨账号、团队 scope、并发转团队、原件保留、版本删除及保留失败后手动重试。
- 最终前端命令（frontend 目录）：`node node_modules/vitest/vitest.mjs run src/stores/workspaceTrash.test.ts src/stores/workspaceDurability.test.ts src/stores/workspaceItemSync.test.ts src/stores/noteLibraryStore.test.ts src/pages/StorageSettings.trash.test.tsx src/pages/StorageSettings.test.tsx src/pages/Notes.delete.test.tsx --maxWorkers=1 --no-file-parallelism`：7 文件、73 passed，13.02 秒，退出码 0；预期错误分支日志及既有 Router future 警告保留。`node node_modules/typescript/bin/tsc --noEmit` 最终退出码 0；`git diff --check` 通过。
- Laplace 已完成七文件只读复验：两个 P2 关闭，当前未发现新增 P1/P2；未并发写源或跑付费调用。本次写集仅 note_repository/delete 路由、StorageSettings/workspaceStore 与三个新测试文件；共享路由其他 GET projection 修改属于另一 agent，未回退/提交。MeetingWorkbench、notes projection、AGENTS/README 不由本任务编辑。
- 未提交、未部署、未重启，0 ASR/LLM/云端调用；上述结果是隔离 API/组件/存储层验证，不冒充真实用户数据清理验收。
- 冻结时间：2026-10-20 10:28:30 +08:00（Asia/Shanghai）。自此停止本任务产品 Python、前端与 tests 写入，交主线程统一审查。

### 2026-10-20 上午｜并行集成与实际设备复验

- 主线程并行交付：人工正文修订、App原音频导出、桌面回收站和同会议归组。人工A/B的R2经来源核对与独立评审在已验证范围内100/100，最近模型自动稿仍78/81；两种结果分列，不把人工编辑冒充Luna模型改进。正常owner API PATCH回原内容对象，GET正文一致、版本接口保留旧自动正文，无新纪要对象或ASR/LLM。
- 会议归组实现、独审反例及修复见独立`docs/reviews/2026-10-20-meeting-grouping-journal.md`。主线程在原生开发窗口看到两个父会议4/6份，展开旧稿、重开最新修订正文并返回成功。独审P1为legacy别名/传递桥错误跨canonical合并，24种顺序反例修复后独立8/8反例与64项回归通过；未知或冲突关联单独保留，原件和全部版本不迁移。
- App f8f8662离线CI和独立APK成功，主线程保数据安装。系统导出取消反馈、重新保存及字节hash实际通过；22分57秒原件与新副本均22,266,052字节，SHA-256相同。打开生成确认后取消，仍版本2、旧纪要可重开，实际回听至0:25暂停。无USB reverse/诊断forward、无ASR/LLM。不是正式发布/iOS或全录音逐秒播放验收。App独立docs提交d297d03已推送PR #13，head离线CI通过。
- 合并后的前端全量106文件994项全部通过，129.69秒；TypeScript及生产构建通过，既有警告保留。后端完整回归结果以下方实际命令完成为准。回收站和分组独立审查均无当前未关闭P1/P2。API8919/Vite3189/Metro8081监听仍在，原运行目录未reset/switch，父gitlink不提前更新。
- 本次提交将代码修复、真实失败和实际验收边界一起记录在功能分支PR #61（目标dev）。自动总结尚未收口，仍保留草稿，不合并或发布，不把组件/隔离DB测试写成真实用户数据已清理。
- 主线程最终完整后端命令：`python -B -m pytest -p no:cacheprovider tests -q --disable-warnings --maxfail=1`，**1841 passed、2 skipped、19 subtests passed**，361.45秒，退出0；包含两条并行修复的最终源码。最终审查后构建再确认，不新增付费调用。
