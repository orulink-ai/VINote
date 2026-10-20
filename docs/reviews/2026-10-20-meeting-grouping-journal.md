# 桌面会议主记录归组独立 journal

## 范围及并行文件占用

- 工作树：meeting-context-recovery-20261019/VINote；分支 codex/meeting-context-recovery-20261019；PR #61 目标 dev；不 reset/switch/commit/merge。
- 本任务占用：`frontend/src/components/MeetingRecorder/MeetingWorkbench.tsx`、其 `.test.tsx`；新增 `frontend/src/lib/meetingGroups.ts`、其 `.test.ts`；`app/models/note_library.py`、`app/routers/note_library.py`、`tests/test_note_library_router.py`。
- 必要字段透传还涉及 `frontend/src/stores/noteLibraryStore.ts` 与 `frontend/src/hooks/useLibraryNotes.ts`，仅改新增只读关系字段及映射，不改内容/删除/存储流程。
- `README.md` 的现有产品说明追加本次会议列表行为及只读 API 字段，避免并发修改 AGENTS。
- 不改 StorageSettings、deviceContentStore、主开发 index 或 Hume 的文件。父线程报备工具返回 cannot send to native ancestor，清单同时通过本 journal 留存。
- 已读根 AGENTS、2026-10-19 会议开发 index/frontend review、会议 evidence/recovery plan、UI design 的相关约束。无 `.codegraph`，跳过索引。

## 问题与验证计划

- 已有分组只能连接当前 task/note IDs；summary-only 与 independent generation 是不同 child task，缺少 canonical 原录制关系投影。
- 默认稿按 updatedAt 选、搜索仅代表稿；需要保留真实保存时间、所有内容对象及录制入口，失败/未读取稿不能挤掉可读稿。
- 先用纯合成正反例复现；新增关系必须由服务端 owner/task/单跳 canonical reference 验证，未知/冲突关系分开。只读元数据不依赖媒体仍存在，不补写历史数据。
- 只做离线测试与 TypeScript；无云/ASR/LLM、无设备操作。主线程负责 App/实机/最终集成。

## 完成与冻结

- 代码冻结：**2026-10-20 10:18:54 +08:00（Asia/Shanghai）**。此后本任务只追加本 journal，不再写产品/测试文件，等待独立审查意见。
- 根因：旧投影只连接当前 task/note/migration IDs；summary-only 与 independent generation 的 child task 与父原录制 task 不同，`/api/notes` 未返回 canonical 关系，前端只能分成多行。旧代表稿使用 updatedAt 排序，旧稿后编辑会挤掉后来保存的稿；搜索也只查看代表稿。
- 新只读关系为 `meeting_source {owner_id, canonical_task_id}`：先验证当前任务及 canonical 任务的真实 UUID、目录 containment、非链接常规 owner/mapping 元数据；child 的 `source_reference.json` 必须为精确 v1 单跳结构，owner 相同，parent 为 canonical，source_version 与 canonical `source_media.sha256` 相同。canonical 不得继续引用其他任务；有 `source_original.json` 时同时核对 owner/task/workflow。录制文件缺失或删除不清除已经验证的元数据关系，也不证明纪要被删除。未知/损坏/不同 owner/workspace 不猜合并。
- 原任务直接以自身作为 canonical。capture-only 原件允许显式 meeting intake 类型，已保存 request 的 workflow 必须为 meeting；不依赖标题、日期、文件名猜关系。新增投影不读取媒体内容、不注册/修复历史元数据，不授予播放/生成权限。GET list/detail 以及 create/PATCH 响应都透传，避免保存后内存行被替换而暂时拆组。
- `meetingGroups.ts` 纯 helper 保留全部 note IDs、localSources 和 PendingMeeting 原件，owner/workspace 分隔；默认按 createdAt 选择最新可读 done 稿，updatedAt 只用于保存时间相同的真实记录排序。所有旧稿可展开；无 V1/V2 伪编号。原有 warm-return member IDs、查询/状态筛选/归档及父页面导航回调保留；搜索覆盖所有关联稿。
- 本机 capture history 的原件仍可展开 Sheet；只有服务端 canonical 关联时，入口打开授权纪要的来源详情并明确可用性需核验，不声称文件仍可播放。人工 R2 及旧正文版本完全未写入或迁移。

## TDD 与最终验证

