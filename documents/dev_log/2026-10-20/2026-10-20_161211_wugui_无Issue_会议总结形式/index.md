# 会议总结形式与独立版本

- 时间：2026-10-20 16:12，Asia/Shanghai；建档作者：wugui（git config）；实施：Codex。
- 分支：codex/meeting-delivery-formats-connections；同一 checkout，不切分支/worktree/commit。
- 状态：后端候选于 2026-10-20 16:30（Asia/Shanghai）冻结可受控运行，前端本地已接入；未实测模型、未部署、未提交。真实验收由主 agent 统一执行。
- 需求：一个会议多个纪要版本，同形式允许多版本。brief/concise/detailed 与 text/illustrated/html/comic/infographic 正交。
- 边界：summary service/router、LLM presentation、NoteService 必要接入、前端 dialog/reader/export/types；不改 Feishu/VILab。Wiki parent 容器由 WikiworkerMendel 负责。

## 接口与决策

POST `/api/task/{parent}/regenerate-summary` 现有确认字段另加 `content_depth` 和 `presentation`。每次使用新 operation UUID，旧 operation fingerprint 必须相同且永不重派。GET summary-context 返回 presentation_options/visual_evidence_version，无推理。结果的 `summary_presentation.json` 关联 child task/parent/canonical/source/transcript/visual/model，已有保存纪要通过 task_id 保留关联；不按形式去重。

draft 保留全部来源命题，fact review 使用完整来源及所选详略；不加入私有样例答案或人工 groundtruth。只有模型自动生成原稿可参加主 agent 的内容质量验收。Markdown 为 native Feishu 输入，HTML 从同一 Markdown 安全派生，无附加推理。图文只复制已核验截图到 child/screenshots；原视频和 donor evidence 不变。漫画和信息图未接通真实图像生成与核验链路，明确 unavailable，vision 不代表 image generation。

## TDD

- 新 tests/test_meeting_presentation.py：实现前 2 failed/1 passed（模块缺失）；实现 presentation scope 后通过，后续汇总另记。
- tests/test_meeting_summary_regeneration.py 新格式测试：修正测试中局部 import 后，`.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider tests/test_meeting_presentation.py tests/test_meeting_summary_regeneration.py -q --tb=short` 为 4 failed/56 passed，四项拒绝新字段，符合接口缺口。
- 系统 python 缺 yt_dlp 的环境失败不作为产品 Red；后续使用仓库 .venv。

## 历史关联与待验证

前置来源与规则：[会议证据与恢复](../../2026-10-19/2026-10-19_190000_wugui_无Issue_会议证据与恢复/index.md)。本次仅增加通用形式，不替代其质量分数。主 agent 统一做真实模型运行与评分；本 agent 不调用 ASR/付费模型。

## 2026-10-20 冻结候选与反例修正

- 用户指出“前八帧附文末”无法建立段落关系，已删除。当前自动工作稿组织事实关系，最终复核 JSON figures 选择真实 FRAME，并绑定已包含的 fact、唯一正文段落及 caption；渲染核验 frame 索引、既有 hash、复制 hash、对应段落后才插入，最终不显内部 ID。无有效选帧则失败，不用默认图凑数。
- 新形式请求启用 material protocol 1。draft 全源组织 subject/relation/object/qualifiers/status/source_refs；review 全源核对并返回最终 Markdown + 逐 fact/topic accounting。detailed 不允许以详略为理由丢弃 material fact；允许基于来源理由拒绝不成立的工作稿命题。校验结构、依据地址及正文 passage 对应，不将 JSON 合规冒充语义正确。
- 不规定 topic/fact 数量，不要求每帧出事实；irrelevant reference 可用空 fact_ids + reason。支持合法空 facts/topics、单 topic、字段扩展。禁止未知 source_ref。输入原文仍完整提供，不从工作稿字数推断覆盖率。
- 原始 draft 在解析前通过既有 private `meeting_working_draft.json` 保留；原始 review 在解析前绑定请求状态，通过 finally 写 `meeting_fact_review.json`。这些诊断不能授权执行、自动修复、重试或再次推理；正常资产路由不开放诊断文件。
- 旧请求不带新字段时仍按原自由文本链路；新请求只带 depth 或 presentation 时，另外一项显式归一为 detailed/text，进入自动两调用结构候选。没有 response_format/JSON schema provider 能力已实证的声明，不能把离线 fake 响应视为 Luna 能力验收。
- 连接 agent 的 connection_snapshot 已接入，source 只复制 mode/server_url/connection_id/asr_model/llm_model，不写 configured/凭据。可选 connection_id 随请求进入 fingerprint 并核验同一连接，UI 同 Origin 换连接也关闭确认。

## 验证结果（无真实 ASR/LLM）

- 后端：`.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider tests/test_meeting_fact_material.py tests/test_meeting_presentation.py tests/test_meeting_summary_regeneration.py tests/test_meeting_review.py tests/test_meeting_source_references.py tests/test_video_summary_materials.py tests/test_default_full_summary.py tests/test_summary_failure_recovery.py tests/test_meeting_parallel_analysis.py -q --tb=short`：122 passed、1 条既有 Starlette 弃用警告。之后新增自动两调用/真实 JPEG 选择的 synthetic 测试，单文件 `tests/test_meeting_fact_material.py` 6 passed。
- 前端：NoteEditor/NoteGenerator/新 dialog/ResultPreview/HTML 五文件 153 passed；补充冻结保存正文导出和同 Origin 换连接后，三个专用文件 15 passed。`frontend/node_modules/.bin/tsc --noEmit` 通过。
- Red：新 material 模块 3 项在模块创建前失败；HTML 新测试在实现前因模块不存在失败。首次组合回归暴露 draft prompt 字符串拼接错误（23 failed/97 passed），补 `+` 后同组合 122 passed。错误及修正均为本地候选过程，未称真实模型稿。
- 浏览器 HTML 静态导出包含 CSP，禁脚本/嵌入/表单、原始模型 HTML、危险链接、远程图片；只嵌入本 task 的已认证 JPEG。iframe sandbox 空权限。编辑 split 模式预览可反映草稿，但导出使用已保存正文。Markdown 保留为 native Feishu 输入，无 Feishu 修改。

