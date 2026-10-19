# 前端详情、播放与安全恢复 review

- 作者：wugui / Codex；2026-10-19，Asia/Shanghai。
- 范围：共享 `codex/meeting-context-recovery-20261019` 分支的前端与前端测试；未切分支、未 stage/commit，未改后端、模型配置或他人文档。
- 关联：[同任务索引](index.md)、[范围](../../../../docs/plans/2026-10-19-meeting-evidence-and-recovery.md)。本文件为前端独立记录，避免并发覆盖主索引。

## 选择性复用

审查 PR60 的 `b94c9ec` 对基点 `b492a43` 的 diff，仅应用 5 个 frontend 路径：
`meetingGeneration.ts/.test.ts`、`meetingProcessing.test.ts`、`FeishuSettings.tsx/.test.tsx`。
不 cherry-pick 后端或整提交，不带入旧 journal、错误白名单或区间恢复代码。
保留显式 retryable=false 不派发 retry、真实 failed_stage、缺省显式 retry 兼容，以及群列表按需读取、账号/请求隔离。

## 新增前端行为

1. 详情标题两行展示，实际溢出时可键盘打开完整标题对话框；标题、工具栏、长正文允许正确收缩换行。
   视频区域在窄视口保有可用高度，原视频管理放在播放区下方的按需展开区，避免导出/状态挤掉播放器。
2. 视频播放及正文时间跳转使用 `/api/notes/{id}/media?playback=true`；音频与原件导出保持原 `/media`，不下载预览副本当原件。
3. 播放失败仅发一个带超时、可取消的 Range `bytes=0-0` GET 来核对 HTTP 状态，不运行生成。
   202 或 503+Retry-After 显示预热；404/410 表示播放来源不可用，不推断笔记已删除；401/403 提示账号权限；
   网络、500、解码/格式或探测超时保持“尚未就绪/未核验”，不谎称原件丢失。
4. 重新加载调用同一个媒体元素的 load，metadata 到达时恢复时间点/倍速；放大、正文/逐字稿切换不替换播放器。
   换账号、换内容、卸载及较晚的探测响应不会覆盖新状态或把已能播放的媒体改成 missing。
5. 录制操作显示真实音频/视频类型；读取中、读取失败、确认不可用与已删除分别显示。失败删除不解绑播放器；过期元数据/下载不会流入新内容。
6. 失败录制提供精确任务的只读入口；非失败内容在展开区提供查看处理任务，带回原详情上下文。
   导航不提交生成，显式恢复仍走既有服务端合同，不凭 UI 创造安全重放授权。

使用已有 UI Skills 交互合同、UI/UX Pro Max 的长 token/加载反馈与 shadcn/Radix 组件指导。
生产前端不硬编码提供方时长，不按模型名推断视觉能力，不添加模型回退；本轮无 ASR/LLM 或通知调用。

## 验证

Red：新增 4 个详情播放回归在基线全部失败，复现视频没有 playback 参数及错误/重载语义问题。
第一轮真实浏览器仅检查横向边界仍漏掉标题挤掉可见视频，查看合成截图后增加播放器实际可见高度及完整标题对话框断言，再修布局。

Vitest 单 worker 关联命令（frontend 目录）：

```sh
npx vitest run src/pages/NoteEditor.test.tsx src/components/Notes/SavedRecordingActions.test.tsx src/components/Notes/RecordingRetryBar.test.tsx src/components/Notes/NoteDetailTitle.test.tsx src/hooks/useNoteMediaPlayback.test.ts src/lib/meetingGeneration.test.ts src/lib/meetingProcessing.test.ts src/pages/FeishuSettings.test.tsx src/components/Settings/FeishuDestinationPicker.test.tsx src/pages/NoteGenerator.test.tsx --maxWorkers=1 --minWorkers=1 --reporter=dot
npx tsc --noEmit
```

最终关联回归 10 文件/161 项通过，包含精确只读处理入口测试；TypeScript `tsc --noEmit` 通过。
已有 Router future/act warning 不等于运行验收；没有触发后端构建或模型请求。

