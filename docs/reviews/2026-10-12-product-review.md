# VINote 两端产品经理独立初审

日期：2026-10-12。角色：产品经理。范围：`D:/projects/VINote` 桌面前端与嵌套 `VINote-app` 的完整用户旅程、信息架构和产品边界。

**最新限定复评分：桌面 7.5/10，App 6.9/10，综合 7.2/10。** 详见文末当前证据复审；这是产品判断而非实机通过率，原生会议重复修复仍待重测、真实 MCP 翻译 provider 尚未交付。

以下初审段落保留当时快照；后续获授权的实现、OAuth 新事实、共同矩阵与 03:45 V1 检查项见文末补充。初审“仅审查/OAuth 未完成”不代表当前状态。

**初审实得分：桌面 7.1/10，App 6.6/10，综合 6.8/10。尚不满足完整两端 10 分验收。** 这是基于当前源码、产品契约和提供的真实结果作出的产品判断，不是实机通过率，也不是另外两位审查者的评分。主干采集、文档整理及跨端文字同步已有实际进展；主要不足是恢复入口、会议原件的可发现性、文件与内容的关联，以及跨流程返回。

## 审查边界与证据等级

- 只读取当前路由、页面、关联组件和必要文档；仅创建本报告。未修改业务代码，未回退脏工作区，未启动服务或测试，未操作浏览器、桌面窗口或手机，未读取 `.env` 或凭证，未发送线程消息。
- 主仓库 HEAD 为 `08b5902`，App HEAD 为 `0f698a4`；两者都有未提交修改。判断针对读取时的工作区，不能用这两个提交号代表全部被审源码。父代理仍在修改，复审应重新核对行号和实现。
- **用户提供的实际结果**：`python.org/about` 网页已生成笔记；桌面 PDF 成功并在手机可见；手机 DOCX 成功且 native 桌面可见、已同步；公共 workspace API 与飞书应用配置已部署。本人没有重放这些流程。
- **本次实际查看的截图**：`data/workspace-bundles/desktop-word-public-synced.jpg`，可见 Android 手机来源、已同步、正文与对话标签；这是当前 Word 展示的正向证据。截图正文中的“支持”“失败会保留”等描述属于笔记内容，不作为对应能力已验收的证据。
- `data/workspace-bundles/app-pdf-public-synced.png` 是旧截图，只用于确认当时 PDF 正文在手机可见；不据它判定现版本缺陷，也不推导其画面外的控件已正确。
- **飞书边界**：用户明确选择已有应用，并由用户自行选择；尚未完成 OAuth。配置部署不等于账号已连接，更不等于文档、权限与通知已交付。不得代选应用或为评分要求新建应用。
- **未验证**：原生录音/录屏权限、暂停和后台行为、磁盘不足、进程退出后的恢复、网络断连/未知回执、版本冲突、回收站跨端恢复、飞书 OAuth 与实际发布、真实 MCP 调用、账号隔离和退出后的恢复。本次不增加低内存电脑的运行负担。

导航责任以 `docs/plans/2026-10-11-workspace-v3/navigation-final.md` 为准；其中支持格式和 `docs/shared-workspace.md:42` 的“共享地址尚未切换”已落后于用户最新实证，不能覆盖网页/PDF/DOCX 成功及公网同步事实。登录文档、动态网页、扫描 PDF、冲突与离线附件等仍未因此得到验证。

## 维度评分与可验收 10 分定义

两端权重相同，综合取两端加权均值后四舍五入。评分同时考虑实现完整性和证据覆盖，未知路径不当作已成功，也不当作已发生故障。表内 10 分条件须有对应真实结果，修完代码或热更新成功不能直接升为 10 分。

| 维度 | 权重 | 桌面 | App | 本维度 10 分条件 |
| --- | ---: | ---: | ---: | --- |
| 信息架构、入口和返回 | 15% | 7.5 | 7.5 | 会议与笔记、文件库、插件、设置和账号职责唯一；类型是页内筛选；入口说明生成或仅保存；详情返回保留实际来源、筛选和阅读位置 |
| 笔记全旅程与文档边界 | 20% | 8.0 | 8.0 | 写笔记、网页/视频、PDF/DOCX/文字/音视频导入均有明确支持边界；成功保存、编辑、版本和跨端读取闭环；普通文档不出现虚构逐字稿/原音能力 |
| 会议采集、历史和纪要 | 15% | 8.0 | 6.0 | 保存原件即可在会议历史找到；未生成、处理中、失败、完成是同一会议的状态；只有明确选择生成才调用处理；暂停、取消、权限拒绝及重试保留原件 |
| 文件库与原件/内容关系 | 15% | 7.0 | 5.5 | 通用导入不擅自变成会议；来源文件可预览或说明限制、直接整理、找到关联内容；内容能回溯来源；删除任一对象的范围明确且互不误删 |
| 取消、重试和持久恢复 | 15% | 5.5 | 6.5 | 未知提交先核验；相同任务恢复不重复处理；离页、前后台和重启可从唯一任务入口找到原请求；取消与后台继续语义准确；保存失败不清回执 |
| 插件、飞书与外部交付 | 10% | 6.5 | 6.5 | 尊重已有应用选择，真实 OAuth 后正确显示权限；选择版本→授权→返回原交付草稿→文档/权限/通知有独立回执；MCP 授权、确认和未知结果均有实证 |
| 设置、账号与数据控制 | 10% | 6.0 | 5.5 | 账号身份/安全/设备与应用设置职责明确；定稿中的存储、隐私、关于及帮助能力实际可用；退出仅当前设备，待同步内容和录音被保护，数据发送范围可理解 |

计算：桌面 7.075，App 6.600，综合 6.8375。正文展示为 7.1 / 6.6 / 6.8。完整账号安全、登录设备、目录迁移和隐私偏好在导航契约中明确尚未完成；本报告不把占位说明当作实现，也不自行删去这些条件来获得“完整两端满分”。

## 用户旅程覆盖结论

| 旅程 | 当前证据与判断 | 验收状态 |
| --- | --- | --- |
| 登录、注册、找回密码、退出 | 两端有登录/注册流程，App 有密码重置入口；桌面退出提示待同步，App 阻止未保存录音时退出。账号页主要展示身份 | 源码审查；实际过期、离线登录和独立退出未验证 |
| 会议录制→保存→稍后生成 | 桌面 `Meetings` 将原件与纪要交给 `MeetingWorkbench` 聚合；App 结束后提供仅保存/生成选择，保存失败也有恢复提示 | 正向源码证据；App 返回会议历史存在问题，原生未验证 |
| 写笔记、粘贴链接、导入文件 | 当前两端 `ContentIntake` 已显示粘贴链接/导入文件，写笔记独立；生成按会议/笔记工作流区分 | 网页/PDF/DOCX 已有用户实证；父代理入口修改后的完整交互未验证 |
| 阅读→编辑→历史→再生成 | 桌面有本地详情和 workspace 详情，App 有版本/编辑/基于文字生成新版本；已有正文失败时保留的设计合理 | 当前 Word 展示已观察；版本恢复、冲突和全部编辑路径未验证 |
| 来源文件→关联笔记→删除/恢复 | 桌面文件详情有整理、关联内容及独立原件删除；App 本地录音可播放、导出、删除，通用文件链路弱 | 文件库关联与类别问题见下；双端删除/恢复未验证 |
| 飞书/MCP | 插件目录职责已建立；两端有授权/确认/运行状态；飞书可分别展示创建、权限、通知阶段，未知结果不自动恢复 | 飞书仅配置部署，OAuth/交付未验证；MCP 实际调用未验证 |
| 存储、同步、账号设置 | 文本/版本与设备原件分离，冲突和回收站有页面；App 设置明确生成时会向转写服务发送音频 | PDF/DOCX 双向可见有实证；其余管理能力未验证或未完成 |

## 优先问题（最多八项）

以下均为当前源码确认的产品断点或定稿能力缺口；具体实机复现均未在本次执行。P1 表示影响核心旅程或可能产生重复/失联任务，P2 表示可继续工作但破坏一致性、回溯或既定验收范围。

### 1. P1：首次整理任务的未知提交与跨退出恢复没有形成统一闭环

**位置**：`frontend/src/pages/NoteGenerator.tsx:199`、`:224`、`:264`、`:275`、`:288`、`:359`；`frontend/src/pages/Tasks.tsx:63`；`VINote-app/src/screens/TasksScreen.tsx:33`、`:65`；`VINote-app/src/screens/NoteIntakeScreen.tsx:95`。反证核对：`app/services/workspace_generation.py:255` 的 jobs 只列 workspace 文字再生成记录，不是首次来源整理的通用任务清单。

**触发**：桌面提交已被服务接收但响应丢失；此时回执尚未设置，错误页仍允许直接重试生成。或已收到任务号后关闭桌面再打开新会话；回执只写 `sessionStorage`，任务页也从同一处读取。App 当前任务可从入口草稿恢复，但全局任务页未读该草稿；终态时“更换来源”写空草稿，旧任务没有通用恢复入口。

**影响**：桌面用户可能重复花费处理资源或失去已接收任务的可见入口；App 用户看到“原任务保留”，却难以从任务页找到原首次整理任务。不能将离页可查询等同于跨重启持久恢复。

**建议**：首次提交前保存账号隔离的操作标识和来源摘要，服务按该标识核验/去重；桌面与 App 将所有已接收和待核验任务登记到持久任务账本，并由全局状态与任务页消费。未知响应提供核验，不直接重新生成；更换来源保留旧记录。验收应核对重试前后任务 ID 和处理次数，实际断连/重启目前未验证。

### 2. P1：App 文件库导入普通音频默认进入会议链路

**位置**：`VINote-app/src/screens/FileLibraryScreen.tsx:39`、`:41`；`VINote-app/src/lib/localFiles.ts:29`、`:38`；`VINote-app/App.tsx:139`（文件页分支）；`VINote-app/src/screens/RecordingsScreen.tsx:255`。

**触发**：从“文件库→导入文件”选播客、课程或访谈音频。调用未传 `keepAudioInFiles`，按扩展名转入 `importRecording`；打开后进入录音页面，主要处理操作是“生成会议纪要”。

**影响**：用户只是在保存资料，产品却替他选了会议目的；同一音频从笔记入口导入和从文件库导入得到不同对象及后续语义。当前笔记入口已使用 `keepAudioInFiles: true`（`NoteIntakeScreen.tsx:84`），这一正确边界尚未覆盖文件库。

**建议**：文件库默认将音频保存为通用来源文件，整理时按用户明确选择进入总结笔记；只有会议页导入或显式“作为会议处理”才创建会议记录。补核旧会议录音兼容，不能改变既有纪要归属。实机类别与生成结果未验证。

### 3. P1：App 会议历史漏掉已保存但未生成纪要的会议

**位置**：`VINote-app/src/screens/NotesScreen.tsx:47`、`:52`、`:99`；`VINote-app/App.tsx:158`、`:162`；`VINote-app/src/screens/RecordScreen.tsx:159`。对照：`frontend/src/pages/Meetings.tsx:423` 与 `frontend/src/components/MeetingRecorder/MeetingWorkbench.tsx:59` 已合并未完成原件和会议纪要。

**触发**：录制后选择“仅保存录音”，离开录音库，再进入“会议与笔记→会议”。该页数据来自 `listNotes()`，仅筛选会议笔记，不加入本机未生成录音。

**影响**：保存成功的会议不在预期历史入口出现，用户易以为未保存；需要到文件库再找。录音并未因此被删除，问题是历史与状态断层。

**建议**：App 会议列表按会议对象聚合原件和全部纪要版本，展示未生成/处理中/失败/完成，直接进入同一会议上下文；文件库只承担原件管理，不另建重复纪要列表。新建、仅保存、失败后再进入、生成成功后去重均需实机验收。

### 4. P2：App 通用文件只能绕回笔记页重新选择，缺少来源与结果互链

**位置**：`VINote-app/src/screens/FileLibraryScreen.tsx:42`、`:44`；`VINote-app/src/lib/localFiles.ts:8`；`VINote-app/src/screens/NoteIntakeScreen.tsx:84`。对照：`frontend/src/pages/FileLibrary.tsx:101` 有关联内容/整理动作。

**触发**：App 文件库已保存 PDF、DOCX、视频或笔记入口保留的音频，打开详情。页面只有导出/删除和“前往笔记页选择文件”的说明；没有把当前文件直接交给整理入口，也没有通用文件到笔记的关联元数据。通用音视频详情本身没有播放控件。

**影响**：用户重复寻找和选择同一文件，重新选择又复制原件；整理完成后难以从原文件找到结果，难以判断是否已经处理。现有 DOCX 成功证明整理入口可用，不代表文件库闭环已完成。

**建议**：提供“整理成笔记”并传入当前文件身份，复用现有原件；持久关联文件 ID、任务 ID 和笔记 key，允许一份来源关联多个版本/结果。内容详情提供来源设备和本机原件入口；音视频提供本机播放，文档不支持内嵌预览时给出清晰打开/导出动作。不得把此设备链接同步成另一设备可播放承诺。未实机验证。

### 5. P2：飞书授权/设置的返回只到页面，没有恢复本次交付草稿

**位置**：桌面 `frontend/src/components/Notes/FeishuDelivery.tsx:118`、`:132`、`:499` 与 `frontend/src/pages/FeishuSettings.tsx:193`；App `VINote-app/src/components/MeetingDetailWorkspace.tsx:514`、`VINote-app/src/components/FeishuDeliveryPanel.tsx:34`、`:48`、`VINote-app/App.tsx:159`。

**触发**：在内容交付中选版本、目录或通知对象，再去管理飞书设置。桌面链接没有携带交付上下文，设置返回固定插件页。App 关闭发布 Sheet 并切到设置，返回详情后 Sheet 不恢复；再次打开从默认设置初始化。

**影响**：授权前后的任务连续性丢失，用户需重选甚至可能选错版本/目标。连接配置职责正确，但本次交付的选择与默认设置不是同一份草稿。

**建议**：保存账号隔离、内容/版本绑定的未提交交付草稿，传递有效返回上下文；设置返回原发布步骤并重验权限，不自动提交。目录、版本或权限变化时重新要求确认。尊重用户自行选择已有应用；OAuth 尚未完成，当前只能确认源码断点，不能声称已发生真实误发。

### 6. P2：App 从详情返回会重置列表筛选和位置

**位置**：`VINote-app/src/screens/NotesScreen.tsx:39`、`:43`、`:44`；`VINote-app/src/screens/FileLibraryScreen.tsx:18`；`VINote-app/App.tsx:138`–`:159` 的条件页面渲染。导航契约：`docs/plans/2026-10-11-workspace-v3/navigation-final.md:50`。

**触发**：选择项目/归档/关键词并打开笔记，再返回；或文件库筛选录音后打开录音页，再返回。根组件切换页面后原列表被卸载，搜索、筛选是组件内初始状态，未恢复滚动位置。

**影响**：用户批量核对资料时反复搜索与滚动；从归档打开的内容返回未归档列表，容易误认为刚才的对象消失。

**建议**：按账号及页面保存搜索、项目、类型、归档与列表位置，详情携带实际来源上下文；恢复列表时丢弃已失效对象的定位但保留筛选。通过手机返回按钮、Android 系统返回和跨标签切换实际验证；本次未验证。

### 7. P2：桌面侧栏重复展开文件类型和插件子项，名称仍有漂移

**位置**：`frontend/src/components/Layout/Sidebar.tsx:44`–`:48`、`:90`；`frontend/src/pages/FileLibrary.tsx:90`；`frontend/src/pages/Connections.tsx:60`。契约：`docs/plans/2026-10-11-workspace-v3/navigation-final.md:26`、`:31`。

**触发**：展开文件库或插件。文件类型已在页内 Tabs 出现，却再以五个子路由展开侧栏；插件又显示飞书和“MCP 连接”，而目录/详情称“MCP 工具”。

**影响**：同一筛选有两套控制，侧栏被本应属于页面的类别拉长；两端一级结构相同但实际展开规则不同。不是发现了第二套 MCP 后端，而是一个功能多种位置/名称。

**建议**：侧栏仅会议与笔记分组保留会议/笔记两项；文件库和插件作为直接主入口，类型/连接选择在各自页面维护。MCP 统一名称。现有 query 和旧深链继续兼容。最新 Word 截图只展示收起状态，展开后的密度与点击行为未实机验证。

### 8. P2：完整设置/账号契约尚未交付，App 缺少关于与帮助入口

**位置**：`frontend/src/components/Settings/ProfileSettingsPanel.tsx:9`；`frontend/src/pages/Settings.tsx:158`；`VINote-app/src/screens/AccountScreen.tsx:35`–`:43`；`VINote-app/src/screens/SettingsScreen.tsx:8`–`:15`。契约：`docs/plans/2026-10-11-workspace-v3/navigation-final.md:18`–`:22`、`:65`。

**触发**：用户到账号管理安全/设备，或到 App 设置寻找版本、帮助、许可证及数据控制。现有账号主要是邮箱/身份与退出；App 设置没有关于入口，隐私主要为说明文字；目录迁移和安全会话也未完成。

**影响**：无法完成定稿中的管理旅程，遇到授权/原件问题时手机用户缺少就地确认版本和求助路径。这里是明确的能力缺口，不是声称现有会话接口失效；项目文档已坦诚记录尚未完成，不能把“有说明”计为满分。

**建议**：先补可交付的关于、版本、帮助/诊断和许可证；按定稿完成安全、设备、隐私和存储管理能力并验证，真实不支持的操作明确说明。登录事件只能作历史，不能冒充在线会话；隐私必须区分本机保存、处理上传与共享文本同步。若本轮明确缩小交付范围，应修订验收范围并称为该范围通过，不能称完整两端 10 分。