## 主 agent 调用与未完成项

```json
{
  "operation_id": "<fresh UUID>",
  "confirmed": true,
  "context_revision": "<GET summary-context.context_revision>",
  "source_version": "<GET summary-context.source.version>",
  "model_name": "<explicit current catalog ID>",
  "content_depth": "detailed",
  "presentation": "text"
}
```

POST `/api/task/{parent}/regenerate-summary`；使用外部连接另带 `connection_id`（来自 `/api/vilab/config`），内置不填。GET context 返回 presentation_options、visual_evidence_version。GET `/api/task/{child}/summary-presentation` 返回冻结形式、parent/canonical、source/transcript/visual/model 信息。保留现有 GET receipt/task 恢复，未知结果不重 POST。每个新 operation 可同形式再生成一份，现有保存链路依 child task_id 关联形式元数据，不改共享 DB/Feishu/Wiki ownership。

未完成：真实 Luna material protocol 接受性、A/B 模型自动稿质量与所有形式产物评审；真实图像生成漫画、信息图；跨独立生成操作复用同一已冻结事实稿（当前复用完整 ASR/speaker/visual 原始证据，各 operation 仍各自自动 draft/review；HTML 确定性派生与图文插图直接复用本次审核正文）。这些不能以 unavailable 或离线通过标为需求完成。主 agent 计划只先 A 一次受控运行，失败保留原响应/operation，无循环盲重发。当前代码冻结之后仅前端和记录继续修改。

## 准备阶段缺陷与纠正（2026-10-20 16:34–16:40）

主线程实际 A 的 task `5ece65dd-705f-4cd8-8886-508ef74649fc` / operation `073e777b-a6e7-4e9d-acd2-1491279d0bd8` 在 preparing 失败，无 provider、无 ASR、无 note，不能评分。失败 artifacts/intent 未被重放或改写。

离线只读诊断（临时脚本 `.desktop-build/meeting-delivery-20261020/diagnose-summary-preparing.py`，拦截网络）：receipt/fingerprint、owner/task、context revision、source version、canonical reference、options、snapshot 均匹配。selected parent visual version 与确认时一致；旧 run_once 由新 child 查 visual，漏掉 selected parent，落到不可用 canonical cache 而抛 409。前后失败 artifacts SHA-256 比较一致。诊断没有执行 accept/run_once、没有改 DB 或任务文件。

主 agent 修改 `_context` 返回值保留 `parent_folder` 并用其加载 visual 两行，本 agent 未重叠修改。新增 parent-only donor 回归在修前失败；修后分别以 NoteService 边界 stub、真实 NoteService + LLM stub 执行，canonical cache 无效仍正确使用 selected parent，模型 stub 被调用一次，child success，ASR stub 为零，donor 不变。

准备自检改为枚举原因（owner/task/context/source/reference/request/snapshot/visual 等），只携带安全分类，无正文/原始异常/凭据。首次新诊断测试仍 KeyError，定位到 TaskArtifactService 仅接受 ASR/summary-unconfirmed 码；新增独立 `summary_preflight.py` 确切白名单后，序列化接受合法新码、拒绝任意前缀相似字符串，保持 retryable=false。原先实际失败 artifacts 不补写新原因码。

验证：专项修前 2 failed；修后 4 passed（含模型 stub 与白名单反例）。随后后端 11 文件组合 **152 passed**（1 条既有 Starlette 弃用警告）。前端新增账号切换取消迟到 HTML 导出后，3 文件 **16 passed**。此前 Vite production build 通过，有既有 Browserslist/大 chunk/动态导入警告，不等于实际设备验收。

冻结记录：第一次受控 A 前的 SHA-256 保留在 [backend.sha256](backend.sha256)；准备缺陷修正后另存 [backend-preflight-fix.sha256](backend-preflight-fix.sha256)。prompt/material 从第一次实际 A 前冻结至本段未修改。主线程将另行明确创建新 operation，失败旧 operation 继续仅查询，真实结果由主线程记录。

模型连接 agent 后续增加 `connection_auth_mode` strict source 字段的协作请求，summary snapshot 复制字段的增补须在本次 A 冻结窗口结束后处理；当前内置连接测试不涉及外部 account auth，未宣称此项已完成。

## A-02 结构拒绝、局部模型与连续版本修正（2026-10-20）

用户反馈 A-text-detailed-02 task `3abf5bf4-5492-4252-8083-ec5769c03e2d` 在 prepare_fact_material 的 coverage 关系校验失败。只读解析原始 working draft：2 topics、49 facts、91 coverage 条目，其中 8 条 coverage 导航关联未逐边镜像 fact.source_refs；所有事实仍有其自己的有效来源地址。这不是成功纪要，未进入 review，不评分。

新增 synthetic 反例先复现旧强约束失败。移除“coverage 每条导航必须都是该 fact 的直接支持边”条件，仍检查所有 fact source_refs 非空且属于真实供给来源、coverage source 完整唯一、fact ID 合法、空关联须有理由；不修改或补造任何支持边。draft/review 提示明确 coverage 仅为导航建议，不能作事实证明，完整原始材料仍在两次调用中。实际原始 raw 以独立保留证据的 **27 ASR windows + 64 frames** 重验，结构接受，文件未改写，无 provider/ASR 调用。实际材料只用于离线诊断，未进入任何生产提示或测试期望。