真实浏览器：`node scripts/note-detail-playback-smoke.mjs http://127.0.0.1:3219`。
使用独立 loopback Vite、headless Edge、新浏览器上下文；全部 API 被 GET-only 合成 fixture 拦截，禁止写请求和出站访问。
两段自行生成的横屏/竖屏 WebM（6 秒、7 秒），实际 Chromium 解码、开头/中段/结尾拖动及 ended、放大返回、预热后重载时间/倍速均通过；
1360/900/480 宽度无横溢，视频可见。实际点击导出并校验与各自 original SHA256 一致，与 remux preview 不同。
完整标题可打开/关闭，原播放器不替换。0 模型调用、0 通知、0 非 GET API。
本机合成证据目录标识：`vinote-playback-ui-0tgwgE`，含 evidence.json 与两张合成截图；不提交视频或用户资料。

## 验收限制与交接

上述浏览器验证为前端合成两视频 E2E，API/数据均 mock；不替代主线程固定两份私有录屏的真实 backend/Range/末尾解码验收，
更不代表安装包、真实模型总结、保存或飞书通知通过。原件绑定、转码/容器修复和真实两视频后端验证由主线程负责。
本轮只保留共享工作树的未提交前端修改，等待主线程审查、集成与发布安排。


## 追加：已有会议仅重新生成纪要

前端新增 `RegenerateMeetingSummary`，只在已保存会议详情提供上下文确认入口；草稿未保存或保存中不可提交。
显式读取 summary-context 与当前云端配置，展示确切 LLM ID，确认时核对模型仍相同，不强制固定模型、不提供回退。
复用已核验转写及可用说话人/视频资料，不重跑 ASR；409 仅说明资料当前不可用，不引导直接转录。
提交前持久化账号/Origin/详情绑定的 UUID operation 与独立回执，保存失败不 POST；未知结果、reserved 以及重新打开均沿用现有 operation GET 查询页，不重发。
账号、路由、Origin 切换丢弃过期确认和响应。已有任务及原纪要不被覆盖，结果沿用新任务保存路径。
仅在新纪要保存获确认后清除原详情的待确认指针；失败或未知保持保护，即使状态误报 retryable 也不派发摘要重试。
此追加涉及新组件及测试、NoteEditor 接入、NoteGenerator 回执恢复及测试；未写后端文件、未调用真实模型或通知。
定向组件及恢复测试 2 文件/72 项通过；最终全关联回归 11 文件/172 项通过，TypeScript `tsc --noEmit` 通过。
本轮摘要入口仅有离线 mock/API 合同测试，尚无真实 LLM 或安装版验收证据。


## 追加：会议占位记录不得冒充完成

定位：MeetingWorkbench 对没有 PendingMeeting 的已保存对象直接标完成，归档投影也曾强制完成；useLibraryNotes 的共享历史投影还会覆盖已知 pending/failed 为 done。
修复：保留已知来源 status；Meetings 对有明确 taskId 的会议做去重、只读 GET 状态核验，任务失败显示需处理，处理中与未核验分别展示，完整成功任务结合已保存状态才显示完成，pending 成功结果显示纪要待保存。
不按标题或占位正文识别状态，不修改笔记、IndexedDB 或任务；任务读失败/not_found 不视为笔记删除或完成。账号、Origin、路由、内容版本改变会取消并丢弃旧响应，涵盖账号 ABA。
关联回归 5 文件/34 项通过，TypeScript 通过；已有 frontend 全关联 11 文件/172 项通过是本次窄修复前的独立结果。
新增 GET-only 合成浏览器脚本 `frontend/scripts/meeting-status-smoke.mjs`；真实 headless Edge 渲染四条合成记录，验证两条失败、一条完整成功、一条状态读取失败和需处理筛选。
1360 与 480 宽截图已查看，无横溢；证据临时目录标识 `vinote-meeting-status-CDUFMM`，0 写 API、0 模型、0 通知。
这些截图是合成数据渲染证据，不是用户私有会议或安装版完整验收。未打开或改动主线程的 3189/runtime，未改后端、未提交。


## 追加：画面核对阶段

NoteGenerator 优先识别 stage/status analyzing_video，GenerateProgress 为视频来源显示位于转写与纪要生成之间的“核对共享画面与发言”阶段；LocalRecordingPreview 与阶段词典保持相同文案。
残留 processed/received 秒数及旧 progress 不能充作视频百分比；等待画面时纪要生成、保存保持待开始，明确逐字稿就绪不等于纪要完成。
组件与真实轮询映射新增回归；4 文件/127 项关联测试通过。未调用模型、未改后端、未提交。


