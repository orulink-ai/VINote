# 会议多形态、外部模型连接与飞书归组

- 开始时间：2026-10-20 16:12 Asia/Shanghai；建档者：wugui / Codex。
- 分支：`codex/meeting-delivery-formats-connections`，基于本次 fetch 的 `origin/dev`（7bb2698）。
- 状态：实施中；尚未宣称实际端到端或内容质量通过。

## 用户目标与范围

1. 联系人有效状态与失效热词，发送前核验；未知与权限不足不等于离职。
2. 保持侧边栏，重整右侧设置容器及紧凑的位置选择器，保留账号/异步保护。
3. 以原始材料识别实际参会候选，别名仅用于匹配，绝不把被提及者等同参会者。
4. 简介/精简/详细与文字/真实图文/HTML/漫画等分离，能力不足明确不可用，不自动换模型。
5. 本机与外部 VILab 分离；外部 URL 可显式自定义，按 Origin 隔离目录、模型与凭据，历史任务保持冻结。
6. 用户指定 Wiki 节点下按会议归组，每场会议容纳不同形式及同形式的多个版本。每次外部写入保留精确回执，不重放未知结果。
7. 两份已有录屏复用完整 ASR、说话人和可用画面证据，各形式分别评分；100 是目标，不预设达标，不把人工修订冒充模型自动输出。

## 边界

- 现有主仓库内实施；不建立新 Git worktree，不触碰运行中的旧检出或手机数据。
- 不改 vilab-server、不部署公网后台；飞书使用桌面已有用户 CLI 连接。
- 不重跑 ASR。App 保持音频会议范围，本轮先实施桌面共用能力。
- 用户已授权将会议产物写入所给 Wiki 节点；不由此推导向未经明确选择的其他联系人或群发送消息。

## 并行职责

- UI：飞书设置及位置选择器和组件测试。
- 连接：外部 URL、连接身份、目录及选择隔离和测试。
- 总结：复用材料的多详略/多呈现生成及保存。
- 主线程：参会候选、自动策略、Wiki 会议归组、集成审查与真实验收。

## 验收计划

行为回归覆盖失效对象、同名/被提及人员、空目录和无权限、切换服务及凭据隔离、同源多版本、部分成功/未知结果。真实输出按事实35/覆盖25/来源融合15/组织15/可读10逐项给证据，内容与形式分别核验。

## 关联历史

补充 [飞书本机自动交付](../2026-10-20_114725_wugui_无Issue_飞书纪要自动交付/index.md)，沿用其授权、冻结来源、写入回执及未知不重放约定。

## 变更与验证记录

- 16:12：fetch 后确认主工作区无未提交文件，创建功能分支；切换后 App gitlink 与本地独立检出不同，保留其现有分支/提交，不重置或暂存。
- 新功能测试、真实模型运行、Wiki 回读及评分尚待执行；历史质量分数不能充当本轮结果。
- 16:24：原生 Tauri 当前分支编译启动，用户完成登录。Vite3189/API8919均复用原测试数据；不以网页预览替代原生窗口验收。
- 16:33：用户明确100分必须是配置LLM自动原稿；人工稿仅作评审对照，禁止人工编辑产物后计作自动满分。
- 16:33：首次受控A操作在准备阶段失败；未调用提供方/ASR、无最终纪要，不评分。离线核对定位summary-only加载画面时错误地查询新子任务而非父任务已有缓存，正在修复并补回归；原失败回执保留，不重放。
- 16:34：用户明确取消离职/停用状态获取改造。已要求撤回新增状态表、API查询、附加授权和拦截，恢复原联系人选择。此决定替代目标1的在职状态部分；不影响身份核验、对象热词、参会人确认及其余改造。
- 验证批次：新总结相关85项、auto-policy/Wiki94项、集成绑定105项及新交付选项7项通过；前端位置/连接/设置/HTML四文件28项通过、TypeScript通过。并行后续编辑仍须最终回归，不将这些批次冒充最终全量。

### 16:43–16:50｜桌面重启和版本生成审查