第二版输入隔离：新增真实 NoteService + 自动两调用 model stub 反例，上一版 note.md/result.json/working draft/review 全部放哨兵；第二版的两次模型输入均含原始转写和独立 speaker evidence，均无上一版哨兵，选择的 second-explicit-llm 固定在 child snapshot，零 ASR，旧版文件不变。继续复用原始证据，不接入上一版纪要或上一版事实稿作为新输入。

对话框增加当前连接目录 GET 的局部 LLM 下拉框，只允许可用 LLM，过滤 ASR 和不可用条目；全局模型仅初值，目录错误 fail closed，选择与形式/详略进入本次 operation 和 POST，不写全局偏好。连接 ID/revision 改变关闭旧确认。用户可在同会议重复选择形式和模型。

旧 localStorage pointer 先按原 operation GET receipt/task；只有确认 task success 且同工作区已保存纪要实际关联该 child task，才移除旧 pointer 并准备新操作。unknown/pending、成功但尚未保存、纪要读取失败继续查询原操作，无新 POST。旧成功回执本身不作为已保存证明。

快照协作：经用户授权与模型 agent 确认，validate_source 只读核验原 connection_id/owner/Origin/auth mode，不读活动指针。summary snapshot 已复制 connection_auth_mode。新受理操作在既有服务端 SourceRequestDB.receipt_json 写 `summary_snapshot_sha256` 并在调度前提交，执行时比对完整冻结 snapshot 摘要、explicit LLM/connection_id，再在原 task_snapshot 中执行；删除与当前全局 `_snapshot()` 比较。请求字段不变，无新数据库 schema。磁盘快照不能自证授权；历史无此 DB 绑定不新增执行权限，也不重放旧 operation。管理员改变内置 Origin 的既有严格边界不变。

TDD：冻结全局切换/篡改 4 项在修前失败；修后首次组合仅 3 项测试断言漏计 ContextVar 的运行时 configured 字段，修正断言而不把 configured 写入持久 snapshot。组合 **180 passed**；随后扩展 Origin/ID/authmode/LLM/needs_stt 篡改等专项 **10 passed**。前端 5 文件 **162 passed**；tsc 通过，diff-check 通过。均为离线行为测试，不代表实际模型稿质量通过。用户的真实 A-02 intent/raw/status 保持原样，不重放、不人工改稿、不传入私有评分答案。

本轮新冻结哈希另存 [backend-material-navigation-fix.sha256](backend-material-navigation-fix.sha256)，保留前两份冻结记录。真实重跑由主线程另行明确确认新 operation；本 agent 未执行实际模型调用。

## A-03 离线诊断与 A4 候选冻结（2026-10-20）

主线程实际 A03 task `53e1e0bf-994f-466e-9317-626e56984781` 已完成两次 Luna 调用，但 detailed material omission guard 拒绝；仍 failed / retryable=false，未发布。独立评审 `.desktop-build/meeting-delivery-20261020/A-text-detailed-03/quality-review.md` 给未人工改写的 raw markdown **82/100**，不是本轮提示修正后的分数。报告只作诊断，未将其具体答案、型号、数字或人工 groundtruth 放入生产提示或测试期望。

原始工作稿 47 facts 全部 material=true；原始复核 41 included、3 rejected、3 omitted_for_depth。三项 omitted 的来源性质涉及含混碎片和偶然操作/读数，不能因第一阶段的 true 标记就视为必须入文。与此同时，初稿没有收录某些清楚可见的实质请求正文，review 也未从完整来源补回；included 的逐字片段校验不能证明语义对应，更不能发现工作事实集之外的遗漏。独立报告还发现含混 ASR 的基础对象/事件被具体化，仅对其属性加免责声明，和多项相对期限、条件、可见方案变化的损失。

仅修通用 draft/review 提示组织，不放松校验器：先独立阅读全部语音与画面，区分实质请求正文和旁边的界面控件，再形成主题与候选关系；记录触发条件、请求行为、预期结果及源中实际存在的约束。保留请求强度、相对时间、数量条件、方向与方案状态，不从邻近词补造对象。先验证基础事件/对象，再限定其属性；无法建立连贯业务命题时按来源理由拒绝，不用坏词清单凑详细程度。正文形成后再次扫查完整来源中遗漏的请求/约束，不将 working facts 当作覆盖边界。

复核按“独立重建来源 → 判相关性与支持性 → 写正文 → 审计最终正文”顺序执行。允许对误标 material=true 的工作候选以具体 non_meeting / incidental / garbled 来源理由 rejected；仍支持的重要事项不得为缩短正文伪装 rejected 或 omitted_for_depth。重复事实合并后可共同指向同一 included passage，passage 必须体现实际关系与条件，不能只共享一个词。详细版 material 遗漏 guard 和所有未知 source_ref 拒绝规则保持不变。

视觉依据更正：用户已确认同 owner / Origin / model 的有效 protocol-2 synthetic receipt（supported=true、finish_reason=stop、TTL 有效），A03 summarizer vision=True，实际供给64帧。catalog 缺 vision 字段不推翻此既有验证；本轮未降为 OCR、未重复 probe、未切模型。图像已输入不等于模型正确理解每帧。

TDD：source sweep 新提示契约用例修前 1 failed；修后与来源相关性、merged accounting、material 重判、空 coverage 等用例通过。最终后端11文件组合 **196 passed**，1条既有 Starlette 弃用警告：meeting_fact_material / meeting_presentation / meeting_review / meeting_source_references / video_summary_materials / default_full_summary / meeting_summary_regeneration / summary_failure_recovery / private_meeting_artifacts / vilab_connections / meeting_parallel_analysis。前端源自上一阶段后未改动，最近5文件 **162 passed**、tsc 和 Vite build 通过，构建有既有依赖/分包警告，本轮未重复跑前端。所负责文件 diff-check 通过。

