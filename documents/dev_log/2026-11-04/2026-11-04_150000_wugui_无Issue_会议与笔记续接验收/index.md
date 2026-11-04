# 会议与笔记续接验收

- 创建：2026-11-04，Asia/Shanghai；作者：wugui；执行：Codex
- 分支：codex/meeting-asr-20261102；状态：进行中、本地未提交
- 来源：用户提供共享会话，继续整场总结、飞书发布、原文件归属与桌面 UI/UX 优化。

## 边界与验收

完整逐字稿一次输入，禁止固定拆分；一个原文件对应一条内容，允许多个总结版本；保留原始材料与未知发布记录。须在桌面完成原音频新版本生成、飞书一键发布及正文/位置回读，离线测试不等于验收。保留所有既有工作区修改，不合并 VILab 功能分支。

## 2026-11-04 接续调查

- 最新任务 4e8efb3a 的最终复核输出 84175 字符后连接中断，没有 finish/DONE；未保存完成纪要。
- 当前 notes 表为空，原文件保留；旧短测试飞书交付完成，原长会议没有可查询本地回执，不能据缺失断言未发布。
- 启动现有 public 桌面开发入口，页面确认侧栏已无文件库，但仍有重复资料区与大量常驻控件。

## UI 方向与依据

用户明确要求实际优化而非入口搬移。保留产品黑白与蓝色选中态；扁平桌面框架、对齐的资料行、单层工具栏、24/15/13px 字阶，8px控件圆角。原文件属于内容，版本不重复成为会议。