- 用户关闭开发应用后，重新启动同一功能分支 Tauri 原生窗口（会话27090，Vite3189/API8919）。实机截图和可访问性树确认登录保留，全部页显示2场会议，各5/7份关联纪要，3份未关联历史纪要另行折叠；打开会议可见旧稿与原录制。此验收仅证明列表归组和原生启动，不代表总结质量通过。
- 用户明确新版本必须由当次选择的LLM基于完整原始ASR、说话人及画面重新生成，不能改写上一版纪要。已发现弹窗缺少当次LLM选择、历史操作指针可能阻挡连续生成，交给总结模块补齐并验证。
- A实际模型操作d48bb176-eb10-4533-962c-6f0bb9e5c26d/task3abf5bf4-5492-4252-8083-ec5769c03e2d在事实材料校验失败；未产出完成稿，无有效分数。失败原回执和模型材料保留，不修改旧产物或重放，不调用ASR。
- 已将参会人确认router限定挂载到desktop_runtime，注册其表；新交付选项+参与人离线测试96 passed。审查发现参会确认若绑定最终稿/版本会导致同会议新版本失效，已要求改成可信同源会议与证据的身份，不以最终文字推断身份。
- 独立审查发现CLI文档恢复仅允许docx URL，不能接收Wiki节点；安排补齐格式及反例测试，仍由原目的地/空白文档/账号验证决定能否恢复，不能根据URL直接授权。

### 2026-10-20 16:34 +08:00｜wugui / Codex（模型连接并行）

- 模型连接模块已完成源码及离线验证后停写，未提交；其余并行模块和真实桌面验收由主线程收口。
- 新增 owner/Origin/凭据不可变连接记录、各连接独立模型选择，以及 catalog-only check / 显式 save 接口。检查不推理不切换；默认发行地址不变，用户可明确覆盖。新地址不继承旧地址 JWT 或部署密钥。共用 issuer 验证与跨 Origin 账号 token 授权尚未开放。
- 通用 `VILabCloudService.connection_snapshot(owner)` 已直接同步总结并行线程，持久任务保存连接 ID 和原 Origin，HTTP/SSE/PCM ASR/旧 HTTP ASR 解析原绑定；未修改总结或飞书模块。配置页面仅添加紧凑管理连接行及弹窗，保留 sidebar。
- 后端相关集合 179 passed；前端设置及布局集合 24 passed；`npx tsc --noEmit`、本模块 `git diff --check` 通过。完整命令：后端 `pytest tests/test_vilab_connections.py tests/test_paired_model_selection.py tests/test_vilab_integration.py tests/test_vilab_transcriber_retry.py tests/test_vilab_empty_speech.py tests/test_cloud_http_direct_transport.py tests/test_task_model_source.py -q`；前端 `vitest run src/components/Settings/VILabConnectionSettings.test.tsx src/components/Settings/ModelSourcePanel.test.tsx src/components/Settings/CloudModelSelection.test.tsx src/components/Layout/MainLayout.loading.test.tsx`。早先另含 STT 配置集合 110 passed。
- TDD 记录：新接口专用测试先于实现写入；首次运行因目标模块尚不存在而收集失败，不能冒充具体行为反例已在旧实现复现。模块实现后持续补充与通过凭据、快照和竞态测试；UI 测试为实施后补测。未运行真实 ASR/LLM、未发起真实连接检查、未新起/重启 runtime 或原生窗口。
- 正式协议见 [模型连接说明](../../../../docs/vilab-model-connections.md)，专用覆盖见 [后端测试](../../../../tests/test_vilab_connections.py)、[前端测试](../../../../frontend/src/components/Settings/VILabConnectionSettings.test.tsx)。实际外部连接、原生桌面操作及推理尚待主线程明确验收。

### 2026-10-20 16:48 +08:00｜wugui / Codex（显式账号连接与初始化防护）

