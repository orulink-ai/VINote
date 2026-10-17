# VINote 两端 UI/UX 独立架构审查（2026-10-12）

## 2026-10-12 接续：身份403与逐条同步策略（未验收）

父级真实匿名核验：两次 session_read 约167–169ms，`/user` HTTP403约311/767ms；不是这两次的8秒 deadline 或 Keychain慢读。本机列表保留，在线 verified 仍未通过。开发诊断保持默认关闭；新增固定公开错误code白名单，未知/缺失分别输出 unrecognized/missing，不输出账号、headers、URL、正文、凭证或原始message。尚未获得实际403 code，未把所有403当expired，未改变fetchMe仅401刷新规则。取得明确code后才能确定最小安全刷新分支。

用户新增逐条唯一ID、sync opt-in/本机only、原媒体不sync。当前代码缺口：`VINote-app/src/lib/useTrustedSession.ts:46` 核验后自动调用全量同步；`workspace.ts:152` 起扫描所有本机notes、按task/workspace分组并自动建mapping，`:272` 起拉取全部云条目；后端 `app/models/workspace.py:16`/`:157` 与 App mapping 无逐条策略字段。`app/routers/workspace.py:38` 的旧 import-local 与 migration service 也必须受新合同约束，不能把整个设备历史再次全量导入。

随后PM确认：新内容默认同账号同步，创建前可选仅本地；离线默认对象仍待同步。已上云关闭仅停止后续同步，准确提示“后续仅本地，云端已有版本保留”；云直达先真实持久保存完整正文与可读版本。云副本撤回是独立确认、原operation ACK流程，softdelete仅云回收站，不称永久擦除。下段“新对象默认本机only”为架构此前待确认候选，已被PM本段替代；旧对象不能因无policy而自动批量迁移，清理旧测试集未获授权。技术落地还需真实policy/epoch绑定扫描、队列、附件和每次PUT，保留unknown/pending/CAS基线；关闭不清队列或假ACK，开启不抬基线。当前仅合同，未实施。

待PM确认的最小合同：canonical content_id独立于title/task/version；既有workspace_key保持云对象身份，不能改名重建或用标题去重。新对象默认本机only、旧无mapping对象不自动提升同步；已上云对象如何标记为legacy/需确认由产品定。关闭同步必须区分本设备暂停与账号对象撤回，不能隐式DELETE云副本。持久policy绑定owner+serviceOrigin+content_id；每条出站/入站、图片附件准备、后台队列和迁移都先查显式授权，CAS仍fresh、unknown原operation与草稿保留；policy未知则不发送，不提升baseline、不冒synced。原媒体不上传；显式MCP/云模型/飞书会发送正文，不能把本机only按钮描述为所有数据绝不上云。上述为只读缺口/待确认建议，尚未实施策略、改desktopstore或部署。

## 结论与证据口径

**初审实得分：6.8/10。桌面端 6.8，App 6.7。当前不满足定义验收 10 分。** 这是架构师对 UI 状态契约的独立评分，不替代产品经理、设计师的独立审查，也不代表已完成两端全量实机验收。

初审阶段仅阅读当前工作树中的页面、路由、客户端状态与服务边界、必要文档和已有截图，仅写本报告；该阶段没有修改业务代码或运行测试。下面原始问题均为静态代码推导，**触发场景均未由本审查者实机复现**。仓库正在并行修改，原始问题行号对应初审读取快照，修复后须按符号重新核对。

**后续修复补充：** 用户随后授权修复 #4/#5，并核查本地编辑的 CAS 基线，定向本地回归与 TypeScript 检查已通过，详见 #4/#5。随后又授权三角色直接沟通和 source POST 持久回执模块开发，具体范围与状态见本文整产品契约补充；**初审分数维持 6.8/10，不据本地测试自动改分。** 没有回退工作树、启动服务、操作浏览器或手机、主动读取 `.env` 或凭证、修改实际云数据。

采用的真实证据（以下为初审时点，后续修复及实际结果以本文末尾最新小节为准）：

- 用户提供的实机事实：`python.org/about` 网页生成笔记；桌面 PDF 生成成功且手机可见；手机 DOCX 生成成功且 native 桌面可见并显示已同步。这些是已有成功样本，不能外推到断网、冲突、账号切换、冷启动及发布版独立运行。
- 已查看 `data/workspace-bundles/desktop-word-public-synced.jpg`：最新桌面 Word 详情显示 Android 来源、已同步、正文/对话，未出现逐字稿或原音控制。截图证明该时刻的页面呈现，不证明所有版本与失败路径。
- 已查看 `data/workspace-bundles/app-pdf-public-synced.png`：旧 App PDF 截图仍有逐字稿及“原音在桌面端”提示。父代理正在修复该问题；当前 `VINote-app/src/components/MeetingDetailWorkspace.tsx:78-100` 已有文字来源分支。**不把旧截图当作当前仍未修复的证据，修复后的 App 实机状态未验证。** ContentIntake 同样由父代理修改并验机，本报告不重复承担该整改。
- 按用户最新事实，共享 workspace API、飞书应用配置已经部署。飞书选择已有应用由用户自行决定，OAuth 尚未完成。未 OAuth 属于验收边界，不作为“部署失败”或用户操作缺陷，不要求代理替用户选应用。
- `docs/shared-workspace.md` 当前状态段仍有“两端地址尚未切换”等旧描述；`navigation-final.md:39` 仍有网页/PDF/Word 未接通的旧描述。判定能力时采用当前代码与用户最新实机事实，不能沿用这些历史文字否认成功结果。本报告不修改这些文档。

## 分维度评分与可验收 10 分条件

分数评价的是已审查的 UI 契约成熟度，不是测试覆盖率或安全保证。两端按相同权重评分，再等权合并：桌面加权 6.825，App 加权 6.675，合并 6.75，显示为 6.8。

| 维度 | 权重 | 桌面 | App | 达到该维度 10 分必须有的验收证据 |
| --- | ---: | ---: | ---: | --- |
| 导航、返回与视图状态 | 15% | 7.5 | 6.5 | 会议/笔记、文件、插件、账号/设置及任务的进入与返回均回实际来源；搜索、筛选、滚动和交付草稿恢复；深链接与系统返回行为可预测 |
| loading、failure、retry 与任务恢复 | 20% | 6.0 | 7.0 | 提交前落盘意图；已接收任务在断网、离页和冷启动后可查；未知回执不能被普通重试悄悄创建新任务；重试沿用原操作及输入 |
| 模态层级与焦点 | 10% | 8.0 | 8.0 | Sheet→选择→危险确认顺序正确；Esc/Android 返回先处理最上层；取消回原控件；键盘、软键盘及屏幕阅读器可达；不出现两个活动任务层抢焦点 |
| owner 隔离与会话切换 | 15% | 8.0 | 8.0 | A/B 账号切换时旧网络、读盘和任务结果不会显示或写入新账号；401 有界刷新，服务故障不清空草稿；缓存、原件、附件及运行记录均隔离 |
| 同步与修订一致性 | 20% | 6.5 | 6.0 | 当前正文、展示修订、证据、导出/发布快照一致；并发修改明确冲突；切换服务不吞冲突；删除/恢复未知回执可恢复；全部版本保持可达 |
| 原始媒体/文档生命周期 | 10% | 7.0 | 7.0 | 录制或导入后源文件可定位；生成失败仍保留；跨端明确缺少原件；删除原件不删正文/版本；文件与内容互相链接；录音停止、取消和错误均释放资源 |
| 公共生成与插件真实边界 | 10% | 5.0 | 4.0 | 发布版 App 在电脑关闭、无 USB/loopback 转发时完成明确支持的公网生成；共享 API 与设备原件 API 分工可见；OAuth 未完成时不承诺已连接/可发布；MCP 未知结果只查状态 |

已有正向证据：桌面 `lib/navigation.ts:1-13` 校验 contextual parent；App 根组件持有返回来源；桌面 `workspaceStore.ts:304-323` 在提交前持久保存写操作；App `integration.ts:21-42` 绑定 owner、401 最多刷新一次且不重放传输失败；服务端 `workspace_service.py:104-178` 有 owner+operation 回执、revision CAS 和历史保留；App `workspaceStorage.ts:65-75` 提交完整快照后更新账号索引；原件播放仅经本机映射授权（`workspaceStorage.ts:88-89`）。这些实现值得保留。

模态代码也已有明确基础：桌面 `index.css:257-266` 定义任务 50、选择 55、确认 60、提示 70；`WorkspaceNote.tsx:650/712/730` 在打开另一任务/确认前关闭来源 Sheet；App `BottomActionSheet.tsx:30-53` 支持系统返回/无障碍退出先回内部步骤。**实际焦点回归、模态切换动画期间的层级、软键盘遮挡仍未验证，不能据静态 z-index 给满分。**

## 优先问题（最多 8 项）

### 1. P1：发布版 App 保留生成入口，但没有对应公网生成 Origin

**位置：** `VINote-app/src/lib/integration.ts:7-19`；`VINote-app/src/lib/noteIntake.ts:44-65`；`VINote-app/src/screens/NoteIntakeScreen.tsx:97-109`；`app/__init__.py:47-61`。

**具体触发：** 发布版（`__DEV__ = false`）进入“链接或文件转笔记”，点击生成。generationBaseUrl 固定为空；`/api/generate`、`/api/generate_from_upload`、`/api/task` 均不走 integrationBaseUrl，直接得到 INTEGRATION_NOT_CONFIGURED。共享云 runtime 提前 return，不注册这些设备生成路由。源码 App 在 loopback 服务上成功生成，不证明发布版能独立生成。

**用户影响：** 输入/选择文件后才发现主要动作不可用；“可公网同步”容易被理解成“可公网生成”。离开电脑的核心整理流程未闭环。

**建议：** 在入口读取真实能力并提前说明可用范围；若生成是交付范围，配置独立、经鉴权的公网生成服务和任务查询，不把 workspace 服务当成设备原件上传服务。保持共享内容与原件边界。

**验收：** 电脑关机、关闭 USB 转发，用真实发布配置在蜂窝网络分别生成网页、PDF、DOCX，并恢复一次查询失败；未支持的部署在选择文件前清楚禁用/解释。**未验证。**

### 2. P1：来源生成的提交/恢复记录不完整，未知回执仍可能创建第二份任务

**位置：** 桌面 `frontend/src/pages/NoteGenerator.tsx:221-290/359`、`frontend/src/pages/Tasks.tsx:57-69`；服务端 `app/routers/note.py:397-418/676-692`；App `VINote-app/src/lib/noteIntake.ts:13/63-74`、`VINote-app/src/screens/NoteIntakeScreen.tsx:78/95`、`VINote-app/src/screens/TasksScreen.tsx:65-70`。

**具体触发：** 桌面网页/PDF/DOCX POST 已被接受但响应丢失，receipt 尚未赋值；失败页普通“重试生成”再次 POST。服务端这些路径每次创建 uuid4，没有客户端提交键去重。即使收到回执，桌面只存 sessionStorage，窗口冷启动后任务恢复入口也丢失。App 有 uncertain 提示，优于桌面，但每账号仅一个 intake 槽；终止失败后点“更换来源”会覆盖原 taskId，任务页只读取录音与 workspace 文字任务，没有来源 intake 历史入口。

**用户影响：** 重复生成/费用、已接收结果失去可发现入口；“保留原任务”的提示没有完整恢复路径。此处不指本机文件库已有 task_id 去重，也不指带 meeting_session_id 的录音路径。

**建议：** 两端在 POST 前按账号持久保存 submission id、来源及状态，服务端返回同一提交的任务；用持久任务集合替代 sessionStorage/单槽，未知提交先查 receipt，明确开始新来源也保留旧任务卡。