实际 A03 原始 draft 在当前代码下离线结构接受；未修改的 raw review 仍被详细版遗漏 guard 拒绝。只读 `revalidate-review-03.py` 验证 failed 状态保持、所有任务 artifacts 哈希不变，provider_calls=0、asr_calls=0。本轮没有修稿、重放、补发布或新 provider 调用。

A4 后端候选哈希另存 [backend-a4-candidate.sha256](backend-a4-candidate.sha256)。本次后端 prompt/material 已收尾冻结，待主线程新 operation 的真实模型验收；不把离线 green 声称为内容质量达标。每次局部 LLM 选择、连续同形式版本、冻结连接快照与安全 HTML 仍以先前测试结果为准；漫画/信息图真实产物能力及各形式的实际质量验收仍未完成。

## A04 结构拒绝只读诊断（2026-10-20）

用户委托离线诊断 task `bc5448b5-86a3-4633-95a3-200fbb24785e`，不改 prompt、不再调用 provider。只读脚本 `.desktop-build/meeting-delivery-20261020/diagnose-review-04.py` 在 bootstrap 前禁止 socket connect；重新执行当前 prepare/finalize，仅在进程内拦截 `_require` 获取确切首个失败路径，未改变校验结果或候选内容。

draft JSON 与结构通过：3 topics、21 facts（20 material=true）、91 coverage。review JSON 可解析：20 included、1 rejected、零 omitted_for_depth；21个fact与3个topic ID分别完整唯一；所有 included passage 均为正文实际子串，无非法图片/内部引用标记，figures=[]。首个拒绝位于 `meeting_fact_material.py:120` 的 topic_audit.T001.passage 连续子串检查。该引用197字符，实际对应正文 span [47,246)，唯一差异为正文两段间的 `\n\n` 未复制进 topic passage。没有错字、重排或缺失事实文字；其余 topic passage 均通过。

本次失败属于冗余主题引文的格式约束过脆，不能视为内容质量失败或通过；A03 的 material omission 拒绝则是另一条路径。A04 正文1676字符，raw review信封5417字符，逐项重复正文并未形成语义正确性证明。独立 reviewer 继续评未修改 raw markdown；本次未评分、未修稿或补发。

诊断确认所有 A4 backend 冻结哈希匹配，task artifacts前后SHA全部相同，status仍failed / summarizing / retryable=false，网络尝试0。本轮仅增加诊断脚本和日志，未更改产品代码或冻结prompt。建议的机制调整待单独实施：删除冗余 topic 精确引文硬门槛；逐步用紧凑来源问题清单及必要图片锚点代替全量逐fact/逐topic复抄正文，保留完整来源复核、真实来源地址与图像安全验证、完整provider终态和无自动重试；不要将格式合规或空问题清单声称为质量满分。

## A05 候选：关系保真与受限 topic 排版规范化（2026-10-20）

用户最新明确要求先做最小结构修正，保留全部 fact accountability，不采纳上段删除 topic 硬门槛/缩短信封的设计方案；本段取代该建议的本次实施范围。仍为一次自动 draft + 一次完整来源 review，无新增检查调用、修复调用、provider重试或ASR。A04独立原稿评分86/100、A03为82；这些不是新候选的分数，也不证明提示改进的稳定效果。

改动限 `meeting_fact_material.py`、`meeting_draft.py`、`meeting_review.py` 与对应专项测试。两次提示均增加通用关系维度核对：先拆来源中的触发→行动→结果及阶段/范围/时态/状态，方向图按各有向边分别组织；合并正文后重新对照原始来源和工作候选，不能用相同对象、结果或目的地替代条件/阶段。数字连同单位、对象、配置、页面状态及时间角色核验，特别检查小数点/分组/符号；不可读或无法绑定的数字不以合理值补齐，仍保留有支持的定性信息。相邻名词或说话人不清不能吞掉独立可辨的期限、要求强度或条件，也不能借此猜对象、姓名和具体日期。没有加入报告中的会议答案或样本型号/数值/条件。

topic passage 仍要求规范化后的连续子串：仅折叠空白，并容纳中文字符/中文句读之间的排版空白；不做Unicode字符替换、不删除英文词或数字之间的空白，不将分开的标识符、小数或数字拼接。正文和raw不改写。非空但不匹配的引文即失败，即使有reason也不能绕过。reason分支只接受空passage、非空字符串reason，且该topic不能仍有included fact。fact引文保持exact；figures锚点保持exact且唯一；详细版material omission与来源地址校验未改。

TDD：第一轮新增用例修前 **14 failed / 19 passed**；实现后专项 **33 passed**。再加入两项figures反例，证明topic能容纳排版差异时，图像锚点的同类差异和重复exact锚点仍分别拒绝。最终11文件后端组合 **217 passed**，1条既有Starlette弃用警告，122.20秒。覆盖topic中英文空白/CRLF/tab/NBSP、正文保持原样、错误词/数字/方向/遗漏/重排/跳过中段拒绝、reason类型/空值/旁路、fact exact、figure exact唯一，以及既有两调用/原证据/无ASR/冻结快照/失败恢复。提示契约测试只证明规则与完整来源进入两次调用，不冒称离线证明模型关系理解正确。

真实raw只读对照：A04原始draft和review在当前校验器下可接受，未人工修正文或审计；A03原始review仍被详细版重要事实遗漏保护拒绝。两次脚本均核对各task全部文件SHA前后一致，历史status仍failed、不发布；A04网络尝试0，A03无provider/ASR。对比旧A4冻结清单，仅本轮三个LLM文件发生变化，未碰主线程原件reveal UX、Feishu或模型连接实现。前端本轮未改。

新冻结清单：[backend-a5-candidate.sha256](backend-a5-candidate.sha256)，清单自身SHA-256 `6C0CC187265EF418ECEC28C99E70DB6D7449CB28BC75CB201C9AB51151E58B55`。保留A4及更早清单。代码与测试收尾后冻结，由主线程以新operation单次A05 runner实测和独立评分，本agent不执行付费调用、不重放旧operation。