## 追加：重新总结保留原录制时刻

formatContentTitle 优先使用服务端结果标题中经日历/时钟校验的来源时间前缀（兼容 | 与 ｜），主题继续使用最终 Markdown LLM 标题，不把来源时刻按浏览器时区重算。
NoteGenerator 的 summaryOnly 回执初次恢复、查询恢复及重新查询三条路径均不再将新 operation.createdAt 当作来源时刻；没有可信来源时间时保留时间未知。
回归明确覆盖“来源 15:41、新操作 19:35”，另覆盖无来源时间与无效日期/时钟；先验证基线失败，再完成修复。
3 文件/81 项关联测试通过，TypeScript 通过。无后端写入、无真实模型调用、不改已保存笔记，未提交。


## 前端最终交接验证（2026-10-19 19:58）

产品源码已停止修改；仍在原共享功能分支，未 stage/commit。
最终 18 文件/244 项关联 Vitest 通过，另补 LocalRecordingPreview 1 文件/8 项通过：合计 19 文件/252 项；`tsc --noEmit`、frontend `git diff --check` 通过。
最后在独立 3219 Vite 重跑两项合成浏览器 smoke，均通过；独立 Vite 随后关闭，未触碰主线程运行端口或后台任务。
- meeting-status-smoke：失败占位/真实完成/不可核验及筛选、1360/480 布局；新证据目录标识 `vinote-meeting-status-z498zE`。
- note-detail-playback-smoke：合成横竖 WebM 实际解码、首中尾与 ended、预热重载保位、原件导出 SHA256、1360/900/480 无横溢；新证据目录标识 `vinote-playback-ui-HDtJYN`。
新截图已查看；API 皆 mock 且仅 GET，0 写请求、0 模型、0 通知。
这些是离线源码/组件/合成渲染证据，不能称为客户实际双视频 E2E，不能证明真实模型质量、安装包或发布验收。
真实 A3 与质量复核由主线程执行，本轮不介入；中文 PR、CI、打包和部署由主线程统一安排。


## A3 后最终前端复核（2026-10-19 20:04）

收到主线程 A3 成功事实后，仅再次验证既有源码，未读取实际会议正文或任务产物，未发起 ASR/LLM，未重启任何运行服务。
最终同一轮关联 Vitest：19 文件/252 项通过（30.74 秒）；独立 `npx tsc --noEmit` 通过；`npm run build`（tsc && vite build）通过。
包含来源 15:41、新操作 19:35 的标题保存回归：原时刻保持15:41，LLM主题保留；无来源时间不取新操作创建时间。未改已有保存记录。
构建仅生成被忽略的 frontend/dist，不是桌面打包或部署；Browserslist 数据旧及 chunk 大小为非阻断警告。
最终日志为本工作树 frontend/frontend-final-validated.log 与 frontend/frontend-final-build.log（不提交），最近的两项合成/mock API 浏览器 smoke 证据仍单独标记为离线验证。
本轮产品源码零追加改动，所有前端改动仍未 stage/commit，交主线程统一审查、PR/CI/桌面构建安排。


## PR61 后追加：bare task 工作流未知时保持中性

审计现有 FileLibrary、Tasks、NoteEditor、RecordingRetryBar 与独立/摘要 operation 入口：已知会议均保留 meeting=1。当前 GET task 响应没有 workflow；new-generation-context 对活动任务不可用。本轮不新增任何 API 查询，不读取 request.json/artifact metadata，不按媒体格式猜 workflow。
NoteGenerator 对没有明确 meeting 标志、也没有匹配 owner/task 的既有路由上下文的只读 task 显示“处理记录”和“正在处理任务”，不套用笔记六步；有效返回来源保留，缺省/非法来源回到 /tasks?tab=generation。
未知 workflow 时不展示依赖 workflow 的新生成入口，必要原件入口使用 unknown 用途；查询原任务仍为 GET-only。明确 meeting=1 及原有普通生成流程保持不变。
新增中性运行页、安全返回、外账号来源即使带 meeting_video 也不推断会议的回归，基线先复现2项失败；修复后 5 文件/149 项关联测试通过，tsc --noEmit 通过，diff检查通过。
产品源码仅 NoteGenerator.tsx 与其测试；本节为附加记录。未改后端/Python、未重启 runtime、未发起 ASR/LLM/通知，未 stage/commit。
后续方向：待活动任务结束后，由主线程单独增加 owner-scoped task workflow 权威响应字段及后端验证，再考虑前端接入；本轮未实施。