- 用户明确授权内网/公网共用已登录账号，此决定替代上条16:34中“仅独立key、不开放跨Origin账号token”的初版边界。外部连接新增 account/API key 选项；显式点击检查才向精确Origin发送共享会话token，其他地址额外确认。后端要求同意和授权Origin完全匹配，禁止重定向，不继承旧API key。只持久issuer/subject元数据，不复制token；账号刷新沿用既有helper。
- 新增 `connection_auth_mode` 随原Origin/连接ID冻结，已通知summary并行线程保留。后端相关集合192 passed（含专用连接41项）；完整命令为 `pytest tests/test_vilab_connections.py tests/test_task_model_source.py tests/test_vilab_integration.py tests/test_paired_model_selection.py tests/test_cloud_http_direct_transport.py tests/test_stt_profile_service.py tests/test_vilab_transcriber_retry.py tests/test_vilab_empty_speech.py -q --maxfail=2`。仅合成DB/HTTP反例，未实际请求LAN/public catalog，未推理。
- 用户反馈原生窗口空白，静态导入调查未确认新增模块形成直接循环，但发现连接模块加载时读取并订阅authStore的风险。改为无store依赖的identity模块，authStore完成创建后同步发布owner变化；保留同批A→B→A失效和store reset。真实store图按auth/appMode/connection三入口导入的3项测试通过，导入无网络请求。未声称复现或设备验证白屏已修复，等待主线程重开原生窗口确认。
- 此次前端 `vitest run src/stores/appModeStore.initialization.test.ts src/stores/authStore.test.ts src/components/Settings/VILabConnectionSettings.test.tsx src/components/Settings/ModelSourcePanel.test.tsx src/components/Settings/CloudModelSelection.test.tsx` 共30 passed；`npx tsc --noEmit`、本次文件 `git diff --check` 通过。
- 用户指出summary worker执行前仍与当前全局选择比较。已确认该行为会在受理后切连接时拒绝执行；不能据此宣称冻结任务可正常完成。已直接协调summary agent：按已持久快照的owner/connection_id/Origin/auth_mode校验，受理指纹绑定snapshot SHA256，执行不重新读取global；原无hash旧operation不新增执行权限。该模块由summary agent修改/验证，本线程未多人写入同文件。
- 无新增runtime/原生窗口、云调用、ASR/LLM、提交或推送。连接源码本轮完成后冻结，真实连接和原生UI验收由主线程进行。

### 2026-10-20 16:54 +08:00｜wugui / Codex（真实账号目录只读验收）

- 主线程报告：native重启后截图及AX确认两会议恢复，循环初始化防护与HMR全局reload正常。本线程未操作原生窗口，不冒充个人设备验收。
- 用户明确授权后，本线程复用现有 `bootstrap` 配置及唯一已核验owner，通过真实 `VILabConnectionService.check` account模式，逐个明确授权精确Origin，只发 `GET /v1/models`。`http://192.168.1.143:9876` HTTP200，目录为2 ASR + 5 LLM，其中1 LLM disabled、其余4 available；`https://api.orulink.ai` HTTP200，2 ASR + 2 LLM全部available。实际LAN目录多于预期，未将其误记为2+2。
- 校验前后当前连接、具体模型及连接/账号授权记录数量完全一致；未调用save、未落盘check_id/token、未切换连接或模型。请求禁止重定向、关闭系统代理，公网TLS默认校验。零ASR/LLM推理。
- 私有最小证据：`.desktop-build/meeting-delivery-20261020/account-catalog-live-check.json`；执行脚本 `check-account-catalogs.py` 仅包含目录检查和非敏感结果，未输出凭据。调用耗时LAN637ms、公网1962ms，不代表推理性能。产品源码继续冻结，无提交/推送。

- 17:10：用户追加旧稿“待归档”显式关联需求，独立模块及边界/测试见[旧会议稿显式关联](../2026-10-20_170054_wugui_无Issue_旧会议稿显式关联/index.md)。这是展示关联补充，不回改此前模型连接或domain来源授权，不迁移旧产物。

- 17:10：按用户截图给出的另一个确切公网Origin `https://api-hk.orulink.ai`，再次使用现有bootstrap/owner和显式account consent，只读 `GET /v1/models` 实际HTTP200，2 ASR + 2 LLM全部available，1211ms。未跟随重定向、未save、零推理，前后持久连接/模型/授权记录数量一致。私有非敏感证据 `.desktop-build/meeting-delivery-20261020/account-catalog-api-hk-live-check.json`。本轮无需修改发行默认地址；此地址在现UI按其他Origin需额外明确确认，不冒充已经加入快捷信任名单。


### 2026-10-20 17:42 +08:00｜主线程：原件定位 UX 与实机验证