## 前端已知失败显式另建入口与 A05 只读诊断（2026-10-20）

主线程已启动A05，随后启动B01；用户要求持续冻结backend/prompt，仅修前端入口。改动仅 `RegenerateMeetingSummary.tsx` 及其测试，沿用既有Dialog/Field/Button和焦点恢复hook，不改主线程原件reveal UX。

初次点击原纪要页生成按钮时，按原operation GET receipt与task；只有accepted、精确operation/task身份一致、task failed/summarizing/retryable=false且不是已知unconfirmed类别，并且owner键下原source-receipt精确绑定child/parent/note/Origin/workspace/summaryOnly/accepted时，才显示“保留失败记录，另建新版本”。此时不清pointer、不读新生成context、不POST。用户主动点击后再次核验，再打开局部LLM/详略/形式选择；最终确认前再读原receipt/task和pointer，仅身份、状态和原receipt字节全部保持时才写新UUID的独立记录并替换pointer，随后仅POST regenerate-summary。旧source-receipt始终不改不删；失败记录仍可查询。正常已成功且已保存逻辑保持原样。

unknown/reserved/未保存成功/GET失败/身份不符仍只进入原操作查询。确认期间pointer被新操作替换或task变为结果未确认，禁止新POST。连接/账号/路由改变沿用原remount隔离。Dialog增加viewport限高、overflow-y-auto和overscroll-contain；取消保留pointer和旧receipt，恢复到“另建新版本”触发按钮焦点。

TDD修前 **5 failed / 31 passed**；修后专项 **36 passed**。随后前端5文件组合（RegenerateMeetingSummary/ResultPreview/summaryPresentation/NoteGenerator/NoteEditor）**183 passed**；`tsc --noEmit`通过。有既有React Router future flags及NoteGenerator ABA用例act警告。测试包括16种未知/错绑状态、3种提交前变化、新模型与HTML选择、新UUID/唯一summary POST、旧receipt原样保留、滚动样式和取消焦点。离线组件测试不冒称实际小屏设备已验收。

A05 task `1847fe26-1323-4bf3-83b6-df3a5bfdf457` 离线诊断：draft 4topics/35facts/91coverage结构有效；review 32included/3rejected，无omitted_for_depth，35fact/4topic ID完整唯一。首个失败在line132，fact F030 included passage非正文子串。该引文包含正文未写出的共享权限描述，去除全部空白后仍不匹配；因此不是A04式排版差异，不能据用户的条件授权统一放宽factproof来放行它。本次不修原稿、不更改audit、不评分、不发布，等待独立评审。

只读诊断脚本增加可选task/冻结清单参数，bootstrap前禁止网络；A05任务全目录SHA前后一致，状态仍failed，network_attempts=0，A05 backend冻结清单匹配。本轮未调用provider/ASR、未replay、未修改backend/prompt或B01运行实现。

## A/B 运行结束后：fact/topic 统一受限布局匹配（2026-10-20）

用户报告B01 draft HTTP524、summary_result_unconfirmed、无working draft/final，明确不重试/重放；同时解除运行冻结，允许离线修正排版guard。前端已知失败显式新操作入口上一段已完成，183 passed / tsc通过，本段未再次改变前端。

须纠正混淆：A04是已证实的topic排版误拒；A05 F030则含正文没有的实质描述，去掉全部空白仍不匹配。本段没有把A05当成纯空白误拒，也没有为放行它改正文、audit或事实门槛。

实施仅把已有受限布局规范化抽为 `_proof_quote_text`，统一用于fact included和topic引文；仍要求非空连续匹配，保持拉丁词/数字边界和全部标点/字符，不能靠reason挽救不匹配。原始响应与正文保留，fact/topic完整计账、source_refs与详细版material遗漏保护不变。figure实际段落的exact且唯一检查、fact关联、真实frame校验和插图替换均未改。此结构修正不新增或修改prompt，不增加模型调用。

TDD：扩充fact/topic对称用例，修前 **6 failed / 45 passed**；修后11文件后端组合 **233 passed**，32.65秒、1条既有Starlette弃用警告。覆盖排版空白可接受、词/小数/数值/方向/标点变化、跳过中段、引用凭空新增句子均拒绝，figure锚点exact唯一仍拒绝相应反例。原始A05再次只读执行仍在F030拒绝，artifacts全部SHA不变、状态failed、网络尝试0；A03重要事实遗漏仍拒绝，文件与状态不变。没有改或重新派发B01。

另存当前后端清单 [backend-proof-layout-fix.sha256](backend-proof-layout-fix.sha256)，自身SHA-256 `B2DE471AD50C63C3CD9C2CC5C1657597772B8E9EBFE67F7C41C6B0BC3284397C`，保留全部旧冻结证据。本段未启动provider/ASR、未人工修稿、未重放或发布旧失败候选。

## 异步生成入口焦点恢复补证与修正（2026-10-20）

用户指出原组件没有显式opener/ref/onCloseAutoFocus，异步prepare期间按钮disabled可能令焦点落到body。原有取消测试只覆盖即时mock、已聚焦的失败版本按钮，虽然DialogContent内部useOverlayFocus提供通用恢复，但其开窗时采集activeElement，不能覆盖这个异步缺口。此前“焦点恢复完成”的概括范围过宽，本段补正，不将原测试当成所有焦点路径已证实。