## 父代理正在修改的专项复审门槛

不将以下工作重复列成第九、第十个优先问题，也不假定已完成。

1. **笔记入口**：当前源码已有粘贴链接/导入文件，且说明将生成总结。父代理需实机核对两端“写笔记”“粘贴链接”“导入文件”不让用户误解为单纯归档；与文件库同名导入的不同结果应在入口/下一步清楚表达。网页链接不应暗示任意需登录在线文档都支持。
2. **普通文档详情**：`NoteEditor.tsx:293`、`MeetingDetailWorkspace.tsx:79` 已见文档/文字分支，当前桌面 Word 截图也无逐字稿标签；仍需检查全部页面和操作菜单。特别是 `VINote-app/src/screens/NoteDetailScreen.tsx:172` 只看 `task_id` 就显示“原录音与重新生成”，不能用服务任务 ID 冒充本机录音 ID。父代理正在处理这一类问题，完成后以实际菜单及来源分支重新判定。
3. **跨设备媒体**：桌面来源 PDF/Word 在 App 仅应显示来源信息、正文/版本与合适操作；没有音频就不提示“原音在桌面”。笔记入口音频可以具有真实转写证据，但本机媒体访问应匹配来源文件，不能因为不是会议而丢失已有证据。

## 完整两端 10 分的验收清单

“10 分”定义为上述七维度条件在约定支持范围内全部通过，并且八个优先问题有关闭证据；不能用本报告、修复声明或一张成功截图替代测试。本人本次只审查，以下交由持有实机的父代理/验收者执行。

| 验收组 | 必须观察到的结果 | 当前状态 |
| --- | --- | --- |
| A. 导航与入口 | 两端从会议、笔记、文件、插件、设置/账号进入和返回；筛选/位置保留；链接与文件入口语义清晰；没有重复管理位置 | 源码已审；完整实机未验证 |
| B. 文档和笔记 | 两端分别写笔记、整理公开网页、PDF/DOCX、文字与音视频；选错格式/扫描或登录来源时明确失败；成功保存后编辑和查看全部版本；普通文档无空逐字稿/原音操作 | 网页、桌面 PDF→App、App DOCX→native 桌面已有用户实证；其余未验证 |
| C. 会议与原件 | 两端录制保存、仅保存、稍后生成、暂停继续、取消、权限拒绝和保存失败；会议历史立即可见；重复生成聚合到同会议；原件仍可播放/导出 | 未验证；App 列表/归属问题待闭环；App 不支持录屏应如实说明，不伪造能力 |
| D. 文件与内容 | 从文件库导入音频不强制会议；已保存文件直接整理且不重复复制；来源/结果互链；删除原件保留文本版本，删除内容保留原件；回收站恢复跨端可见 | 源码边界已审；实际删除/恢复及互链未验证 |
| E. 失败与取消恢复 | 提交响应丢失、查询断网、保存失败、换来源、重启、账号退出再登录均保留原请求；全局任务页可找到；重试 task ID/操作 ID 不变化，无重复生成或外部发送 | 未验证；任务入口和持久回执问题待闭环 |
| F. 双端同步 | 双向编辑、版本、项目/归档、冲突、回收站、附件失败；电脑关闭后手机仍访问公网内容；已同步只在服务持久回执后出现；不同账号不可交叉读取 | 双向文档可见/桌面 Word 已同步有实证；其余未验证 |
| G. 飞书与 MCP | 用户自行选已有应用→真实 OAuth→连接状态/权限→原版本草稿恢复→确认文档/权限/通知回执；仅失败步骤恢复；MCP 每工具授权和实际确认，未知结果先核验 | 应用配置已部署；OAuth/交付、真实 MCP 均未验证 |
| H. 设置与账号 | 实际查看模型选择用于下一任务、存储/隐私/版本/帮助；账号安全和设备管理按定稿可用；退出仅此设备并保护录音、草稿和待同步，重登原账号恢复 | 源码部分存在；完整能力未完成/未验证 |

每组记录端别、实际使用版本/工作区快照、步骤、结果和时间；必要时附截图及脱敏的任务/版本/回执标识。失败路径需保存前后对象和请求对应关系，不能只截“成功”提示。不记录凭证，不要求为验收发送未授权消息。

**复审结论规则**：当前只能维持初审 6.8/10。父代理修复入口和文档详情后，应更新相关判断；其余源码问题、未实现能力及未验证路径未关闭前，不给完整两端满分。已部署与真实成功结果应如实保留，也不得因旧文档重新判成尚未接通。

## 2026-10-12 限定实现与三角色共同验收补充

本节为后续获授权的限定实现与新事实，取代前文“本人只审查”的本轮工作范围；保留初审得分：桌面 7.1、App 6.6、综合 6.8，不因代码完成自动加分。

文件闭环已修改 `local_file_service.py`、真实路由 `files.py`、`note.py` 的独立文档 upload 分支、`FileLibrary.tsx`、`NoteGenerator.tsx` 的原件注册调用、`test_local_files.py`。PDF/DOCX 可先按 owner 注册原件、传 `local_file_id`、文件库同文档发起生成，同选中文件复用 ID；失败仍可导出原件，删除原件保留正文与版本。原有 task lease/reuse/checkpoint 保留；文件库回执使用 localStorage。21 项小范围 pytest 通过（临时数据库、合成文件、模拟 worker，未调用云端；阻止 dotenv 加载）。首次 POST `/api/files` 注册的未知回执尚无服务端去重；不能以同 task 重试宣称全链幂等。

删除可发现性已修改 `frontend/src/pages/Notes.tsx:101`、`:273`、`:320` 与 `VINote-app/src/screens/NoteDetailScreen.tsx:86`、`:99`、`:135`、`:231`。桌面行更多菜单独立于打开按钮，App 顶部更多有“操作”文字，使用现有确认组件/接口。确认共享 tombstone 才退出或移除，未知结果保留目标，沿用既有同步恢复；原件与已发布飞书文档保留。App 从真实 mapping/cache 识别共享对象，即使 UI 对象缺少 workspace_key；普通文档无原录音菜单。未同步本地正文没有可恢复删除：桌面仓库 DELETE 会永久删除版本/正文，App 无 mapping 分支会 removeItem 正文/history/outbox，因此页面禁用此分支并明确先同步，不伪造本地回收站。桌面 6 项 Vitest、App 4 项 Jest 通过，两端 `tsc --noEmit` 通过；串行、512MB Node 上限、未重建。删除/恢复实机待主代理核验。

三角色已直接对齐：导航保持会议与笔记（会议/笔记）、文件库（类型页内筛选）、插件、设置、头像账号。原件归文件库，正文和版本归内容，长任务/未知结果归既有恢复入口，授权与默认偏好归插件，具体版本发布归详情。失败保留输入、版本及原操作；同步成功不等于发布成功。飞书公司应用只由真正有权限的管理员一次配置，普通用户各自连接账号；高级折叠不是权限边界，CLI 仅管理员辅助，不能共享 user/refresh token。

| 全产品环节 | 共同达成/当前证据 | 未达成或未验证 | 负责人 |
| --- | --- | --- | --- |
| 获取内容与录制 | 来源/会议边界已共识；公开网页、PDF/DOCX 成功有用户实证 | 完整权限拒绝/取消/离线/仅保存/暂停后时间、native B站入口复核未验证 | 主代理实机；产品判定边界；设计入口 |
| 设备原件→生成 | PDF/DOCX 注册与复用、失败导出/删除不伤正文：21 pytest | 当前设备完整互链/真实导出未实机；首次文件注册未知 POST 未去重 | 产品限定补丁；主代理实机 |
| 单次生成回执与恢复 | 架构确认 source/file 路由 41 本地测试；产品两端客户端 29 聚焦回归＋双端 tsc 通过，unknown/accepted/reserved 与原 task 重试契约一致 | 公网部署/native 冷启动未验；reserved 不是耐久队列或 LLM exactly-once；媒体与首次文件注册去重未覆盖 | 产品限定客户端；架构服务；主代理部署/实机 |
| 编辑与版本 | 默认、展示、导出、发布绑定同 revision 的契约一致 | 双端草稿、切后台/重启、版本翻页和冲突真实闭环未验证 | 主代理详情；架构一致性；设计状态 |
| 云同步 | 桌面 PDF→手机、手机 DOCX→native 桌面已同步为用户实证；公共 API 已部署 | 断网/附件失败/双端并发、电脑关闭、跨 owner 隔离完整实机未验证 | 主代理；架构协议 |
| 飞书授权与交付 | 用户报告 owner 自选已有应用 OAuth 成功及私人文档 create/write/permissions 完成 | App 交付记录/通知及其他用户未验；关闭组织外/链接分享不保证仅本人，内部继承仍依飞书组织策略 | 主代理 Feishu 页/实机；架构权限契约；设计文案 |
| 内容插件与 MCP | 用户纠偏已达成：翻译仅真实远程 MCP，正文/目标中英 schema 映射、固定源版本、两阶段确认、真实 run 结果另存；diagram 保留，架构图组件就绪（其报告 20 回归） | 无已连接翻译服务证据；精确只读恢复与双端 MCP UI 进行中；保存复用普通新版本编辑/CAS；真实授权、译文/新版本与图可读性未验 | 产品合同→设计 desktop 交互→架构核验/保存；主代理 App/实机 |
| 归档/删除/恢复 | 指定两页可发现回收站与真实确认；desktop 最新 8＋App 4 页面回归，架构同 deleteOperation 恢复协议已实现 | 未同步本地可恢复删除不支持；两端删除→回收→恢复/保持原件实机结果待用户反馈 | 产品列表/菜单；架构协议；主代理详情与实机 |
| 设置与账号 | 账号与设备原件隔离、本端退出不撤销其他设备契约达成 | 新手、隐私/设备管理及未配置服务路径能力/实机未全验 | 主代理；三角色核对能力 |
| 离线与切后台 | 只查询/有界刷新、未知写保留原操作、不假成功契约达成 | 冷启动/后台回来/切账号时全生命周期实机未验证 | 主代理实机；架构恢复；设计保留上下文 |

上述“达成”仅指明确契约或列明的测试/用户实证，未宣称全产品已验收。本人未启动服务、操作浏览器/手机、读凭证或写云数据。

## 一小时内容增强 V1：产品范围确认

已核查现有链路：`app/services/content_plugin_service.py:13` 注册 translation/actions/glossary/diagram（用户所说 terminology/flowchart 对应实际 glossary/diagram ID），`:106` 经 `summarizer` 调用真实 `llm._complete`，`:129` 起核对后保存新版本并保留源版本；`app/__init__.py:52` 已挂路由。`frontend/src/pages/Connections.tsx:69` 起有添加启用、选择内容和版本、预览及明确保存 UI，`:90` 提交模型处理。不是静态按钮，但真实云端模型处理未验证。现有 `tests/test_content_plugins.py` 5 项 pytest 通过，使用临时库/合成模型，覆盖隔离、只预览、显式重试、版本冲突和保存回执丢失，不等于上线或真实模型成功。

`frontend/src/components/Markdown/MarkdownContent.tsx:96` 把 mermaid 当高亮代码，`VINote-app/src/components/MeetingMarkdown.tsx:121` 把 fence 当代码块，两端均无实际流程图渲染/缩放/节点交互。两端 package 未找到 Mermaid、SVG 或 WebView 渲染依赖。`VINote-app/src/screens/ConnectionsScreen.tsx:12` 仅飛书/MCP，没有内置四种内容处理 UI。已有图片是 Markdown 内容附件，并非图片生成 API；模型“输出 Mermaid”不代表用户看到了图。

一小时按可完成的优先级定义以下 V1，已先发设计角色，随后由设计契约交架构限定新实现文件；本人不猜新 API 或抢写业务：

| 优先级/能力 | 范围与交互验收 | 明确边界 |
| --- | --- | --- |
| P0 MCP 全文翻译 | 插件页管理用户选定的真实远程 MCP 工具；两端从纪要/笔记固定已保存版本发起；仅英语、简体中文；工具授权与本次确认后发送正文，核对原译文并明确另存新版本 | 用户纠偏为 MCP 功能，内置 content-plugin translation 不计交付；无服务不假安装/回退内置 LLM；现有参数 JSON 最大 64 KiB，不截断或自动切块；不增加日德语、选段翻译、自动覆盖或发布 |
| P0 总结流程图 | 正文/插件预览内可解析的简单 flowchart 渲染为步骤关系；适配、展开、缩放或原生滚动；同时保留文字依据与源码降级 | 限安全子集，最多 20 节点/40 边；不执行模型 SVG/HTML/click/外链资源；无明确流程据则说明；不画虚构数值图，不承诺通用 Mermaid |
| P0 请求与版本状态 | owner+operation+源版本持久回执；未知先 GET 原运行，显式重试同 run；保存冲突保留预览；离线/未同步/未启用/模型未配置有实际去向 | 当前 desktop operation 只在组件状态，关闭再打开可丢失，需补恢复；普通文本生成去重不自动覆盖插件或首次文件注册；不宣称模型 exactly-once |
| 保留既有行动项/术语 | desktop 现有预览与新版本能力保持；动作项仅整理明确负责人/日期，词表校对附清单 | 不创建外部任务，不冒充检索或事实验证；App 首轮只接翻译/流程图，其他能力未接入明确说明 |
| 证据与图片 | 仅已有真实时间戳/链接且当前设备确实支持的跳转；总结图提供可读文本替代 | 当前 diagram 只返回 Mermaid＋文字依据，没有节点证据映射，不能伪造点击节点定位原文；不新增无配置图片生成服务 |

对象范围统一：网页、PDF/DOCX、文字、音视频与会议生成的共享正文都可处理，不把 PDF 当录音、不重传原始媒体。插件管理启用与运行，详情保持版本阅读/发布职责，导航不变。不得把 V1 缩小范围的通过写成完整产品 10 分；两端真实翻译、图渲染、取消、离线未知回执、版本冲突及冷启动仍由主代理实机验收。

## 03:45 检查点：全主页面 V1 最终方向与验收项

产品方向已确认：优先打通“获取→原件保存→单次生成→阅读编辑/版本→同步→插件处理/发布→归档与回收恢复”的完整旅程，再补两端全文翻译与可读流程图。全部主页面按同一状态与返回契约检查，不增加一级导航，不以一个新按钮代替闭环。新能力由产品范围交设计师，设计师把交互契约交架构师；架构指定实现文件、安全边界和分工后实现。本人不新增视觉/翻译业务实现。

两端所有页面的共同通过条件：标题能说明对象，主动作与当前状态一致；返回保留实际来源、筛选及未保存输入；首次使用有唯一下一步，离线和失败保留缓存/草稿/原请求；取消选择与取消已提交处理区分；未知写先核验同 operation，禁止自动生成新 ID 重发；键盘/读屏能发现操作，图有文本替代，确认默认保留对象。颜色、层级、间距与图交互由设计师统一，不展开新的整套导航或大重构。

| 主页面/流程 | 03:45 必须可观察的 V1 验收项 | 当前证据/未达成 |
| --- | --- | --- |
| 登录/注册/找回密码 | 校验失败保留输入；验证码/密码模式返回明确；令牌过期可有界刷新或重新登录，云端配置失败不伪装本地注册 | 源码有能力；新手/断网/到期实机未验证 |
| 会议列表与录制 | 录制停止先保存；仅保存即在当前设备历史可见；后续选择生成；暂停/取消/拒绝权限不丢原件或占设备；返回会议保留对象 | 完整原生权限、后台与失败实机未验证；不把 App 不支持的录屏写为支持 |
| 笔记列表/获取/直接写 | 两端可找到网页/视频链接（包括 B站入口）与 PDF/DOCX 导入；显示支持边界；写笔记不是生成；已接受的来源可回任务与结果 | 网页与文档已有实证；主代理提供入口截图并复核 native，本站未重新实测 |
| 文件库 | 类型页内筛选；导入原件与生成是不同动作；PDF/DOCX 同 file ID 发起与重试；失败可导出；来源/结果互链；删除原件不删正文版本 | 21 pytest 有限模拟验证；真实互链/删除导出仍需实机 |
| 内容详情/编辑/版本 | 普通文档无假原音/逐字稿；编辑失败保留草稿；选择/默认/导出/翻译/发布明确绑定同一源版本；版本冲突不覆盖，返回实际来源 | 文档同步/Word 展示有实证；完整版本/草稿/冲突实机未验证 |
| 项目/归档页内视图 | 不产生重复内容；归档与删除语义不同；打开→返回保留项目/归档与筛选；没有持久化能力的不伪装已保存偏好 | 源码部分存在，完整实机未验证；保留旧深链 |
| 全局任务与恢复 | 同 owner 的来源生成、同步、插件和交付有可找到的状态；未知提交核验原 operation，冷启动不丢回执；仅明确失败能显式重试 | 来源去重模块有架构测试，主代理接入待验；首次文件注册 POST 未去重仍风险 |
| 插件目录与内容处理 | 真实连接/发现/逐工具授权；中英全文翻译仅通过选定 MCP 工具；受限 flowchart 预览；固定源版本，原文不改，确认才另存新版本；同 run 恢复、关闭/重启不丢未知回执 | 内置翻译有源码不代表满足需求，须移除假入口；远程翻译实际授权/调用/保存未验；图渲染按架构就绪组件接入，不得用高亮代码充当图 |
| 飞书连接与发布 | 普通用户仅连接本人账号；真实公司默认/个人覆盖与管理员权限分明；具体版本在详情确认私人文档位置/阅读权限；创建、权限、通知独立回执，未知不自动重发 | 用户已确认 owner 现有应用 OAuth 成功；主线程正在私人文档发布实机，本报告不先记成功；其他用户公司默认链路待验 |
| MCP 连接与执行 | 启用真实工具、显式授权；选择内容/参数预览→确认→记录结果；撤销/失败/未知可找到；不伪装安装了未接入的翻译/检索服务 | 源码有协议；实际远端执行、拒绝与未知结果未验证 |
| 存储/同步/回收站 | 仅服务持久回执显示已同步；附件失败保持未确认；双端删除与恢复同对象/版本，原件及已发布文档保留；本地未同步不走永久删除分支 | 删除桌面 6/App 4 测试，两端类型检查通过；主线程正在双端删除同步实机；恢复未验证 |
| 设置/头像账号 | 模型选择作用于下一任务；外观/存储/版本帮助职责清晰；退出只此设备，保护未保存录制/草稿/回执；重新进入原账号恢复、不同账号不互见 | 完整安全/设备撤销/目录迁移能力未交付；不以登录记录冒充设备管理；实机待验 |

