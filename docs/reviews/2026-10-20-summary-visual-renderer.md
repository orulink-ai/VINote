# 画面分镜与信息图：前端 renderer 冻结

本轮只实现前端读取、验证、展示、导出及合成验收。未调用 provider、ASR、飞书；未改 FileLibrary、侧栏、LLM 冻结文件，未提交或切分支。真实 visual sidecar 尚未生成，不能将以下合成截图算作真实模型成品或原生验收。

## 协议与接入

- 与 Dirac／Peirce 对齐 `visual_protocol: 1`，内部 presentation 保持 `comic | infographic`；comic 产品名改为“画面分镜”。精确 TypeScript 类型及边界位于 `frontend/src/lib/summaryVisual.ts`。
- ResultPreview 先读既有 `/api/task/{task_id}/summary-presentation`；仅对应两种形式时 GET `/api/task/{task_id}/summary-visual`。404、缺失引用、错误协议或正文不匹配均保留正文，给出可读提示；不自动生成、不补造图。
- sidecar 严格绑定当前 task、完整已保存 Markdown UTF-8 SHA-256（不 trim／归一化）及 block 原文。预览有未保存编辑时，图形仍绑定 `exportContent`，不将编辑稿当已保存依据。block、claim、frame、scene、node、edge 的上限、唯一 ID 与引用在设备重复验证。
- 标签是完整纯文本，不因有据 URL 字面量或 `<` 比较拒整图，不转成链接、资源或任意 SVG／HTML。图形只用 renderer 自建 SVG 元素；坐标不来自模型。截图仅由当前 task 和 0..7 索引构造固定认证 JPEG 路径，外部 URL／路径字段不进入协议。
- Peirce 负责独立 sidecar artifact/router 的 owner、accepted receipt、完整状态、可信截图映射／hash 校验与 GET 接入；Dirac 后续负责生成／review 输出接线。本轮前端未绕过该链路直接制造真实产物。

## 展示和导出

- 分镜明确显示录屏截图、时间和说明，独立于图文正文；画面失效时保留说明、原文与重新读取入口，不用装饰卡片代替原画面。
- 图解支持 cards／comparison／flow／relationship；保留真实节点、全部关系、环路／自环及文字依据。单列流程图收紧画布，宽图在自身区域滚动；页面不横向溢出。说明没有固定总结章节。
- SVG 完整内嵌允许的 JPEG；PNG 由相同 SVG 在浏览器 Canvas 渲染，有尺寸与像素预算。JPEG 读取限制 2 MiB，拒重定向；缺图不导出不完整成品。HTML 同时包含经验证图形与原正文，延续既有 CSP 和安全 Markdown。
- SVG／PNG／HTML 复用 `downloadRecording` 的原生 OS 选择及分块字节路径；UI 提供准备中、失败、取消和图形保存反馈。owner／账号切换 epoch、task／正文／标题变化、卸载均使旧导出失效，包含快速 A→B→A 和 StrictMode 用例。
- 共享原生 helper 的系统保存框标题目前仍是“导出原文件”（既有 Rust 行为）；本轮没有改该共享底层。图形按钮和完成提示已使用图形名称。真实 Native 图形另存为尚未操作。

## 验证

最终前端 6 文件 **46 tests passed**：协议／引用／hash／纯文本标签 20、布局 3、SVG 与安全 HTML 导出 5、新 ResultPreview/导出边界 11、原 ResultPreview 5、原 summaryPresentation 2。TypeScript 检查通过；主线程可在冻结后统一 tsc/build。

```text
yarn test src/lib/summaryVisual.test.ts src/lib/summaryVisualExport.test.tsx src/components/Notes/ResultPreview.visual.test.tsx src/lib/summaryVisualLayout.test.ts src/lib/summaryPresentation.test.tsx src/components/Notes/ResultPreview.test.tsx --maxWorkers=1 --no-file-parallelism
```

隔离 headless Edge／临时 Vite 使用全新“星港观测站”合成数据和 Canvas mock JPEG，未读取用户录屏、未输入原生 UI。真实组件在 320／1280 宽度截图，无整页溢出／pageerror，只有模拟 GET。两种形式均真实下载 SVG 和 PNG；PNG 再解码验证非空：分镜 1104×520、信息图 1104×1064。该验收验证本地渲染与导出，不验证 LLM 图形质量或真实 sidecar 完成。

忽略目录证据：`.desktop-build/meeting-delivery-20261020/summary-visual-render-acceptance.json`、同名 `.mjs`；`synthetic-visual-comic-{320,1280}.png`、`synthetic-visual-infographic-{320,1280}.png`，以及两形式独立 `.svg`／`.png` 导出。

## 本轮文件清单

修改：

- `frontend/src/components/Notes/ResultPreview.tsx`
- `frontend/src/lib/summaryPresentation.tsx`

新增：

- `frontend/src/components/Notes/visual/DiagramGraphic.tsx`
- `frontend/src/components/Notes/visual/SummaryVisualPanel.tsx`
- `frontend/src/components/Notes/visual/SummaryVisualSvg.tsx`
- `frontend/src/lib/summaryVisual.ts`
- `frontend/src/lib/summaryVisualExport.tsx`
- `frontend/src/lib/summaryVisualLayout.ts`
- `frontend/src/lib/useSummaryExportScope.ts`
- `frontend/src/components/Notes/ResultPreview.visual.test.tsx`
- `frontend/src/lib/summaryVisual.test.ts`
- `frontend/src/lib/summaryVisualExport.test.tsx`
- `frontend/src/lib/summaryVisualLayout.test.ts`
- `frontend/test-fixtures/summaryVisual.ts`
- 本文档。

其他 agent 的 RegenerateMeetingSummary、meetingVersion、后端、Cargo 和 App 改动不包含在本轮责任清单中。

## 后续源码文案变更（尚未原生验收）

主线程已将 `frontend/src-tauri/src/original_download.rs` 的共享保存框标题由“导出原文件”改为“另存为”，适用于媒体、HTML、SVG 和 PNG；仅改文案，不改变 IPC 能力。上文保留测试时事实，此变更尚待主线程重编 Native 后实际验收，不计已完成原生验证；renderer 前端继续冻结。