## ce7e717 后追加：懒加载返回与未知失败页

App 的外层 RouteFallback 只有中性加载文案；错误“返回笔记”来自 MainLayout 内层 Suspense 所用 loadingPageParent 的默认 /notes。
本轮产品修复仅 navigation.ts 增加 bare /generate?task=... 的 /tasks?tab=generation 返回，位于有效 query/state parent 与 meeting=1 判断之后，普通笔记入口保持原行为。
增加真实 MainLayout+挂起 Outlet 的渲染回归，覆盖 bare、已知会议、有效查询 parent、无效查询/有效 state、全无效 parent、普通笔记六种情况。
复核已提交 NoteGenerator 的未知工作流保护仍同时存在于按钮显示和 openNewGeneration handler；仅追加失败页回归，确认 unknown/terminal 且误报 retryable 时依然只 GET task，无新操作确认、无保存、更换来源或 POST。
4 文件/90 项关联测试通过，tsc --noEmit 通过；单元基线先复现加载返回错误。未知 workflow 权威字段留给后续后端独立修复，本轮不读取底层 metadata、不新增 API。
未改 App/MainLayout 产品实现及后端/Python，未重启 runtime、未运行 ASR/LLM/通知；仅保留前端及本记录的未提交 diff，已有并行后端改动保持原状。


## 追加：独立失败子任务 frozen context v2

只读核对 Hume 已集成 schema，NoteGenerator 的 open/confirm 不再硬限 protocol=1：v1 不接受 canonical 字段，v2 必须有规范 UUID canonical_task_id 且不同于当前 parent/所选 task；其他协议拒绝。
确认前再次校验，保存 frozenContext 原值；仅 v2 POST 明确携带 canonical_task_id，v1 请求仍只有既有四字段。冻结 ASR/LLM 与 Origin 验证不变，不替换模型、不自动 retry/新建操作。
新增 v2 丢响应/accepted 单次确认、非法 canonical（缺失/null/格式/大小写/同 parent）、v1 意外字段、账号 ABA 0POST 与 reserved 原 operation GET-only 恢复；已有 v1 与加载返回测试保留。
先复现 v2 确认无法打开的基线失败；5 文件/111 项关联测试通过，tsc --noEmit 通过。该测试包含已有加载态/bare 失败保护及冻结模型展示回归。
产品改动仅 NoteGenerator.tsx，另更新测试与本记录；不写 Python、后端或运行数据，不启动/重启服务，不调用 ASR/LLM/通知。保留未提交 diff，由主线程追加 commit。


## 追加：独立确认使用权威 source.type

确认时不再复制可能缺失的旧 receipt.sourceType；使用已校验 context.source.type 的明确白名单：video/meeting_video 映射视频，audio/meeting_audio/meeting_recording 映射既有音频分类；明确 transcript、file/document 保留对应类型，其他为 unknown，不按标题/扩展名猜测。
confirmed context 的分类优先于提交响应的泛化 source_type；已登记 operation 的 GET 恢复及重开 accepted 回执也从原 frozenContext 恢复分类，不覆盖原 frozenContext，不新增 POST。
视频会议因此在 ASR 阶段即可显示五步并保存 meeting_video，音频保持 meeting_recording；未知分类不会降级成音频（新独立会议保存 meeting_unknown）。普通旧 intake 的兼容行为保持不变。
新增六组模拟确认→回执重开→进度→自动保存回归，覆盖视频/音频别名和伪文件名未知值，同时检查 15:41 原时间与只一次显式 POST；提交响应故意返回泛化 audio，验证其不覆盖冻结来源分类。
4 文件/135 项关联测试通过，tsc --noEmit 通过。以上为离线 mock 合同验证，真实 UI v2 确认仍由主线程执行。
未调用实际模型、未写 Python/后端、未重启进程；保留未提交 diff。


## 追加：独立 operation 原件返回身份