实际路由补充：`VINote-app/App.tsx` 给详情 `onSettings` 的回调当前指向飞书，不可作为同步恢复按钮。限定删除页已改为“账号→设置→存储与同步”的明确路径说明，未改路由；若提供详情直达恢复，需要设计交架构/主代理新增专用回调并保留详情返回，不能复用模糊的设置回调。该修正后 App 4 项 Jest 再次通过。

03:45 交付记录必须分为“已实现并测试”“实机已通过”“未达成/未验证”，附端别、对象/版本/任务或操作标识、步骤、结果与时间。主线程正在执行的私人飞书发布、双端同步和删除只在收到真实结果后更新通过状态。全文翻译至少记录一份真实源/译文/保存后双端版本；图至少记录支持流程成功、恶意/不支持语法安全降级及手机可读文本。任一未知结果、误跳转、草稿丢失、错误删除或越 owner 写入均不能通过对应项。

完整产品评分仍维持初审桌面 7.1、App 6.6、综合 6.8；截至本补充没有完整覆盖的实机结果，不升级为 10。V1 通过只代表明确范围通过，不能抹去未实现账号能力、未覆盖本地可恢复删除或首次文件注册未知回执。

架构最新预审补充，已交设计一并传递：来源回执模块虽有 26 项测试，`note.py` 尚未接入，应继续标待集成。插件 start 仅进程锁，复合 PK 多 worker 并发碰撞未处理会 500；retry 无 attempt fencing，旧执行可能覆盖新尝试结果。这两项不是本产品页测试已覆盖的保证，需架构完成运行 claim/attempt 与持久客户端回执后再验安全恢复；未完成时保持待核验，不提供会重复执行的假恢复。架构候选受控 flowchart AST→桌面 React SVG、App 原生 View/Text/ScrollView，符合既定产品子集，但须由设计契约转架构确定文件与语法，产品不自行实现。

设计已正式将最终契约转交架构，产品接受以下收敛并以其替代上文图交互的可选表述：两端展开与可读滚动是 P0，桌面缩放非额外硬门槛，有控件才要求真实工作。图仅单链、基本多分支/汇合 DAG；环路、复杂语法及超 20 节点/40 边完整降级为源码＋依据，不截断成误导图。翻译宽屏同容器双栏、窄屏/App原译文切换保留阅读位置，恢复固定 source version_id 和 language；保存前明确“新版本将作为当前版本，原文保留在源版本中，不会发布到飞书”。failed/interrupted 才显式重试，未确认仅核验原 run。新实现仍由架构指定文件和安全规范，主线程实机；产品与设计不抢写新功能。

架构接契约后已确认实现所有权（进行中，未计通过）：架构负责 `content_plugin_service.py` 原子登记/attempt fencing/固定源序列化与测试，以及两端新 `simpleFlowchart.ts` 和 `SimpleFlowchart.tsx` 组件/测试，无新服务或 native 依赖；主线程负责 Connections/App内容插件 UI、两端 Markdown 接入、owner+operation 持久恢复与详情正确导航。架构不写现有 Connections/MeetingMarkdown/MarkdownContent/NoteDetail/WorkspaceNote；产品限定删除页已完成，后续不重复写这些新功能。

后续实际反馈与最小修正：用户已实际看到 Notes 行操作菜单；后台同步时禁用移入回收站缺少说明，现改为“正在同步，完成后可移入回收站”，同步结束自动恢复菜单项。列表 sourceDevice 的 desktop/mobile 显示为桌面端/手机。笔记列表数量行新增轻量“回收站”链接，指向既有 `/settings/sync#trash`；仅为现有回收站标题补锚点、滚动/焦点定位，返回通过既有 PageReturn 保留笔记项目/归档筛选，无新侧栏或管理页。桌面该组最新 8 项 Vitest 通过（含锚点定位、返回筛选和 busy→可操作），并非实机跨端恢复通过。

App 详情菜单已有“移入回收站”，尚无直接浏览回收站按钮；查看/恢复在账号→设置→存储与同步的同步类下。用户正在自身测试笔记上实测跨端 delete/restore，结果待反馈。新实测事实：飞书私人文档 create/write/permissions 已完成（用户报告，本人未重放）；App 查看交付记录待验，不把该结果外推通知、其他用户权限或完整交付恢复。分数维持初审，待完整证据复审。

架构后续已报告来源路由接入完成并释放 `note.py`：网页/文档 upload 支持 `X-VINote-Operation-Id`，GET `/api/source-requests/{op}` 按同运行身份核验，重复返回同回执，reserved 不自动运行。来源回执与原件测试合计 41 项通过为架构报告的模拟证据；客户端接入、公网实机和首次 `/api/files` 注册去重仍分别待验/未完成，不外推全链保证。


## 来源客户端收尾与 MCP 翻译纠偏（最新契约）

来源客户端限定实现已完成：`frontend/src/pages/NoteGenerator.tsx:216` 先将 owner、operation 与来源/原件 ID 保存到 localStorage，再 POST 同 `X-VINote-Operation-Id`；`:231` 未知重入只 GET 原 operation，accepted 轮询原 task，reserved/404/鉴权/网络失败保留原 ID。`:358` 仅明确 failed/error+retryable 经最新 task 状态核验后显式重试原 task。`frontend/src/pages/Tasks.tsx:58` 找到当前与历史 owner 回执，原 operation 深链恢复，损坏/缺失的深链不默默新提交。`VINote-app/src/lib/noteIntake.ts:42`、`:99` 与 `src/screens/NoteIntakeScreen.tsx:26`、`:96` 使用同一契约，持久化失败不 dispatch，旧屏幕/并发点击复用受保护请求；后台恢复只读查询。没有修改 App.tsx、集成服务 Origin、正文详情或其他生成路由。

验证证据：desktop NoteGenerator 12 项＋Tasks 2 项 Vitest，App noteIntake 12 项＋screen 3 项 Jest，合计 29 项聚焦回归全部通过；两端 tsc --noEmit 通过，指定文件 diff --check 通过。串行运行、512MB Node 上限；使用模拟接口/本地存储，无云数据写入、服务启动或原生 UI 操作。架构已直接确认客户端与 source 服务契约一致。服务器部署/公网与手机原生端冷启动仍未实机验证；App generation Origin 在开发使用本地端口、生产为空的现有限制未改，不能宣称此补丁已接通公网来源生成。reserved 不是耐久队列，可无限待核验；媒体/逐字稿/录制入口及首次 `/api/files` 注册未纳入 source 去重，不宣称 LLM exactly-once。

产品纠偏：先前将 translation 作为内置内容模型插件的 V1 方向偏离用户要求，撤销该交付与验收项。翻译只作为用户选择的远程 MCP 工具；上文“复用内置模型翻译”与 60000 字符边界已由新契约替代。diagram/安全图渲染独立保留，不借翻译纠偏取消它。无真实远程服务时没有可执行翻译，不用本地/内置 LLM 假装安装成功。

| MCP 翻译 V1 合同 | 必须可观察的行为/验收 | 当前能力与负责人 |
| --- | --- | --- |
| 插件定位与选择 | 插件页复用 MCP 连接、发现和逐工具授权；用户选择一个真实已发现工具作为翻译目标；未连接显示连接服务去向，失效/停用不得调用 | 已有连接/工具 API；设计负责 desktop 管理 UI，主线程 App；架构审 schema 适配 |
| 固定上下文与语种 | 详情从明确的已保存源 version 发起全文中文或英文翻译；源快照、目标语、connection/tool/schema 指纹在准备前固定；未保存草稿需先保存，不悄悄变版本 | 详情接入主线程；仅 zh/en，历史其他语种记录不等于本轮支持 |
| 工具契约与内容范围 | 按真实 inputSchema 明确正文与目标语字段，不能按工具名猜；V1 仅支持这两类参数及无需额外未知必填输入的工具；发送正文纯字符串和目标语，不附标题、来源 URL、账号/版本 ID、录音、文件或附件二进制 | MCP 通用 invoke 已存在；复杂 schema 明示不兼容，不暗中补参数。正文内原有 Markdown 链接作为原文保留，不主动加载/上传其资源 |
| 本次授权与确认 | prepare invoke 返回 awaiting_confirmation；展示目标服务/工具、源版本、本次正文与参数范围；用户明确确认后以同 requestId、token 执行；取消准备不发生远程调用，工具定义变化重新发现/授权 | `mcp_connection_service.py:607`、`:645` 已有两阶段与定义核验；主线程/设计接 UI，不另造自动确认 |
| 全文限额与结果 | 按参数 JSON 实际 UTF-8 字节检查现有 65536-byte 上限；超限明确拒绝并保留全文，不截断/暗中切块；仅接受 isError 非 true、未截断、非空且可保存的 text content；源内容 60000 字符与实际参数 JSON 64 KiB 边界同时检查。非文本、错误/超限可查看实际记录但不假装译文完成 | 现有 MAX_ARGUMENTS=65536、MAX_RESPONSE=1MiB；主线程/设计按真实 run 提取文本供用户核对，保存复用现有编辑；远程真实翻译未验证 |
| 预览与另存 | 宽屏原译文对照、App 切换保留位置；用户明确另存同笔记新版本，原版本保留；注明新版本是否成为当前版本，不自动发布或替换原文；CAS 冲突保留译文，源被删除不偷偷恢复 | 复用 workspace 写入/版本契约；主线程实现，设计确认当前版本语义；未知保存核验原 operation/version，不重新调用工具 |
| 中断、失败与恢复 | owner+requestId、源快照和实际 run 先持久；断网/后台/冷启动只读恢复，unknown 不重放；已派发失败也不保证可重复执行。仅证实未派发才允许用户明确重新准备并再次确认；运行中退出不声称取消远程任务 | 已有 owner/requestId 去重与 runs 分页；精确只读查 requestId/run 的必要补口由架构定，不能把不存在路由写成已支持；取消目前只支持待确认状态 |
| 实机与隔离 | 真实用户选工具→授权→确认→中英全文结果→预览→另存→双端版本；另验无服务、schema 不匹配、超限、拒绝确认、未知回执、版本冲突及切账号 | 设计/架构已直接沟通；实施与主线程实机待验。内置 translation 合成测试不能作为本项通过证据 |

本轮不自建或部署翻译服务、不推荐虚构服务 URL、不共享第三方用户令牌，不扩大工具执行权限，也不自动安装“内置翻译”。产品合同已交设计师，并同步架构核查现有能力/安全限制；新实现文件仍由架构限界，主线程负责 App。若没有可用远程 MCP，只能交付正确的连接和调用闭环，不能宣称真实翻译已验收。

飞书权限语义补充：架构发现现有 access_scope=owner_and_selected_recipients 过度保证。真实关闭组织外/链接分享不保证只有本人可读，内部上级与继承访问仍由飞书组织策略决定。私人文档 create/write/permissions 成功事实保留，产品文案不能据此承诺“仅本人”，主线程修正该语义。

综合评分仍为初审 6.8/10；本轮来源客户端 29 回归通过与 MCP 合同明确不构成完整两端 10 分或远程翻译实机证据。


沟通收敛：设计已回应复用真实 schema 字段映射、无兼容工具配置空态、64 KiB 超限保留全文；架构已移除内置 translation catalog 与新运行/重试，历史只读并保留 diagram。产品接受其独立保存 ledger/API 候选：从 owner 真实 succeeded/nontruncated run 服务端提取结果，验证参数映射与固定源版本全文/目标语言，CAS 追加绑定 source parent 的新版本；同 run 保存固定 operation/payload。该 API 与精确查询入口仍由架构和主线程最终限定文件后实现，尚未计“完成”。已有结果在连接停用后可以核验/显式保存，不因停用重复执行工具。


架构最后明确的新接口合同（实现中，非已部署证据）：GET `/api/mcp-connections/runs/by-request/{requestId}`、GET `/api/mcp-connections/runs/{runId}`；POST `/api/mcp-connections/runs/{runId}/save-version` 请求仅 `{note_key,source_version_id,base_revision,text_parameter,language_parameter,target_language:'zh'|'en'}`，不收客户端译文/title/operation_id。backend 以 owner/run 产生唯一保存 operation 和新 version，从实际 run 的文本 content 以双换行拼接，校验完整源正文、实际两参数、成功/非截断/schema/定义 hash 后 CAS 保存。保存返回标准 workspace note；GET 原 run 附 `contentSave={status:'prepared'|'saved',note_key,version_id}` 或 null，未知只 GET。独立 `app/routers/mcp_content.py` 由主线程在 `/api` 下注册，架构负责新 backend 模块/测试；产品已将精确契约转设计，不修改这些新文件。


### 最终分工更正：普通版本编辑，不增加专用保存 API

父线程最新决定覆盖上一段 save-version/ledger/contentSave 候选：全部撤销，不新增专用保存模块或表。架构只补 GET `/api/mcp-connections/runs/by-request/{request_id}` 与 GET `/api/mcp-connections/runs/{run_id}`，使用路径参数，不用 querystring；owner 精确只读隔离/代理，返回已有 flat MCPRun，无 contentSave、新保存 API 或后台译文认证。已成功工具停用后仍可读历史；unknown/failed/404 不重新 invoke。

译文经用户预览核对后，desktop 使用已有 workspace 标准新 version CAS；App 主线程使用 editNoteContent 固定 CAS baseline＋原文 history，然后请求同步，收到实际确认前不能称已同步。保存属于用户的普通版本编辑，不承诺后台自动验证翻译语义、源全文或事实完整；先前服务端提取/验证/独立保存账本均为已撤销方案。选中的旧 source version 和全文快照必须固定；当前对象 CAS baseline 单独绑定，不能把选择旧源版本理解为允许覆盖更新的对象。保存冲突、未知结果仍按既有编辑恢复协议保留译文、原版本和原写 operation，不重新调用工具。

文本提取只接受成功 run、isError 非 true、非 truncated 的非空 text content，拒绝把资源/图像内容伪装译文。源内容 60000 字符边界和真实参数 JSON 的 UTF-8 65536 字节边界同时生效，超限保留完整源内容并拒绝派发，不自动截断/分块。以上最终合同已同步设计与架构；两个 GET 的实现/部署与真实翻译实机仍分别待确认，不新增满分证据。


### App MCP 工作流快速源码复核

主线程最新 App 实现已读：Connections 翻译路由真实 MCPScreen，详情“全文翻译·MCP 工具”与流程图分离；实际 discovery 后用户手选两个 string 字段，目标仅 en/zh、enum 不匹配拒绝；prepare→明确确认→invoke 前 owner 持久 intent，源 Note 快照固定、正文可对照，保存调用带正文/revision baseline 的 editNoteContent 并保留原文 history。这些方向符合需求。没有实际远程翻译工具/运行证据，本轮仅确认配置与源码，不给已跑通或新评分。不推荐、预置无依据的 MCP 服务。

| 优先级/实际触发 | 证据与用户影响 | 最小调整/负责人 |
| --- | --- | --- |
| P1 原运行超出最近 50 条或响应丢失后冷启 | `VINote-app/src/screens/MCPScreen.tsx:41`–`:45` 仅从第一页找 pending；`:51` 的 recoverMCPIntent 只读存储，存储刻意 result:null，可能始终不能恢复真实结果 | 主线程用架构已完成的精确 GET by-request/runId 路径；404/failed/unknown 不重 invoke。只读结果展示不能依赖现存可用 tool，否则成功后工具停用/移除无法恢复 |
| P1 调用未确认/unknown 时关闭弹层、换连接再打开工具 | `MCPScreen.tsx:62` open 与底部 sheet 的 onClose 把内存 pending 清空；查看工具按钮随后可以 clearMCPIntent 并覆盖原记录，绕过原请求保护 | 关闭/换连接只隐藏 UI，保留独立 active intent；新准备前按持久 intent 核验，待确认可显式 cancel，unknown/failed 保留查询，不让返回操作丢保护 |
| P1 超限全文、截断结果或非约定额外输入 | `src/lib/mcpTranslation.ts:16` 只限制 60000 字符，不检查 JSON UTF-8 64KiB；`:26` 未拒绝 truncated，也未判空白；translationArguments 合入任意 extras，翻译模式 UI 鼓励填额外项 | 主线程发送前按真实 JSON 字节双限额，拒绝 truncated/空白文本；翻译 V1 仅正文与目标语，不擅自扩展业务参数，未知额外 required 明示不兼容。普通 MCP 工具保留通用参数编辑，不靠两个 string 字段就声称工具确有翻译能力 |
| P2 译文已写本机但同步失败/冷启动 | `MCPScreen.tsx:142` savedResult 仅 React 状态，文案“已保存·正在同步或已同步”无法判断实际阶段；重开后已保存状态丢失可能误导重复保存/显示冲突 | 主线程持久本地保存目标/状态，保存成功明确“已保存到本机，云同步待确认”，只有真实同步 ack 显示已同步；恢复原 run 与普通编辑回执，不重新调用工具 |