主参考为当前桌面产品与用户提供的 [unslop](https://github.com/heydamir/unslop)（Damir Sokolovsky，CC BY 4.0）；Refero 在线研究返回 NO_SUBSCRIPTION，采用其 bundled typography/anti-slop 工作界面密度准则。保留现有图标、品牌和中性色语义；拒绝装饰卡片、重复说明和多重胶囊筛选。无新增图片。

笔记页去除重复介绍和大入口卡片，改为紧凑资料操作行；统一主动作与列表文字层级，编辑/删除仍保留键盘可达和可访问标签。纯样式变更以既有行为测试、TypeScript 和真实桌面截图验收，不新增镜像样式断言。

## 待验收

- [ ] 完整原会议新版本生成并保存
- [ ] 新版桌面一键发布到软件研发 / 会议纪要并回读
- [ ] 会议/笔记原文件归属、版本和返回导航
- [ ] 桌面视觉、键盘和窄宽度检查

未提交、未部署；真实验收结果随后追加。

## 飞书回执兼容核查（2026-11-04，Codex 并行调查）

- 只读检查当前数据库：仅短测试有 completed delivery 和 operation receipt；无旧长会议 delivery，也没有已提交 rejection。缺失记录不足以证明远端未写入，未清理历史未知请求。
- 既有改动已把明确的来源校验拒绝持久化，然后返回 `PUBLISH_DEFINITELY_REJECTED`，客户端恢复可编辑草稿；原操作仍不可重放。
- 发现该改动抛普通 `HTTPException`，使内部调用方失去 `FeishuError.code/uncertain`。先收紧回执测试，观察 `test_graphic_rejection_is_committed_and_blocks_late_replay` 失败，再保留 `FeishuError` 类型及原 `meeting_context_unverified` 分类；HTTP 409 证明结构不变。图形校验测试的提示断言兼容该结构化 detail。
- 回执、图形校验、旧正文、已保存会议知识库链路、手动分组与 CLI completion 合计 **240 项通过**（59.16 秒）。此前 delivery/注册恢复/二维码/回执组 **85 项通过**。前端 FeishuDelivery、protocol integration、publishGuard 共 **89 项通过**。
- 前端初次测试因当前 Node 的原生 WebStorage 没有配置文件导致 localStorage 未定义；以进程级 `NODE_OPTIONS=--no-experimental-webstorage` 使用 jsdom Storage 后通过，未改产品代码。
- 未进行真实发布、账号变更或数据库修改。新生成纪要的真实桌面一键发布与回读仍由主流程验收；单元测试不等同于远端成功。

## 普通笔记原文件归属（2026-11-04，Codex 并行实现）

- `/api/files` 只投影一个 `note_id`，不能据此恢复所有版本。新增 note list/detail 的只读 `original_source`；唯一已注册文件关联用 `file:<id>`，严格校验 owner、任务映射、单跳引用和原始 manifest 的关联用 `task:<canonical>`。PDF/Word 的注册文件不要求媒体 manifest；没有证据的历史内容仍独立显示。
- store/hook 保留该字段；新增 `groupNoteDossiers` 返回代表版本与完整版本数组。只按 verified original/owner/scope 分组，不按标题、URL、内容或未经校验 taskId 合并，不改已有正文或数据库。
- 新测试先因缺少实现失败；修正测试任务夹必须有 `.task_id` 的真实定位条件后，后端新投影与 note-library routes **25 项通过**；前端 grouping/store/hooks **24 项通过**，TypeScript 通过。Notes 页面接入由主流程执行。
- 扩展旧 meeting-source-link 回归 **38 项通过、4 项环境失败**：`test_real_symlinks_under_target_are_rejected[source/media_dir/owner/manifest]` 创建真实 symlink 时遇到 Windows `WinError 1314`；没有跳过测试或更改系统权限，不能声称该四项验证通过。
- Notes 页面已接入：先按归档/项目/类型筛选，再按可靠原文件分组；搜索匹配任一版本时保留整组，列表按一条笔记计数，原生 details 展开所有总结版本并链接到各自正文。代表行明确“编辑/删除当前版本”，删除确认说明其他总结版本不受影响。保留父流程既有布局。
- 页面新增两个行为测试，先观察“一份原文件仍显示两条、删除语义不明确”的失败；接入后 group helper 加 Notes 四组共 **25 项通过**，TypeScript 与 diff whitespace check 通过。保留原列表组间顺序，只在组内选最新版本，避免无关重排序。

## 本轮集成验证与待续

- 独立审查发现两项 P2，均已修复：scoped 原文件详情的加载/失败/缺失状态不再回落到文件集合；处理中筛选覆盖实际转写、总结等后端阶段。对应两个文件 60 项回归通过。
- Notes 同源版本接入后，5 个相关测试文件 25 项通过；最终 `npm run build`（含 TypeScript）通过。现有大 bundle、Browserslist 数据与 Tauri 静态/动态导入警告保留，未扩大本轮改动范围。
- compact protocol8 提示消歧后 429 项回归通过；未改完整原文输入要求，未进行真实新总结调用。
- `git diff --check` 使用 CRLF 兼容 whitespace 规则通过。
- 桌面操作被用户其他窗口占用，多次输入被中断。已请求约两分钟桌面操作窗口，尚未收到回复。原生 VINote 仍停在 canonical 原任务记录；新总结、真实飞书发布和视觉截图验收均未完成。后台浏览器预览有独立登录态，未绕过登录或复制凭据。
- 未提交、未部署、未合并 VILab；保留已有工作区改动与历史数据。后端冻结，待桌面可操作后从“生成新版本”确认复用完整原始转写，再完成原生一键发布验收。


## API 实际测试（15:30）

用户明确要求直接接口测试与优化，停止桌面争用。当前范围不实际新增飞书文档。确认完整转写在后续任务 4e8efb3a-98cc-4774-a5b0-d99794feec35，原始上传任务的 reuse 不可用是正确状态。经正常 HTTP context/meeting-versions 接口创建新测试任务 4fa03b80-6367-4667-8c46-7597fc53e812；操作 4c8e2a9d-6e14-4f45-8093-d00c78593a98 回执 accepted，复用完整转写、inherit 原模型、detailed/text。没有重识别、重放旧操作或飞书发布。数据报告 data/meeting-api-validation-20261104.json 不含凭据。等待实际完成。

### 实际结果：未通过

15:42:15 任务失败，生成耗时约 710 秒。保存的原始 working draft 为 81,986 字符，JSON 语法错误位置 offset 46,999（line 1, column 47,000）：中间事实行缺失 field 的值。输出有闭合尾部，但不能据此推断成功，也不能猜测补值。错误发生在 prepare_final_draft / decode_final_review，尚未进入 protocol8 最终核对；因此本次不能验证 compact review 的真实完成效果。

输入文件逐字节与完整旧转写一致（746 段、full_text 33,188 字符），API 文件列表仍只有一份 canonical 原件，新任务在该原件 summary-children 中可查。未保存为完成笔记、未发布飞书。无自动重跑，保留原回执与失败草稿。下一步仅改善具体错误分类及安全诊断信息，避免把格式错误笼统描述成事实核对不完整；不放宽事实验证。

## 用户纠偏：删除默认事实 JSON 阻塞链路

用户明确表示校验反复挡住查看结果不可接受，并要求“赶紧跑通，要合理的链路，不合理的删了”。此指令覆盖旧档案中默认文字会议必须事实账本/二次审核的要求。新默认设计：完整原始转写一次提交，同一冻结模型直接返回 Markdown，完成传输且非空即进入正常展示与保存；不宣称事实已核验。不分三段、不使用旧总结作为输入、不增加自动模型重试。

下游只读审查确认：note_service、文字presentation renderer、note library保存与RelatedSummaryTasks恢复都没有事实账本门槛。只移除生成默认路径的强制protocol3→review gate；保留主机生成的summary_presentation元数据、原件归属、模型绑定和提交回执，避免破坏版本与后续主动飞书发布。历史JSON草稿和专用图形/HTML路径不删除数据。

### 新默认实现与验证

默认text/default/oneshot已改为direct_markdown_scope下的单次全文请求，VILab不再要求response_format=json_object；非空完整Markdown直接走现有保存。208项针对性回归通过，独立代码审查未发现下游阻塞。显式legacy accurate与非text呈现保留兼容，正常文字不再进入事实JSON/二次审核。开发服务最终reload期间首次提交未取得回执，经只读确认数据库无receipt、GET receipt=404后保留该记录，独立新测试已受理（operation 715fdcd2-18d2-4475-b358-464d4d997ccd，task 2de3999b-9324-4a61-b347-56255d49e287）。15:53:05开始总结，后端冻结，未实际发布飞书。

### 简化链路真实验收通过（15:54–15:55）

- 仅一次 VILab chat/completions POST；完整原转写复用，transcribe=0，summarize=103.809秒，总pipeline=105.954秒。
- task 2de3999b-9324-4a61-b347-56255d49e287 成功，直接产出7,997字符Markdown，1个一级标题、7个二级议题标题。
- 正常POST /api/notes返回201，note cd6c96ad-6953-5927-9f5f-75fc1037edf6；GET回读正文与生成结果逐字一致，meeting_source仍指向原canonical 546bfcb5-4cf1-47f2-b4a7-34a1b3612970。
- 读者可以直接打开 output/2de3999b-9324-4a61-b347-56255d49e287/note.md 或会议列表中的新总结。未宣称事实逐条核验、未实际发布飞书。UI优化代码已构建与行为验证，真实视觉验收仍未完成；遵循用户最新要求不再抢占屏幕。
- 最终相关核心回归208通过、代码审查无阻塞、CRLF兼容diff-check通过。未提交/合并/部署。

### 16:25 通知实现与验证
- MainLayout 全局来源回执观察器仅 GET，不重发来源请求、不保存或发布内容；按账号持久化活跃/终态，历史终态首次发现仅建立基线。前台应用内结果，后台官方 Tauri notification 2.8.0 原生插件；拒绝/不可用保留应用内结果。
- 设置页替换虚假邀请/邮件开关为真实后台通知偏好及显式权限按钮；任务过程中不申请权限。账号切换中止旧响应及点击跳转，系统正文不含文件/会议标题。
- Producer API：trackGenerationNotification(owner, { taskId?, operationId?, meeting, mode?, title? })，仅新的已接受任务调用。结果优先实际 task_id 对应 note，否则绑定原 operation/task 恢复路由。
- RED：新增核心测试缺失模块；GREEN：通知核心/原生适配/observer/MainLayout loading 16 tests passed；tsc --noEmit passed；cargo check --lib passed（notification 2.8.0 / tauri 2.12.5）。插件依赖要求 JS @tauri-apps/api ^2.12.0，lock由2.11.0更新2.12.4；Rust相关依赖正常解析更新。
- 未触发真实系统通知、未操作桌面。官方平台限制：Windows系统通知需安装应用，onAction只处理屏幕内toast点击，不处理已移入操作中心的点击；应用内结果入口保留。来源 https://v2.tauri.app/plugin/notification/ 与 https://v2.tauri.app/reference/javascript/notification/ 。

### 16:36 用户要求暂只保留飞书
- 移除桌面MCP/内容处理工具产品入口：导航仅保留直接飞书，搜索与设置文案简化；Connections与旧/settings/mcp转到飞书并保留合法返回上下文。NoteEditor/WorkspaceNote不再暴露翻译/流程图，Tasks不再展示或读取MCP tab。
- 历史MCP模块、收据、凭据与后端保持原样；未调用删除/撤权接口。原Connections目录测试替换为直达飞书且不清历史数据的行为测试；历史正文、返回筛选上下文仍有覆盖。
- 测试：受影响97 tests通过（首轮旧MCP入口4断言失败后更新为退出产品后的预期，WorkspaceNote.read35通过，其余62通过）。tsc当时仅NoteGenerator.tsx:592 producer owner可undefined由root处理。
- 通知补充：同步账号epoch校验，覆盖A→B→A同批次切换，旧响应不接纳；TaskNotifications5 tests通过。

### 16:40 通知快速完成与录制恢复补充
- 新请求POST返回前，receipt observer可能已看到快速终态；ledger现在显式区分静默baseline与已通知终态。producer可补充激活前者，不能重播后者或旧未分类终态。
- 原录制notification允许recordingId；无已保存note时转到真实会议定位协议 locate_recording + locate_focus=meeting。已有note仍优先，避免跳只读task页面而无法恢复录制保存。
- 新增2个RED后修复，核心+observer11 tests通过。tsc本次仅其他并行文件的临时预览React未使用和LocalRecordingPreview nullable待处理，已通知root；未修改这些文件。


## 16:47 最终整合验收

- Root 接入新上传/独立生成/纪要版本/录制任务的受理通知；通知保存失败不影响已受理工作。录制恢复跳转保留 recordingId；快速完成基线竞态与账号 ABA 由通知代理修复。
- Root 生成相关四文件 263 项：初轮 261 通过，2 个旧文案断言“不重新转录”更新为当前“不重新转写”后针对性 2 项通过。新增录制通知失败不影响处理及恢复历史不重新注册测试。
- 最终 npm --prefix frontend run build 成功（tsc + Vite）。保留现有 bundle size/Browserslist 非阻断提示。原生 notification Cargo check 由代理验证通过，未发送真实系统通知。
- 正常本机已认证 GET /api/meeting-source-links/display 返回 200，新增表与路由实际可读。没有为验收改写真实会议信息。
- 后台浏览器真实组件使用独立合成内容检查日期列表，观察到重复时间主标题和双展开入口后修正，最终截图 data/ui-meeting-date-preview-20261104.png。临时 HTML/TSX fixture 已删除，浏览器已关闭。此为组件视觉证据，不是原生完整流程验收。原生只读截图因窗口遮挡捕获到其他应用，未作为验收证据、未保存。未切换/点击用户桌面。
- 飞书设置/MCP入口由对应代理完成；21联系人/26群只读正常刷新已验收。没有对外发送消息/发布。
- 声纹与录屏人物匹配的官方研究及现有代码边界见 docs/superpowers/plans/2026-11-04-speaker-identity-research.md；未声称声纹已上线。日期元数据独立于canonical ID；未实现跨设备导出迁移bundle，未生成上传源仍在独立区块日期分组。

### 17:06 说话人与飞书发送联动：主动开启默认参会人通知
- 飞书设置“自动发布并通知”由用户主动关闭→开启时，draft同时启用auto_publish/notify_participants；必须保存并明确确认目的地/接收人/阅读权限才写入偏好和启用本设备。加载既有用户设置不迁移、不默认写入。
- 保留notify_self、groups、contacts、destination_config与版本归组。关闭auto只关闭未来自动交付，保留接收预设；仍可手动取消参会人选项仅生成文档。
- 明示先确认说话人/实际参会人，再发布对应文档并通知；候选不授权发送。身份未确认时继续沿用waiting_participants整体等待，不拆文档/通知冻结回执。
- 只读审查：capture_saved_meeting标记已完成，后开启不补发历史；resume_participants只恢复同owner/canonical/evidence/connection/policy的waiting且job_id空、lease已过的原行，CAS验证payload不变。unknown/submitting/accepted/failed/cancelled不由确认重放。
- 验证：新opt-in测试RED后修复，设置三组54 tests passed；标签最终回归automatic30 passed；tsc passed；后端auto_runtime/outbox/policy95 passed。未发真实消息、未部署、未改历史凭据或发送收据。

### 17:12 说话人/飞书联动独立审查
- original_asr_evidence返回原始leaf，TranscriptSegment保留speaker_id。只读抽样output已保存ASR含746片段、speaker ID 1–14、segment粒度且无estimated标记（未输出正文或联系人）；旧546b目录缺最终transcript/asr_evidence，未把它冒充已验证样本。
- 发现speaker_unknown/speaker_overlap可被映射已交review修复（当前valid_speaker_id已排除）。发现窗口focus先卸载导致人工匹配草稿丢失已交summary修复。
- 自动发布确认检查：同owner+canonical+evidence+connection复用；_enqueue事务锁确认revision后冻结recipients，变更映射不改已冻结发送或重放旧任务。
- NoteEditor此前MCP移除遗留的3处旧产品断言已调整，保留历史版本/返回上下文测试，35 tests passed。未改NoteEditor实现或执行真实发送。


## 说话人与飞书联动整合

- 后端新增真实speaker资料、候选和独立speaker confirmations表。确认映射只引用真实speaker与本次核验联系人，与参会人确认同CAS事务；unknown/overlap不可绑定。正式API只读验收：HTTP200、14个speaker、0姓名候选、can_confirm=true、unconfirmed。未猜测/保存真人身份。
- Root新增meeting_speaker_context：accepted receipt冻结人名上下文，run前重读scope/版本，换账号/连接或撤回时仅省略姓名；使用与NoteService一致的原始ASR leaf，估算时间段不实名归属，不传open_id给模型，不改原始文件。
- 新context/summary-regeneration总87项通过（旧测试仍要求2次JSON draft/review，按用户已确定的单次Markdown改为1次，并保持原始来源/模型冻结/不重做ASR断言）。复审后取消以UI三条sample决定后台归属能力，6项针对性回归通过。
- 自动发布开关只在用户主动启用时同时选择通知参会人，保存确认才生效；现有偏好不迁移，历史不补发。未确认等待原未发送intent；unknown/accepted不重放。未实际创建飞书文档或发送消息。
- 导入入口修复由review完成：新draft独立收据，旧task/op可恢复，迟到响应scope保护；138项通过。

最终整合：所有本轮代码冻结后 npm --prefix frontend run build 成功（tsc、Vite 3153 modules），git diff --check通过。会议单导入/原件显示研究见 docs/reviews/2026-11-04-meeting-intake-originals.md；会议17+原件45项通过。当前实现为证据候选＋人工确认及同会议复用；未上线跨会议声纹自动识别。无真实外发验收。

### 17:25 预设联系人真实查询诊断（不发送）
- 使用现有账号仅内存认证cookie调用本机8900实际/api/feishu/contacts（未输出token/姓名/open_id）。缓存21位联系人；选已有姓名精确查询HTTP200/items1、首字前缀HTTP200/items1，两者返回fresh selection proof；空query为422。/api/feishu/status确认transport=cli、connected=true、contact_search=true。截图空输入按钮disabled不能证明后端搜索失败，当前未复现用户具体姓名问题。
- 请求路径确为FeishuCLIService→cli.api GET search/v1/user，不是hotwords目录展示。未改偏好、未发送消息或发布文档。
- 独立确认缺陷：contacts把缓存唯一同名当作显式alias，API返回其他尚未缓存同名对象会被按旧ID过滤。修为真实姓名搜索保留API完整页，只有名称不同的明确alias才收敛到指定ID。授权/短期selection proof机制未改变。
- 新增同名大小写/空白归一化2项RED及显式alias保留1项；修复后CLI object catalog + hotwords 92 passed。此缺陷已由离线测试证明，但未宣称是截图搜索问题的已证实根因。

### 联系人默认最近列表补充
- 用户明确需要打开即看到联系人；/api/feishu/contacts空字符串或省略query现在支持CLI实时最近可见联系人。复用已核验CLI +search-user --has-chatted结果，不从旧cache直接签proof，不额外枚举群。
- 每项按原owner/connection/app/sender绑定签900秒selection_token。无cursor的CLI列表返回has_more=false/page_token空、partial=true，更多结果以search_required=true提示输入姓名缩小；具名搜索原分页不变。HTTP transport仍需输入姓名，纯空白参数维持422。
- 3项RED后实现，catalog+hotwords95 tests passed。真实本机8900空query回读HTTP200、20联系人、partial/search_required均true、全部有fresh proof；仅输出数量与布尔状态，未输出姓名/ID/token，未发送消息或改偏好。

### 17:47 联系人初始空白与设置分层收尾
- 用户澄清打开后一个联系人都不可见。CLI 连接的联系人弹窗现自动读取近期可见联系人，支持回车姓名搜索，区分加载、失败、空列表与部分结果。非 CLI 保持按姓名搜索。
- 联系人选择收进独立弹窗，保留关闭后的草稿；文档位置、自动发布、通知对象分层，说明与高级选项按需展开。
- 新增 5 项联系人组件回归，覆盖初次列表、回车查询、迟到响应、非 CLI/断连边界、空列表。前端 60 项通过，后端联系人 33 项通过；代理另验证 catalog/hotwords 95 项通过。
- 本机只读接口返回 20 位近期联系人并携带新鲜选择凭据；完整联系人仍需姓名查询。未发布文档或发送通知。
- npm --prefix frontend run build（tsc + vite）通过；diff --check 通过。尚未进行原生桌面视觉验收。

### 原 URL 下载失败任务恢复（本轮追加）

- 修复 `/api/task/{id}/retry` 对 `kind=media_url` 且明确 `failed_stage=downloading`、`retryable=true` 的原任务返回无原文件 409 的问题。沿用原 URL、原 task ID、冻结模型与 owner；summary、独立操作、未知/活动结果保持禁止恢复。
- 原 URL worker 使用一次性内存恢复 claim，避免现有 request.json 导致无操作退出，并避免重复排队/重复消费。worker 的 finally 清理 ACTIVE。
- 新增 `tests/test_media_url_download_retry.py`：恢复一次、重复点击/claim、状态边界、owner、独立操作、冻结来源失败、worker 异常清理。与媒体提交测试合计 37 passed；原始 worker 注册非 meeting 子集 7 passed。没有真实模型或发送调用。
- 单独全量原始 worker 注册测试中的 meeting fixture 因 meeting_model_boundary 的模型能力检查失败，已告知主代理，未修改该边界。
- 主代理开始真实原任务 retry 后已冻结 Python 编辑。只读复核补充发现：ensure_source 在缺少冻结快照但传入显式 confirmation 时允许 capture_source；URL 恢复分支应在 live 完成后拒绝非空 model_confirmation，保证此路径严格仅复用冻结模型。已即时告知主代理；当前已有快照的实际恢复不受此边界影响。

### 设置辅助页紧凑布局与窄窗口验收

参考锁沿用当前中性桌面工具设计；读取 Refero craft-details 的表单标签、focus-visible 与布局细节。Settings 去除大内容外框，窄窗口分类紧凑换行；Storage 回收站操作可换行、确认框限高滚动；Team 创建和成员邮箱补显性标签、表单与长名称适应窄窗口；Projects 改为紧凑行列表。保留所有业务操作与路由返回上下文。

验证：Settings / StorageSettings / StorageSettings.trash / SettingsNav 共 25 tests passed。`frontend/scripts/settings-layout-preview.mjs` 使用独立 headless Edge 和拦截 API 的合成数据，在 760×600 查看 4 页面：无水平溢出、无 API 写入、无浏览器异常。截图位于 docs/reviews/2026-11-04-{settings,storage,team,team-members,projects}-760.png，已人工读图。不代表真实账户或原生窗口验收。tsc 留给主代理整体收尾（其他代理同时编辑页面）。Python 保持冻结。

### 阅读、编辑与生成操作层级（进行中）

继续既定 Refero 表单/层级参考锁。NoteGenerator 缩小来源/资料标题与主要按钮，来源明细收紧，失败状态仅突出原任务查询/恢复，其他处理方式折叠，所有原安全条件与 continue/newdraft 保留。WorkspaceNote 将导出、分享、删除移至现有内容操作，保留编辑/保存和飞书入口；WriteNote 去掉厚卡片；NoteEditor 调整窄屏留白和工具区密度。

测试首轮 206 项中 201 通过，5 项为旧布局可见性/主操作数量断言；更新预期并保留删除/恢复安全检查后，重跑相关 164 项全部通过；未改动的 NoteEditor/WriteNote 42 项首轮已通过。真实组件模拟截图发现共享 TaskNotifications 使用当前 lucide 版本未导出的 CircleAlert，导致整个 App 模块加载白屏，已即时告知主代理；该共享文件由主代理持有，本代理未改。截图须等该问题修复后重新验收，不将白屏截图计为通过。

截图复核完成：主代理修复共享图标后，`frontend/scripts/reading-layout-preview.mjs` 在真实 App 路由以独立 headless Edge / 合成 GET API，检查生成新建、运行、失败、笔记阅读、编辑五种状态，分别 1440×900 与 760×600；10 张截图保存 docs/reviews/2026-11-04-{generator-new,generator-running,generator-failed,note-read,note-edit}-{1440,760}.png。已读图检查；无横向溢出，浏览器 pageerror 为 0，API 写入为 0。宽窗口正文与工具区分离；窄窗口工具可换行，编辑器保留独立正文滚动区；新建较矮窗口可纵向滚动抵达主操作。共享通知模块已正常加载。没有访问真实账户数据、模型、原生通知或飞书发送。源码/行为测试已冻结，最终构建由主线程执行。

### 旧 UI 可达性审查与通知入口修复

- 以 TypeScript AST 检查 src 下 import/export、字面量 dynamic import 与反向依赖，并核查 App 完整 lazy routes、唯一非字面量 import（仅 appModeStore 初始化测试）、仓库文本引用与组件用途。未仅按名字 grep 判死代码。
- 删除桌面 `components/Notes/ContentIntake.tsx`（旧入口大卡片）及 `components/Settings/ProcessingModelPicker.tsx`（旧模型选择器）：二者无生产/测试/动态导入引用；既有 Notes/NoteGenerator/ModelSourcePanel 已承接可达入口与模型设置。移动端同名 ContentIntake 为独立实际使用组件，未动。
- RetainedOriginals、MCPSettings、ConnectorPluginStore 均有测试引用，依授权限定不删除；App 的 /settings/mcp 与 /connections 继续安全转飞书，/settings/sync 保留存储兼容。不删除后端接口/凭据/历史数据。
- 发现 NotificationSettingsPanel 虽已实现但无任何生产引用，造成后台系统权限设置不可达。新增 Settings 的 notifications tab、总览链接和分类导航，接回真实面板。RED 缺入口失败，GREEN Settings/Nav 16 tests passed。
- headless synthetic 760×600 重新检查5页，截图 notification-settings-760.png 可见真实设置；无水平溢出/异常/API写入。未请求系统权限或发真实通知。

### 最后全流程只读视觉审查与飞书阻塞提示修复

独立 headless Edge mock 读取：生成新建/运行/失败、笔记阅读/编辑、飞书发布面板、移回收站确认后取消；覆盖 1440×900、1024×768、760×560。所有 API GET 均拦截为合成数据，非 GET 一律阻止；未调用模型、发送、实际删除或权限提示。三个尺寸无水平溢出，发布弹窗边界在窗口内，无 pageerror，实际写入请求为 0；截图 docs/reviews/2026-11-04-audit-{feishu,trash}-{1440,1024,760}.png。生成/阅读对应1024截图亦已生成。后台保存/Tasks最新合并仍由对应代理验证，不据此声称真实任务全闭环。

发现并报告：未配置飞书时发布面板同时显示未安装插件、需升级服务、未配置、需连接四条阻塞提示。主线程授权最小修复后，按 configured→connected/身份核验→protocol→设备启用顺序展示当前原因，保留管理连接入口、原回执/发送/权限校验及内部安装状态；可用连接后的启用动作改称“启用飞书发布”。新增两项首次阻塞提示测试 RED→GREEN，FeishuDelivery 69 tests passed。三尺寸重拍确认单提示，无实际操作。其余已读模块未发现新增白屏或可证实的跨页不可达问题；新后台保存与进度实现需主线程最终集成验收。

### 主线程最终集成验收（2026-11-04）

- 已实际恢复 B 站原任务 77dc99af-efca-402e-a18b-8c77b6690ea2；生成 5022 字符 Markdown，保存笔记 3ebcb746-c7d3-4dec-82e7-471405a98310。X 任务 c819f049-6974-467f-b4c1-92bef0accd46 生成 1472 字符学习笔记，保存为 0141a200-7592-4a5f-ab1a-9398938904b5。API 校验结果各一篇；X 同一任务重复保存返回原 ID，未重复创建或覆盖编辑。
- TaskNotifications 接入后台成功结果保存后再标记完成；仅处理当前跟踪中的活动任务，不回放历史终态。保存暂时失败保留恢复机会。任务中心展示各任务实际阶段与可用时长进度，保存后直达笔记。
- 最终定向验证：前端后台保存、通知、任务轮询与实时任务页 36 tests passed；后端 X/B站读取、来源网络保护、原 URL 恢复、幂等保存、飞书 outbox 与笔记接口 202 tests passed；tsc + Vite production build 通过。构建仍有现有大 chunk 提示。
- 界面已在独立无头浏览器以合成数据检查 760/1024/1440 尺寸；不等同原生窗口或真实账户全交互验收。未触发真实系统通知、飞书发布或消息发送。原生最小窗口配置变更需重新启动加载。
- X 当前范围为公开单条帖子的嵌入文字，不保证长帖全文、整串讨论或图片/视频内容。云端服务现有并发限额仍适用。
- 先前较宽测试中旧 meeting fixture 与当前固定云模型能力约束不一致，未放松生产边界，不声称全仓测试全部通过。全仓 diff --check 存在既有/并行改动的 CRLF 空白报告；本轮核心文件按 cr-at-eol 检查通过，不批量改写其他文件。

### Stageshow 安装与任务状态组件（18:51）

- 按用户截图核验 benjitaylor/skills：仓库目前一个 stageshow/SKILL.md，示例不是独立 skills。通过系统 skill-installer 安装至 C:/Users/18063/.codex/skills/stageshow，版本元数据 1.1.0。已阅读 skill 与 craft 指南；范围为产品演示/说明动画，未将伪 UI 的 kit 控件替换生产业务组件。
- 设计沿用 VINote 现有中性色/交互强调色参考锁；借鉴 craft 中标题与元信息分组、进度单轨道和适量状态色。新增 TaskProgress 生产组件：仅经过有效性检查的实际转写数据有百分比与可访问进度条，其他阶段用状态图标；遵循 reduced-motion。
- 主动修复录音任务恢复后的旧错误文字与失败按钮优先级，完成状态与结果入口遵循实时结果；正常状态信息不再标红。
- Tasks.live 初始进度条断言 RED，新增恢复状态回归，最终 Tasks.live/Tasks.source/useTaskCenter 共 30 passed；tsc/Vite 构建通过（现有 chunk 警告保留）。headless 合成资料 760/1440 截图人工检查无横向溢出/JS 异常，不等于原生桌面全流程验收。未调用真实模型或发送飞书消息。

### 跨页任务反馈与通知动作（18:56）

- 按用户继续完善授权，沿用 Refero 现有参考锁与 craft-details 可访问性原则，参考 Stageshow motion 的“状态变化只改变相关元素”和结果明确可见；没有把演示 kit 引入生产组件或添加装饰动画。
- 新 ActiveTaskBadge 订阅本地已有任务状态，展开导航显示尚未完成数量，折叠显示提示点。新增独立 activity 事件只在存储发生变化时广播，不触发额外网络轮询或重入任务轮询；账户隔离、终态减少、重复登记不加数有回归验证。
- 通知按结果提供打开笔记/打开纪要/查看原因/继续保存；长标题可换行、动作不压缩，保留原来源恢复地址与系统通知策略。
- 定向测试 ActiveTaskBadge/Sidebar.navigation/taskNotifications/TaskNotifications：36 passed；生产构建通过，现有 chunk 警告。独立 headless mock 760/1440 检查导航数量与失败通知，无横向溢出或 pageerror；窄屏导航抽屉覆盖时通知保持在遮罩之下，不抢操作焦点。未调用真实模型或飞书发送。

### 全局细节重审与导航层级修正（19:16）

- 用户指出不能只修任务页。覆盖任务、飞书、设置、会议、文件库、导入与两类阅读页：一级任务/飞书页不再虚构返回笔记/记录；加载占位保持相同层级；从设置或内容明确进入飞书仍保留原返回上下文。统一真实详情页返回区紧凑间距，会议标题去逐字动画，并统一主要标题样式。
- 任务标题收敛为“任务”，标签和搜索同一工具区，行操作缩小；新版本模型/形式/时间折叠；不再在中文 UI 显示接口英文成功信息。随机媒体名以导入录音/视频展示，保留原来源和检索字符串，不改任务 ID/文件/存储标题；生成标题优先。失败原文中的技术保护说明不作为主要文案。
- 文件库列表和详情沿用显示名称处理，格式筛选统一为下划线标签，修正音频图标归类。导入提示补齐当前 X 公开单条文字范围。两种笔记阅读页的标题与主要操作从超宽才并排调整为普通桌面宽度并排，减少头部纵向占用。
- 定向回归首组120通过；追加飞书上下文/文件库/生成器184通过（与首组有重叠）；阅读器/上传组件39通过。最终 tsc+Vite 构建通过，core.whitespace=cr-at-eol 本轮文件 diff 检查通过。保持既有 chunk 警告，不声称全仓所有测试通过。
- 独立 headless mock 检查会议/任务/文件库空与有数据、飞书/笔记首页、导入新建/运行/失败、阅读/编辑、设置辅助页，宽窄尺寸760/1440；另按用户截图构造随机文件名/英文成功信息/旧失败/新版本的任务页1280/760，均无水平溢出或JS异常，人工读图并再次调整文件筛选和阅读头部。场景为模拟资料，不称原生真实账户验收；没有桌面输入、真实生成、发布、通知或删除。
