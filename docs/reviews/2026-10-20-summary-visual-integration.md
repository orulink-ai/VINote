# 会议呈现接线与验证边界

## 当前实现

同一会议的每次新版本仍使用既有 summary-only endpoint，复用原始 ASR、说话人和已保留的画面证据。上一版纪要不进入输入。保持一次完整来源 draft、一次完整来源 review；不增加模型调用、修复调用、自动重试、ASR 或模型替换。

内容详略独立于形式：`brief`、`concise`、`detailed`。简介以约 30–45 秒阅读为目标，优先主要主题、关键安排和必要约束，不固定章节或硬截断。

- `text`：复核正文。
- `html`：同一正文由前端安全模板渲染、导出，模型不生成可执行页面。
- `illustrated`：既有 review figures 关联 included claim 与真实 frame，在对应正文段落插原视频截图；没有有效选择则明确未完成。
- `comic`：兼容原 API 枚举，产品含义是“画面分镜”。第二次 review 返回本轮正文块及受控分镜布局，设备展示真实录屏截图；不冒充人物生图或 AI 插画。
- `infographic`：第二次 review 根据内容选择 cards/comparison/flow/relationship，设备 SVG/Canvas 渲染；不要求生图模型。

只有后两种形式增加本轮 review 的 `visual:{scenes,diagram}` 数据，不改变协议版本或 text/HTML 的输出要求。模型提供 block/frame 引用和短标签；后端补 task、正文 hash、截图序号和时间，不接受模型资源路径、任意 URL、HTML、SVG、JS、CSS 或坐标。标签来自本次复核正文，作为转义纯文本处理。

## 调用字段

先通过已认证的 `GET /api/task/{parent_task_id}/summary-context` 取得当前来源版本；用户确认后，新建 UUID 并调用 `POST /api/task/{parent_task_id}/regenerate-summary`：

```json
{
  "operation_id": "新建的 UUID",
  "confirmed": true,
  "context_revision": "GET 返回的 context_revision",
  "source_version": "GET 返回的 source.version",
  "model_name": "本次连接目录中明确选择的可用 LLM ID",
  "content_depth": "detailed",
  "presentation": "html"
}
```

`presentation` 可替换为上述五种枚举，`content_depth` 可替换为三种详略。若局部模型目录选择提供 `connection_id`，一并传该 ID；后端按本次连接与模型冻结，不修改全局偏好。不重用旧 operation，不把 unknown 自动重发。

分镜／信息图成功后，前端通过已认证的 `GET /api/task/{child_task_id}/summary-visual` 读取 sidecar。读取绑定 owner、accepted operation/task fingerprint、冻结模型快照、原始 review、成功状态和 `result.json.markdown` 精确 UTF-8 hash。Windows `note.md` 的物理 CRLF 不是 hash 权威。未生成、旧任务或校验失败返回 404，不假装图形已完成。

## 责任与文件

- 本 agent：`meeting_visual_review.py` 的可选提示/有效来源快照；`summary_visual_generation.py` 的布局到 wire、真实帧关联、hash 复核和截图复制；现有 review/state/note/render host 接线。
- Peirce：`summary_visual_artifact.py` 的 wire/storage/receipt 校验，`summary_visual.py` 读取路由及测试。
- Mendel：ResultPreview、受控 SVG/Canvas 渲染及 SVG/PNG/HTML 导出。
- main：app factory 的单次路由挂载、真实 provider 调度、实机验收与评分。

一次性 patch 已应用。生成器及 staged-host 动态测试已在执行结束后移入 ignored `.desktop-build/meeting-delivery-20261020/visual-host-patch-evidence/`，不作为永久产品工具。正式 `tests/test_summary_visual_pipeline.py` 直接验证当前实际 host，无动态修改模块或重新应用 patch。

## 已验证与未验证

接线组合 216 passed；最终 brief/时间角色提示澄清和正式实际 host pipeline 组合 106 passed。另有 Peirce 独立 artifact/router 55 passed。均为离线合成测试，不是模型事实质量分数或真实图形成品验收。

Bbrief03 原始 review 完整可解析，有 10 个正文块；draft 26 claims，audit 28 条，missing=[]、extra=[C27,C28]，缺对应 additional_claims 定义与证据；另有 included 错引未纠正。因此保留 guardfailed、不发布、不补定义或删 audit。独立原正文评分 90/100 与产品失败状态分开。后续仅通用提示澄清 ID 对应、纠正证据和时间事件角色，不加入会议具体答案。

冻结清单位于开发档案 `backend-visual-integration.sha256`，包括旧 15 文件及五个新运行文件。后续真实批次的运行结果、评分和明确授权的边界修复应分别记录，不能用这些 tests 声称各形式已达 100 分。