改动仍仅RegenerateMeetingSummary组件和测试：点击时、setBusy/await之前把event.currentTarget存入opener ref；DialogContent显式onCloseAutoFocus阻止默认恢复，只在当前组件仍活动、owner/Origin匹配、原按钮仍连接且可用、没有其他已打开dialog时返回该按钮。mounted清理改用layout effect，owner/route key切换的旧实例同步失效，旧overlay不会恢复旧页面焦点。没有改共享Dialog/useOverlayFocus、后端、prompt、provider或knownfailed gate；error_code缺失仍按原强绑定及专用unknown码规则处理。

新增延迟GET测试，在按钮已disabled时显式模拟body焦点，验证取消/关闭/Escape三种关闭和失败版本二次prepare，另验证owner/route变化后不调用旧opener.focus且不夺走新表面焦点。首次测试中jsdom的disabled按钮blur行为不等于浏览器，修正模拟方式后，修前产品反例 **4 failed / 38 passed**；显式恢复修后专项 **42 passed**。随后5文件组合 **189 passed**，`tsc --noEmit`和diff-check通过；保留既有Router future flags/ABA act警告。原测试与新增测试分别在RegenerateMeetingSummary.test.tsx:232、:249、:269、:289，实际行号以当前源为准。

backend-proof-layout-fix清单13文件全部匹配，本轮未修改任何后端或真实任务证据、未启动provider/ASR、未提交。焦点证据为组件测试，不扩大为全部浏览器/设备已实测。

## 来源原样片段、命题部分拒绝与稳定正文块（2026-10-20）

用户要求在主线程阶段commit后的同一分支继续最小通用机制优化；本轮不碰主线程UI/媒体/agents、不调用provider/ASR、不写人工会议稿。设计与读取说明见 [protocol 2审查文档](../../../../docs/reviews/2026-10-20-summary-source-claims-v2.md)。实际新增产品模块170行；其余产品变更为来源ContextVar、小型视觉来源描述、协议分派/提示接入及新候选严格protocol选择，无新API或数据库schema。

协议2新增真正原始ASR窗口文本绑定，证据quote原样且唯一匹配，重复（包括重叠重复）须精确字符start/end消歧；不借用装饰文字，不规范化source/span。命题anchor在其实际来源文本/视觉observation内原样存在。命名实体有独立entity claim，未知可null，数值、条件、期限分别计账。rejected不再是整fact非空理由即放弃，须逐claim受控原因、具体理由及重新验证的来源；unclear_entity仅限entity claim。block IDs避免复抄正文，每claim完整引用或有据处置，完整来源review可用同样来源约束补additional facts。真实图文选帧转换为现renderer既有exact唯一段落接口，无OCR时的frame observation始终是模型视觉判断，不假装已验证OCR。

严格区分边界：程序验证原样文字存在、来源类型/地址、命题计账和block引用，不证明ASR词义、拒绝理由蕴含、block语义覆盖或图片识别正确。完整两调用不变，不自动补调用/重试/切模型。新显式详略候选强制protocol2，不悄悄降级；旧v1 helper仍可读取旧结果，不迁移或重放旧operation。旧诊断外层协议不变；v2原始可评分正文仅按blocks顺序确定性组装，API成功结果仍返回Markdown。

TDD：全新合成命题用例首次 **6 failed / 16 passed**，接入后 **22 passed**；四文件核心组合 **154 passed**。补视觉/插图/并发后首次组合3 failed/261 passed，原因是测试把pytest.raises放在会先拒绝的无vision/noOCR context之后，调整测试捕获范围，未修改该既有安全门槛。随后组合 **264 passed**。最后视觉observation附加伪quote字段绕过anchor的反例修前1 failed/30 passed，单行按真实kind选取锚定文本修后最终12文件组合 **264 passed**（31.76秒，1条既有Starlette警告）。整理测试分组后新协议专项 **31 passed**；没有新增产品变动。

验证包括：来源窗口错配、原文数字/空白/片段篡改、metadata伪证据、start/end类型/范围、唯一/重叠消歧；未知实体与有据独立属性、整fact/无来源拒绝禁止、entity理由滥用于数字禁止；空facts/单topic/扩展及新增漏项、block错误/重复/缺项、v1降级拒绝；无OCR图像不冒充文本、真实frame关联/段落exact唯一；两个并发会议各一次draft一次review、原始来源/原响应/ContextVar不互串。既有第二版排除旧纪要、无ASR、模型冻结及恢复回归保持green。未改或重新解析实际会议原稿以修正其内容，未将私有评审答案作为提示或测试期望。

候选现已冻结：[backend-source-claims-v2.sha256](backend-source-claims-v2.sha256)，15个后端文件，清单本身SHA-256 `222E248BF3D6DDAD909C09EB5C051D04DD4EA66A7528F527A2CA50D6346FEE19`。由主线程审查后明确新operation运行；本agent不调用。协议2真实provider接受性和真实质量分数仍未验证，不能以264 passed冒称100分或稳定产出。冻结后停止追加实现。

## v3 来源纠错最小修正与冻结（2026-10-20）

A08/Bbrief02原始JSON均可解析，失败都在冗余anchor子串检查而非JSON语法。只读逐项核对：A08 24 claims，16项ASR证据中15项原样精准，C15将实际ASR:0023引到0022；另5项anchor不在引文。Bbrief02 28 claims，16项ASR证据中15项精准，C26将实际ASR:0013引到0014；另4项anchor不匹配。独立Aristotle复核相同。原始响应、失败状态和旧operation不改、不重放。

用户批准的最小v3修正：移除anchor要求；逐项检查draft证据，来源错配仅附verification=unverified，原quote/ref/offsets不修不删，进入已有完整来源review。review audit可用同格式evidence替换该claim旧证据，included使用原有效证据或替换后的有效证据且必须重新严格核验；不得相信模型自报verification。rejected新证据也严格核验可信来源，但不要求与旧错误ref求交或重验被拒旧证据。未输出的omitted候选仍受空blocks/理由/深度material门槛，不新增旧错误证据门槛。v3 field为非空分类标签，允许责任等分类扩展；unclear_entity仍仅entity可用。legacy v1/v2路径未放宽。