以上四项已直接同步架构与设计供主线程最小收敛，本产品未修改他们的 MCP/详情文件。架构确认精确 GET 已在既有 mcp_connections router 完成、无需新注册，返回 flat Run，无专用 save API；其 owner隔离/历史读取/超过第一页恢复测试为架构报告，未部署实机。完整工作流还需真实工具授权、拒绝、超限、unknown、工具停用、保存冲突与双端版本实测。来源客户端已完成的 29 项聚焦回归与双端类型检查保留，无需因本次审查改动或重跑无关业务。


### 03:32 整体入口复审：五项最终产品判定与归属

本轮已与设计师直接整体复审；设计在收尾 Connections/MCPSettings，不能将其存在设计稿/报告外推为所有入口已合理或已落地。当前用户不满的独立处理记录与跳错目录仍有源码依据；下面是检查点前的最小收敛，不换整套导航，不改正在完成的 source 回执代码。

| 优先级/产品判定 | 当前源码依据与实施方向 | 实施归属与验收 |
| --- | --- | --- |
| 1 主目录只承载对象/服务，类型是筛选 | Sidebar.tsx:41–:48 主组已接近定稿，但文件全部/录音/录屏/视频/其他仍展开目录；:95 处理记录与设置并列常驻。保持会议与笔记（会议/笔记）、文件库、插件；文件类型退回既有页内 filter；设置与头像保留，不增目录 | 主线程 Sidebar/MainLayout/App；设计审层级。两端能明确回答“内容/原件/服务/偏好在哪里”，没有类型树/重复处理入口 |
| 2 获取内容与会议/原件边界要可见 | Notes 的 ContentIntake 是写笔记、粘贴链接（含 B站）、导入文件整理的入口；Meetings 是录制/导入会议与会议历史，停止先保存；FileLibrary 保存/导出/删除设备原件并关联文本结果。不得把文件库再做笔记目录，或让会议入口承担普通 PDF/DOCX | 主线程 Notes/ContentIntake/Meetings/FileLibrary/App；产品 source 文件闭环补丁已完成，不重写。每个入口文字说清对象与下一步，导入保存不等于已开始生成 |
| 3 任务是对象状态，不是功能目录 | 当前 Sidebar:95 裸 /tasks 没有 origin；Tasks 的记录恢复存在回 /meetings 落地页而非原对象，生成源码恢复已带原operation。优先在原内容/文件/插件对象行显示进行中/需核验与详情就地继续；全局仅轻量真实状态入口，旧 /tasks 保留兼容兜底，不加导航层级 | 主线程 Tasks/MainLayout/App及对应对象状态；设计统一状态样式。打开任务能看到同一对象、阶段、原件/结果、真实错误与可用继续；unknown 只核验，不能直接甩到无定位目录/重新生成 |
| 4 配置和调用分层，空态不伪装能力 | Plugins/Connections 管真实连接、发现、逐工具授权与默认配置；正文调用从详情固定源version进入。MCPScreen 当前同页管理、JSON、调用确认混层，需要按进入目的渐进展示；“未连接工具”引导配置，“已连但无源正文”引导从笔记/会议详情选择版本，不能靠 dummy MCP 填满 | 设计 owned desktop Connections/MCPSettings；主线程 App MCPScreen/详情。无真实服务仅配置态，不自动带正文/派发、不预置无依据服务；详情调用保存前保留源快照与授权确认 |
| 5 返回与恢复必须回原对象 | navigation.ts:9 只允许 /workspace/id，/note/id 与插件配置上下文会 fallback；FileLibrary:96/:102 回链固定 /files，丢当前 type/query/选文件；App 有 return screen 但不足以替代对象/版本位置。补合法详情与配置父路由，携 origin path+query+对象/选版本，保持项目/归档/文件筛选；任务返回原origin，恢复入口别重定向默认笔记目录 | 主线程 navigation helper/Tasks/FileLibrary/App与详情；设计审返回语义。串行小测试验证“原列表→对象→任务/插件→返回同对象/筛选”，不用新增通用路由栈或大构建 |

实施优先级：先撤处理记录的目录地位并保住状态可发现性、补原对象返回，再理配置/调用空态与字段层级；现有 Notes/文件/会议入口按归属校正文案和动作，不重复新增主按钮。产品经理只写本报告并对已完成限定补丁收尾，设计不抢 Sidebar/父线程路由，架构后端已冻结 ready。source 客户端 29 聚焦回归、两端 tsc 完成，不因这次全局复审中断或回退。本人未实机验收新导航/返回，仍维持综合初审 6.8，不强行 10。


## 当前证据复审、原生会议重复修复与真实 MCP provider 方向

新增真实事实采用用户/主线程报告：review bundle SHA-256 `[私有摘要已省略]` 已公网部署，single worker/1GB，manifest/schema/health/deploy检查通过。App已接公网精确 by-request GET；这些不等于真实翻译工具执行、来源未知提交恢复或 App Auth transient 已验收。主线程实际看到了6节点/5边流程图为转述证据，不能外推全部图布局与原生滚动。本人没有部署、读服务器或操作原生端。

当前源码确认导航收敛：Sidebar 文件类型树与常驻处理记录已撤，历史入口放头像，携 path+query；合法 note/workspace detail、飞书/MCP配置、回收站 hash 可作为内部返回目标；App GlobalTaskStatus idle为空，仅实际录制进度/同步状态或异常展示。源码也确认 App此前四项MCP修正已落实，包括精确GET、关闭保留pending、两字段参数双限额、结果截断/空白拒绝以及 locallySaved。设计报告 desktop4文件44测试＋tsc、最后19为前述子集；主线程导航/图22测试为其报告。本人未将其累加到自己source29项，也未称完整页面通过。

仍有两处具体返回/恢复缺口，主线程负责（本轮不抢写）：`VINote-app/App.tsx:153` 的 Account onTasks 仍指向 data，而 AccountScreen:43 显示“处理历史”，标签与去向不符，应独立正确路由到 tasks 并设 tasksReturn=account，存储同步保留自己的回调；`frontend/src/pages/Tasks.tsx:122` 切 tab 使用 setParams({tab}) 丢掉 returnTo，子记录回链也多写固定 /tasks，应保留既有 query/origin并携选中对象，避免重新回默认笔记。这两项不能因导航helper测试通过而标已闭环。飞书 ensure_permission 仍旧 owner_and_selected_recipients 声明，实际仅关闭外部/链接分享，组织管理/继承策略仍适用，语义修正未完成。

### 03:44 原生旧会议双行：限定补丁与完整历史边界

用户实际 Tauri截图显示旧会议同标题/日期两行，这是实际故障，不以UIA抽象否认。源码定位到两段：内容库仅 cached mapping/desktop-id关联，未完整识别 mobile stable source及保留的App迁移版本ID；MeetingWorkbench仅 noteId/draftNoteId关联录制，未按原task及多个内容对象投影聚合。已获用户限定授权修改两个实现文件和一个新测试文件：

- `frontend/src/hooks/useLibraryNotes.ts`：稳定 mapping、desktop/mobile包装源ID、文档化App版本来源ID与 task/media metadata 作为身份；identity仅关联，不授予本地媒体路径。保留新的本地编辑，以及归组的全部 localSources，避免共享代表项遮掉本地历史。没有按标题、正文或日期认同对象。
- `frontend/src/components/MeetingRecorder/MeetingWorkbench.tsx`：按同workspace scope内稳定task/source关系的连通组显示一会议行；当前代表内容选最新真实记录，失败/处理中保留；“来源与历史内容”显示每份本机/共享内容的全部版本入口及每个原录制入口。同标题同正文同日期但不同身份仍独立，缺身份不猜合并。
- `frontend/src/hooks/useLibraryNotes.identity.test.tsx`：8项新聚焦＋原hook1项，9项全部通过；最新frontend tsc --noEmit与指定文件diff --check通过，512heap串行。覆盖missing mapping/media migration、多个shared对象、task关联录制、不同会议同标题/正文、保留新草稿、tombstone不复活、workspace隔离、失败及多原件保留、UI每份历史入口。

这是纯列表projection，无API写入、历史版本合并/删除、原件删改、回滚或服务启动。测试验证输入本地/共享版本对象没有被修改，全部记录保留可达；不是已将迁移历史搬入一个共享对象。原生截图实际那一对是否含足够稳定身份必须由主线程HMR后复核。若两行确无mapping/task/source/version证据，继续分别显示并收集脱敏ID关系，不能用标题或正文强行隐藏，未来迁移补证由架构另定。

### 产品方向纠正：提供可用翻译 MCP，而非让普通用户填JSON

“本轮仅接existing URL、不自建”是本角色自行范围判断，已撤销，不是用户限制。正确configure/invoke闭环已收敛，但没有真翻译provider是功能缺口，不能完成翻译验收。普通用户最终只应选择真实provider、中文/英文、固定源版本，授权确认、原译文预览和另存版本；地址/schema/JSON保留高级自定义工具能力，不作为默认翻译路径，更不预置meaningless工具。