**验收：** 人工中断 POST 响应后重试，只创建一个任务；收回执后关闭并重开客户端可查回；App 失败任务更换来源后仍能从任务页恢复。**未验证。**

### 3. P1：桌面“生成新版本”的恢复标识仅在组件内存，冲突生成结果未提供保留入口

**位置：** `frontend/src/pages/WorkspaceNote.tsx:93-98/194/256-279/797-808`；`app/services/workspace_generation.py:313-332`。对照 App `VINote-app/src/components/GenerateVersionPanel.tsx:38-63/73`。

**具体触发：** 桌面生成新版本发生超时或 409 保存冲突，用户返回列表再打开详情或重启。generation 被重新置空，新操作生成新的 UUID；catch 仅展示 message，不保存 `ApiError.detail.generated_content`。服务端虽按同一 operation 提供回执和生成输出保护，客户端失去原操作就无法兑现“重试原生成请求”。

**用户影响：** 重复 LLM 生成、任务与要求无法恢复；已经生成的冲突正文用户不能比较或另存。App 已有持久请求及冲突另存能力，跨端恢复能力不一致。

**建议：** 桌面按 owner+note 持久保存原 request、错误与生成输出，再发送；任务页连接同一恢复记录；409 展示已生成正文并提供比较/另存，成功确认后再清理。

**验收：** 同一生成请求在离页、重启、超时后沿用 UUID；并发编辑触发 409 时旧版本及生成输出都能找回，恢复不再次生成。**未验证。**

### 4. P1：App 切换共享服务时，先覆写 baseline，可能自动覆盖远端不同修改（已本地修复，待云端/实机验收）

**修复状态（2026-10-12）：** `VINote-app/src/lib/workspace.ts:48-72/91-130/184-208/237-244` 保留旧服务已确认基线，与本地待写正文、新服务远端做三方比较，再决定是否调整预期 revision。正文、标题、来源类型、归档、metadata 和逐字稿/说话人证据均参与核验；旧基线缺失、revision 不匹配、远端不同修改或 tombstone 均保守进入 conflict，保留草稿，不发 PUT。远端保持旧基线或已符合待写结果时才可重设基线；明确 404 的新服务记录按 revision 0 新建。迁移读取不先覆盖持久缓存或服务 Origin，中断后仍有原比较基线。

**本地编辑基线补充：** `workspace.ts:191-206` 创建 pending 时优先采用源 `Note.workspace_revision`，不因后台拉取提升了 mapping.revision 就抬高草稿的 CAS 基线。带 workspace_key 的草稿缺少源 revision 时进入 conflict；r1 草稿遇到 r2 mapping/远端时仍按 r1 请求，由 CAS 拒绝并保留远端 r2。父代理的详情订阅和编辑入口校验不在本次修改/验证范围。

以下为原始发现，位置与过程保留作整改对照：

**位置：** `VINote-app/src/lib/workspace.ts:64-87/159-174`。

**具体触发：** state.serviceOrigin 与 integrationBaseUrl 不同，已有 mapping.pending，本地旧 baseline 为 A，新服务同 key 正文为 B，待提交草稿为 C。第 73 行先把远端 B 写入 state.cache；第 79 行取出的 baseline 已是 B。第 82 行 `remote.content !== baseline.content` 为 false，随后自动把 C 的 base_revision 改为 B 的当前 revision，允许直接写入。

**用户影响：** 本应让用户比较的跨服务冲突变成自动替换最新正文；即便历史保留，当前正文和“已同步”状态仍违背显式合并契约。不是指已经证明当前普通同步发生了覆盖。

**建议：** 切服务前保留独立旧基线；先做旧基线/本地草稿/新远端三方比较，基线不明则保守列为待核验，不自动提升 base_revision 绕过冲突。

**验收：** A/B/C、title/metadata/证据/归档/tombstone 差异、未知或失配基线、相同内容安全恢复、未建立 pending 的本地草稿、迁移中断、404 新建及本地编辑 revision 均已有定向模拟回归。云端真实服务切换、冲突比较/合并 UI 和两端冷启动恢复仍**未验证**，不声明已完成产品验收。

### 5. P1：App 删除回执丢失后，恢复可能永久复用删除操作 ID（已本地修复，待云端/实机验收）

**修复状态（2026-10-12）：** `VINote-app/src/lib/workspaceStorage.ts:22-23` 为 deleteOperation 最小追加可选 action 与 serviceOrigin，兼容旧持久格式；`VINote-app/src/lib/workspace.ts:289-342` 在发送前持久记录原动作，已知动作的未知回执只用原 action/ID/base_revision 重放。确认原回执后，相反动作使用当前 revision 与新 ID；相同动作不重复变更。无 action 的旧格式仅先读最新状态，不猜测原意图、不将旧 ID 用于新动作；读取失败保留记录。确定的 REVISION_CONFLICT/OPERATION_REUSED 也须读回成功后才退役旧记录。标有其他服务 Origin 的操作保留并要求返回原服务核验。

**并发保护：** 删除/恢复与同步共用 inFlight，避免双击创建两个 ID 或同步覆盖待确认意图；`workspace.ts:149` 在有 deleteOperation 时不上传本地编辑。实际任务页未确认操作的呈现没有修改，也未实机核验。

以下为原始发现，位置与过程保留作整改对照：

**位置：** `VINote-app/src/lib/workspace.ts:228-243`、`VINote-app/src/lib/workspaceStorage.ts:22`、`VINote-app/src/screens/TasksScreen.tsx:62-63`；`app/services/workspace_service.py:84-89/183-190`。

**具体触发：** 删除已在服务端提交，响应丢失，deleteOperation 持久保留。后续同步已读到 tombstone，用户在共享回收站点恢复。客户端 `deleteOperation ||=` 复用原 ID/base_revision，未记录该 ID 的 action；恢复 action 的 fingerprint 与原删除不同，服务端返回 OPERATION_REUSED。失败路径没有清理或恢复该操作意图。

**用户影响：** 回收站已有记录却不能通过正常“恢复”操作取回；按提示刷新也可能再次发送同一错误 ID。

**建议：** 持久保存 action+原请求；先核验或重放原删除回执，确认后清理，再以当前 revision 和新 ID 发起恢复。任务页显式展示未确认删除；不能将未知删除 ID 直接改用于 restore。

**验收：** 丢弃删除成功响应→同步拉取删除标记→重放原删除→新 ID 恢复，以及未知恢复按原 ID 重试，已在模拟服务验证。旧格式两种当前状态、读取离线、意图落盘失败、重放仍离线、确定拒绝后读回、跨服务禁重放、未知删除禁 PUT、同步互斥也已回归。真实云端回执语义、回收站/任务页交互、两端重启与断网恢复仍**未验证**。

**#4/#5 验证记录：** 新增 `VINote-app/__tests__/workspaceRecovery.test.ts`，采用模拟 API、账号及文件系统，保留真实 workspaceStorage 的快照提交/读取路径，不访问云端。修复前定向回归为 13 失败/3 通过；随修复扩展后的最终结果为 **1 组、27/27 通过**，0 snapshots。仅运行下列两项检查，顺序执行，每项设置 `NODE_OPTIONS=--max-old-space-size=768`：

```text
cd VINote-app
npx jest __tests__/workspaceRecovery.test.ts --runInBand   # exit 0；27/27
npx tsc --noEmit                                         # exit 0
```

未运行服务、全量测试、构建或浏览器/手机检查；没有生产部署或实际云数据修改证据。这些结果确认本次本地代码修复，不能替代满分验收。

### 6. P1：详情未跟随远端修订更新，桌面仍标“最新正文/已同步”

**位置：** 桌面 `frontend/src/pages/WorkspaceNote.tsx:70-74/187-211/348-365/375-389/424`、`frontend/src/components/Layout/WorkspaceSync.tsx:23-25`；App `VINote-app/src/screens/NoteDetailScreen.tsx:53-72`、`VINote-app/App.tsx:99/113`。

**具体触发：** 桌面打开 r1，另一端编辑为 r2，后台 sync 更新 details[key]。note 更新，但本地 baseline/title/content 只在进入或 attempt 时 restore；未编辑时 dirty=false，因此无新修订提示，仍显示“最新正文/已同步”，导出及飞书 content 取旧 baseline，revisionId 却取新的 note.revision。App 详情只在 id/attempt 时 getNote，前台同步更新 libraryRevision 也未触发详情重读。

**用户影响：** 用户以为在看最新内容，实际阅读/分享旧正文；桌面版本标签与提交的正文可能不一致。服务端是否拒绝飞书该快照另需实机核验，本报告不声称它已发布错误版本。

**建议：** 无草稿时按新 revision 原子更新正文、标题、证据和动作快照；有草稿时保留并提示比较。App 订阅 workspace 修订；导出/发布须绑定实际正在查看的 revision/version，不能混用实时 note 与旧 baseline。

**验收：** 两端详情保持打开，另一端编辑后，界面明确更新或提示；导出/发布正文与显示修订相同；有草稿不被覆盖。**未验证。**

### 7. P2：App 返回列表丢失搜索、筛选和滚动，会议子页的系统返回不一致

**位置：** `VINote-app/App.tsx:65-75/128-131/158-164`、`VINote-app/src/screens/NotesScreen.tsx:39-45/92-106`、`VINote-app/src/screens/FileLibraryScreen.tsx:18/41`。契约见 `docs/plans/2026-10-11-workspace-v3/navigation-final.md:50-55`。

**具体触发：** 在笔记或会议搜索、选归档/项目、滚动后打开详情再返回。根组件条件切换卸载列表，本地 useState 和 FlatList 位置重新初始化。文件库打开录音页面后同样重新挂载。手机主“会议”页按 Android 返回会进入根 handler 的默认 notes，而“笔记”页通常允许系统退出，二者作为同一主区的子页行为不对称。

**用户影响：** 连续核对多条内容反复重新定位；页面返回名称虽正确，上下文没有恢复，系统返回也不能稳定表达上级。

**建议：** 按 owner+目的地持有 query/filter/project/scroll/选中行，或保持主列表挂载；统一定义主区子页的 Android 返回规则，并覆盖任务、录音、设置上下文。

**验收：** 搜索+归档+第 N 行→详情→标题返回/系统返回均回相同筛选和位置；文件库类型筛选、项目上下文及登录切换不串状态。**未验证。**

### 8. P2：桌面 PDF/DOCX 直导入与文件库原件生命周期未闭合

**位置：** `frontend/src/pages/NoteGenerator.tsx:241-267`；`app/routers/note.py:678-692/1024-1044`；`app/services/local_file_service.py:69-75`；`frontend/src/pages/FileLibrary.tsx:101-103`。对照 App `VINote-app/src/screens/NoteIntakeScreen.tsx:84/103`。

**具体触发：** 桌面从笔记入口直接导入 PDF/DOCX 生成。该路径不调用 `/api/files` 注册原件，后端提取 bytes 为 text，任务仅保存 document_text.json；没有注册可管理的 PDF/DOCX 副本。反向先导入文件库时 PDF/DOCX 的 can_generate=false，页面只有保存/导出说明，无法选这份既有原件直接整理。App 来源入口已先保存为 LocalFile。

**用户影响：** 桌面“导入文件→文件库保留→后续整理/关联内容”的用户契约断开；生成失败或需要重新导入时只能自行寻找原路径。**不意味着用户磁盘上的原文件被删除，也不否认当前 PDF 生成成功。**

**建议：** 桌面先按 owner 注册保留原件，再从该 file id 发起生成并关联 note/task；文件库对 PDF/DOCX 提供同一整理流程，详情显示真实可用性。若不保留副本，应在导入前明确该限制，不能把它呈现成文件库已管理的原件。