首次新增回归9 failed/18 passed；其中一条歧义quote测试最初使用只出现一次的the，改为实际重复的a，未因此调整产品匹配规则。修后四文件组合189 passed；最终移除未输出候选的多余strict检查后v3/v2专项64 passed。用例覆盖错引原样保留/伪验证覆盖、无纠正included禁止、有效纠正替换而非合并旧证据、跨旧错ref有据拒绝、非法数字/offset/ref/重复引文拒绝、additional_claims纠正、unknown entity部分拒绝、非空字段扩展与两次完整来源调用/原始draft和review保存。最后同组合重跑结果随后补记。

Aristotle对最终源码独立离线验证：A08/Bbrief02分别24/28 claims均prepare通过，仅C15/C26保留unverified；原artifact字节不变。自己的首个重复离线脚本误以为视频manifest含identity嵌套键而KeyError退出，未修改数据、未调用provider，不将该失败脚本算成通过。采用独立核验结论，不人工改错quote来通过最终发布门槛。

已冻结[15文件清单](backend-v3-source-correction.sha256)，清单SHA256：45B895F6856A19387DB3F0F55DA54F075E6E71695ACF467D3D7118231DA01CA4。protocol文件SHA256：515352D1C91E37EDE9923D06892F68C611F9F6318AFDDD8EB3DB724A374C63A5。未改变两调用数、原始完整来源、原始响应保存、连接/模型选择，无新增协议版本/自动修ref/补调用/重试/ASR/provider。由主线程另建A09/Bbrief03真实operation；结构通过不能声称真实事实100分。视觉backend交Peirce独立实现，本候选不接visual prompt/host。

最终冻结源码四文件组合重跑190 passed（25.09秒，1条既有Starlette弃用警告）。冻结清单逐项核对全部15文件一致。

## 视觉接线应用、真实批次冻结与工具整理（2026-10-20）

A09 draft HTTP524未返回稿；Bbrief03完成draft/review但guardfailed。B只读对账为26claims/28audit、missing=[]、extra=C27/C28，无additional_claims，且included错引需有效纠正，不能自动补定义、删audit或人工改稿。Peirce独评原始10块正文90/100，与失败不发布分开。提示仅强化原有claimset/新增claim定义/有效证据替换及通用时间事件角色，无样例人名数值或答案。

用户解除当批冻结后，已应用visual-host-integration.patch。新增独立prompt/state快照与generation adapter，接入既有review/state/note/render；原有text/HTML不新增visual字段要求，两调用不变。分镜为真实录屏，不调用生图；信息图为本轮正文的受控布局，设备渲染。adapter复用Peirce wire/sidecar模块，Mendel负责前端。app factory曾多人重复挂路由，main已保留artifacts=note._note_service.artifact_service单次挂载，并将测试改为assert count=1；该文件归main，我不再修改。

独立新模块+staged-host组合71 passed；应用后组合首次212 passed/1 failed，失败是新增测试错误期待generate_from_transcript kwargs含model_name，而实际模型由冻结ContextVar承载，改测试检查accepted child快照，未改产品。随后216 passed。最后按用户要求强化brief约30–45秒阅读目标与时间谓词角色比较，未增schema/guard。一次性generator/staged测试在运行结束后移入ignored .desktop-build，正式tests/test_summary_visual_pipeline.py直接执行当前host；最终六文件组合106 passed（5.95秒，13条既有Starlette/FastAPI弃用警告），diff-check通过。

原20文件冻结清单SHA D8A816A704DC362451581C0B8853E4F6B76BE65DB2F7E168FD81B7343E635B43；main已启动A HTML detailed01/B illustrated concise01，明确冻结core20。唯一授权例外：Peirce独立artifact模块修首/尾块合法空白与finalizer整体strip的投影差异，两种正在运行形式不调用它。prompt/host不再变更；修复及测试后仅更新20文件SHA，不等待文档。

接线、请求字段、责任边界和证据说明补入[视觉接线文档](../../../../docs/reviews/2026-10-20-summary-visual-integration.md)。本agent本轮零provider/ASR、未commit、未切branch/worktree，旧真实稿、intent、receipt和状态未修改。实际各形式质量与完成状态由main另行真实调度及评分，离线green不能冒称100分。

授权边界修复已由Peirce完成并冻结：artifact SHA8825F1DC269D69F8FAF571404A0C7A5B600FE952BED25B6439A493E7535D92D4，专项58 passed。刷新20文件清单前确认仅该独立模块发生改变，旧清单另存backend-visual-integration-pre-boundary.sha256；prompt/host保持原样。本agent仅更新清单与档案，未碰运行中两路源码。

### 2026-10-20 19:20:29｜最终冻结 SHA 补记

- Peirce artifact 边界修复及兼容验证共74 passed：artifact58 + generation/pipeline16；零provider/ASR。
- artifact SHA256：8825F1DC269D69F8FAF571404A0C7A5B600FE952BED25B6439A493E7535D92D4。
- 20文件清单SHA256：908793CAD54A4F24783E58DAA53B589878EF7A7A50A085A524838464C89AD053；逐项核验全部一致，清单已是授权修复后的版本，无需重写。
- main正在最终8模块联测，计划同分支阶段commit，尚未合并；本agent不修改core、不提交，不预报联测或commit成功。

### 2026-10-20 20:05 · 实际结果、原生运行与本机 OCR 补强