实际读取的官方公开资料：[DeepL MCP README](https://github.com/DeepL/deepl-mcp-server/blob/main/README.md)（GitHub连接返回modified2026-07-31；org从DeepLcom移动到DeepL，初始直连TLS失败后已通过GitHub公开读取）：Node18+、必需DeepL API key、stdio；真实工具translate-text参数text/targetLangCode，text可string或string数组，en默认en-US、zh默认zh-Hans。当前VINote outbound仅公网HTTPS Streamable HTTP，因此不能把官方stdio命令假装成可直连URL；实际schema若是union，还不能把“两个string字段”当兼容保证。DeepL路线需受控桥接、实际模型/API凭证与运行验收，不能伪造URL或安装完成。

产品推荐优先研究独立的第一方受控HTTPS Streamable MCP adapter，调用现有可用文字provider，明确标签“VINote文本翻译·MCP（当前模型服务）”，不冒充第三方DeepL、不把旧content-plugin换名。必须真实initialize/tools/list/tools/call协议，明确text:string和target_language:zh/en、真实模型调用/错误和无provider配置态；discover成功才允许用户启用，继续逐工具grant和本次confirmed执行、同request只读恢复。固定第一方Origin、owner身份/有界专用授权与provider/model mode一致性由架构审，不能把Supabase用户Bearer保存成通用凭证或转发任意URL，也不能靠匿名/共享管理员token扩大用户权限。新adapter为下一独立实现增量，不改本轮已部署冻结关键API；本角色只定产品并研究，不新增mock服务或重启runtime。

候选已发设计/架构核查，provider尚未实现部署/真实运行；没有必要先索取用户秘密来阻塞其他目标。若选择DeepL而确需管理员API资格，再仅问一个必要信息“是否已有可用于该部署的DeepL API计划/凭证，并通过安全配置交管理员”，不在聊天要求粘贴key。首选现provider路线的最终鉴权与新文件边界由架构交接。

### 复评分：保留未验收项，有限反映已修复实现

同初审权重，两端等权，更新有当前源码、本人聚焦测试或用户/其他角色明确报告支撑的维度；降低会议维度以反映刚出现的原生列表实际故障，补丁通过不等于实机已关闭。评分是产品判断，不是实际运行通过率，也不是设计角色视觉分数。

| 维度 | 权重 | 桌面当前 | App当前 | 有限证据与仍缺项 |
| --- | ---: | ---: | ---: | --- |
| 信息架构、入口和返回 | 15% | 8.0 | 7.5 | 导航目录/真实idle状态已收敛；Account历史错路由、Tasks换tab丢origin与完整实机返回仍缺 |
| 笔记全旅程与文档边界 | 20% | 8.0 | 8.0 | 网页/PDF/DOCX和双向同步用户实证保留；完整编辑草稿/版本冲突/所有来源实机仍未验 |
| 会议采集、历史和纪要 | 15% | 7.0 | 6.0 | Tauri真实重复故障已定位、9测试补丁；原生重测/权限暂停后台与会议完整history仍未验 |
| 文件库与原件/内容关系 | 15% | 8.0 | 6.0 | PDF/DOCX注册复用与21pytest、App持久原件/来源测试；两端全部真实互链/导出删除仍缺 |
| 取消、重试和持久恢复 | 15% | 7.5 | 7.5 | 本人source29+双tsc与两端MCP恢复代码/角色回归；native冷启离线/媒体去重/首次注册仍缺 |
| 插件、飞书与外部交付 | 10% | 7.5 | 7.0 | OAuth/私人doc create-write-permissions用户实证、MCP授权恢复UI有明确实现；没有真翻译provider、实际MCP执行未验、飞书scope声明待纠正 |
| 设置、账号与数据控制 | 10% | 6.0 | 5.5 | 本机保存/同步确认分开；设备安全/隐私/迁移完整能力未交付；AppAuth transient根因尚未验证 |

计算桌面7.525→7.5，App6.900→6.9，综合7.2125→7.2。初审6.8作为原时点保留；当前不能给10，不能把部署health/模型预览/代码通过外推真实MCP、原生采集、跨端恢复、账号故障及全页面UI验收。产品当前未达成负责人明确：主线程会议native/路由与实际证据，架构第一方provider鉴权/协议增量，设计provider产品化配置/调用层级；本人限定duplicate/source实现已完成与实得分评审。


架构 provider 研究已直接确认：下一增量选“VINote 官方云翻译·MCP”，而不是声称继承手机本地/自定义模型。独立第一方router/service真实协议 initialize(2025-06-18)、initialized202、tools/list、tools/call；固定text:string/target_language:zh-en、additionalProperties:false，JSON text实际输出。专用vinote-session连接只能由server provisioning建立，固定管理员公网Origin；principal验证本人owner后仅内存转发本人Bearer到该固定第一方地址，不持久Supabase token、不转任意remote、不共享用户token。云summarizer按(owner,None)+Bearer复用现云provider，其路径不读取本机mode/profile，普通UI须准确标官方云模型。LLM在线程执行，adapter不递归套MCP network_slot，同owner_generation_slot限制1，不能放大并发；现MCP40秒内未完成为unknown禁止重放。第一方schema适配免普通用户填JSON，真实部署/调用/失联与保存验收另行执行。该方案仅是已研究合同，尚无新增adapter或provider成功证据；本轮已部署runtime继续冻结。


第一方adapter认证最后补强：仅Bearer不足以阻止直接tools/call绕过本次确认。受控transport向固定managed endpoint发送run ID，adapter须验证owner、已持久running run有效lease、managed connection/revision/definitionHash/tool/完整args fingerprint全部绑定一致，不能信header自称已确认；(owner,runID)唯一CAS claim保证同参重复只读原receipt、不再次模型调用，未知/进程中断不重新派发，并提供本人只读核验。generic create/patch不能伪造vinote-session/修改其固定URL，原HTTPS DNS pin/私网与重定向拒绝保持。此新claim是MCP provider执行授权与回执，不是已撤销的译文专用保存ledger；实现需独立文件加现transport最小桥接，不能声称纯新文件即可使当前静态token连接安全可用。1GB slot1、40s超时/失联、隐私与真实模型执行仍待下一增量验证。


第一方翻译provider完整性验收补充（架构源码复核报告，未修改冻结代码）：现OpenAILLM._complete约300秒timeout且未显式关闭SDK重试，只返回content而丢finish_reason；VILabLLM同样仅取content，cloud stream默认transient最多2次。因此不能复用字符串返回就称全文完整、模型只执行一次或安全可保存。新adapter可复用已验证身份、模型选择与管理员Origin，但provider call需独立设置max_retries=0、明确超时，保留finish_reason/refusal/usage及原run回执。length/content_filter、缺失正常终结、拒绝、空/超限/中断不得进入“完整译文可保存”；预览状态必须如实显示未完成并保留原文。现MCP总40秒与LLM300秒不一致，需要架构明确一致的managed deadline或持久provider receipt供原run只读核验；长文超时不能通过重新tools/call重试。只承诺客户端/adapter不自动重派发，不把该规范扩充成上游模型exactly-once。第一方provider明确官方云模型、目标语zh/en原值，DeepL区域映射仅属于实际DeepL适配器。以上为下一增量必要规范，非已实现/部署或真实翻译证据。

### 原生会议去重与 MCP 返回深链验收更新（04:08）

用户最新原生 HMR 实证：会议 7 条均恢复单行，每条 2/3 份历史入口可见；这是实际 UI 修复证据。历史正文与全部版本的逐项读取仍由主线程检查，不能仅凭入口可见声称无历史损失。保持目前桌面 7.5、App 6.9、综合 7.2，不自动满分。

用户实际 browser 从 /settings/mcp?note=desktop-a639... 返回 /workspace/desktop-a639... 见“尚未缓存”。本次仅改 WorkspaceNote.tsx 与新 WorkspaceNote.read.test.tsx，不改 store、Tasks、App、FileLibrary、backend，不启动服务或操作真实云数据。源码已有 loadDetail(key,true) 的精确 GET；已确定页面状态问题是详情可存在而 baseline 尚未建立时误走“尚未缓存”分支，不能据此断言真实网络链路只有这个根因。现在冷入口/基线未建立显示读取中；完整网络失败显示原错误与独立“重新读取”，该按钮仅重 GET 原 key，不因草稿 dirty 变成提交保存。保留缓存/未提交草稿；store 已接受 GET 但离线缓存写入失败时保留准确记录可读并报告错误。增加 owner/key 请求隔离、初始化失败重试、精确响应 key 校验、MCP 返回携带原列表上下文（query returnTo 经既有导航白名单验证）。历史继续按 key 分页读取，修订变化明确失败并允许重新读取；不全量 sync、不按 title 找对象。

新增 13 项聚焦测试使用现有真实 workspaceStore 及受控 API/cache mock，覆盖冷 MCP 返回、缓存/基线过渡、网络失败重试和返回、404/无权、历史分页、缓存写失败、离线草稿保留且重试无 POST、切换路由及账号迟到响应、初始化失败/等待、MCP 上下文往返、历史分页并发修订失败恢复。13/13 通过，frontend TypeScript --noEmit 通过；未作浏览器/原生新故障实机复验。主线程下一步按真实同一 key 重走 MCP 返回，记录精确 GET 状态与重试结果，如仍失败再查实际错误而不猜标题或抢 store。

架构最新已获授权编码第一方 VINote 云翻译真实 MCP 独立 router/service/model/tests 及必要桥接；目前属于实现中，尚未部署/真实翻译验收，撤销先前“本轮完全冻结未实现”的时点结论。产品合同仍要求明确第一方/云模型、中英固定源版本/正文、实际发现与逐工具授权、确认执行、完整性与 refusal 校验、unknown 原 run receipt 只读核验，不能把正在实现写成已经成功。

### Legacy 编辑页分区与翻译入口产品确认

已直接同步设计师与架构：NoteEditor UI由设计师持有，不改业务请求。只读单标题/单正文，标题Input与正文编辑器只在编辑态，双栏须用户主动选择；同名首H1如合并仅限呈现，不修改正文/导出/历史数据。主操作编辑/保存与飞书发布，导出/版本/删除/MCP归明确内容操作情境区，不复制两套详情导航。

已定位NoteEditor.tsx:780“同步版本与工具”实际仅跳workspace；WorkspaceNote.tsx:407“工具”进入通用MCP且无mode=translation，因此翻译不可发现。最小统一：分别“查看同步版本”与“全文翻译 · MCP”，后者直达既有/settings/mcp?mode=translation&note=已确认sharedKey，保留/note/id及原query作为合法returnTo；不猜本机ID、标题或版本，不传未保存草稿。没有关联或同步未确认必须说明待完成步骤。NoteVersions本机历史与共享历史保持真实范围与全部入口，同区组织而非假合并。删除菜单根据既有能力准确称移入回收站或永久删除，不伪造本地恢复。本次仅核查/设计交接，未修改设计师文件；实现与实机验收未完成，评分不变。

最新主线程实际浏览器复验：workspace/desktop-452d...→工具→MCP→返回内容详情，正文/标题正常、无notcached告警。记录一个真实对象往返通过，不泛化所有冷启动/离线/账号切换。Legacy返回files上下文仍在设计师修复，未声称通过。

两端详情产品主次结构确认：阅读只有一个标题、一个正文；编辑（编辑时保存）与“发布到飞书”为主动作；“内容操作”内导出/公开链接或文件分享/本机与同步历史/全文翻译MCP/流程图/分类归档，危险删除末项并确认。发布、公开分享与导出不混称；可保轻量修订状态，但不再复制第二套工具条/详情导航。App当前MeetingDetailWorkspace:240“导出 / 发布”混合命名、:328原音区“使用MCP工具”与顶栏已有全文翻译入口重复，属于后续主线程最小UI收敛建议，不是本人已改。文档仅真实原件，不能露假原录音。Legacy上下文需把已验证files parent（filter/q/file/query/hash）随note深链returnTo持久传回；不能仅pathname+search丢location.state原parent。已交接设计，不抢文件。

## 最终方向下全局导航与页面职责复核（本轮只读）

本节是当前源码时点的结论，替代前面已被修复的导航问题，不回退历史证据。没有修改设计师、主线程或 store 文件，没有启动服务、操作浏览器/手机、读取凭证或执行真实云写入。五个一级职责保持用户方向：会议与笔记、文件库、插件、设置、账号；App以三个常驻Tab加头像内设置/账号承载，不额外增加处理记录、项目、归档或文件类型一级目录。历史路由保留不等于新增导航。

### 入口责任表

| 入口/对象 | 桌面实际页面与入口 | App实际页面与入口 | 产品责任及状态 |
| --- | --- | --- | --- |
| 会议与笔记总入口 | Sidebar.tsx:39→/notes，子会议/笔记；App.tsx:155默认/notes | WorkspaceNavigation.tsx:41三个Tab之一；NotesScreen.tsx:91会议/笔记子切换 | 内容归属和来源入口；总体结构源码达成，所有跳转实机未验 |
| 会议 | /meetings→Meetings与MeetingWorkbench；录制准备/麦克风/历史 | App.tsx:173 meeting NotesScreen→RecordScreen或RecordingsScreen | 录制先保存原件，之后明确选择生成；纪要/原件分责任。原生7条各单行及2/3历史入口可见已实证；逐份历史、全部录制状态未验 |
| 笔记获取 | Notes.tsx:130写笔记，ContentIntake→/generate?mode=url/file；/write | NotesScreen笔记→TextNoteScreen/NoteIntakeScreen | 写正文、链接（明确B站）或导入整理；来源清楚，不在插件配置页创建笔记。网页/PDF/DOCX有既有实证，所有来源未验 |
| 内容详情与版本 | /note/:id本机正文/媒体及本机历史；/workspace/:key共享正文/所有分页历史 | NoteDetailScreen→MeetingDetailWorkspace，保noteId/detailReturn | 同一个内容旅程中的真实数据范围，禁止复制两套主工具条，不能假称本机/共享历史已合并。共享详情→MCP→返回一个真实对象已通过；legacy新布局/完整files往返待复验 |
| 项目、归档、回收站 | Notes页内项目/归档筛选；/projects兼容视图；Notes回收站轻链接→/settings/sync#trash | Notes页内项目/归档筛选；共享回收站在账号→设置→存储与同步 | 内容组织与可恢复删除；不增加一级菜单。归档会议与回收站可达性仍有P1 |
| 文件库 | /files页内类型/query/file；FileLibrary文件信息/关联内容/原件管理 | FileLibraryScreen页内类型/query，Sheet文件信息/整理为笔记/文件操作 | 管当前设备原件、真实关联内容与导出删除。手机Word选择/旧brokenPDF来源确认取消及确定/返回Files已实证；未生成该Word，未验生成后的关联闭环 |
| 插件总览 | /connections及Sidebar飞书/MCP子页 | /connections screen→ConnectionsScreen；设置授权与插件为同一页面快捷访问 | 配置、真实安装/授权状态、选择已保存内容使用能力；同一服务快捷访问允许，不能重复维护授权 |
| 飞书 | /settings/feishu连接账号与默认配置；详情FeishuDelivery发布 | FeishuSettingsScreen；详情发布到飞书/交付Sheet | 插件配置与版本发布分开；OAuth及私人doc create/write/permissions已有实证。App交付记录全流程、通知与组织策略范围未完整验 |
| MCP与流程图 | /settings/mcp通用连接与上下文translation模式；Connections实际diagram catalog/选择内容 | MCPScreen真实MCP；ContentPluginsScreen diagram | 配置与调用分清；全文中英翻译真实MCP、固定已保存源正文、明确授权确认、预览另存版本。流程图6节点5边App正文实证有；新第一方翻译普通入口及公网运行尚未验 |
| 进度、历史与恢复 | 头像→/tasks，Tasks生成/同步/飞书/MCP；SourceTaskProgress只在DEV挂载 | 真进度/同步异常GlobalTaskStatus、头像处理历史→TasksScreen | 应从当前对象/故障进入准确原操作。已撤一级处理记录；仍有源回执/故障定位入口缺口 |
| 设置与账号 | 底部/settings：账号/空间/模型/录制/外观/数据；头像身份、处理历史、退出此设备 | 头像AccountScreen→SettingsScreen→模型/外观/存储同步/插件快捷访问 | 参数用于下一次处理、数据控制与本设备退出；账号当前主要显示身份，不能称已交付全设备撤销/完整隐私治理。App处理历史误入data已修，旧问题撤销 |

### 有限实际证据矩阵

| 环节 | 当前已达成证据 | 尚未达成/未验证 | 负责人 |
| --- | --- | --- | --- |
| 获取/生成/原件 | 既有python.org网页、桌面PDF与手机DOCX成功，两端可见同步；新手机文件Sheet与选择确认返回实际通过 | 新所选Word明确未生成；原件关联返回/导出删除全格式，媒体请求去重未覆盖 | 主线程实机与App；桌面文件设计 |
| 会议历史 | 用户native HMR7条单行，2/3份历史入口可见；本人9项聚焦测试 | 每份历史正文/原件/全部版本逐项核验；暂停/后台/设备权限完整旅程 | 主线程实机；本人stable identity投影已完成 |
| 详情/MCP返回 | 用户实际workspace/desktop-452d…→工具→MCP→返回，标题正文正常且无notcached；本人13测试/tsc | 其他对象/离线/账号切换实机；legacy新files上下文真实往返 | 主线程实机；设计持有legacy及下一页WorkspaceNote |
| 编辑/版本/插件 | App真实6node5edge流程图已更新；两端有固定源/草稿/冲突保护代码 | 所有版本标签正确、失效版本链接不得换源；第一方真实翻译执行、结果完整性、回执恢复与另存实际成功 | 架构provider；客户端专用入口持有人待主线程分配；设计UI |
| 同步/发布 | 既有共享API、OAuth和私有飞书doc create/write/permissions实证 | 完整跨端删除恢复、飞书App交付记录/通知/组织策略范围及新bundle部署实证 | 主线程；架构协议 |
| 导航/设置账号 | 一级目录已收敛；Tasks切tab保returnTo、App处理历史正确；legacy深链与App主次动作源码新修 | 表列10项P1及完整全页面返回；新手/离线/后台/冷启会话全流程 | 主线程与设计；产品只读复核 |

设计角色最新报告：NoteEditor22聚焦测试与tsc通过；本人已见state或query来源读取、files上下文持久、显式翻译、主编辑/发布与单内容操作。App当前MeetingDetailWorkspace主动作也已改编辑+发布到飞书，原音区重复MCP入口已移除，旧“导出/发布”主操作问题撤下。WorkspaceNote下一页UI由设计师接手，本人不再编辑其页面；原读取补丁需保留。架构最新冻结第一方真实MCP后端，96定向pytest与6模块compile为其报告；旧公网SHA不包含该adapter，客户端专用provision入口尚未分配/完成，不能称已上线翻译。

### 当前优先问题（10项，P0未确认；全部是P1）

| # | 分类与精确证据 | 具体触发/用户影响 | 最小处理与实施归属 |
| --- | --- | --- | --- |
| 1 | 缺失入口：[Meetings.tsx:108](/D:/projects/VINote/frontend/src/pages/Meetings.tsx:108)、[Notes.tsx:81](/D:/projects/VINote/frontend/src/pages/Notes.tsx:81) | 归档一份会议后，会议列表过滤!archived，默认笔记含archived视图仍过滤meeting；未归项目的归档会议在常规列表不可达，用户误以为丢失。数据未删，不能把不可见说成历史损失。源码明确，实机未验 | 在现会议页增加归档筛选，或明确公共归档视图包含两类；保stable key/历史/详情，不按标题补对象，不新侧栏。主线程/设计 |
| 2 | 版本深链换源：[MCPSettings.tsx:159](/D:/projects/VINote/frontend/src/pages/MCPSettings.tsx:159)、[Connections.tsx:121](/D:/projects/VINote/frontend/src/pages/Connections.tsx:121) | query明确version但该ID不存在时静默fallback默认/首版本，翻译或整理可能使用另一份正文，违反固定源要求。当前源码与架构复核，不是96后端测试覆盖 | 有指定ID却不存在时清源、禁止新调用、说明版本不可用；用户显式选择别版才继续。保原请求回执原源，不能自动换源或重复调用。客户端持有人由主线程明确分配 |
| 3 | App回执恢复入口缺失：[TasksScreen.tsx:35](/D:/projects/VINote/VINote-app/src/screens/TasksScreen.tsx:35)、[noteIntake.ts:22](/D:/projects/VINote/VINote-app/src/lib/noteIntake.ts:22) | URL/document已有owner source-request档案，但处理历史生成页读取workspace/jobs与录音，不枚举这些来源提交；离开或冷启后用户难从“处理历史”找原unknown/reserved操作。Intake自身重入恢复已有，不否认该能力 | 历史页列owner原operation状态并指向原Intake恢复；unknown/reserved仅GET原ID、accepted原task；不可猜task、自动新POST或扩大媒体去重承诺。主线程App/架构契约 |
| 4 | App原件关联内容缺失：[localFiles.ts:8](/D:/projects/VINote/VINote-app/src/lib/localFiles.ts:8)、[FileLibraryScreen.tsx:46](/D:/projects/VINote/VINote-app/src/screens/FileLibraryScreen.tsx:46) | 持久LocalFile没有note/task映射，Sheet只整理/文件操作，生成完成后不能从该原件明确打开已有正文/原处理状态，可能重复进入新生成。最新Word选择确认已通过，生成明确未做，故本环仍未验 | 用真实file ID→operation/task/note映射保历史；有内容打开原对象，有unknown仅核验，缺映射不按名字/content猜。主线程App，架构定义关联；不推翻已通过选择Sheet |
| 5 | App返回列表状态丢失：[NotesScreen.tsx:37](/D:/projects/VINote/VINote-app/src/screens/NotesScreen.tsx:37)、[App.tsx:173](/D:/projects/VINote/VINote-app/App.tsx:173)、[TasksScreen.tsx:24](/D:/projects/VINote/VINote-app/src/screens/TasksScreen.tsx:24) | 搜索/项目/归档筛选后打开详情、MCP或任务再返回，条件分支卸载后local state重建；处理历史子分类也默认生成。App文件category/query已有父级view保护，不把它说成同样未修 | 保存轻量owner/view快照和原tab，不复制数据；回到原过滤与选中来源。主线程App；列为源码生命周期问题，完整实机未验 |
| 6 | 跨页状态与故障定位缺口：[MainLayout.tsx:63](/D:/projects/VINote/frontend/src/components/Layout/MainLayout.tsx:63)、[GlobalTaskStatus.tsx:15](/D:/projects/VINote/VINote-app/src/components/GlobalTaskStatus.tsx:15)、[App.tsx:176](/D:/projects/VINote/VINote-app/App.tsx:176) | 桌面生产只见头像历史入口，当前MainLayout任务进度面板仅DEV，离开生成页缺常驻真实状态入口；App点同步/冲突状态却进默认生成分类，再找同步。idle隐藏已对，不要求恢复顶级任务目录 | 真活跃/异常才显示轻量状态，携实际对象或op及初始同步分类；readonly进入原状态，不能点击即重派发。主线程/设计；生产与App实际该路径待验 |
| 7 | 部分返回上下文仍缺：[Settings.tsx:35](/D:/projects/VINote/frontend/src/pages/Settings.tsx:35)、[Tasks.tsx:295](/D:/projects/VINote/frontend/src/pages/Tasks.tsx:295)、[SyncSettings.tsx:147](/D:/projects/VINote/frontend/src/pages/SyncSettings.tsx:147) | 设置页SettingLink进任务/插件/录制无来源；Tasks飞书记录打开内容无historyReturn；同步冲突进详情无同步parent，返回落默认笔记。Tasks切tab与大部分恢复链接已修，legacyfiles新代码已修，不重复列旧缺陷 | 只补既有合法parent/query/hash，不新增目录；飞书记录定位相应交付展示，不自动发布。统一白名单返回，主线程/设计，各路径实机待验 |
| 8 | 回收站可发现性仍不对等：[Notes.tsx:233](/D:/projects/VINote/frontend/src/pages/Notes.tsx:233)、[TasksScreen.tsx:62](/D:/projects/VINote/VINote-app/src/screens/TasksScreen.tsx:62)、[NotesScreen.tsx:81](/D:/projects/VINote/VINote-app/src/screens/NotesScreen.tsx:81) | 桌面笔记已有回收站链接，会议页没有；App删除后列表只有归档筛选，须头像→设置→存储同步找共享回收站，删除完成后的下一步难找 | 内容页轻量“回收站”进入既有section/初始视图并带原列表上下文；共享恢复不承诺恢复已删除原件或本地永久删除。主线程App/设计；跨端delete/restore由主线程实测 |
| 9 | 有意义MCP配置与调用入口未交付：[MCPSettings.tsx:512](/D:/projects/VINote/frontend/src/pages/MCPSettings.tsx:512)、[MCPScreen.tsx](/D:/projects/VINote/VINote-app/src/screens/MCPScreen.tsx)、[WorkspaceNote.tsx:407](/D:/projects/VINote/frontend/src/pages/WorkspaceNote.tsx:407) | 当前两端未见第一方provision入口，普通用户仍需服务地址/字段选择；共享详情“工具”仍通用模式，不能立即发现中英翻译。后端已实现不代表用户已能接通 | 独立明确持有人接后端真实第一方配置，区分配置/正文调用；managed不可任意改地址/凭证，discover/grant/preview/confirm仍保留。404/405待更新、503服务未配置如实报，不退假内置。设计处理WorkspaceNote显式翻译，主线程分配客户端第一方入口并部署验收 |
| 10 | 版本术语误导：[workspaceStorage.ts:91](/D:/projects/VINote/VINote-app/src/lib/workspaceStorage.ts:91)、[NotesScreen.tsx:152](/D:/projects/VINote/VINote-app/src/screens/NotesScreen.tsx:152) | 只数generated且至少1，却在列表/可访问名称标“版本V1”；编辑和新流程图已实际更新仍V1，用户会误判未同步/丢更新。本次App图正文更新已有实证，不能再当旧正文故障 | 优先显示“当前正文/历史版本”，workspace_revision明确称“同步修订”；仅完整历史可证明时才显示总版本数，不把generated计数、分页结果或fallback1当完整序号。不改内容、不删edit历史、不虚增版本。主线程App/架构统一术语 |

本轮不确认P0：未取得未经授权写入、已发生历史删除或可重复派发的新增实证。表中代码推导问题标为源码证据，实际流程未验就仍写未验；发现失效version换源不等于已实际外发了错误正文。处理目录已撤，页内文件类型和项目/归档方向不再争论。评分沿用最近有限证据的桌面7.5/App6.9/综合7.2，非全页面通过率；当前不能声称完整验收或10分。十项只读结论交主线程按持有人收敛，产品不逐点抢写页面。

责任时点更新：主线程刚明确分配设计师desktop MCPSettings.tsx/clienttype/tests第一方UI，App与部署由主线程持有，Connections不在新UI改动范围；第9项“待分配持有人”已解决，但功能实现/部署/实机仍未完成。产品已确认普通入口官方云翻译无需URL/token，真实unverified/discovery/grant/preview/confirm状态、managed固定实际schema中英预填、自定义高级、无URL凭证编辑；失效指定版本禁调用并显式重选，provision失联仅GETlist、禁用连接不擅自启用、404405待更新/503管理员未配置不让普通用户填key。此为确认设计与责任，非成功执行证据。

架构最终交接的产品语义补充（角色源码审查报告，本人未作新增运行验证）：版本优先使用“当前正文/历史版本”，workspace_revision称“同步修订”。generated计数可能缺edit/imported，且受分页/legacy缺kind影响，不能声称完整生成次数或总版本序号。第一方providerDispatched:true仅是进入可能外发阶段的保守持久标记，不证明远端接收、完成或计费；unknown仍需原回执核验。桌面非attachment Markdown图片可直接请求HTTP(S)外链，属于浏览器联网隐私边界，不是后端SSRF；没有实际请求或凭证泄露证据，AST处理安全不能外推所有图片安全，不将此增列为已确认P0。后端仍冻结；96tests与py_compile维持原角色证据。新公网owner/协议/新表RLS、模型完整中英译文、普通入口与失联原receipt须主线程新包部署后实际验收。本次只更新产品文档，未改backend/UI，未启动服务或操作云数据，评分不变。

### 当前两页交接及非会议生成目标确认

本人只读核查已见WorkspaceNote主要内容操作/单内容操作、源版本Sheet、显式mode=translation以及readError重GET分支；MCPSettings已出现第一方provision、managed固定与只读凭证、失效指定版本清空源并禁invoke。设计角色报告WorkspaceNote22聚焦测试（包含本人13读取/owner回归）、MCPSettings20与helper9通过，最终tsc通过；不重复计作本人运行。第2项桌面MCP失效版本已修，Connections.tsx:121仍fallback，故P1只保留该未改分支；第9项desktop普通第一方入口已实现，App/新部署/真实翻译仍待验，不再说desktop入口尚未实现。

主线程新实际手机证据：主次动作已收敛；版本与生成Sheet切换只一个遮罩；关联来源choice取消/确认/返回通过。属于具体交互实证，不外推全文翻译、文件生成或完整所有历史。前述Word选择流程仍未生成该所选文件。

新增生成目标产品确认：用户实际PDF→版本→生成显示“完整纪要”；源码workspace_generation.py:299无条件把minutes映射“完整会议纪要”，:306却已对非meeting采用detailed，提示目标与来源冲突。本次已明确交架构最小修正：保API template=minutes/summary/actions兼容，按与现style一致的可信source_type，meeting_recording/meeting_video的minutes为“完整会议纪要”，PDF/Word/网页/text等非会议为“完整结构化笔记”；两端仅显示对应名称，不造新枚举、不因title/taskId/媒体类型推断会议。结构化笔记依据原文主题、论点、明确步骤、结论组织，不强塞参会人/会议时间/决议或虚构负责人期限。保原生成操作/回执/历史及失败保留，修正只作用后续明确生成，不自动重跑既有请求。架构做小范围调用参数/目标与style分支回归，UI由设计/主线程持有。本人未改代码，新目标尚未修复实机重验，评分不变。

非会议目标UI交接更新：设计角色报告已仅修WorkspaceNote，isMeeting精确限定meeting_recording/meeting_video；minutes可见名称分别“完整会议纪要”与“完整结构化笔记”，value=minutes及summary/actions、业务请求/operation恢复与历史均保持。2026-10-12 04:36:27（Asia/Shanghai）其WorkspaceNote定向25/25通过（包含document/video/两种meeting来源及生成失败保留、POST仍minutes），frontend tsc exit0；此为设计角色测试证据，不能与前22/13重复相加。产品把桌面目标显示与兼容测试记为实现完成；后端目标提示修正、实际新输出与全部历史仍需各自证据，不称全流程完成、不升分。本人本次仅更新产品文档。

非会议目标后端完成交接（架构角色报告，非本人重跑）：workspace_generation.py:299-309用同一exact source_type meeting_recording/meeting_video判定minutes目标与meeting/detailed style，其余目标、枚举、claim/CAS/unknown恢复不改。test_workspace_generation_claim.py:353新增六来源×三template共18用例，覆盖实际generation/prompt/publication、标题不影响分类、稳定历史与原文保留、同operation重放不重调用；合原14项共32 passed，service py_compile通过，第一方冻结文件未改。当前源码可用于新打包，但架构明确已部署1f9524…不自动包含此增量。实际PDF新生成输出仍待主线程运行；公网health/公开配置、各客户端tests与tsc按来源记录，不代表模型可用或真实翻译成功。桌面显示和后端目标实现现均有角色回归证据，生成结果实机未验；评分不变，本人未编辑业务代码。

### App MCP翻译上下文精简产品确认与独立P1方案（待实现授权）

用户实际Sheet Schema约1232px、确认区escaped JSON全文与泛化写入/删除警告，是专用翻译旅程的信息层级问题；已确认交设计师布局、主线程App实现，本人不抢MCPScreen/App.tsx。专用上下文展示固定所选已保存正文/源版本、官方连接与必要发现/逐工具授权状态、中英选择、可读正文及目标语言核对，最终明确确认才执行；正常已授权不展示URL/token/全schema/无关开关，第一方固定参数无手填。高级管理保完整MCP连接配置与运行记录，往返保origin/note/version及原unknown。JWT仅现认证header内存，不进入参数/持久源/预览；源只body，历史失效禁止暗换最新。工具未授权不执行，结果未知仅查原run/receipt，失败可返回原内容，译文核对后保存新版本留原文，不自动飞书。固定状态/帮助/按钮slot避免异步位移。主线程报告真实第一方连接/发现已成功，但实际调用仍在验证；footer曾跳138px现已修并观察稳定，属于主线程实机证据。设计报告桌面23页测试及tsc通过，非本人运行/桌面实机。

用户要求优先独立最高P1，App intake历史连接须先方案等确认。只读发现noteIntake.ts:22已按owner+op存档；TasksScreen生成仅workspace/jobs/录音，缺源档案入口；recoverIntake与inspectIntake会写/清当前intake槽，直接从旧历史调用可能覆盖另一份在途来源。本人的具体待确认scope：noteIntake.ts增owner档案索引/精确读取及历史查询持久路径、TasksScreen.tsx生成分区挂一个新聚焦IntakeHistory组件、相关tests；不改App.tsx、MCPScreen、NoteIntakeScreen、notes/workspace store、FileLibrary或后端，不借历史入口再提交新源。该组件就地核验与查看结果，复用Tasks既有onOpen打开已保存笔记，无需父路由桥接。

方案验收：只列当前owner实际记录，一项损坏不吞全部；来源标签/状态/op清楚，旧无时间不虚构。新操作存非敏感serviceOrigin标记，恢复只对照当前已配置允许服务，不信任缓存地址发任意请求，不自动将旧未知origin改绑当前服务；generation与workspace/MCP配置不同，不从public health推导source服务已配置。unknown/reserved精确GET原op，reserved不重新dispatch；accepted查询原task，成功结果只读预览，再明确保存/打开既有笔记；失败重试须新GET确认同task failed/error+retryable后用户明确点击，不产生新op或媒体去重承诺。历史查询/保存不改清另一个current在途来源，清当前槽仅匹配同op/task且本机保存成功；owner/服务切换迟到响应不可发布。聚焦回归覆盖档案索引/坏项/owner隔离/服务不匹配、unknown404无POST、reserved、accepted同task、保存失败保留、历史不覆盖另一在途项、返回任务分区。该方案已准备但未编码，按用户明确要求等待scope确认；不把方案写成入口已交付，评分不变。

架构只读核查补充source恢复方案：当前integration.ts:8生成Origin在DEV为127.0.0.1:8900、production为空；generate/upload/source-requests/task均走该Origin，cloud workspace factory不注册note.router，因此公网workspace/MCP health不能证明source endpoint可用。生产空Origin应明确未配置，不猜共享integration地址。新POST前固定并持久非秘密source serviceOrigin，查询原op及accepted task必须对照同一来源服务；仅localhost地址相同也不能证明后端安装/服务身份相同，如现回执没有可核验serviceID则保留身份待核验，不能借共享workspace ID作源服务证据，也不为本限定客户端任务新造API。旧unknown origin仅列待核验、不跨服务POST；媒体旧分支不声称去重。App第一方provider receipt使用已有兼容别名/api/mcp-connections/first-party/translation/receipts/{runId}，canonical mcp-first-party路径在当前客户端不属shared白名单，会错误落入generation Origin，须主线程实现按合同选择既有别名。

第一方实际run 6719…新状态（架构诊断报告）：model_unavailable定位于select_model预检，两次GET已经返回可解析JSON，但默认模型与llm/available匹配或返回形状尚待白名单字段核查；不是已发生翻译模型POST失败，也不是已完成翻译。在未取得实际响应证据前不改选择模型、不假fallback、不重放原run。产品维持真实连接/discovery已成功与执行未通过分开陈述；没有实际模型结果、计费或全文成功证据。本人未修改代码或执行诊断，intake历史scope仍待用户确认。

## 剩余 P1 实施收敛与最新证据（本轮产品确认）

本节替代前面对应问题的旧状态；本人仅核查源码、向设计师交接并更新本报告，没有编辑业务或 UI 文件，没有实机操作或新增运行测试。主线程最新真实桌面证据：从 files（type=video、选中 file 保留）进入 legacy 关联详情再返回，准确恢复 video 筛选、自动打开同一文件 Sheet，三分区可见。该暖运行路径已通过，撤销其“返回未验”状态；冷启动仍未验证。App 上下文翻译专用页面已交主线程实现，不能继续按“无人持有”报告。

已撤回一项误判：SyncSettings.tsx:88 虽提供固定 fallback，Layout/PageReturn.tsx:9 会读取并验证 location.state.returnTo；Notes 已传的回收站来源可被采用。不能按 fallback 字面判断这条返回坏了，也不因此修改 SyncSettings。桌面 Tasks.tsx:148-151 已列当前 owner 的 source 回执并可恢复原 operation；“没有桌面来源历史入口”不成立。App Tasks 未接 intake 档案是另一项独立缺口。

### 最小实施方案及归属

| 优先顺序 | 精确缺口 / 源码依据 | 产品方案与验收条件 | 实施归属 / 状态 |
| --- | --- | --- | --- |
| 1 | 归档会议无法从会议列表直达。Meetings.tsx:108 排除 archived，Notes 默认笔记范围也排会议 | 仅会议页增加“未归档 / 已归档”，archived=1 写入 URL；保其他 query、现状态筛选与返回。未归档保录制、处理中和纪要；归档只列精确 meeting_recording/meeting_video 的已归档内容，不混入独立本机原件、不在此生成。按当前内容归档状态筛选，沿用稳定身份投影和完整历史，不把历史拆成新行、不按标题去重。无结果提供准确空态，归档不删除原件。验收归档后可找到同 key、打开各历史、返回仍为归档筛选，原件仍存在 | 桌面设计师已确认持有 Meetings / MeetingWorkbench 与聚焦 tests；父级实机。尚未宣称实现完成 |
| 2 | 恢复任务的来源摘要受新路由 mode 影响。NoteGenerator.tsx:104 接受旧 receipt，:128 仍按 route 设置 mode，:437 URL 分支忽略 sourceTitle；坏回执错误态 :442 没有处理历史链接 | 只改 UI：receipt 存在时，标题下始终显示“原任务来源”、真实来源类型、sourceUrl/sourceTitle、原 workspace 和 accepted/reserved/unknown；运行中也可核对。恢复态不显示可误认新任务的来源表单；原元数据缺失明确说明，不能用路由或新 selectedFile 补猜。recoveryUnavailable 显示保留回执与现处理历史链接。原核验/重试权限、锁、POST/存储/状态恢复不改；当前模型设置只标为下次新处理，不冒称旧任务模型。验收 document receipt 从 URL 路由进入仍显示原文件；损坏回执可进入历史且零 POST；unknown/reserved 仍只核验原请求 | 桌面设计师获确认 NoteGenerator UI / focused tests；不动冻结 Tasks / MCPSettings / WorkspaceNote。实现与实机尚待证据 |
| 3 | 设置多层来源链未完整传递。Settings.tsx:35 SettingLink 不带 state，:85 setParams({tab}) 重建 query | 内部切 tab 保现合法上下文；外部跳转带当前设置 tab 的完整来源，二级返回沿已有 resolvePageParent。区分返回设置与返回原内容，不新增目录，不把账号身份页扩成虚假会话管理。验收 storage→同步/处理历史、spaces→团队、上下文进入设置后切 tab 均回正确来源。已正确的 Notes→回收站 state 返回不作无效修复 | 桌面设计师后续限定项；涉及冻结 Tasks 的目的页修复另交父级，不抢文件 |
| 4 | 插件总览失效指定版本静默换源。Connections.tsx:121 仍 fallback 当前默认版本；MCPSettings 同问题已修 | 指定 note/version 时精确匹配；找不到则禁调用，解释版本不可读并允许明确重选。只有未指定版本的新选择流程可预选默认。不换正文、不自动执行。验收错误 version 不调用工具、重新明确选版本才可继续，返回原列表/详情上下文仍在 | 父级另指定 Connections 持有人；不占设计师已冻结页面，不重复修 MCPSettings |
| 5 | App intake 历史缺口与历史查询覆盖当前槽风险。noteIntake.ts owner+operation 档案已有，TasksScreen.tsx:65 生成分区未接 | 在现处理历史生成分区列真实 owner 档案，固定原 operation 与服务来源；unknown/reserved 只 GET，accepted 查原 task，明确失败才按原同 task 权限重试。历史查询/保存不覆盖或清除另一在途 current；未知旧服务身份只读待核验，不借 workspace health 猜 source 能力。详细合同沿用上节，不再新增任务一级入口 | App 父级后续；此前本人限定方案未编码，不再占父级 App 文件。验收 owner/服务隔离、坏项、零自动 POST、另一在途项保留 |
| 6 | 状态入口与故障分类不对应。MainLayout.tsx:64 进度组件仅 DEV；App GlobalTaskStatus.tsx:15 同步/冲突，App.tsx:176 点击仍进默认生成分类 | 桌面生产仅真实活跃/异常显示轻量入口，复用已知任务/同步状态，不把开发诊断面板上线；App 同步状态直达现同步分区/冲突，生成状态直达原操作。空闲隐藏，点状态不执行重试。回到来源保对象和筛选；验收离开生成页可找原任务、点同步故障不用再猜分类 | 父级协调两端布局/Tasks 持有人；本轮产品不修改，生产实机未验证 |
| 7 | App 原件生成后的关联闭环未交付证据。localFiles.ts:8 LocalFile 无 note/task 映射 | 同真实 file ID 保存 operation/task/已确认 note 关联；有结果打开原内容，unknown 先核验，不把整理按钮默认当再生成。同文件可有多份真实内容，用关联选择而非覆盖旧项。失败原件仍可导出；删原件不删正文，删正文不伪造原件丢失。旧无映射明确说明，绝不按名字或内容猜。验收明确一次生成→回原件→开已有正文→失败/删除两种关系 | App 父级与架构契约。已通过 Word 选择、旧来源确认和返回；所选 Word 未生成，不能据此称此闭环通过 |
| 8 | App 列表/任务返回与删除恢复下一步不清楚。NotesScreen.tsx 本地筛选状态、TasksScreen.tsx:23 默认分类；会议页和 App 内容列表缺轻量回收站入口 | 保当前 owner 的列表视图与任务分类快照，回原搜索/项目/归档范围；列表放轻量回收站，进入既有同步回收站分区并返回原列表，不加侧栏。共用既有软删除/恢复，不承诺恢复已删原件或本地永久删除。验收筛选→详情/MCP→返回、删除→回收站→恢复→同列表 | App 父级后续；桌面会议页轻量回收站由设计师评估复用已授权页内范围。跨端恢复有父级实测计划，不能外推未走路径 |
| 9 | App “版本 1”不是完整版本数。workspaceStorage.ts generated 计数与 NotesScreen.tsx:134/152 的 V1/fallback 标签 | 使用“当前正文 / 历史版本”；workspace_revision 叫“同步修订”。没有完整历史证据时不显示总版本数，不把 generated 子集、分页数量或 fallback 1 当正文版本。编辑/流程图后正文更新与该标签问题分开，保全历史 | App 父级；现已实走流程图更新，标签误导仍待修，不能再次误报旧正文未同步 |
| 10 | 真实翻译未通过是交付阻塞，不是再加一个假插件。第一方已连接/发现，原 run model_unavailable 位于模型选择预检 | 继续真实第一方 provider 诊断，明确官方云模型；保专用上下文授权、固定版本/body、中英、可读预览、明确执行、结果核对另存。无可用模型如实显示服务不可用，不假翻译；unknown 只读原 receipt，不重放。验收真实完整中英结果、原文历史留存、失败返回和未知恢复；不得用部署 health 或 schema 发现代替 | 架构 provider / 父级部署与 App / 设计师桌面已实现入口。模型结果尚未通过；此项与菜单收敛分别验收 |

第 2 项链接边界已直接告知设计师：navigation.ts 当前不允许 /generate 作为 returnTo，不能把 /tasks?returnTo=/generate... 当作有效回程承诺。本次 UI 补丁用已验证的原 notes/files/meetings parent（保 query/hash）进入已有任务历史，再通过现同 operation 恢复链接回原任务；若确需直接回生成页，另交严格路由契约，不顺手扩大白名单。

### 共同达成 / 未达成 / 负责人 / 实机证据矩阵更新

| 环节 | 共同状态 | 负责人 | 实机证据与界限 |
| --- | --- | --- | --- |
| 桌面文件→关联内容→返回 | 本次具体路径达成 | 父级实机、设计师 legacy UI | video 筛选、同一 file Sheet 和三分区真实通过；没有冷启动证据 |
| 会议身份与完整历史 | 单行达成；归档入口和全部历史正文未达成验收 | 设计师页内归档、父级实机 | 原生 7 条各单行、2/3 历史入口可见；不能只凭可见称所有历史内容无损 |
| 源操作持久恢复 | 桌面已有入口；恢复摘要/App 历史仍未达成 | 设计师摘要、父级 App、架构协议 | 聚焦代码/测试证据与已有 source 请求合同；完整两端冷启/换服务未验证，媒体与首次文件注册不宣称去重 |
| 插件配置→上下文调用→译文保存 | 配置/发现已达成具体证据；真实译文未达成 | 架构 provider、父级 App/公网、设计师桌面 | 真连接/discovery 成功；model_unavailable 预检失败，无完整翻译或真实保存结果证据 |
| 设置/账号/归档删除恢复/列表返回 | 具体已修路径保留；全局仍未完成验收 | 各限定 UI owner、父级跨端实机 | 不把 PageReturn fallback 当现缺陷；不把暖返回外推冷启动、退出/换账号或后台恢复 |

无新增已证实 P0。现有评分保留桌面 7.5、App 6.9、综合 7.2，初审 6.8 为历史时点；这些是有限证据的产品评分，不是全页面通过率。上述待实施、待部署、待实机项目未关闭前，不能给可验收 10 分。产品方向已明确交接，不以增加报告或再换导航代替修复。

### App 列表限定方案：待用户确认文件后实施

新分工：产品持有列表版本术语、归档筛选与返回状态方案；父级持有 App.tsx / MCP / 详情 / 文件库 / intake。拟仅修改 src/screens/NotesScreen.tsx 和 __tests__/NotesScreen.test.tsx，用户明确要求先确认；本次尚未编辑这两文件。已直接向架构师询问 all-version 总数与缓存快照语义，尚未把询问写成其已认可。

源码明确：backend workspace_service.py:42-47 的 version_count 是按 owner/key 统计所有 WorkspaceVersionDB 行，不限 generated，独立于 :50-64 详情分页；但这是读取时快照，并不承诺当前最新云端状态。App workspaceStorage.ts 的列表 Note.version 是已载入 generated 子集且 fallback 1，Note 类型没有传递 version_count。限定不改 store/types/请求时，列表及无障碍名称直接改“当前正文 / 已保存正文”，不显示 V1、总版本数或伪同步确认；不逐行读取历史、不增全量同步。真实总数后续仅在相应缓存快照及完整语义传递后展示，不拿数组长度代替。

归档作为独立状态“未归档 / 已归档”，与笔记类型、关键词、项目可组合；会议精确按 meeting_recording / meeting_video 归属，避免 startsWith 猜未知类型。归档空态准确，不移除历史或原件。返回状态拟在该组件内部保当前运行的轻量视图快照，按 owner + kind + 固定项目隔离，保搜索、类型、归档、项目与列表位置；不存正文或 token、不改 App 根路由，不宣称冷启动恢复。切账号/卸载后迟到读取不得污染另一个视图，恢复快照前不误写默认值。清除筛选尊重固定项目边界。聚焦验收包含真实五条 edit 历史却 Note.version=1 时不露假总数、两种会议来源与普通笔记归档、归档+类型+项目+搜索组合、卸载返回恢复、会议/笔记/项目/owner 隔离、坏数据或迟到读取、同步失败仍保可读正文。待用户确认写 scope 后串行运行聚焦 Jest，不重建原生、不修改父级页面。本节是待确认方案，不是实现/实机证据，评分不变。

架构已直接确认上述方案：version_count 还包括 __vinote:current:/saved: 自动快照，不等于手工编辑次数；优先“当前正文”，只有确已持久缓存的来源才称“已保存在本机”。快照仅白名单视图字段，owner 验证完成后才读写，key 精确 owner/kind/initialProject；账号变化先清旧 rows。每轮异步和订阅绑定 owner 与递增 epoch，切账号、props 变化或卸载提升 epoch，提交前再次核对真实 owner，防 A→B→A 老响应重新命中相同字符串。项目初值变化切换独立快照，清筛选保持固定项目。回归加入迟到旧账号响应、logout/return、同账号不同项目隔离。此为架构只读确认，本人仍未改组件或测试，用户文件 scope 待确认。

### App 翻译真机反馈后的产品精简确认

设计师报告已查看父级 app-translation-context-redesigned.png：三项完成状态仍各占 48dp、原调用恢复信息红色内部裁切、主按钮仍叫“全文翻译当前笔记”、来源缺可见固定版本说明。本人未操作或查看该真机页面，按设计师明确图像证据认可最小修订，由父级持有 App 实施；设计师继续桌面两个 P1。

服务卡保真实服务名、连接/逐工具授权短状态与单一“连接与授权”入口；已授权时管理退为高级文字。静态状态不用触控尺寸，48dp 用于可触控对象。配置用单 Sheet 完成，关闭后才打开正文预览 Sheet。模型状态单独解释，发现成功不能标健康，model_unavailable 是 select_model 预检失败/待核验，不能据此声称模型 POST 失败或新增未经实现的健康探针。主操作“预览翻译”；恢复原 run 的信息放独立中性可读卡，失败可查看原调用，unknown 只核验原 GET、不自动再次 POST、不借预览改绑原来源。固定来源展示“当前正文 / 所选历史”和可信版本绑定，正文可展开；没有时间写“时间未记录”，不单因时间缺失阻断。只有无法核验已保存正文的固定版本或既有 baseline revision/content 绑定时才禁调用并引导读取。已有 run 沿原 source/tool/args，不改为当前最新正文。保稳定底部操作位置和分步骤确认/另存新版本。此为方向确认，未取得本次修订的实现、实机或真实译文成功证据，评分不变。

### App 列表文案限定补丁实际交付

用户已确认独立列表/测试范围，本轮按最新要求先收敛版本术语：仅修改 NotesScreen.tsx:134 可访问标签与 :152 可见摘要，统一“当前正文”，不把 generated.length/fallback1 当全部版本数或当前版本序号，不伪造全量版本/同步状态。Note 对象与正文、打开原 ID、归档/列表请求保持；归档组合与返回快照方案本轮尚未实施，不算随此补丁完成。父级 App.tsx / MCPScreen / NoteDetail / FileLibrary / Intake 均未编辑。

NotesScreen.test.tsx 新增4项（计数1/7/缺失及详情目标与无额外读取），Red先4 failed+既有8 passed，修正后12/12 passed，串行Node heap512。受控用例保持最新编辑正文和原对象，不代表本人读取了实际用户五份历史。列表 diff --check exit0；全App tsc --noEmit 当前失败，明确 MCPScreen.tsx(169,563) TS1005 缺右花括号，父级持有文件，本人未抢改。没有真机/冷启动复验、不启动服务、不提交。维护既有App开发档案，评分不因文案补丁自动上升。

设计师新交接桌面两P1已实现并聚焦回归：会议stable identity聚合后按当前代表归档过滤（7 Meeting+8 identity为角色报告）；NoteGenerator仅恢复UI，17项与后续6项针对复测、最终frontend tsc角色报告通过，后续6不能再冒作新增17之外全部独立测试。父级额外授权WorkspaceNote中文取消等27项角色报告通过。以上均尚待父级实际新UI复验，不能把角色测试当产品本人实机。

架构新只读实际模型元数据结果供主线程交接：当前账号本机选 codex/gpt-6-luna 且 available，public default llm_model 为 null；本机个人偏好不自动成为公共owner偏好。架构准备新增真实 MCP 工具可选 model 参数与 owner-scoped models GET，显式可用model优先、未传只用验证默认、不取首条fallback；参数须绑定确认 fingerprint，schema变更需重新发现/授权，旧run6719…不能replay。该准备不是已部署成功或本轮列表改动，客户端字段由主线程负责。

架构随后确认后端最小修正已实现：GET /api/mcp-connections/first-party/translation/models 需本人已 provision 连接，现 owner Bearer / Cookie 既有 integration proxy 返回 providerId=vinote-cloud-translation、modelParameter=model、models（id/modelType=llm/runtimeStatus=available）及 defaultModel:string|null；无凭证或本机偏好假同步。vinote_translate_text 新 optional model 参数纳入预览/确认 args hash，显式不可用直接失败，未传仅用验证默认。新 schema 必须重新 discover + grant；新明确调用可携当前用户选择的可用 model，不重放旧 failed run。架构角色报告 67 firstparty 测试通过，通用 MCP 与32 template 回归当时仍在串行执行，不宣称已通过、已部署或真实译文成功。父级负责客户端接字段与实际验收，本人只转交合同并记报告，没有扩大列表补丁或修改 MCP。

最终交接更新：架构已冻结后端，firstparty68 + generic MCP47 + template32 共147 passed，py_compile/diffcheck通过，为架构角色证据；完整下一包需包含模型目录/参数增量与非会议模板修正，尚未部署或真实模型POST。设计师获最新人类授权后接桌面模型目录与确认参数，39聚焦测试角色报告通过，其当时 tsc 仍在串行检查。仅 validated default 预选，null明确要求用户选择；目录失败/所选模型失效禁准备，durable args与预览绑定同model，旧schema重新发现/授权，旧失败run只读恢复。设计师实际查看App新图确认三个完成行消失、服务短状态与原调用卡分离；本人未查看或操作真机。产品确认历史失败卡可称“上次翻译尝试/原调用”，但当前新运行不能一刀切叫上次；模型与语言同参数区。单Sheet/硬件返回及真实译文保存仍待父级实机，评分不变，无新增scope。

### 最新用户实机证据与整体优先未验收项

用户明确实际通过：Native WorkspaceNote 取消生成后返回正文且没有残留 Dialog；App compact 来源、单层配置 Sheet、GET 真实 available 模型、显式选模型进入预览；App 列表实际显示“当前正文”，没有错误“版本1”。这三条标为对应具体路径通过，撤销其未验状态；不外推真实译文、冷启动、所有返回路径。

本人的列表业务文件实际变化仍只有 NotesScreen.tsx:134 accessibilityLabel 与 :152 可见摘要两处，“版本 {item.version || 1}”改“当前正文”；未改 Note.version、正文或总数，也未编辑父级 App.tsx/MCP/详情/文件库/intake。对应 NotesScreen.test.tsx:113-140 新4项，连原8项共12/12实际通过，覆盖计数1/7/缺失时不露假总数、最新正文和原对象不变、打开原详情ID且不增加读取。本轮没有重跑全树 tsc，先前 MCPScreen 语法阻断是当时记录，不据此断言当前仍存在。归档组合和组件返回快照尚未实施；当前源码仍是旧本地 query/filter/project 状态，不把文案真机通过算作返回状态修复。

整体优先验收收敛如下，由父级实机，产品不再新增目录或重复转述角色交接：

1. 真正翻译执行→完整中英结果核对→另存新版本→原文/所有历史保留→另一端可见。当前只确认配置与预览；unknown保原run核验、失败不覆盖原文仍需实际异常路径。
2. App 原件→明确生成→关联已有正文/原任务→回原文件；失败原件可导出，删除原件不删正文。Word所选生成仍未实走，不能用来源选择Sheet通过代替关联闭环。
3. App intake档案进入已有处理历史，冷启动/后台/失联恢复原op/task且不自动POST，另一在途来源不被覆盖；媒体/首次原件注册覆盖边界如实说明，不能称全入口幂等完成。
4. App筛选/归档/项目→详情或MCP→返回原列表状态；桌面新归档会议和来源恢复UI实走；回收站delete/restore返回同范围以及逐份历史读取完整。已通过的文件库暖返回与单行会议不重复报故障。
5. 飞书真实交付记录在App可读、失败按原步骤恢复；同步冲突/离线/账号切换回正确对象与类别，状态只有ack后称已同步。单例私人doc发布及双端正文已有实证，不等于这些异常路径全部通过。
6. 两端完整录制生命周期（权限取消、暂停/停止、未保存退出/后台、原件回放）、新手账号/会话过期与生产配置状态。已有具体录制或登录证据保留，尚未取得整套原生/冷启动覆盖；不存在的账号安全/隐私功能不冒称已交付。

当前无新增已证实P0；评分仍桌面7.5/App6.9/综合7.2，不以逐个截图或代码通过推算满分。以上是明确未完成验收的环节，不全部等于已确认功能故障。

### 另存译文的账号绑定条件风险（P1，未实测）

架构最新独立审查提出，本人只读核对当前 MCPScreen.tsx:224 与 notes.ts:75-84 后保留该风险：成功结果保存先 getNote(id)，调用 editNoteContent(id,value,pending.source)，expected intent owner 未传到笔记写入口；editNoteContent 从调用时当前账号构建 namespace，baseline 只比较 content/workspace_revision。若旧A异步保存续行时已登录B，B恰有相同id与相同baseline，存在先写B正文后persistMCPIntent(A)才拒绝的条件路径。没有实际复现、没有证实越权发生，不升为已确认P0；父级持有两文件，本人不编辑、不启动测试。

最小产品验收合同：译文只能保存到原 intent 所属账号和固定源笔记。父级可给 editNoteContent 增 optional expectedOwner，入口与每次写前核对真实当前owner，namespace必须绑定expectedOwner，正文与历史均不能写入另一个账号；MCPScreen在保存开始固定原owner与epoch，异步读取/保存后检查owner、mount/epoch再发布状态。既有baseline CAS、历史保存与重复保存逻辑保留，不能靠最后intent持久化替代前置笔记授权。聚焦回归条件为A原run→切B且同id同baseline→点击/迟到保存必须拒绝，B正文和历史零写；同owner正常另存保原历史、保存失败保持译文与原run；切账号/卸载迟到响应不报已保存。本项加入整体验收第1/5项，在真实译文成功之外单独验证，评分不变。

架构最新已落实 notes.ts 第4参数 expectedOwner（只改 notes.ts 与新 notesOwner.test.ts，未改 MCP 页面/后端）：namespace 与 workspace读取固定originalOwner，入口、读取后和历史/正文写前后 guard，保 history-first 与 baseline CAS。角色报告新12+既有7共19/19串行 Jest 通过；旧代码先Red 7失败，其中同ID同baseline切B写入路径在受控测试复现，因此风险已有测试证据，仍未实测用户账号越权发生。父级 MCPScreen须传冻结原intent账号给第4参数并保页面owner/mount/epoch迟到结果隔离；此调用端接入与真实保存当时尚未确认。架构单次tsc当时待执行，不声称当前全App类型通过。本人只转交合同与记证据，没有改父级文件、跑新增测试或替代真机验收。

## 当前验收交接总表（最新用户实走证据，替代对应旧状态）

本人只读与限定组件测试证据、用户真机回报分开标注。当前不能给全产品10分；最近有限评审分桌面7.5、App6.9保留参考，不用新截图自动升分。

| 环节 | 已达成与证据 | 仍未验收 | 下一步 / 负责人 |
| --- | --- | --- | --- |
| 导航与笔记入口 | 用户最新native新版笔记入口、PDF详情实走；App列表“当前正文”真机通过；本人列表12测试已通过 | 全主页面冷启动、账号/离线返回没有整套覆盖 | 保现会议与笔记/文件库/插件/设置/头像；父级实走，产品不换目录 |
| 详情版本与生成 | native版本Sheet→generation唯一Dialog→取消返回正文，无Dialog残留，用户实际通过 | 非会议新完整结构化笔记输出、全部历史逐份读取仍未确认 | 父级选一份真实PDF生成核对并检查历史，不重跑旧unknown |
| App翻译配置与执行 | 用户实际单层config→硬件back→footer预览新请求，GET available模型选luna→真实云MCP完整英文成功，DAG6节点5边保留；旧failed未replay | 中文方向、正文完整性的更多样本不是本次单例结论；保存回执未取得 | 当下先完成同run保存及跨端核对，不扩大新工具 |
| 译文保存账号安全 | 用户确认19笔记库+9MCP测试及tsc通过，owner绑定修复有测试证据 | 用户最新明确点击Save后尚无真机保存回执，跨端仍在走 | 父级核对本机新版本/原文历史、ack后另一端同正文、重复保存不再写；失败保译文 |
| 桌面原件与关联返回 | 历史实证桌面PDF生成手机可见、手机DOCX桌面同步；桌面video筛选→关联详情→回同file三分区Sheet通过 | 文件删除/失败导出全部样本不完整 | 已通过暖返回不重复当故障；缺项父级补证据 |
| App文件原件闭环 | Word选择、旧brokenPDF来源确认取消/确定、回Files及三分区真实通过；文件库controlled真实保留 | 所选Word未生成；原件→已确认正文/任务关联、失败导出与独立删除未闭环 | 父级后续实现真实file关联，不按title猜 |
| 来源持久恢复 | 桌面现Tasks有owner+operation历史，source客户端与恢复锁已有聚焦测试 | App历史未接intake档案；后台/冷启/失联/服务切换未完整实走；媒体和首次注册不承诺全去重 | 原op/task只读核验，reserved不重dispatch；父级后续 |
| 归档、删除与列表返回 | 桌面会议去重原生7条单行、2/3历史入口可见；桌面归档UI已实现测试；App受控view契约本次完成16测试 | 桌面归档实走/所有历史正文、跨端恢复返回范围；App父级接view/退出重置及实机卸载返回仍待确认 | 父级接分类state及实机；本组件不改根路由 |
| 飞书交付与同步 | 既有真实OAuth、私人doc create/write/permissions和跨端正文已通过具体证据 | App完整交付记录、异常步骤恢复；冲突、离线、会话切换、状态正确定位未全面验 | 父级以原记录验恢复；同步只在ack后标已同步 |
| 录制、账号与发布形态 | 保留既有具体录制/登录证据；当前无新增已证实P0 | 权限取消/暂停停止/后台/未保存退出全套、冷启动会话与production内容生成配置未完整验 | 下一阶段分设备/发布形态核对，不靠HMR代替安装包验收 |

### 本次唯一新增实现：NotesScreen 受控视图契约

用户限定本项独立scope，本人只改 NotesScreen.tsx 与对应 NotesScreen.test.tsx，未改 App.tsx/MCP/详情/文件库/intake。导出 NotesView={query:string,filter:string,project:string}；可选 view/onViewChange，父级每类别独立state持有并logout重置；传view时直接读取父级值，不用挂载effect回写默认值，无view仍沿用本地交互。initialProject始终约束实际筛选与回调project；清筛选仅回query空、filter全部和固定项目，不调用onChangeKind。筛选/回调不触发新读取、同步或目录，不增加持久正文/身份缓存，不承诺冷启动。

新增4项覆盖controlled首帧/不回写、父级会议笔记独立快照卸载返回、固定项目与清筛选类别不变、父级reset即刻生效且不加请求；旧实现先3 failed、13 passed（reset用例后来加强首帧断言，未称全部4项均先失败）。最终16/16通过，App tsc --noEmit exit0、列表diffcheck exit0，均本人串行Node heap512执行。

替换筛选JSX长行期间出现短暂语法错误，用户实机HMR红屏报告，修正后完整Jest/tsc已通过；本人承认该编辑问题。随后最终文件完整保存，React Native Babel preset parse两次exit0，最后一次针对最终保存文件。不能声称本人看到红屏消失；父级需恢复实机验证Save回执。后续同类JSX修改保持完整有效行的原子补丁，不让中间结构进入HMR。

### 整体剩余P1与下一阶段

| 顺序 | 剩余项 | 最小关闭条件 |
| --- | --- | --- |
| 1 | 译文保存及跨端闭环尚无回执 | 本机新版本、原文历史留存、重按不重复写、共享ack、另一端同正文及DAG；失败可继续看结果 |
| 2 | App列表返回父级尚待接入/实走 | 分别传meeting/note view与onViewChange，账号退出重置；搜索/归档/项目→详情/MCP→返回原范围，清筛选不换类 |
| 3 | App原件关联正文与来源历史未交付完整闭环 | 真实file/op/task/note关联及已有结果直达；原件失败仍可导出；历史不覆盖另一current，unknown/reserved仅原GET |
| 4 | Connections指定失效版本仍静默fallback（源码121） | 失效源禁调用，说明原因并明确重选，不能自动取默认正文 |
| 5 | 全局状态与多层返回上下文剩余源码缺口 | App同步/冲突入口直达对应分区；设置切tab/多层保来源；已有正确PageReturn路径不重复修 |
| 6 | 归档/回收站恢复与全部历史实走覆盖不足 | 同key所有版本可读，恢复回原列表范围；不承诺恢复已删原件或本地永久删除 |
| 7 | 飞书异常、离线冲突、会话与录制/正式包矩阵未完成 | 以当前真实任务逐条补证据，区分可重试与unknown；按实际能力标不可用，不伪造新手/账号安全能力 |

当下验收窗口先稳定当前HMR、完成已成功英文译文保存跨端与父级controlled接入，停止新增功能。下一阶段先补App原件关联/来源历史/准确状态返回，再核对失效版本和归档恢复；最后按会议/笔记/文件/插件/设置账号组织双端冷启动、离线、失败和正式包回归。不新换导航、不以评分替代关闭条件，不把未验收一律说成已发生故障。

## 父级实机保存与跨端结果更新（代码冻结，仅review更新）

证据来源为父级实际Android与桌面浏览器观察，经本线程交接记录；不是产品角色本人操作，也不将其简写为“用户声明”。本节替代前面对应“尚无保存回执/跨端待验/RootApp未接”的时点状态，不代表全产品通过。

| 验收项 | 当前结果与父级实机证据 | 适用边界 / 剩余 |
| --- | --- | --- |
| Android真实MCP英文翻译 | synthetic PDF正文716字符，明确选择模型后真实英译成功 | 仅此具体样本与英文方向；不能外推任意长文、中文方向或所有provider |
| 明确保存新版本 | 父级Android点击明确保存按钮后，按钮实际显示saved | 此次保存反馈通过；全部历史逐份核对、异常/重复保存真机覆盖仍未完整确认 |
| 同正文桌面可见 | 父级桌面浏览器实际读取同一正文，已同步revision4，英文正文visible | 此次Android→桌面浏览器保存与同步闭环通过；revision4是同步修订，不是总版本数，不外推所有设备/离线冲突 |
| 旧失败调用不重放 | 原6719failed未replay | 此旧调用路径通过；其他未知/中断调用恢复仍依原run核验，未取得全矩阵实机覆盖 |
| NotesView父级接入 | RootApp已接controlled，父级6导航tests与tsc通过 | 不再列未接入；手机App重启核验中，跨重启筛选/项目/会议笔记隔离及logoutreset实际结果尚待观察 |

产品当前明确关闭：本synthetic PDF英文翻译→明确保存→同正文桌面浏览器同步可见的具体验收链，以及RootApp契约接入的代码/测试项。仍保留整体P1：NotesView重启/返回实机核验；App原件与正文关联、source档案处理历史；Connections指定失效版本fallback；准确状态分区与多层返回；归档/回收站完整历史及恢复；飞书异常、离线冲突、会话与录制/正式包矩阵。此前“保存无回执/跨端仍在走”不再是当前阻塞，不能继续机械重复。

当前仅修改本review，全部代码冻结；没有新增测试、运行、部署或产品本人实机操作。有限评审分保留桌面7.5/App6.9作为此前评审参考，不因一个成功样本宣布10分或全产品通过；下一次评分须按明确关闭的整体验收范围复评。

## 冻结后的版本历史UX提案审定（仅产品/设计review）

父级DOM实际发现 current:3 / saved:3 / edit-revision 三条同时间，换标签仍像重复。设计师据此提出来源与版本Sheet内结构化展示，本人核对现 WorkspaceNote.tsx:743-807 与 workspace_service.py:132/166 的快照生成语义，认可下述限定提案；本次不写代码，不把设计当已交付。

保现Sheet、NativeSelect及现读取/比较/恢复/默认/生成行为，不新增入口弹层。NativeSelect分三组：当前正文（现空值）、生成版本（仅真实kind=generated）、编辑/保存与其他记录（自动快照、普通edit、imported、未分类均独立保留并准确说明）。空组不显示，各已载入真实条目正常可选，不自动折叠、不按时间/标题/正文去重、不造三项V编号；不把译文kind=edit推断成生成或翻译专属类型。

“当前正文”卡仅展示当前已保存状态、已知同步修订与正在查看范围，不新增第二份正文编辑器；dirty区分本机未保存草稿。显式返回当前沿现versionId空值。默认标记只匹配metadata.default_version_id的真实ID，不按相同正文或当前选中猜；默认ID尚未载入如实说明。历史__vinote:current条目称自动正文/修订快照，不能称此刻当前正文；__saved按实际语义说明写入前正文快照。普通edit不按同时间自动归属于某快照。

选中后显示真实记录含义、完整时间或“时间未记录”、短正文预览；若原始全文严格相等，可说明“正文与当前正文完全相同”，仍保独立记录。现ID/parent/evidence放可展开记录详情，无字段不造。选择仅阅读；比较先关Sheet再开现Dialog，取消保原选择；恢复/设默认仅改解释，不改变确认和写入业务；历史选中时沿现返回当前后才可新生成的限制。

解冻门槛：父级先确认视觉，之后才授权WorkspaceNote与聚焦tests静态UI范围。验收三条同时间记录全部可选且含义有区别，所有已载入条目ID/相对顺序/默认ID/parent/evidence保留、原文及历史无写入；取消与dirty不产生新请求。全历史未读完不能声称条目数量等于全量。该项是保存历史的理解成本P1，不据此认定数据重复损坏；代码冻结与整体评分保持。

### App紧凑入口与列表返回最新验收（短更新，仅review）

本人实际查看新版 data/workspace-bundles/app-notes-current.png：两个来源卡并排，B站/网页/公开文档与PDF/Word/音视频提示保留，写笔记次按钮，当前正文标签及三条笔记可见，图中无红错或loading。80dp入口高度按父级实现交接记录，非从截图像素推算。父级实机确认detail返回立即保三条cached rows、query=pdf→详情→返回仍pdf、meeting archive与notes视图独立；对应暖返回和分类隔离已通过。跨重启默认重置属于视图行为，无业务持久要求，不声明filters跨重启已持久化，也不继续列为本轮阻塞。

父级集中48 focused App测试通过（NotesScreen18 / root6 / ownerlist12 / oldowner12），App及frontend tsc通过，非本人本次重跑。本次仅更新review、未改代码。先前列表受控契约“父级未接/返回未验”与“20秒空loading”不再作为该实走路径的当前问题；不外推所有设备或异常耗时。剩余重要P1包含桌面来源原件入口误开旧正文（须核验真实owner关联后直达文件库，0match仅当前设备未找到可核验关联）、App原件关联/来源历史及整套异常回归；全部产品仍未完整验收，不抬满分。

来源职责P1短更新：设计师按父级新授权已实现source-only接线，WorkspaceNote先关来源Sheet再以真实local note关联进入文件库；文件/录音按实际note_id/noteId筛选，无匹配说明且无旧正文fallback，默认不自动开文件Sheet，点真实文件ID后才操作，返回保原workspace上下文。两组新focused tests与tsc当时未跑，父级实机未完成，因此记“已实现、待验”，尚不关闭P1，也不声称解决同task多notes漏关联。App新版截图已查看三row/并排入口/次写笔记；独立账号行顶部留白仍在，窄屏/大字未知，留后续视觉验证。本次仍仅review，无业务代码/后端/数据修改。

### 最新限定关闭：source职责与手机Header（父级实机证据）

父级已实际走通 workspace来源Sheet→files真实note关联→0match准确说明未找到，无旧正文fallback→返回原workspace当前英文r4；关闭该具体source职责P1。该synthetic PDF属于旧docbytes路径，仅提取正文、未持久原件；不能从text补造PDF，不判为最新入口丢失。最新版NoteGenerator先注册真实fileid路径保留，此样本不替代新版有原件场景与多候选关联的全部验收。父级集中71 desktop focused通过、frontend tsc通过。

父级手机回看确认头像已与Header同行，只有真实同步忙时出现globalstatus行，无空账户行；19 Notes+6 Root及App tsc通过。此前独立账号行留白问题在该实走状态关闭；窄屏/大字及其他异常布局仍未验证。本次仅更新review，不新增task、代码、测试或运行，不外推全产品通过/满分。

### 本轮限定关闭：新PDF原件、设置返回与App原录音（父级实机证据）

以下按父级最新桌面原生与Android实机观察记录，不是产品角色本人操作；替代此前对应路径的待验状态，不改变全产品评分。

| 具体关闭项 | 本轮实际证据 | 验收边界 |
| --- | --- | --- |
| 新PDF生成后的可见原件入口与来源页面职责 | 新desktop PDF生成note `10391e70`，真实original ID前缀 `2e6`已注册；NoteEditor→查看原文件进入关联来源页，仅显示1条原件，无全局导入、搜索或类型筛选；原件Sheet关闭后返回同一正文 | 此新PDF路径通过；不代表所有生成落点已迁到统一详情，也不外推多关联/其他文件类型 |
| 原件导出一致性 | 父级真实导出PDF，SHA与1017字节源文件一致 | 此原件注册→关联→导出闭环通过；旧仅提取正文而未保留binary的资料仍不能补造原件 |
| 设置返回来源 | Native Tauri正文→Sidebar设置→模型→设置总览→原正文实际走通 | 此正文来源返回链关闭；带列表query/hash、非法returnTo及其他二级路径的实机覆盖未齐 |
| App原录音详情责任与外部返回 | 当前原录音详情仅展示所选录音，Header实际返回FileLibrary；42秒本地播放完整 | 此文件库直达详情和返回、播放路径通过；列表进入详情再返回列表、硬件返回及删除后不可用态未取得本轮完整实证 |
| 云端慢核验不阻塞本地原件 | 父级观察本地播放/导出不被慢核验阻挡，unknown状态禁止生成 | 此具体慢核验状态通过；不等于云生成已接受、已完成或未知提交可重放 |

父级交接App关联架构53项测试及App TypeScript检查通过，作为其测试证据记录；本人本轮未跑测试。Word实机生成仍待结果，不能随PDF一起关闭。

剩余优先验收：Word原件→生成→关联→导出；App列表/外部两种原录音返回链和删除后状态；准备取消、native停止未确认的显式重试、已停止但保存失败复用原件、晚生成等异常分支；桌面成功采集与原件持久保存（本轮此前仅有麦克风失败实证）；失败处理记录精确定位原件；外链图逐图加载在预览、另存版本和重开后的实际覆盖。离线冲突、跨账号、全量历史/恢复及正式包矩阵仍未完整验收。

本次仅更新本review，不修改业务代码、不新增任务、不运行测试。此前有限评审参考桌面7.5/App6.9保持不变，以上是具体路径关闭，不是全产品通过或满分。

### 最新验收覆盖与下一P1：App可信缓存先读

以下为父级实际Native/Android观察与集中测试交接，替代本报告此前相应“待核验”状态；产品角色本次未操作设备或运行测试。

| 路径 | 最新真实证据 | 结论与边界 |
| --- | --- | --- |
| 同一合成稿离线冲突恢复→比较→合并→保存→两端确认 | Android关闭/重开比较Sheet保留全部合并marker；勾选远端r2核对后一次submit，Sheet自动关闭，待处理0、synced6。详情显示已同步，正文含offline/sync/desktop marker；Native桌面同一对象preview全部收到 | 此具体草稿留存、提交ack及跨端链通过，不再列ack待验或无比较Sheet。比较后再次竞争、其他账号、删除冲突仍未验证 |
| Desktop Notes整页布局与本轮限定修正 | 同1282×822窗口保持5条完整记录，来源/搜索/筛选对齐；新版实际截图已覆盖。父级最终3 suites共52项及TypeScript检查通过 | 此窗口密度与本轮范围通过；不外推所有屏幕、大字或全产品UI。此前13项是中途检查，当前以52项交接为准 |

下一P1是App已有缓存详情首读等待约20秒及启动核验遮住缓存。时长来自父级实际观察，根因尚未确认。只读源码证据：`VINote-app/App.tsx:113`先等待fetchMe，`:154`在authenticated=null时整屏spinner；`src/screens/NoteDetailScreen.tsx:70`开始loading，`:72`清空note，`:148`加载状态占据正文。`src/lib/notes.ts:47`的getNote只读本机Storage及workspace文件，不含网络；`src/lib/workspaceStorage.ts:31`读取并解析账号快照。不能把详情耗时直接归因于网络，也不能据此声称已发生跨账号泄露。

产品允许缓存阅读/本机编辑的有限合同（已发送设计师及架构师；仅方案，不授权本轮改代码）：

1. 先确认本机持久会话及缓存归属：当前owner、认证来源、workspace服务origin、对象ID均匹配，才能先展示缓存。旧账号、旧服务、缺少可信归属的数据不能作为当前正文；不能为了快按标题猜关联。
2. 账号核验进行中或服务暂不可用时，可信缓存可读，可编辑并仅保存本机草稿；状态明确“已保存到本机，账号核验后同步”。可读与远端写权限分开：核验成功前禁止手动/自动云写、云删除恢复、生成、MCP调用、飞书发布，说明原因，不显示已同步或自动重放未知请求。
3. 有缓存先展示正文，沿用元信息状态区显示核验/后台读取及失败重读；不清正文、不用全屏loading遮盖。无缓存保留独立首载、失败与返回；缓存读取错误不得伪装空列表或成功同步。本地读若仍慢，由架构核实读取/解析瓶颈，可信内存快照不得充当最新CAS依据。
4. 核验或读取的迟到结果必须校验owner/session/origin/对象；切账号、切服务、离开对象后不可回填。后台新正文不得覆盖编辑草稿、pending或conflict。401明确重新登录，服务故障不能当退出；原账号草稿保留但不展示到新账号。
5. Header及硬件返回保持原来源、列表query/filter、版本及草稿。核验成功后按既有真实同步回执更新状态；不新增一级入口，不改现有会议与笔记/文件库/插件结构。

下一实走验收限定：同账号可信缓存在慢核验/断网时先可读并可仅本机保存；核验前所有远端写均被阻止；重新联网后正确同步且不覆盖稿；账号/服务切换期间迟到读取不显示旧正文；无缓存或损坏缓存有真实失败与返回。这些路径目前未验，不以本次合同抬分。整体仍未accepted，参考评分保持桌面7.5/App6.9。