**验收：** PDF/DOCX 直导入和文件库导入都能找到同一原件及结果；生成失败原件可导出/重试；显式删除原件后正文、历史、跨端内容保留。**未验证。**

## 三角色整产品契约补充（2026-10-12）

产品角色已明确同意导航不变、文件/正文/发布状态独立、普通用户 OAuth 与管理员公司配置分工，以及未知 POST 风险单列；设计角色提出的同一生命周期、容器层级和返回契约与本架构审查一致，双方已直接沟通。下表是统一开发与验收基线，**不表示表中缺失能力已经实现**。

| 域对象 | 唯一入口与责任 | 状态机/失败边界 | 普通用户与管理员 |
| --- | --- | --- | --- |
| 来源/原件、录制会话 | 会议与笔记发起获取/录制；文件库管理本设备原件，类型为页内筛选 | 采集中→本机持久保存→可整理；取消/错误释放资源，保存失败不进入生成；原件与文字独立删除 | 用户管理本人设备原件；公司管理员不因此获得原件访问权 |
| 来源任务/提交回执 | 任务与恢复承接唯一持久任务；来源入口返回同一任务 | reserved→accepted→处理成功/失败；未知回执先核验原 operation/task，不创建新提交或自动重放副作用 | 用户查本人任务；管理员配置服务能力，不能冒充用户任务 |
| 内容/版本/证据 | 会议与笔记列表→详情→版本；项目/归档/回收站在内容区 | 草稿→待写→确认同步，或失败/conflict保留草稿；正文、导出、发布须绑定同一查看修订 | 用户编辑本人内容；版本不可覆盖，跨设备修改不提升草稿 CAS 基线 |
| 附件/同步 | 内容拥有附件引用；文件库拥有设备原件；同步设置统一管理 | 本机附件→上传确认→正文确认；失败不伪称 synced；签名到期重新鉴权，历史附件权限按 owner | 用户只能读本人获授权附件；管理员维护私有存储，不能使原件成为公共附件 |
| 飞书/MCP 连接与外部交付 | 插件管理授权/默认偏好；详情确认某版本发布；任务入口核验未知副作用 | configured、本人 connected、目标可发布、文档已创建/写入、权限已确认、消息已通知各自独立；未知不自动重发 | 公司管理员配置应用一次；成员分别 OAuth；工具调用服从原有 grants/确认，不扩大权限 |
| 归档/删除/恢复 | 内容区菜单与回收站；原件删除在文件库 | 共享正文软删→已确认 tombstone→新操作恢复；待写/conflict先处理；未知删除沿原操作核验 | 用户删本人内容不删原件/飞书文档；无可靠回收路径的本地无 mapping 删除禁用并提示先同步 |
| 账号/设备会话 | 头像管理账号；设置管理设备/模型/存储 | 本端退出→清本端会话与可见状态；不撤销另一设备；切换 owner 丢弃旧异步结果，不跨账号回写 | 普通退出不是全设备撤销；没有实现的设备撤销/账号注销不得用按钮替代 |
| 前后台/返回/弹层 | 既有全局任务入口；真实父页返回，同任务在同容器推进 | 前台查任务/拉取修订/有界刷新；后台不承诺常驻；失败保留输入、筛选、版本、operation；危险确认前收起菜单 | 同一契约覆盖两端；焦点、系统返回、进程重启实际行为仍需实机证据 |

**公司应用默认的最小落地：** 现 `app/services/feishu_application_service.py:14` 已支持本人应用覆盖后回退服务端 settings。部署管理员一次配置用户选定的 existing 公司应用，普通成员沿此默认各自 OAuth；CLI 仅辅助管理员核对应用，不复制 CLI 或其他成员的 user/refresh token。没有已验证管理员 RBAC 时先采用部署配置，不能把现仅修改本人 owner 的 `/application` PUT 变成任意成员的公司配置写入口。状态建议返回 source(company/owner/none)、ready、can_manage 及非秘密应用/组织标签；普通页首要动作是账号连接，高级配置必须同时满足后端权限，不能仅折叠表单。

OAuth state 与个人 connection 应绑定 app_id/tenant/配置版本；回调和刷新拒绝跨应用旧绑定。不同应用/组织切换清对应 tokens/state/旧 open_id/name、更新 connection_id，重新核验位置/群，已有文档保留，未知交付不能在新连接下自动重跑。当前 `save_application`/`clear_application` 仅清 tokens 而保留 open_id，仍有换应用后旧身份触发 409 的风险。相同应用转为公司默认时须核对应用/组织/回调/范围并保持兼容本人 OAuth，不能无故破坏刚完成的连接。上述为主代理待实现契约，本审查未修改飞书文件。

**最新飞书事实更新：** 按用户/主代理最新实机事实，所选已有应用匹配，个人 OAuth 自动刷新后桌面“阳晓冰”已连接，并已实际完成私人文档 create/write/permissions。组织浏览器提示上级/组织访问策略仍适用，因此这些成功不证明只有本人或所选接收人可读。接收人阅读、消息通知、多成员默认继承及换应用恢复仍未验证。本架构角色没有自行调用或操作飞书。

**source POST P1 本地模块与路由交付：** 用户先授权新增 `app/services/source_request_service.py`、`app/models/source_request.py`、`tests/test_source_request_receipts.py`，以及 `app/db_models.py:20` 的 SourceRequestDB，随后明确移交 `app/routers/note.py` 路由集成写权；路由现已完成并释放。owner+operation_id 复合主键选出唯一登记者，同输入返回同一 task_id，不同输入/输出选项返回 409；上传身份须由服务器 type/size/SHA-256（含名称）或经 owner 核验的 retained_file_id+不可变版本构成。仅保存指纹、task 与最小回执，不保存来源正文/密钥。reserve 的 created=True 是首次排队资格；reserved 中断后可查但不自动再排队。accept 只确认提交，不代表生成成功。带 `X-VINote-Operation-Id` 的文档网页/PDF/DOCX/TXT 分支复用原回执，鉴权 GET `/api/source-requests/{operation_id}` 只查询本人记录并 no-store。没有 header 的历史调用保持兼容。

模块定向回归 **26 passed**；路由接入后串行运行 `tests/test_source_request_receipts.py tests/test_local_files.py` 为 **41 passed**，包括并发同/不同输入、重启复用、落盘失败、身份隔离、文件指纹、回执不可覆盖、URL/上传/保留文件重复请求不重复派发及 GET 鉴权/无副作用。仅本地临时数据库与模拟服务。产品角色另报告来源客户端 29 项聚焦回归与双端类型检查通过；这属于角色交接证据，不是本人执行。公网部署与实机未知回执恢复尚未验证。音视频/逐字稿分支、原件 `/api/files` 首次注册未知结果不在此次覆盖范围，也不宣称后台排队或 LLM 完整 exactly-once。

**仍缺失：** 发布版 App 公网 generation Origin 仍未配置；此次代码与客户端定向通过不能消除该发布限制。source POST 未覆盖的分支与公网恢复仍是明确边界。summary 图片上传、完整可视化/交互不得凭有入口或代码围栏认定完成；本次仅落地下面的受限流程图。不得通过移动入口、改文案或折叠配置冒充能力已经实现。

### 限定流程图与真实 MCP 翻译：最终交付边界

两端新增 `lib/simpleFlowchart.ts` 导出 `parseSimpleFlowchart(source)`，返回 `{ok:true,graph}` 或 `{ok:false,reason}`；桌面 `components/Markdown/SimpleFlowchart.tsx` 与 App `components/SimpleFlowchart.tsx` 均 named export `SimpleFlowchart({source}:{source:string})`。source 是 Mermaid 围栏正文。只解析 TD/TB/LR、最多 20 节点/40 边的单链/分支/汇合 DAG，源码最多 12000 字符；环路、超限、未知语法整图降级为原因与完整源码，不截断成误导图。React 构造真实 SVG 节点/有向边，App 使用原生 View/Text 与计算边；没有模型 SVG、HTML 执行、WebView 或新资源请求。禁止 init/click/style/subgraph/外部资源；支持展开、双向可读滚动、文字关系替代。无确切证据的节点不假装可跳转。

桌面解析/组件 **20 tests passed**，App 解析/组件 **20 tests passed**；两端 `NODE_OPTIONS=--max-old-space-size=512 npx tsc --noEmit` 通过，串行检查。主线程负责现有 Markdown 渲染器接入，随后报告 App tsc 通过。实际 PDF 图形、Tauri/手机滚动、读屏与恶意/不支持语法显示仍待主线程实测。此安全边界仅涵盖流程图 AST，不代表全产品既有 Markdown 远程图片、上传附件或后端 URL 下载已额外获得全面 SSRF/SVG 安全认证。

**翻译纠偏以用户最新要求为准：** 翻译仅走真实远程 MCP 工作流，撤销此前内置 LLM translation 的 V1 交付范围。`content_plugin_service.py` 已从 catalog 删除 translation，拒绝启用、新 start 和历史 retry；历史 GET/结果保留，旧 zh/en/ja/de/unknown 语言不改标，缺少语言返回空串而非默认英语。diagram 保留跨 worker 首次插入仲裁与持久 lease token CAS fencing；过期旧尝试的成功/失败不能覆盖新尝试。get/start/retry 保留源版本/正文/标题/language/retry_safe，runs 列表不含源正文。最终 `tests/test_content_plugins.py` **16 passed**，仅本地数据库与模拟模型。

共同 MCP 合同：优先用户已有、真实发现并启用的连接/工具，实际工具名称与 definitionHash 来自 tools/list，不按名字猜翻译能力。用户明确选择实际 schema 的不同顶层 string 正文字段/目标语言字段；没有复杂组合或无法提供的其他必填字段。只向工具发送冻结版本全文字符串与 zh/en，不附 title、owner、版本 ID、URL、原件或附件。按实际 JSON UTF-8 字节校验 64 KiB 参数限制，同时保持产品 60000 字符上限；不静默截断/分块。工具定义/授权变化重新发现与确认，annotation 不授予权限。

在 POST 前按 owner 持久 requestId、连接/工具/参数映射、固定源正文/版本及保存用当前正文/revision baseline。复用现有 invoke 的 awaiting_confirmation→显式 confirmed+token→running→succeeded/failed/unknown/cancelled，确认显示真实外发正文、目标语言与服务来源。unknown、已派发失败、404、鉴权/网络错误不自动换 requestId 或重放工具；只有证实未派发且用户重新审阅确认才可能发新请求。工具成功后停用仍可读取历史，但不能再次执行。

为避免第一页 50 条漏掉原请求，既有 MCP router 增加 **GET `/api/mcp-connections/runs/by-request/{request_id}`** 和 **GET `/api/mcp-connections/runs/{run_id}`**，按本人 owner 精确查询，复用 principal/no-store/integration proxy，返回现有 flat Run。过期 running 保守显示 unknown，过期确认返回 failed 且不返回 token；GET 不写库、不发现工具、不调用远端。`tests/test_mcp_connections.py` **47 passed**，包含超第一页恢复、同 requestId 跨 owner、路由隔离/代理/缓存头、过期只读与连接停用后的成功记录读取；未调用真实 MCP。

父线程最终决定**不新增专用翻译保存 endpoint/ledger**。仅提取成功、isError 非 true、非 truncated 的非空 MCP text content 为纯文本 Markdown 预览；用户明确确认后走既有普通新版本/编辑与 workspace CAS 保存，保留源历史，收到同步确认前不称已同步。固定源版本与当前 CAS baseline 各自冻结；草稿或新修订冲突保留预览，不覆盖。这是用户核对后的普通编辑，不宣称服务端自动证明译文完整、事实准确或某第三方翻译服务已连接。现有入站 `/mcp` 只有视频笔记/样式工具；自建翻译 MCP adapter 理论可行但需要真实 protocol tools/list/tools/call、管理员部署/鉴权/服务来源与模型出网说明，不能仅包一层方法就冒充远程 MCP；本次不新增适配器或服务。