根因：pending.localFileId 复制旧 receipt 或回退 task:独立父，返回资料链接再优先信任该值，将独立处理记录误作原件。
修复：冻结上下文保留 source.file_id；v2 要求它精确等于 task:已验证 canonical UUID，并且 context.parent_task_id 与该 operation.parentTaskId 相同；v1 同理绑定明确原 parent UUID。仅在字段实证一致时预选原件，不凭 canonical 数值自行创造 file_id。
确认前保存正确 localFileId；重开旧 independent 回执时从原 frozenContext 重新绑定，忽略历史错存的父/子 localFileId。缺失、错配或无上下文时返回带原 returnTo 的文件库，不错误预选任意文件。
新增旧回执三组 GET-only 回归（正确/缺失/错配）和明确确认前持久化实证测试；4 文件/142 项通过，tsc --noEmit 通过，前端 diff 检查通过。
本轮仅 NoteGenerator.tsx、对应测试和本记录。没有新增 API 读取、没有读取真实会议资料、没有模型调用、没有后端写入或提交；重复失败文案留待后续，本轮未扩改。


## 追加：未保存会议的仅重新总结入口与旧总结 retry 保护

RegenerateMeetingSummary 支持可选 noteId，复用于 NoteGenerator 已核验的会议 failed/error task；任务入口明确“仅重新生成纪要/确认，仅重新总结”，复用已有完整转写与可用证据，不重跑 ASR。
无 noteId 使用账号/Origin/task 绑定 summary-operation 指针，确认前持久化；未知/重复只进入既有 source-requests GET 恢复。成功沿用旧 saveNote 流程，保存获确认后统一清理 task 或历史 note 指针。
组件绑定 owner、Origin、route/hash、task、workspace 与返回上下文；summary-context 409 阻断不完整 ASR，模型仍为当前明确云端选择，不添加自动回退。
旧状态兼容：已核验 failed_stage=summarizing 即使 retryable=true，也不允许旧 retry 或完整新处理。将结构化 failed_stage 保存在 verifiedTask，初始判定、旧 retry 前 fresh GET 与按钮/handler 均设保护；不从 message/HTTP 文案推断。
真实组件离线集成回归覆盖失败任务 prepare→confirm（唯一 regenerate-summary POST）→accepted/丢响应 GET恢复→自动保存及指针清理；另覆盖409、未知重复查询、账号ABA、路由迟到响应、旧unknown/typed总结错误及转写失败→新状态总结失败的竞态。
最终4文件/149项关联测试、tsc --noEmit 与前端diff检查通过。原note入口及其成功清理兼容测试保留。
产品源码仅 RegenerateMeetingSummary.tsx、NoteGenerator.tsx；另追加 NoteGenerator 测试和本记录。未写后端/Python、未调用真实模型/通知、未提交；本节完成后停止全部写入/测试，交主线程受控UI验收。


## 2026-10-20：原件导出与生成确认反馈（前端 / Tauri）

作者 wugui；本轮起点 e0426f8，工作树 codex/meeting-context-recovery-20261019。仅本地 diff，未 commit、打包、发布或重启。并行 Python/总结质量修改不属于本记录和写集。

### 实际代码发现与交互约定

- 原 downloadRecording 仅触发隐藏 anchor，调用方没有结果反馈；FileLibrary 也是直接 anchor。LocalRecordingPreview 的生成确认是页内区域，可能落在视口外。
- 导出触发后即显示忙状态并锁定重复点击；native 先选择保存位置，再读取原件流。成功只在最终文件写入完成后显示；取消单独提示“已取消导出，原文件保留”，不记成功/失败；错误显示可重试。支持导出中取消，账号/文件/路由变化使旧结果失效。
- 浏览器直接交给原件 URL（已有 IndexedDB 录制使用原 Blob URL），提示去下载列表查看，不宣称实际落盘成功。跨 Origin 回退保留当前产品页；浏览器的保存位置/下载成功以浏览器行为为准。
- 生成按钮说明确认前不会处理，并打开具有标题、说明及焦点管理的现有 Dialog。暂不生成不启动 worker；明确确认后冻结具体 ASR/LLM，处理中禁重复确认，可收起进度而不取消/重发；成功/失败来自真实 pending record。原 processSavedMeeting、未知 GET-only、operation 与后端代码不改。

### 实现与边界