- 修复前纯分组 3 failed / 1 passed：child 三行而非一行、updatedAt 错选旧稿、不同 owner 共用 task 被合并。服务端新增用例修复前失败：meeting_source 全部缺失。补 save/PATCH 的失败用例后修正响应投影，避免刷新前拆组。
- `npm test -- src/lib/meetingGroups.test.ts src/components/MeetingRecorder/MeetingWorkbench.test.tsx src/hooks/useLibraryNotes.identity.test.tsx src/hooks/useLibraryNotes.test.tsx src/pages/Meetings.test.tsx src/stores/noteLibraryStore.test.ts --maxWorkers=2`：**6 files / 47 passed**。覆盖真实 store snake/camel 字段映射、同源 child 正例、owner/space/未知关系反例、所有对象/原件入口、旧稿搜索与返回展开、原有归档及完整来源导航；既有 store 故意失败读取用例输出 console.error，不是测试失败。最终运行还给了不存在的 `Meetings.return.test.tsx` filter，Vitest 实际执行以上 6 文件，无额外返回测试文件；返回验证来自现有 Meetings 和 Workbench 测试。
- `D:/projects/VINote/.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider tests/test_note_library_router.py tests/test_meeting_summary_regeneration.py tests/test_new_generation_operation.py tests/test_url_worker_original_registration.py -q --tb=short`：**109 passed**，17.11s；仅既有 Starlette 弃用警告。新增合成元数据测试包含读取前后所有证据字节不变、无媒体仍有关系、source_version/owner/UUID/mapping/单跳引用反例；未调用实际 provider。
- `npx tsc --noEmit`：exit 0。限定本任务已跟踪文件 `git diff --check`：exit 0（仅工作区换行提示）。未做云/ASR/LLM、设备操作、commit/merge。
- 本任务新增/修改文件：README；app/models/note_library.py；app/routers/note_library.py；tests/test_note_library_router.py；frontend/src/lib/meetingGroups.ts、meetingGroups.test.ts；frontend/src/components/MeetingRecorder/MeetingWorkbench.tsx、MeetingWorkbench.test.tsx；frontend/src/hooks/useLibraryNotes.ts；frontend/src/stores/noteLibraryStore.ts；本 journal。工作树其他 dirty 文件属主线程/并行任务，未操作。

## 主线程提供的实机证据（非本任务亲自操作）

- 用户本轮报告：native 热更新已看到两个父会议分别 **4 / 6 份**；4 份展开时各纪要入口及原录制可见；API 编辑稿标题已更新，旧稿仍列。主线程正在验证最新正文重开及返回；最终结果由主线程追加其自己的验收记录。本 journal 不将此报告扩大为完整 App/安装包验收。

## 给 Wegener 的独立审查交接

请审查上述冻结文件：重点核对 canonical 单跳 owner/source_version 边界、未知关系不误归、保存/PATCH 后关系不丢、最新可读稿与全部旧稿/原件可达、归档/搜索/返回上下文。人工 R2 和历史版本不应有数据写入。回收站由 Hume 并行负责，不属于本次 diff。

当前 app thread inventory 不显示 Wegener 原生子线程，send_message_to_thread 对本任务原生父线程明确返回 cannot send to native ancestor；没有可用原生协作消息 API，不能声称已发送。此交接供主线程转交 Wegener；本任务已在会话中报告冻结及通知限制。

## Wegener P1：canonical 冲突保护（2026-10-20 后续）

- 按用户请求解冻，仅改 `frontend/src/lib/meetingGroups.ts`、`meetingGroups.test.ts`，并追加本 journal；其余产品/后端/测试文件本轮未写入。
- 已读取私有 offline review 的 review.json；只引用匿名合成反例，不修改审查产物。根因是旧 union 将 canonical task token 和推断 legacy token 视为同等边：不同已验证 canonical 仍可经 app-recording-one / app-recording-one-v2 或任意未知 legacy 连通块被传递合并。
- TDD：新增直接 alias 冲突、传递桥与 legacy 保留用例；校正 authenticated collection owner 的合成夹具后，修复前 **2 failed / 6 passed**，恰对应两类 P1。修复后全部通过。
- 算法先只连接相同 `(owner, scope, team, canonical_task_id)` 的已验证节点；再单独连接未知 legacy 节点；遍历完整 legacy 连通块的全部已验证相邻目标。只有目标恰为一个 canonical 组才附着，多个目标则保持独立 legacy 组。这样不同 canonical 无法被别名 union 覆盖，也不会按输入顺序把未知桥任意分给某一会议。
- 正反例包含直接 app alias 冲突两种顺序；四节点双向传递桥全部 **24 种排列**，分别带/不带原录制，严格核对分组及全部 note/recording ID 可达、原输入不变；同 canonical alias、正常 legacy-only、无歧义 legacy 桥仍按既有规则归组。没有标题/时间推断；代表稿、归档策略与返回上下文未改。
- 最终前端命令：`npm test -- src/lib/meetingGroups.test.ts src/components/MeetingRecorder/MeetingWorkbench.test.tsx src/hooks/useLibraryNotes.identity.test.tsx src/hooks/useLibraryNotes.test.tsx src/pages/Meetings.test.tsx src/stores/noteLibraryStore.test.ts src/hooks/useMeetingReturnScroll.test.tsx --maxWorkers=2`：**7 files / 64 passed**（含既有 14 项返回滚动测试）。既有 store 读取失败用例预期 console.error 不计作失败。
- `npx tsc --noEmit`：exit 0。`D:/projects/VINote/.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider tests/test_note_library_router.py -k MeetingSourceProjection -q --tb=short`：**1 passed / 17 deselected**，仅既有 Starlette 弃用警告。本轮未改后端，不冒称重跑此前全部 109 项。
- 本轮 helper/test `git diff --check`：exit 0。无云/ASR/LLM、无设备操作、无 commit/merge。
- **重新冻结时间：2026-10-20 10:27:39 +08:00（Asia/Shanghai）**。供 Wegener 复核的 SHA-256：`meetingGroups.ts` = `53dce3ef93890ddf09bdffdc2ef1802063b8faed4c9bb01a4a9ba25c2c217508`；`meetingGroups.test.ts` = `c1c09b5e8dcf2ae41c273f0021e96c143f85b8f06cd8f8b5bf3ac3b405b811f8`。完成后停止产品/测试写入，交主线程转交 Wegener 复审。