**飞书权限最小修正建议（未交叉写飞书文件）：** `app/services/feishu_service.py:746` 的 ensure_permission 实际只核验 `permission_public.external_access_entity` 和 `link_share_entity` 为 closed，`actual` 已返回真实字段。`access_scope=owner_and_selected_recipients` 与“仅向所选群授予阅读权限”不能表达实际有效读者范围。建议 private 改为 `access_scope=external_and_link_sharing_closed`，补 `verification_scope=public_sharing_settings`、`organization_policy_verified=false`；说明“已核验关闭组织外及链接分享；组织内部、上级与继承权限仍由飞书组织策略管理；接收人授权另行核验”。继承策略保留 inherited。保持当前权限操作范围，不新增 grant 或修改组织策略；status verified 应明确仅表示 public sharing 设置读回核验。主线程负责落实与 UI 文案，实际组织访问边界未由本人验证。

**客户端交接后的静态复核：** 产品提出的 App 四项风险已由本角色阅读当前 `MCPScreen.tsx`/`lib/mcpTranslation.ts` 确认并转交父线程，尚不计整改通过：恢复仍只扫描首 50 条且读持久 intent 后未立即精确查原请求；关闭 Sheet/切连接清 pending 后可能清掉持久未知操作；翻译仍允许 extras、未检查 UTF-8 64 KiB/未知必填，结果未拒绝 truncated；本地保存状态仅内存且“正在同步或已同步”无法证明云回执。必须分离 active intent 与弹层可见性、按精确 GET 恢复、严格两参数及非截断纯文本、持久保存目标/状态并仅真实 ack 标同步。客户端负责人修改，本角色不交叉写这些文件；桌面也须按同一合同核对。

**打包冻结：** 后端关键 API 已完成并交接，源 bundle 可由主线程打包部署；本角色没有执行部署、服务器操作、服务启动或真实云数据修改。公网 source/MCP/图工作流与两端实际恢复仍未验证，初审评分不自动上调。

**后续角色交接与真实证据更新：** 主线程报告已打包 review source（SHA-256 `[私有摘要已省略]`），包含内置 translation 目录移除及 MCP 精确 GET；此为主线程给出的标识，本角色未自行重新计算或验证 bundle 内容。后端冻结后本角色未再编辑后端。主线程已接双端 Markdown，并实机看到 6 节点/5 边流程图；随后由主线程收紧两端 AST 布局，实际图可见不代表所有图/大字体/原生滚动均通过。本角色不再写这两个 AST 文件。

设计角色随后交接桌面 Connections/MCPSettings 与恢复 helpers 已冻结：frontend tsc 通过，4 文件 44 项定向测试通过，最后 owner guards 后 2 个 MCP 文件 19 项复跑是前述子集，不累加。其说明包含严格两 string 字段、zh/en、JSON 字节限制、持久源/request、关闭不丢未知操作、成功停用历史可读、未知保存同 body/op 与版本核验、冲突保译文，以及内置翻译历史只读。这些是设计角色执行并报告的有限证据，本角色未重跑，真实远程工具仍未实测。内容入口沿 `/settings/mcp?mode=translation&note={key}&version={id}` 与 validated state.returnTo 保留上下文；父线程负责详情入口与 App，不由设计角色跨写。

手机出现 offline-known/旧缓存时，主线程已纠正 VILab 误归因：本角色阅读源码确认 fetchMe 已走 Supabase `/auth/v1/user`，未修改 auth。resume 的该 banner 来自身份核验前的非 401 异常；身份已核验后的同步/飞书错误不触发此分支。需要手机实际阶段/耗时/状态/code/requestId 或网络错误类型才能定位；健康 200/桌面写回执不证明手机 Supabase Auth 正常。保留离线缓存与未确认同步状态，不能把未定位 transient 写成已修复。

**公网部署最新证据（用户/主线程提供）：** review bundle SHA-256 `[私有摘要已省略]` 已实际部署成功；单 worker、1 GB 配置，manifest/数据库 schema/health/deploy 检查输出均通过。主线程另报告 App critical 整改后的 tsc/Jest 通过，并已接新公网 by-request GET。此更新替代此前“仅可打包、尚未部署”的交付时点描述；本角色没有操作服务器或独立读取部署输出，不把部署/健康通过扩充为真实第三方 MCP 翻译、源 POST 未知恢复或手机 Auth transient 已通过。后端自冻结起没有本角色新增修改，不需要因本角色另行重打包。

**metadata 与权限隐私边界：** 回执、manifest、错误诊断仅应记录必要的服务/阶段、状态、时间、操作或请求标识与非秘密版本信息，不含 token/secret、认证头、原件内容或正文诊断转储。source 账本存请求指纹与最小回执，不存输入正文；MCP 运行记录及 owner 范围的本机恢复快照会保存用户明确外发的正文/参数，这是业务数据，不能宣称“没有保存内容”，也不能将 AsyncStorage 的 owner 命名空间冒充存储加密。MCP 翻译不附加 title/owner/版本 ID/URL/附件字段，但原正文可能自带姓名、链接或其他隐私信息，确认须显示真实接收服务及完整外发参数，不声称正文已自动匿名化。账号权限只允许本人读恢复记录，退出本端不等于删除全部持久业务记录或撤销另一设备。

飞书 `permission_public` 的 actual 是分享设置读回 metadata，不是完整有效读者清单；接收人授权、组织管理者/上级与继承规则分别核验/管理，不能根据两项 closed 推导“仅本人”。本角色**未修改过** `feishu_service.py` 或权限 PATCH。最新父线程已实现并报告 focused test 通过：返回 `public_sharing_settings` / `external_and_link_sharing_closed` / `organization_policy_verified:false` 及真实组织继承文案，未扩大权限范围。本机 HMR 已生效是父线程证据；此前 SHA 的公网 bundle 尚不包含此修正，需随下一 adapter bundle 部署，不把源码修改写成公网已上线。

### meaningful 翻译 provider 的下一明确增量（研究合同，未实现）

用户再次纠正，“仅已有远程 URL/本轮不自建”不是用户的显式限制。当前手选 schema 是高级自定义能力，普通用户所需的可用翻译 provider 尚未交付。产品与设计已接受：普通流程选择真实 provider、zh/en 与固定源版本，真实 discover 后授权工具并确认本次外发，读取真实结果核对原译文，再按既有 CAS 保存新版本；不能以手填 JSON、编默认 URL 或给原内置 translation 换名认定完成。