- 前述8模块联测246 passed；提示冲突修复后125 passed，独立审查所提重复引文及OCR/ASR范围措辞问题修复后40 passed。提交4221ff6已推送同一功能分支，PR64仍draft/dev，未合并部署；App gitlink和Cargo换行噪声未提交。
- 最新单场实际原始LLM正文评分：详细文字A10=82（上一轮83、最高86），简介B03=90，HTML A01=84，图文B01=80，分镜A01=77，信息图B01=90。不是两场每形式完整验收；只有HTML成功保存，其余为被guard阻断的raw-review。人工稿不计分。具体正文exacthash与证据范围在各ignored run的quality-review.md。
- A10两调用共105.5秒，新增C22–C28缺audit，且缺figures；B图文02约282秒后模型连接中断，无可评分正文，状态unknown/nonretryable，未重放。所有实际运行仍硬性拦截ASR，未创建ASR checkpoint。不能把离线green或原始正文评分冒称产品成功。
- 原生桌面已重编译重新运行，HTML84分原稿实际预览、另存为4353字节成功；证据补到实际UI验收文档。没有借此宣称质量100或飞书交付完成。
- Windows原生中文OCR已发现并完成A/B各一张真实图测试：727/1398字符，约464/320ms识别时间；125图及两份旧manifest哈希不变。新增有界批处理模块与桌面新子任务派生材料接入：前后图hash、原文/坐标、真实引擎/语言/系统版本、不可覆盖子任务receipt；旧ASR/图片/manifest不改。失败不采用部分OCR，不截断全文材料，不安装/下载OCR引擎，不发新provider修复请求。
- 新OCR接入与既有summary回归86 passed；OCR模块/派生接入/visual pipeline组合94 passed。仍在独立审查，尚未以完整125图OCR的新材料生成下一候选，不提前声称质量改善。

### 2026-10-20 20:26 · 真实 OCR 批次与补充来源标识

- A11耗时187.1秒后模型连接中断，无draft/review；B信息图02耗时126.2秒，有raw review但exact证据拦截。native OCR在两批分别完整采用64/61张、50846/81002字符，均completed且inputs_verified_after；旧ASR/原图/manifest未变。OCR成功不证明模型质量改善。
- B02原始正文独评81、raw visual plan83（旧口径临时分数），不是保存成品。具体问题包括行程方向/同一事件关系错误、重要差异遗漏、8项引文不匹配及缺figures。保留raw不修补。typed质量记录按task和bodyhash绑定，正文与图形计划分开，缺失与unknown不赋分。
- 新冻结统一rubric见summary-quality-20261020-v1文档；历史临时分数不换算、不同版本最高分不拼盘。后续两样本六项取较低分，事实/关系错误必须扣分，不以渲染或测试冒称100。
- 通用来源提示补强：OCR每条frame记录增加与实际图片一致的显式source_ref，不要求模型按61条OCR数组心算图片编号。raw OCR原文、空格和错误不规范化；独立看清图像时使用frame_observation，不冒充exact OCR。没有重排/裁剪帧、修改旧manifest或增加provider。新增绑定断言及视频/OCR组合36 passed。
- UI前置入口和固定弹窗操作区分别c9dd784/dff3ca3已推送并原生验收。新HTML再生成的视觉来源关联修复候选已实际GET与原生弹窗恢复复用，但独立审查仍在修补现代回执缺hash的读取完整性反例，尚未最终冻结。

### 2026-10-20 20:42 · 后续版本视觉材料引用与 v4 实际首轮

- 新子任务用source/canonical/owner/manifest/frame hash绑定的扁平视觉donor引用，DB accepted receipt提交其摘要；不会复制原视频或JPEG、形成引用链、读取上版最终纪要、覆盖旧材料或重新扫描。历史HTML1173只在原accepted指纹、选定父context和视觉版本一致时读取具体原manifest；未知或缺失证明不凭磁盘链接借用。
- 两次独立审查指出并修复现代缺失/null snapshot摘要读取完整性、损坏pointer被own cache掩盖，以及无视觉材料音频context的兼容回归。主线最初把摘要要求扩大到历史own cache，导致A12/B03在intent/provider前停止；原状保留，无模型或ASR调用。后续仅exact历史intent、原accepted指纹及已有legacy Origin proof可读OWN cache，现代形态不借此绕过，递归有界。最终helper c9a6db2da6077e0bbb7d9889361ce21d88feee831fd77b18b799706c51c55b57；独立组合135/135通过，3个实际context恢复reuse/inherit。A原父fresh不可用仍按既有证明拒绝，不影响复用。
- v4接线与统一rubric已在c9f31aa提交；独立561项组合、主线202项核心/host/provenance/OCR组合分别记录。原始draft重复字段在规范化前拒绝；最终claim同一行定义和处置，不自动补缺行，原始响应不改。主线把FinalLedgerError展示文字改为中文说明，机器code属性保留。
- B信息图04通过v4 ledger后，在真实PipelineContext slots赋值presentation_visual失败，耗时130.8秒；raw4保留，未保存或发布、未改旧终态。此前synthetic SimpleNamespace无法捕获该类错误，已补真实dataclass字段，并新增实际上下文回归测试。不能把此轮称为信息图成品验收通过。
- A文字13从已保存HTML1173走真实MeetingVersionService默认reuse/inherit创建，实际parent/operation/model/source冻结，当前draft完成复核中；不使用HTML正文作为材料，不创建ASR checkpoint。后续实际评分仍待原稿返回，不能提前宣称100。

- 后续A13在复核请求等待响应头期间ReadError（165.1秒）退出，没有完整review可评分；保留unknown，未重放。A11同类ReadError为166.7秒，B图文02为RemoteProtocolError287.9秒；这些不是已确认的客户端超时，尚不能据此认定供应商/代理根因，也未修改vilab-server或延长超时掩盖失败。
- PipelineContext单字段修复后，真实slots上下文至summary/render/实际sidecar授权保存读取的6项回归通过，覆盖comic/infographic的成功和严格失败。只替代模型响应/能力探测/测试DB目的地，不用SimpleNamespace冒充生产context；旧B04不改成功、不补写产物，不调用ASR/provider。