- 用户新增要求：录音、录屏以“在文件夹中显示”为主入口；保存副本明确称“另存为…”。会议原件、已保存纪要及文件库共用原件定位组件，IndexedDB-only 录制没有磁盘路径时不伪造入口；已有可信 task 时可核验其保留原件。
- 本机 Cookie + loopback + desktop runtime 专用三个只读 local-path 接口复用 owner-bound resolver。拒绝任意路径、Bearer（含 Cookie 混用）、URL/UNC/符号链接；不代理云端、不下载/复制/修复媒体。Tauri 使用 opener reveal_item_in_dir，选中原文件，不启动播放器。错误就地展示，重复点击受限，迟到的账号/来源结果不打开旧文件。
- 后端31 passed、Rust3 passed；前端原件/文件库相关80 passed，另含交付宿主回归89 passed（不同集合有重叠，不合计）。TypeScript通过。原生壳完成重编译重开，账号保留；native新会话84235、窗口14095374。
- 主线程实际点击文件库第二场会议“在文件夹中显示”。资源管理器窗口68882304打开接受态原目录media并选中source_video.webm（152MB），旁有.playback-preview且未被选中；VINote显示成功定位反馈。此证据是接受态开发原生，不冒充已发布安装包；无删除/另存写入/云发送。
- 会议页真实显示两场时间档案15:41:05、18:02:18，分别7/5份纪要并标已完成。未关联2条旧稿有“关联到会议”入口，打开选择器可选择两份原录制；没有基于标题自动写关联。
- A04实际Luna原稿独立86/100（A03为82），仍有条件、期限、方向和数字问题，且当时结构校验失败；没有人工改稿充当结果。A05明确独立操作1847fe26-1323-4bf3-83b6-df3a5bfdf457复用完整ASR/64帧，实际rawreview因fact passage校验失败，待独评；B01操作c2b086e9-04d5-4474-b4ce-0f4c954c073d正在同一冻结提示词下运行。零ASR重跑，不重放失败任务。
- Wiki容器unknown恢复组件及只读GET/CAS路由已接线；只按精确原delivery绑定核验现有容器，不创建、不自动续发。相关Wiki/runtime后端联测110 passed。


### 2026-10-20 17:49 +08:00｜主线程：审查追加与真实模型结果

- 独立审查后继续修正：原件下载取消后的焦点返回另存为；删除失败改成只读重新核验原件，不再误触导出；IndexedDB媒体读取/另存即时校验当前auth owner，换账号不依赖props刷新；任务原件URL仅允许media下直接文件，拒绝截图、隐藏播放缓存和额外层级。对应5文件48 passed。
- 用户指出文件库关联会议跳笔记错误，已交由会议UI模块同步修复为定位/展开对应会议档案；仍按真实source/task/note身份，保留文件库筛选和选中文件的返回路径，不按标题推断归属。同时核实文件库视频使用完整可跳转预览入口，另存与定位仍使用原件。
- A05实际原始LLM稿独评83/100，较A04回退3分；条件与方向恢复，但发生无据实体具体化及可靠候选过度删除。F030审计引文包含正文没有的实质内容，不是单纯换行；受限空白校验修复后仍拒绝，未放行为完成稿。
- B01实际draft返回HTTP524，summary_result_unconfirmed，无可评分正文。保留原任务与未知结果，不重放、不自动更换模型、不重跑ASR。未将失败处理成100分，也未用人工稿补结果。后续先收口UI和安全边界，再基于通用实体/属性来源绑定继续内容实验。

### 2026-10-20 18:18 +08:00｜主线程：桌面恢复及文件库路由实机复验

- 当前原生窗口31133802运行本功能分支；开发模块加载曾卡住，诊断显示动态App模块加载未完成，Vite开发依赖重建并重启后恢复。移除全部临时index启动诊断，不删除WebView账号/缓存/IndexedDB，不把暂时恢复冒充已确认根因修复。
- 实际从文件库第二场原视频详情点击“查看关联内容”，进入/meetings精确locate_note/locate_task，展开18:02:18对应档案、5份关联纪要和原录制；页面播报已定位，未跳笔记页。返回链接携带原purpose/type/q/file，返回复验另记。
- 原件UX最新5文件49项通过，TypeScript通过；会议路由相关8文件140项通过。原生视频详情当前显示“无法播放媒体”，因此完整预览仍未验收，不计为已修好；保留原件，后续排查真实媒体响应。
- 当前全部更改保存到同一功能分支阶段commit，尚未合并、发布或部署；原App子模块gitlink不包含在本次桌面阶段提交中。真实自动总结A05仍83分，B01为524无可评分正文；未重跑ASR或再发送飞书通知。

- 18:19原生返回复验通过：点击“返回文件库”恢复同一source_video.webm详情Sheet，purpose=meeting/type=all/q及原file身份保留。跳转、定位/展开、返回三段真实跑通；未调用生成或飞书发送。

- 18:22原生“另存为…”复验：确实打开OS保存路径选择框，默认文件名source_video.webm；Esc取消后返回原Sheet，按钮恢复可用，提示“已取消导出，原文件保留”。没有选择目标、没有写副本；不能将取消验收称为实际副本字节保存验收。阶段提交0251565已推送同一功能分支，尚未合并。