本角色实际读取 [DeepL 官方 README](https://github.com/DeepL/deepl-mcp-server/blob/main/README.md)（旧 DeepLcom 地址重定向至 DeepL）：当前文档明确 Node 18+、必需 DeepL API key、stdio transport。工具 `translate-text` 参数为 text/targetLangCode，text 支持字符串或数组，文档说明 en→en-US、zh→zh-Hans。没有据此验证任何可直接注册的公共 HTTPS Streamable endpoint；现客户端不能直接接 stdio。DeepL 路线需要真实协议桥接、管理员提供 API key 与正式部署，union schema 的直接 UI 兼容性也不能先假定。

推荐下一最小方案是**VINote 云翻译·第一方 MCP**，同一现有容器新增真实 HTTPS Streamable router/service，不新增常驻服务或第三方身份。实现 initialize、notifications/initialized（202/204）、tools/list、tools/call，协议版本兼容现客户端；真实 tools/list 发布固定 `text:string`、`target_language:enum[zh,en]`、additionalProperties=false。两端已知第一方 manifest 可产品化这两个参数，普通用户免填 JSON；tool definitionHash 仍来自真实发现，定义改变清 grant 并重新确认。第一方直接使用 zh/en；只有后续真正的 DeepL adapter 才使用经文档核验的区域映射。configured、discovered、granted、可执行、结果成功分别来自实际状态，不能仅配置 URL 就显示已连接。

**最小认证规范：** server provisioning 创建 managed 第一方连接，固定管理员 HTTPS Origin/path 与 `vinote-session` 类型；通用 public create/patch 禁止伪造这种类型、替换它的 URL/token。当前本人经过 principal 验证的 Supabase Bearer 仅留在请求内存并传至固定第一方 endpoint，不写 MCP credential，不借用其他用户/CLI token，不传任意远程地址。继续现 HTTPS/DNS pin/TLS/禁止重定向和私网目标约束。initialize/list 也鉴权，但没有模型副作用。tools/call 还必须绑定现 generic invoke 显式确认后的持久 running run：adapter 核验 owner、managed connection/revision/definitionHash、tool、完整参数 fingerprint 与有效 lease；单独提交“confirmed”或 run header 不能作为授权。此 running 记录构成本次受限短期执行授权。

Adapter 以 (owner, run_id) 唯一 CAS claim 并持久最小 execution receipt；重复同输入只读原回执，不调用第二次模型，不同输入拒绝。外发后未知/进程中断不自动新 run 或再次 tools/call，提供本人只读 receipt 供核验。同容器 HTTP 自调用不得在 adapter 再取得 generic MCP 的同 owner network_slot，避免递归锁；模型在工作线程执行并复用单 generation slot，禁止阻塞事件循环或增加并发占用 1 GB 容器。需独立 model/router/service/tests，另明确审核现 MCP 路由、service 和 transport 的最小身份/本次 run 桥接；仅写新文件并不能使现静态 none/token 模式安全生效。

**provider 复用限制：** `workspace_generation.summarizer` 已支持本人身份与管理员固定模型 Origin，公网 identity=(cloud_owner,None) 路径只核验云模型/服务默认，不读取手机或桌面本机 local/custom mode/profile。因此可复用身份验证、Origin 与模型选择，但标签必须是 VINote 云翻译，不能声称沿用所有本机模型偏好。实际云模型可用性与调用身份仍需新 provider 实测。

不能直接把现 `_complete` 的字符串返回当成完整翻译证明：OpenAILLM/VILabLLM 丢弃 finish_reason；前者 timeout 300 秒且未显式关闭 SDK retries，云流式服务还有 transient 重试，现 MCP 总 deadline 是 40 秒。下一 adapter 应使用独立、禁自动重试的 provider 调用，保留真实完成/拒绝/usage metadata；截断、content_filter、缺失完整终结、空/超限或中断不标 ready/save。managed timeout 与只读 receipt 必须闭环，不让长文超时引出重放。正常完成也仅表示模型完成输出，不认证全文翻译语义/事实正确，仍由用户核对。原正文/链接/图片目标与所有历史版本保留，不重新抓取原件，不执行返回 HTML/SVG/外部资源。

本节已与产品/设计沟通；**只研究并修改当前报告，没有实现、部署或真实翻译 provider 调用**。已冻结 review bundle 与原 API 不受影响，当前 44 项桌面测试也不覆盖此新 provider；下一增量需要协议兼容/越 owner/确认绕过/一次 claim/失联恢复/截断与实际端到端翻译证据后才能计普通翻译可用。

**PDF App 实机纠正与编号口径：** 用户最新实际向下滚动已看到 6 节点/5 边交互验收图，目标 key `desktop-[个人标识已省略]` 的公网正文确已更新；首屏误判不能记为同步失败或本地遮盖的命中证据。本角色没有修改客户端。`workspaceStorage.ts:82-91` 用 `note.revision` 填 `workspace_revision`，用正文/标题匹配 versions 填 `workspace_version_id`；显示用 `version` 却仅计 `kind === 'generated'` 并 fallback 1，与 metadata、workspace revision 和所有版本序号均不同。新增 kind=edit 的图版本可已同步但仍 V1。最小建议由父线程选择：标签明确“生成版本”，或按当前选中真实版本在完整历史中的稳定序号展示；修订号单独标识，不能以分页 versions 数量或 blind revision 代替历史编号。

此前代码的条件性风险仍仅是静态审查：`notes.ts:33-38` 从 mapping.localIds 或 canonical workspace-id 解析 cache key，未使用 local.workspace_key；mapping 缺失且自定义本地 ID 已带 workspace_key 时可能 miss cache。缓存存在时依设备 updated_at 字符串选本地也可能遮盖；pending/conflict 保留草稿是必要契约。此次实机正文成功未证明触发了这些条件，不能以修编号之名覆盖未同步草稿或提升 CAS baseline。

列表 workspaceViews 与详情应共享相同的对象与草稿判定，真正排查时仅记录 key/revision/status/content 更新布尔值，不导出完整正文或 token。用户已证实该 PDF 新正文成功，当前事项收敛为编号语义建议，父线程负责客户端实施。

### 第一方真实翻译 MCP 新授权增量（源码已完成，未部署/未实测）

本节覆盖前文“研究合同、未实现”的历史状态：用户新增明确授权后，本角色已实现独立 `app/models/first_party_translation.py`、`app/services/first_party_translation_service.py`、`app/routers/first_party_translation.py` 与 `tests/test_first_party_translation.py`，并仅修改现 MCP service/router 的必要桥接。实际注册位置是 `app/__init__.py`，增加 import/include，已事先告知；没有改旧 content-plugin translation 实现或把它换名。原 receipt/direct GET 与旧 history 保留。产品/设计已收到同一接口合同；两端 UI 接入与实际部署由父线程负责。

- `POST /api/mcp-connections/first-party/translation` 仅接受 `{}`，返回 `{connection,provider}`。当前 owner 建立确定性唯一 managed 连接，固定真实地址 `https://supabase-vinote.orulink.ai/vinote-api/api/mcp-first-party/translation`，`authType:'vinote-session'`、`managed:true`、`providerId:'vinote-cloud-translation'`。不保存用户 token、不需要额外模型密钥；通用 create 禁止伪造 session 类型，managed patch 仅允许 enabled。configured 只表配置，不冒充模型调用成功。
- 独立 endpoint 实现真正 JSON-RPC initialize / notifications/initialized / tools/list / tools/call，兼容现 Streamable HTTP 协议版本。真实工具为 `vinote_translate_text`，参数仅 `text:string` 与 `target_language:zh|en`，正文最多 60000 字符且参数整体最多 64 KiB。工具定义来自实际 discover，grant 与每次 invoke 预览/确认沿用现服务，provider 注释不代替授权。
- Session Bearer 仅由已验证 principal 请求传入内存，只有固定第一方连接可收到；不是管理员/CLI 共享 token。tools/call 用原 running run ID 绑定 owner、完整正文/语言 fingerprint、tool definitionHash、connection revision、enabled grant、active owner 和有效 lease；独立请求伪造 confirmed 或 run header 不足以执行。Cookie 桌面沿现 integration proxy 获取本人 session，不能回退本机 profile/mode。
- 私有 `mcp_first_party_translation_receipts` 以 `(owner,run_id)` 复合主键确保唯一执行 claim。同输入重入只读原回执，不同输入 409；未知/过期/进程中断均不接管重放。新增表由 factory 导入后参加现 `Base.metadata.create_all` 及 cloud 同事务 RLS/revoke，实际 PostgreSQL 建表/权限仍须部署核验。无新常驻服务、后台模型重试或新任务调度器。
- 实际 provider 使用部署既有 `vilab_server_url` 的 `/v1/models`、`/v1/default-models` 和 `/openai/v1/chat/completions`，当前本人 Bearer，不继承本机 profile。模型来源准确标“VINote 云模型服务”，model/requestedModel 为已核验可用的服务默认 ID，reportedModel 只在真实响应提供时记录，否则 null；usage 仅实际返回的非负整数白名单，不虚构消费量。
- 单进程复用 workspace generation 的 1 个 slot，adapter 不再获取父调用已持有的 owner network_slot；工作线程完成模型请求，事件循环保持可处理同容器 HTTP 桥接。公网 TLS/DNS pin、拒绝重定向/压缩和私网目标、响应最多 1 MiB；无 SDK，实际请求每阶段只发送一次，maxRetries=0。provider 总绝对 deadline 90 秒（预检最多 15 秒），桥接 120 秒，socket watchdog 可终止 trickle；客户端先超时只查原记录。
- 仅 `finish_reason=stop`、无 refusal、非空且有界输出返回 `isError:false` 的 text content。截断、过滤、缺少完成字段、超限或异常不进入保存预览；外发后的不确定响应记 unknown。模型完成不等于语义翻译正确，仍需用户原译文核对。只处理显式文本，不取原文件、外部图片或执行返回 HTML/SVG。source 选择版本冻结与保存时当前 base revision 是两个对象，adapter 不写 workspace，保存继续由现客户端 CAS 与原历史完成。
- 原回执只读 `GET /api/mcp-first-party/translation/receipts/{runId}`；桌面 proxy 的允许路径兼容别名为 `/api/mcp-connections/first-party/translation/receipts/{runId}`。返回 runId/providerId/status/targetLanguage/model/providerDispatched/replayAllowed:false/result/error/createdAt/updatedAt。跨 owner/不存在均 404；客户端不能因 404 发新 POST。generic `GET /runs/by-request/{request_id}` 继续查原运行；若 generic unknown 而 adapter receipt succeeded，展示核验后的结果预览，不伪造 generic 记录已成功或正文已保存/同步。

**本地验证：** 串行 `.venv/Scripts/python.exe -m pytest tests/test_first_party_translation.py tests/test_mcp_connections.py -q`：**96 passed**（新 adapter 49 + 原 MCP 47），仅已有 TestClient deprecation warning。实际 protocol route + 确认链经离线 mock provider 测试；覆盖 zh/en/UTF-8 限额、origin、越 owner、伪造授权/地址、不落凭证、单 slot、重复/并发 claim、未知/过期回执不重放、模型 metadata、finish/refusal、TLS transport 绝对截止/重定向/压缩/超限/POST 中断。没有真实凭证、服务启动、部署或公网翻译调用。

**发布边界：** 已部署旧 SHA `[私有摘要已省略]` 不含此新增 adapter，也不含父最新 Feishu 声明修正；下一包必须重新打包。父负责 README/AGENTS 路由说明合并、部署新表/RLS、实际 cloud model availability 与 HTTPS 自调用、两端普通 provider 入口/grant/确认/完整译文/原 receipt 恢复/新版本 CAS 验收。本角色限授权文件与原报告，不改两端 UI、不执行服务器。第一方中英翻译目前只能记“源码完成且本地回归通过”，不能记“已上线/用户验收完成”。初审评分维持 6.8/10。

**冻结后的设计接口澄清（仅只读/文档，不改后端）：** desktop Connections/MCP 第一方专用 UI 不由本角色持有，需父分配唯一 UI 持有人，不能误以为后端冻结就是两端入口已完成。创建第一次返回 status=unverified，不能展示可执行；旧服务 404/405 说明尚不支持/待更新，503 provider_not_configured 说明云模型服务未配置，普通用户不填密钥。创建失联可先查本人连接列表，显式重试 provision 复用 owner 的确定性连接且不调用模型；这不允许对未知 tools.call 重放。已 disabled 连接重复 provision 不擅自启用，删除后主动重新连接重置发现/grant。

**最终打包交接与只读安全复核：** 后端持续冻结，不再修改关键 API。新包应包含三份 first_party_translation 的 model/service/router、现 mcp_connection_service/mcp_connections 必要桥接及 factory 注册，合入父负责的 Feishu 声明修正；新回归文件在 tests。本轮最终仅只读核对与维护报告，没有重跑测试、启动服务、接触凭证或执行部署，96 passed 仍是上述原串行回归证据。API handler 经过 principal、固定 HTTPS bridge、原 running 授权及复合 owner/run claim，generic token 模式不会获得用户 session；新表参加 factory-before-startup 的 cloud 建表/RLS事务路径，真实数据库权限需父部署核验。

App 版本最小建议收敛为“当前正文”，历史按钮叫“历史版本”，先去掉无法证明的数字序号；workspace_revision 若展示，明确“同步修订”，不是历史版本数。generated count 不含 edit/imported，分页与 legacy kind 缺失也可能不足，fallback 1 不能作为真实全版本编号。App 新图正文已由用户实证更新，本角色不修改客户端。

`providerDispatched:true` 是进入可能外发阶段的保守标记（在网络调用前持久化），不是远端收到了请求、已完成或已计费的证据；未知界面仍须“待核验”，只以完整成功回执进入预览。整体 Markdown 图片安全另有明确现状：desktop ContentImage 对非私有 attachment 引用会直接输出 img URL，ReactMarkdown defaultUrlTransform 允许 HTTP(S)；这与限 grammar 的安全 flowchart 是不同边界。该浏览器外部图片 GET 不等于后端 SSRF，本角色没有实测公网/私网图片请求或凭证泄露；不能把图 AST 安全回归外推成整个产品所有图片来源都已隔离。provider 自身只提交文本、不抓取资源；外部图片的联网/隐私呈现与 App 对应策略仍由客户端持有人进一步核验。

`MCPSettings.tsx:157-159` 当前实际支持 `/settings/mcp?mode=translation&note={sharedKey}&version={selectedVersionId}`，`loadDetail(note,true)` 拉全版本；执行冻结历史 sourceVersion.id/content 与当前 note.revision，来源版本和保存 CAS 基线独立。Connections 也传 version。但该指定 version 不存在时当前客户端静默 fallback default/first，因此不能声称无效历史链接仍保证固定原文。已向产品/设计提出最小 UI 修正：明确 query 含 version 但查无时禁止调用、显示版本不可用，并由用户显式改选；合法当前已读取历史 ID 可原样传，不暗换最新。本角色未改客户端，96 后端回归不覆盖该 UI 分支。

## 满分验收门槛与未验证清单

### 后端冻结后的全局产品剩余项（不新增代码范围）

产品最新只读收敛由本角色复核部分源码，仍不能将入口收敛或后端 96 回归等同全产品完成：

- **归档会议常规不可达，静态确认：** `Meetings.tsx:108` 固定排除 archived；`Notes.tsx:81` 在 project=all 固定排除 meeting，切已归档仍应用相同条件。未归项目的归档会议因此不在这两个普通列表内；这是筛选契约丢入口，不是数据被删。最小修复应提供实际可达的会议归档视图，或让统一已归档过滤涵盖会议；不复制笔记或恢复无关列表。父/产品负责入口，未实机验证。
- **App 处理历史缺 source-request 索引入口，静态与产品报告：** TasksScreen 当前加载 workspace/jobs 与 recording，未接 owner 下的 noteIntake URL/doc 原 operation 历史。intake 原 GET 恢复已存在，但 Account 处理历史缺定位链。采用 owner+serviceOrigin+operationId 的持久 intent/receipt 索引，映射已确认 taskId/workspaceKey；点击未知项只精确查询原回执，缺失/404 不新 POST、不自动重放。不得把 source-versionId 当 operationId 或保存 CAS baseline。
- **App 文件到已生成正文关联不足，静态确认：** `localFiles.ts:8` 的 LocalFile 仅存 id/name/uri/size/category/createdAt/extension；FileLibrary 文件详情有生成/原文另存/原件操作，未呈现已生成正文关联入口。建议在成功持久回执点保存 owner+stable fileId/retainedFileId+immutable version/input SHA → operationId/taskId/workspaceKey 的关系；一个原件可有多次处理结果，不能以 title/content 或设备时间归并成唯一笔记。未成功或索引未知时明确“未关联/待核验”，原件与正文删除分别独立。最新 Word 选择确认返回成功仅为父实机事实，未生成，不能证明关系闭环。
- **其他导航状态，采用产品角色报告、未实机验证：** App search/filter 仅 local state 卸载后可能丢失；同步状态条进入 Tasks 默认生成而非同步；桌面生产跨页 generation/sync 状态入口不足（dev SourceTaskProgress 不属于发布能力）；Settings/Tasks/SyncSettings 部分返回链接未保来源。实际 App 主次动作和 legacy files 深链代码已由父修复，应从未修列表撤下，不能重复指称当前仍坏。

MCP 第一方普通入口仍待客户端实现与新 bundle 部署/实测，当前 schema 参数映射高级流程不是普通翻译交付完成。产品/设计角色报告均已按“源码/本地回归”和“实际部署/实机”区分，本角色后端持续冻结，仅维护本报告与稳定对象建议。

### 最新独立授权：非会议完整模板修正与新部署事实

用户最新真实 App PDF→版本→生成发现 default minutes 目标仍是“完整会议纪要”。产品已明确确认会议来源 exact `meeting_recording|meeting_video` 才用“完整会议纪要”，其余合法 text/file/audio/video 使用“完整结构化笔记”，不按标题、taskId 或音视频形式推断会议，真实人物/决定/步骤等原文信息仍保留。PDF/Word/网页是产品来源名称，workspace API 当前仍使用合法 file/text 等原枚举，不新增假类型。

本角色仅按此次新增授权修改 `workspace_generation.py:299-309`：minutes 目标与既有 style 用同一个 is_meeting 判定，非会议目标为完整结构化笔记/style=detailed，会议为完整会议纪要/style=meeting。summary/actions、API 枚举、strategy、operation/claim/CAS/回执恢复均不改；第一方 adapter 文件仍冻结。新增 `tests/test_workspace_generation_claim.py:353` 18 个真实 generation→prompt→publication 定向用例，六种 source×三个原 template；标题含“会议”仍以来源分类，验证完整原文传模型、原历史保留、生成版本落库与同操作失联重试不再次调用。仓库已有自动 current/saved 历史快照，不把一次生成硬编码成历史总数 2；用稳定 version IDs/唯一 generated/重放总数不变判定。

串行 `.venv/Scripts/python.exe -m pytest tests/test_workspace_generation_claim.py -q`：**32 passed**（原 14 fencing + 新 18），该 service py_compile 通过。没有调用真实模型/启动服务/部署。模板语义修正已通知产品/设计/父，需进入下一包；App 文案改“完整笔记”与此后端行为都具备后才能记为该问题源码修正完成，真实重新生成结果仍待父验证。

**最新部署采用用户实证：** 新包 `1f9524…` 已公网部署启动、health OK（用户只提供缩写，不虚构完整 SHA），但父发现 cloud.env 原未配置 VILAB_SERVER_URL，provider.configured=false。父将既有非秘密固定模型 Origin `https://api.orulink.ai` 配入公开共享运行时并重启 compose，不复制管理员 API key；本人 Bearer 仍由原第一方桥接只在内存传递。本角色未读 cloud.env/凭证或执行服务器。配置存在、health 正常和 adapter 已部署都不等于模型可用/翻译成功；当前仅记配置应用中，实际模型与译文需 UI 执行验收。该已部署包不自动包含随后新增的非会议模板修正。

**客户端新增角色证据：** 设计师已按父分配完成 desktop MCPSettings/client type：识别 managed/providerId/vinote-session、真实 provision unverified、discover/grant/preview/confirm、unknown provision 只 GET、disabled 不擅启、错误待升级/配置及 owner 迟到隔离；显式 version 不存在不再 fallback，空源禁调用由用户改选。设计师报告 20 MCP UI + 9 helper 串行测试、WorkspaceNote 22 回归、frontend tsc 成功，本角色只读确认 MCPSettings 显式 missing-version 分支，不替代其实机验收；Connections:121 的 fallback 仍为剩余已知问题。父报告 App 普通第一方连接/discover/无自动 grant/固定字段中英预览已实现，5 focused MCP tests + tsc 通过，旧 note context render-null-tool 崩溃已修。这些不是本角色运行证据，也不是公网翻译成功；相应“尚无入口源码”旧状态由此最新记录替代。

**首次真实翻译执行失败的原回执定位：** 用户 App 实际 provision/discovery/grant=true 成功，synthetic PDF 确认一次执行后原 run `[个人标识已省略]` failed，structuredContent.error.code=model_unavailable，replayAllowed=false，usage={}；generic error=tool_error。这证明真实 MCP 链路已到 adapter，不证明模型或译文成功。源码 `select_model:151-164` 的两个预检 GET `/v1/models`、`/v1/default-models` 获得 JSON 后，只有 defaults.llm_model 为合法非空字符串且匹配 catalog 的 id/modelType=llm/runtimeStatus=available 才通过；该 code 不是 LLM POST 失败分支。原 receipt 的 model/providerDispatched 可进一步确认预检状态，父负责读原记录；本角色未访问云端/凭证，没有重放或假翻译 fallback。既有 VILabCloudService 使用同一两个 path、data 列表与上述两个字段；没有实际响应元数据前，不擅改字段、降级 available 校验或选第一条模型。

父可在已登录 Terminal 做无认证、无密钥的两次 HTTPS GET，只打印 HTTP 状态、顶层字段名、llm_model 与 id/modelType/runtimeStatus 白名单；若未登录请求被拒绝，记录拒绝，不能读用户 JWT/管理员 key 来冒充同账号可用。原请求 receipt 比无认证 health 更强；诊断未知响应之后再确定是否 API shape 兼容缺陷或实际默认模型不可用。当前用户指令是其余后端冻结，本角色仅只读诊断与报告；非会议模板的 32 回归修正仍未部署。

**新增上下文/恢复边界：** 设计新增稳定状态/错误/恢复槽，报告 desktop MCPSettings 23 tests + tsc 成功；父实机修复 App 操作 Sheet 帮助区域消失导致整体上移约 138px 的误触（固定状态/始终 footer 后稳定）。这些是角色/用户证据，不能外推完整像素与 native 验收。当前 App integrationOrigin 白名单不含 `/api/mcp-first-party`，canonical receipt 路径会落 generation Origin；App 原 receipt 应使用现兼容路径 `/api/mcp-connections/first-party/translation/receipts/{runId}`，已告知产品/设计，不改 API。

source intake 的 generationBaseUrl DEV=127.0.0.1:8900、production空；generate/upload/source-requests/task 均走该 generation Origin，cloud workspace factory 不注册 note.router。公开 workspace/MCP health 与实际发现成功不能证明 App 独立公网 source 生成可用。产品拟新增 owner+operation 档案 serviceOrigin 标记应在新提交前固定并持久，原 receipt/task 恢复沿相同服务；旧 unknown origin 只列待核验，禁止猜 Origin、跨服务 GET 后自动新 POST或把媒体旧链路宣称已去重。本角色只读确认合同，没有扩展 source 运行时或读 cloud.env。

**本人认证元数据诊断的新授权：** 用户实际无认证检查两个模型 endpoint 均 401，没有追加管理员 credential；这与原运行当前 session 的元数据成功后校验失败必须分开。用户随后明确授权本机既有 CloudAccountService 获取本人 token 仅内存、固定 https://api.orulink.ai 两 GET，严格白名单输出。本角色提供 `scripts/check_translation_model_metadata.py`：隐藏输入已知规范化 email，仅匹配唯一 User.id 并核对本人 CloudAccount，读取本人 active-cloud VILabPreference.llm_model；正常 CloudAccountService 获取/必要时刷新既有加密会话，不导出 token/refresh token、不保存临时 token 文件。只 GET 模型目录与默认模型，禁止重定向/环境代理，限定响应字节；输出 model IDs/runtimeStatus/默认/本人所选与 HTTP 状态，错误仅固定标记，不打印 email、userId、credential、异常正文或 header。隐藏输入不可用时停止，不退回可回显输入；目录显示前 100 但本人已选项校验扫描全部已取目录，不因显示分页误判。

新增 `tests/test_translation_model_diagnostic.py` **5 passed**（只测白名单/固定两 GET/拒绝不读 error body/异常不泄漏/选中模型超显示分页），script py_compile 通过；没有运行真实本人认证请求，因为本角色没有收到已知 email 值，父可在本机既有环境运行并隐式输入。未改 first-party 模型选择或其他后端。下一判断应先对照本人明确 cloud LLM 是否实际 available，以及 defaults 是否为空/失效；不能擅用第一条模型或复用本机 custom profile，也不能把元数据成功写成翻译成功。

**给产品列表术语方案的字段澄清：** version_count 是服务端 owner+note_key 下全部 WorkspaceVersionDB 行数，分页读回也保留 total，包含 generated/edit/imported 与 __vinote:current:/saved:自动快照，不是用户手动编辑次数；App cache 仅该次响应快照，不能保证当前云总数。限定不改 Note/storage 类型时列表先写“当前正文”，仅确认已落本机缓存才写“已保存在本机”；不写虚假 V1/云 synced/完整总数。view 快照仅 owner+kind+initialProject 下 query/project/archive/type 白名单；owner 切换先清 rows，异步结果同时校验 owner+epoch，取消/unmount/切换递增 epoch，防 A→B→A 旧回包通过相同字符串 owner；不持久正文或 JWT。该建议仅角色沟通，不修改 App组件/store。

### 新增独立授权：真实模型元数据确认与显式 owner 模型选择修正

用户已实际运行安全脚本，本人 selected_cloud_llm=`codex/gpt-6-luna`；两个模型 GET 均 200，`/v1/models` 的 data 有三项，`codex/gpt-6-luna` 与 `deepseek-v4.1-flash` 均 llm/available；`/v1/default-models` 的 llm_model=null。真实证据已确认原预检只认服务默认导致拒绝，不是已证实生成 POST 不可用。该实际 GET 由用户执行，本角色不持有或输出用户 token。

偏好来源已核对：VILabCloudService.status/select 的 VILabPreferenceDB 按本地 User.id 存储；public MCP principal 使用验证后的 cloud_owner，现无本地选择同步到该 owner 的偏好接口。不能读取共享服务同名表猜测本人偏好，不能修改所有用户默认，也不调用旧 VILabCloudService 的管理员 key fallback 或自动 chat retry。采用最小显式选择：真实工具 vinote_translate_text 新增可选 `model` ID，由客户端将本人已选且 catalog available 的 ID 预选，随固定正文、zh/en 目标语言一起预览确认并冻结。未传参数只接受 validated 服务默认；显式选项不存在/非 llm/非 available 时失败，不静默换默认或首项。实际调用前用当前 owner 的 memory Bearer 重读模型目录校验，不依赖本机 profile。

新增 `GET /api/mcp-connections/first-party/translation/models`，经现 principal 和 Cookie integration proxy；仅已建立本人 managed 连接可读。返回 `{providerId,modelParameter:"model",models:[{id,modelType:"llm",runtimeStatus:"available"}],defaultModel:string|null}`，只保留白名单合法 ID，不输出 token/原始 body/任意 metadata；no-store，默认配置为空/GET 暂不可用不抹掉可供显式选择的目录。与既有公开固定模型 Origin 相同，不接受 caller URL/key，也不进行模型 POST 或偏好写入。

模型参数加入完整 arguments fingerprint 与原确认绑定，省略参数保持原输入形状，不用 model_dump 的新默认键改旧 fingerprint。工具 schema 变化须重新 discover 并由用户重新 grant，旧工具授权不自动迁移。原 failed run `[个人标识已省略]` 仅查询；增加模型参数复用同 requestId 409，不能配置更新后自动重放。用户选择新执行时，须新 requestId 和新明确确认。

生产增量仅 `app/models/first_party_translation.py`、`app/services/first_party_translation_service.py`、`app/routers/mcp_connections.py`；`main.py`/factory/第一方 protocol route/通用执行 fencing 均未修改。不改客户端/飞书、不启动或部署服务。下轮完整 bundle 必须同时带已授权 `app/services/workspace_generation.py` 的非会议模板分支；相关回归在 `tests/test_first_party_translation.py`、`tests/test_workspace_generation_claim.py`，安全脚本及其 5 测试可随源码保存，不是服务运行依赖。父负责合入 README/AGENTS 的新增 route/schema 文档，不扩大本角色写入范围。

本轮定向串行验证：第一方 adapter 68 项（原 49 + 新 19）、通用 MCP 47 项、workspace generation template/claim 32 项，共 **147 passed**；前三个修改模块 py_compile 与定向 diff --check 通过。新用例覆盖真实 data/null 默认形态、显式选中非首项、无效显式不回退、无默认不取首项、旧失败不重放、变模型确认失效、schema 重新授权、owner 隔离/代理及 metadata 白名单。仍是离线 provider stub，不是公网翻译成功或部署证据；父客户端需实际提交 model 并重新发现/授权，否则旧省略参数仍因默认为空失败。本修正未部署，保持初审 6.8/10。

### 最新 46a3400ecd793816 部署与 first-party 最终只读复审

**时点说明：** 本节记录该部署后的首次复审快照；其中 App expectedOwner 保存风险与外链图片自动加载问题随后已授权修复并完成定向回归，不再作为当前未修问题。首次“译文/保存待回执”和下方横向“未验证”均不是对后续实机结果的否定，具体覆盖及剩余边界见最新小节。

采用用户最新实证：新 bundle `46a3400ecd793816` 已实际服务器部署，receipt/health OK、single worker/1 GB，包含显式模型选择与非会议 workspace generation 修正。用户只提供该缩写，不虚构完整 SHA。父 App models GET/explicit choice/重新发现与 grant 已实现并报告 7 focused tests + tsc；设计师 desktop 对应 schema/catalog/固定模型 args/原请求恢复报告 39 tests 通过，tsc 当时仍运行中。以上均标注角色/用户证据。本角色本轮只读源码、沟通与此报告，不运行服务、重测、凭证或真实模型请求，不修改冻结部署代码。真机新调用/完整译文/保存跨端可见尚等待父回执，health 不代表翻译成功。

**后端严重缺陷复核结论：未发现需解除冻结的新增重大缺陷。** principal 重新验证当前 Bearer，再派生 cloud owner；model catalog 仅本人 managed 连接/current-session 请求；不按本机 User.id 猜 public 偏好、不回退管理员 key。explicit model 与 text/language 进入完整原 args hash，选择变化原 requestId 409；执行前按本人可见 llm/available 校验，原 schema grant 不能自动沿用，新 schema discover 取消旧 grant。claim 的 owner/run 唯一约束、原 active-owner/lease/revision/grant 检查及外发前再次验证仍在；模型 POST 不重试，失败/unknown 原回执只查询。实际成功输出须 finish_reason=stop、无 refusal、非空 text，字节与时间受限；这不是语言质量/无遗漏事实证明。保存是用户另一次显式动作，服务不直接改正文或自动发布飞书。

**App 保存仍有一个 P1 条件风险，未实测发生：** `MCPScreen.tsx:224` 的译文另存调用 getNote/`editNoteContent(id,value,pending.source)`，未将原 intent owner 绑定到本地写入口。`notes.ts:75-84` 只读取调用当时账号 namespace 并检查其后未变化；content/revision baseline 不包含 owner。因此旧异步保存如果跨过退出/新账号登录，且新账号恰有相同 ID 与 content/revision 基线，可能在新账号写入旧账号译文，随后 persistMCPIntent(originalOwner) 才拒绝。这是源码允许的条件路径，不是已发生数据泄漏或服务器越权。建议父在 editNoteContent 加 optional expectedOwner（MCP save 传冻结的 intent owner），入口 namespace 必须匹配且写前再校验；MCPScreen 在 await 后/state 更新前加 owner+mounted/epoch 检查。已向产品转父，不交叉写客户端。

**桌面保存链静态通过：** `MCPSettings.tsx:932-945` 读取 owner+epoch 的 fresh detail，helper verifyMCPRun 校验原 requestId/connection/tool/完整 args；translationSaveBody 独立固定 source version 与当前 base_revision，并要求源 ID/content 仍在历史，持久化唯一 saveBody/operation ID 后走 workspace owner CAS，收到新 revision 与该 version ID/content 后才标 saved。冲突/未知保留译文，不再次调用工具。App 本地 history-first 与 content/revision 检查可保护普通并发云更新，workspace pending 保留 source workspace_revision、服务 CAS 冲突不晋升基线；App“已保存本机”不等于已云同步。实际多端保存/冲突仍未验证。

**仍需关注既有预览隐私边界：** App `MeetingMarkdown.tsx:37` → `ContentImage.tsx:28` 对非 attachment 引用直接 Image uri；桌面通用 Markdown 同样允许外链图片。模型/远程 MCP 结果的 Markdown 图片因此会在预览时产生外部 GET，不是用户另行点击的工具调用；固定后端 HTTPS/无 SSRF/安全图 AST 不会自动阻止该客户端行为。未实测外发或秘密泄漏。建议结果预览阻止外链图片自动加载或要求明确点击，私有 attachment 保留 owner 验证读取；不在本次后端冻结中擅自改渲染器。App model_unavailable 文案仍只提示默认模型，显式模型下线时应提示重选并读模型目录，而不是让用户只等默认恢复；这是 P2 文案，不影响后端拒绝安全性。

定义验收 10 分须关闭上述问题，并完成评分表中每项可复验的证据；不是修完代码或出现一张成功截图就自动给 10 分。每个场景记录端、源码/发布配置、版本、输入、操作、结果及截图/无敏感信息的回执，独立复审后才能重新评分。

还需验证下列横向场景：

- **账号与权限：未验证。** A 的同步/生成/附件读取正在返回时切换 B；B 看不到 A 的列表、正文、原件和待恢复任务。A 登回能恢复；共享 API 的未登录/跨账号请求被拒绝；401 刷新有界，502/503 不冒充登出。本次静态基础良好，没有证据声称已发生越权。
- **原生资源与弹层：未验证。** Tauri/Android 的录制取消、停止、错误、暂停恢复；原件播放失败/删除；Sheet 内选择再确认、取消后焦点回位、Android 返回、软键盘及大字体。iOS 没有本次运行证据，不能以 Android 或源码成功代替。
- **同步与附件：未验证。** 并发编辑、tombstone 与离线草稿相遇、历史版本证据、图片上传失败与签名过期、正文离线可读边界、全部版本分页。同步是定期/前台拉取，不应宣称实时订阅；原件不作为 workspace 附件上传。
- **飞书与 MCP：完整发布/异常恢复未验证。** 最新个人 OAuth 与私人文档 create/write/permissions 采用用户/主线程事实；有效读者范围、交付草稿返回、权限步骤失败、通知未知结果、多成员默认应用继承及换应用仍需验证。MCP 翻译真实工具/schema、确认执行、文本预览/新版本、远端 unknown 与重启精确查记录须独立验收，不能以有入口认定完成。
- **发布版公共能力：未验证。** 特别核验关闭电脑后的 App 内容读取、编辑同步与生成能力；本机服务参与的现有成功样本只作为该运行配置证据。

本审查交付独立初审评分、可定位问题和统一验收契约；#4/#5/CAS、source 回执与路由、受限图解析/组件、插件 fencing 与真实 MCP 精确恢复已有本地定向回归。公网与两端完整实机验收仍未完成，不宣称已达到满分；三角色沟通已按用户新增明确授权进行。

### 最新事实更新：2026-10-12 06:58:47 Word 成功回执之后

本节纠正上文历史状态，区分本角色运行的本地回归、父代理提供的真实验收与仍待验证事项；**初审 6.8/10 保留，不自动升分或宣称整体验收 10 分。** 本次仅更新本报告，没有编辑代码、运行测试、启动服务或执行部署。没有新增部署或发布版生成能力上线证据；之前 `46a3400ecd793816` 部署事实仍按原记录保存。

**App MCP 保存 owner P1 已实装修复：** `VINote-app/src/lib/notes.ts` 的 `editNoteContent` 已增加可选第四参数 expectedOwner，固定原 owner namespace，入口、异步读取后及每次写入前核验账号；保存历史在前、正文/CAS 基线核验契约保留。父代理 `MCPScreen` 已传冻结 originalOwner，并补 owner/mounted/epoch 守卫。前轮 owner 保存/列表聚焦回归及父集中验证已通过（父报告累计 48 tests 与双端类型检查；不是本轮 53 项组成部分）。A 切 B 且相同 note ID/content/revision 的条件路径已有定向回归，不应继续标为当前未修。真实跨账号退出/迟到保存完整实机矩阵仍待验收。父此前报告真实 MCP 英文翻译成功且原 DAG 保留；不将旧 failed run `[个人标识已省略]` 改写成成功或自动重放，也不由单次成功推出翻译质量及所有保存冲突已验收。

**外部图片 gating 与 owner 来源图片已实装并测试：** 两端 `ContentImage`、桌面 `MarkdownContent`/App `MeetingMarkdown` 及 MCP 预览调用已接入契约。外链默认按每张图显示 alt/真实 hostname，显式“加载图片”后才发该图请求；失败提供 inline retry，保留 Markdown 正文。`attachment://` 继续原 owner 鉴权，不改成公共外链。App 受控来源截图只接受固定 generation Origin 下严格 UUID 的 `/api/task/.../artifacts/screenshots|media/...` 图片路径，先 owner 核验、受鉴权下载到本人设备缓存后展示；不放开任意相对路径、外站或原始 file URI，不向外站附 Bearer。该路径不是云端原件同步。此前本角色桌面聚焦 48 项、App 图片相关聚焦 36 项通过；App 当时 tsc 的父录制文件错误随后由父修复，本轮 App tsc 已明确通过。父对同正文重渲染 consent 保持的修正属于其后续实现，不能再沿用旧 remount 发现断言当前仍坏。

父提供的最新实际图片证据：browser/native/App 的外图 PNG 加载成功、404 失败后 retry 且正文保留均已走查；App fullwidth 图片布局另有 **31 tests + TS 通过**（父运行证据，不并入本角色测试数）。上述限定于这些实际场景；跨账号迟到图片、签名到期、大字体/全部外站 CORS 和 iOS 等未被这些成功样本覆盖，不写成全量通过，也不把外链默认自动 GET 继续列为当前缺陷。

**App localFile→operation/task→note 关联已实现、本地验证通过：** 新增 `src/lib/localFileAssociations.ts`、`formatDuration.ts`，修改 `noteIntake.ts`、`localFiles.ts`、`screens/NoteIntakeScreen.tsx`、`FileLibraryScreen.tsx`。只为真实 owner 目录中的实际文件建立关联，核对 metadata/大小，固定 operation 与 processing Origin，持久记录 prepared/unknown/reserved/accepted/saved；未知提交只恢复原操作，不新增 POST，不从旧名称/正文推断旧原件关系。保存成功后关联实际 source note；文件库用当前 workspace 映射查可用正文，点击时再次核验，删除/不可用正文不能沿旧关联导航。录音 42 秒显示 `0:42`，未知时长单独显示，包含超过一小时的格式边界。没有修改后端、RecordingsScreen 或根 App，没有把 remote task 当作本地录音访问凭证。历史无记录文件不补假关联；直接“保存原文为笔记”未凭空生成 operation/task，关联测试不宣称覆盖该路径。

本角色刚完成串行验证：`localFileAssociations`、`localFileLinks`、`formatDuration`、`noteIntake`、`NoteIntakeScreen`、`localFiles.intake`、`FileLibraryScreen.associations` **7 个测试文件、53/53 passed**；随后 `npx tsc --noEmit` **exit 0**，两项均 `NODE_OPTIONS=--max-old-space-size=768`，未跑全量测试/构建。先前四个文件库失败是测试序列化 ReactNode 的循环引用，已仅改 host 文本/回调断言并重跑通过，不隐去旧失败、不误称业务实现失败。用例覆盖真实文件与当前正文映射、unknown 不虚构入口/重发、点击时已删除正文、owner/Origin/文件指纹与并发状态保护、时长边界；模拟数据不替代真实 Word 关联走查。

**最新真实 Word 进度采用父回执：** App Word task `1b1d9101` 在 **06:58:47 明确 generation success**（仅提供此 task 缩写，不虚构完整 ID）；父正在从同一文件关联打开已有正文。生成成功已验证，**同文件→关联正文实际跳转尚待父完成回执**，不提前宣称关系闭环已全验收。此前父实走 App 原录音直达详情、硬件返回文件库；插件页唯一 MCP 管理入口及正文翻译说明可见。原件仍是当前设备文件，与共享正文/版本同步分开；本机或源码配置参与的生成成功不证明关闭电脑后的发布版公网生成。

| 横向验收域 | 本次更新后的实际状态 | 仍需保留的验收边界 |
| --- | --- | --- |
| owner/保存 | expectedOwner 与原 namespace 已修、本地回归通过 | 真实 A→B→A、退出时迟到写入/图片完整矩阵 |
| 图片/正文 | gating、受控 owner task 图片已修；PNG/404→retry 保正文已有父实机事实 | 签名过期、离线/大图、全部外站与 iOS，不扩大允许来源 |
| 原件/关联 | 53 聚焦及 App TS 通过；Word 已真实生成成功；原录音详情/返回实走通过 | 同文件关联打开正文正在验收；删除/重启/失败恢复完整实机矩阵；旧文件不推断补关联 |
| 录制/弹层 | 父已有 Android start→pause→取消 stop 仍暂停→返回/恢复→stop→明确 save 及原件播放/导出部分实证 | 不据此覆盖所有资源失败/取消释放、桌面 native 捕获、焦点/软键盘及 iOS |
| 同步/插件/公共能力 | 已有跨端正文成功样本、真实 MCP 英译及既有部署证据 | 并发冲突、未知远端结果冷启动恢复、多成员/组织权限、独立发布版公网 source generation；本轮无新增部署 |

评分维度、对象/入口/状态机矩阵继续有效；历史“未验证”按上述具体时点和覆盖更新，剩余未验项目不以缺按钮或单个成功样本冒充实现/满分。

**随后实际关联闭环回执：** 父已从上述同一 Word 文件点击关联笔记，实际读取本次生成的新正文，再通过 header 返回 Files；父 verification 文档已登记。因此上述“同文件→关联正文跳转正在验收”及矩阵对应待验项，在这个真实 Word 样本上更新为通过。该证据不外推到旧文件补关联、跨账号、删除或重启恢复，也不代表原件跨端同步。PM 确认正常状态的处理编号应折叠后，父实现 Sheet 子组件 `ProcessingDetails`，保留真实 processing state 与关联 note action，报告 **5 tests + TS 通过**；这是父实现/验证证据，仅呈现调整，无业务契约变更。本次本人只更新报告，没有修改代码、运行测试或新增部署；整体评分与其余验收边界不变。

### 本轮 CAS / 飞书精确回执增量（源码已写，等待父串行验证与部署）

App 合并入口为 `resolveWorkspaceConflict(group, merged, comparedRevision, expectedOwner, expectedOperationId)`，只提交用户实际比较的 revision；新 GET revision 不同或 tombstone 时保留原 pending/body/op 与合并草稿，更新比较快照并拒绝 PUT，不盲抬 CAS。用户明确重新比较更高 revision 可再次确认。

飞书新增 owner 隔离 GET `/api/feishu/deliveries/by-operation/{operation_id}` 与 `/by-id/{job_id}`，均只读且 no-store；owner+operation 唯一绑定请求 fingerprint/job，异输入 409，同输入查询原回执不安排新 worker。新增 `feishu_publish_receipts`、`feishu_write_batches` 两表，正文批次先持久 dispatching；unknown/中断 writing 禁止重写，confirmed 批次保留完成证据，只有明确失败批次允许重试。没有实现自动外部读回核验或自动解除 unknown，不能声称完整恢复已验收。

两端发布草稿按 owner+note+服务 Origin 保存冻结正文/version/revision/目标/权限/通知对象及原 operation；失联只查询原 operation/job，404/旧服务不支持继续冻结，关闭与配置往返不清除 unknown，不退 latest GET。新服务 status 明确 `publish_receipt_protocol:1`；客户端打开及提交前检查，缺失时拒绝新 POST/重试并提示升级。代理 status 透传远端能力，不以本机新版本冒充旧公网支持。

后端部署增量为 `app/models/feishu_destination.py`、`app/services/feishu_receipt_service.py`、`app/services/feishu_service.py`、`app/routers/feishu.py`；现有 init_db 已注册模型模块，云初始化保护新增表，不需 main.py 注册。须先本地聚焦验证、再由父打包/部署并核验 status/两张表/精确 GET。当前公网未部署此增量。本角色本轮没有运行 tests/tsc、没有测试进程、没有启动/重启/部署；新测试仅已写待跑。既有 53 tests/TS 证据不覆盖本轮增量。离线 tombstone+草稿恢复死锁、剩余历史批次 ACK 后 revision 变化覆盖风险仍须后续处理；整体评分保持初审 6.8，不自动改为满分。

### 最新增量：逐条本机策略与原操作回执（2026-10-12，源代码验证）
最终 PM 合同采用新内容默认 local-only，覆盖此前历史段落的默认同步建议。App 已实现 owner/Origin/canonical key 持久策略、显式允许、暂停后续发送与接收、原正文及已读历史保留、已发未知 pending 禁止重放、附件准备与晚结果/快照写入策略 epoch 防护；旧 mapping/cache 本身不授予同步，真实 ACK 签名/修订/原服务证据可延续。新 content_id 首存一次，旧 workspace_key 保留，真实不同 ID 不按标题/来源强合并。新 canonical mapping 额外保留已核实本机 recording 关系，云端 media_id 不授予原件访问。无效录制时间及恢复文件仅 mtime 情况显示时间未知；来源笔记可使用真实已有来源/提交时间与已生成标题，无新模型调用。
后端精确 GET /workspace/operations/{operation_id}?note_key=... 使用已有 workspace_operations，返回真实原 ACK revision；owner/key/op 不符或未查到为 404。GET 不执行、不返回最新正文、不解除未知锁。import-local 要求显式非空 keys 与 sync_authorized，阻止旧全量迁移。status 新能力仅表示设备本地策略协议，不替其它设备关闭。没有新表、数据库列或 main.py 注册。旧公网尚未部署这些新接口：可识别旧协议拒绝新写入；读取失败/身份门禁/缺少可核验响应只显示待核验，不误报需升级。
验证为 Node heap512/runInBand 串行的 15 个聚焦 suites、173 个不同测试用例及最终 App tsc --noEmit exit0；后端 tests/test_workspace_policy_contract.py + tests/test_workspace.py 共15 passed。组间重复执行不重复计数。覆盖默认无网络/无 mapping/无附件、稳定 key、不同同名 ID 独立、暂停保历史及旧操作、GET 404 冻结、读取晚到丢弃、旧服务与未知能力区分、owner 隔离、CAS 原基线、删除恢复不 replay、设备真实原件关系。未全量测试、未启动服务、未部署或操作手机，未执行清理。测试通过不等于两端实机或全产品验收，评分不自动升满分。
403 实际证据仍只限两次 /user HTTP403，尚未取得解析后的实际 code，不猜 expired。ApiError.details.code 已通过 fixed whitelist 接入匿名 stage/ms/status/code 日志，不输出账号/正文/URL/headers/token/raw message，相关回归通过。验证时默认 off；随后按人类明确授权临时改为仅 __DEV__ 开启，等待用户手动 retry 采证，父级接收日志后必须恢复显式 opt-in/default off。未扩大 403 刷新条件。
剩余边界：原回执 ACK 查询保持原策略及旧意图，不自动推进剩余版本/重新发送；后续恢复工作必须显式比较/确认。纯本机对象依赖 cloud key 的版本生成/工具另存尚不能假装已支持，不能偷偷开启同步。产品内可恢复本机清理入口尚未实现：须 owner+Origin 备份、同步暂停、保未知 operation receipt、保独立原件索引及媒体、清 legacy cache 回退入口，并持久 reset 抑制旧任务晚到回填；身份未核验时不声称云清理完成。父级独占清理与原件登记写集，本角色未删除任何当前账号数据。

补充时点：用户在临时 __DEV__ 诊断开启后手动 retry，父级窄过滤 logcat 未取得事件；不能据此认定 verifier 未执行或 JWT 已过期。当前 RN0.87 源码 setUpDeveloperTools.js 仅在 console._isPolyfilled 时通过 HMRClient 转发日志，现代 Inspector 具有独立 console 通道，Metro/logcat 非必然出口。随后已恢复 verificationDiagnostics 的显式 opt-in/default off，未改变 auth 403 刷新分类。用户授权同账号正常 sign-in，由父级/用户走正规登录；未使用密码、令牌或DevTools注入。原回执还需最小 ACK==base_revision+1 检查及负回归，现有测试绿不替代该项完成。App当前冻结，不操作手机、不清理数据、不继续并发测试。

认证分类最新修正（人类明确授权，测试待串行槽）：supabase 不再把 refresh 的全部400/401/403转成登录过期；仅 refresh_token_not_found/refresh_token_already_used/session_expired/session_not_found 精确 code 在这些状态下映射需要重新登录且保留 code。其它错误保留原 ApiError 实例、状态与 details；weak marker仅标识错误来自未分类refresh，无凭证/正文缓存，使 verifier 不把这种原HTTP401二次误判expired。fetchMe 仅原401或403 session_expired/session_not_found允许一次refresh，随后必须新/user200同owner才能verified；bad_jwt/禁用/权限/audience/无code不泛化。既有identity/Origin/epoch/signal/存储guard未改。auth.ts、supabase.ts、supabaseAuthCode.ts、sessionVerifier.ts与sessionGate.test.ts已落盘，新增36个参数化/流程用例，尚未运行本增量测试或TS；前173+TS证据属于修改前，不能挪作本次绿证据。诊断仍default off，实际旧403code仍未知，未使用用户密码、部署或清理。


## 2026-10-12：取消跨设备同步（最新用户方向）
本节替代上文同步策略。App会议与笔记由设备资料库管理：登录/前台/列表/保存不发workspace请求；integration边界拒绝所有/api/workspace路径，附件准备不下载或上传。原cache、pending正文/remaining版本/conflict转换为可读资料和历史；旧操作与baseline独立归档，不重放，也不猜未缓存正文。删除进入设置→存储的回收站，恢复保留ID/历史/原文件。详情直接显示编辑、删除、导出、分享；Auth/模型/Feishu/MCP仍通过既有服务与账号门禁。飞书新POST明确提交冻结正文，不用旧cloud version/revision替代输入。图表服务直接正文接口未接入，不能宣称新生成可用；旧结果可另存。
本轮串行Node512聚焦localOnlyLibrary/notesOwner/useTrustedSession/NoteDetailScreen共4suite31tests通过，App tsc --noEmit exit0；未操作手机、重启服务、清理账号或部署。此前refresh补丁仍停在待独立验证，不将本轮31tests混记为其验证。