- lib/recordingDownload.ts：只允许现有 notes/media、task/artifacts、files/content 原件路径及 download=true；拒绝外站、路径回退、playback 参数、额外查询。认证仍经 apiFetch，native fetch 拒绝 redirect，401 不降级到其他 URL。服务端原件使用 Response.body 流读取，禁止整文件 blob()；IndexedDB 已有 Blob 只切片读取；每次 IPC 不超过 1 MiB。
- src-tauri/src/original_download.rs：rfd 0.15.4 系统保存对话框绑定发起窗口，系统负责同名覆盖询问；IPC 不接受磁盘路径、URL、凭证。会话绑定窗口，同目录 NamedTempFile 分块写入并同步后 persist；取消/失败 drop 临时文件，销毁窗口仅清理其会话。rfd/tempfile 使用本机缓存，离线 Cargo.lock 已更新。权限 TOML 与必要生成 acl-manifests 保留；desktop-schema 仅有换行变化，恢复原字节。
- 三个产品入口：LocalRecordingPreview、SavedRecordingActions、FileLibrary（复用 OriginalDownloadButton）。播放 URL 不由本轮改变，导出不加 playback=true。
- root 临时文件 `-` 首次发现长 10 字节，后续只读核对时已不存在；无法认定产生者，本轮未删除未知归属文件。本轮验证日志收至忽略目录，不纳入源码。

### 验证（离线；没有真实模型请求）

实现后补有意义回归，不将其描述成先测试后实现的 TDD。旧 FileLibrary 链接断言随实际下载按钮更新；原件身份/可用性与禁止误生成断言保留。

- 8 个前端文件，209/209 passed：recordingDownload、OriginalDownloadButton、LocalRecordingPreview、SavedRecordingActions、FileLibrary、meetingProcessing、MeetingWorkbench、NoteGenerator。
- 反例包括取消 picker 0 fetch、流式原件无需大 Blob、取消 partial 清理、HTTP 401 不回退、URL 白名单、写入/finish 失败不报成功、重复点击单次调用、旧 owner/route 结果无效、确认前 0 worker、处理中模型展示冻结、收起不重发，以及既有 unknown GET-only 恢复。
- `npm run build`（tsc + Vite）通过；有既有体积警告（部分 chunk >500 kB）。关联旧组件测试存在 React act/组件说明警告，未作为真实 UI 验收。
- `cargo test --offline --lib`：9/9 passed，含 2 个新增原件临时文件/替换字节一致与分窗口清理测试；没有启动 Tauri 应用。
- `git diff --check -- frontend` 通过。
- 日志：`.desktop-build/ux-download-generation-20261020/{frontend-tests.log,frontend-build.log,rust-tests.log}`（当前工作树忽略目录）。

### 留给实际验收

主代理核验浏览器下载列表/跨 Origin 下载回退，native 保存位置、系统同名覆盖取消/确认、磁盘权限失败、大视频内存与进度收起体验。离线 mock/文件测试不证明这些系统 UI 已验收；本轮没有调用 ASR/LLM、通知或修改真实会议内容。


### 同轮补充：浏览器原件下载授权预检

按主代理复核，浏览器 backend URL 分支现在先经现有 apiFetch 发 GET + Range: bytes=0-0，保留认证、redirect:error 与 owner/AbortSignal；无 HEAD 假设。只接受 200/206 且有响应体，始终先 cancel 响应体，再进行浏览器下载交接；服务端忽略 Range 返回 200 时也不读取全文件。401/403/404/500 均显示失败，不触发 anchor，不报 browser_started；预检期间账号/路由失效或取消不再交接。浏览器最终落盘仍不在客户端可核验范围内，只提示查看下载列表。Native 不做 Range 预检，保留单次认证流读取，既有测试校验 apiFetch 恰好一次。

LocalRecordingPreview 确认按钮及说明明确为“确认模型并开始生成”，确认前 0 worker、处理中重复点击保护不变。

本次 TDD：新增/更新浏览器预检用例在旧实现 8 failed、19 passed；实现后相关 8 文件 216/216 passed。npm run build（含 tsc）通过；保留既有 chunk 体积与测试 React 警告。本次不改 Rust/Python；Rust 9/9 沿用上轮实际结果，未重复跑。新证据在忽略目录 .desktop-build/ux-download-generation-20261020/browser-preflight-{red,green,build}.log。仅离线验证，没有模型调用、运行时重启、提交或发布。完成后停止写入，实际浏览器/native 验收仍由主代理执行。
